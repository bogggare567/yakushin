"""Does the model fall apart when the same part is drawn at very different sizes?

The certain-pair QC says the model never merges two different parts. The audit
of a real file says it does. The one thing the certain pairs cannot contain is
the situation that actually occurs: LEGO draws an icon small when the box is
crowded and large when it is not, so a 6x6 plate from a roomy box gets compared
against an 8x8 plate from a cramped one — crisp studs against a blur.

This re-runs the same certain pairs with one side deliberately drawn small, and
reports what that does to both error kinds, at several input resolutions.

Usage: scale_test.py model.pt file.pdf [...] [--sides 32,48,64]
"""
import argparse
import numpy as np
import torch
import fitz
from PIL import Image

import pipeline as P
import baseline as B
from model import IconEmbedder

SCALES = [3.0]
SHRINK = [1.0, 0.6, 0.4, 0.3]     # 1.0 = as drawn; 0.3 = a very crowded box


def shrink_then_fit(icon, factor, side):
    """Lose detail the way a small drawing does, then feed it at model size."""
    im = Image.fromarray(icon.astype(np.uint8))
    if factor < 1.0:
        w = max(3, int(round(im.width * factor)))
        h = max(3, int(round(im.height * factor)))
        im = im.resize((w, h), Image.BILINEAR)
    return np.asarray(im.resize((side, side), Image.BILINEAR), dtype=np.float32) / 255.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--threshold", type=float, default=0.20)
    ap.add_argument("--side", type=int, default=32)
    args = ap.parse_args()

    slots, boxes = {}, {}
    for pdf in args.pdfs:
        doc = fitz.open(pdf)
        start = int(doc.page_count * (1 - args.holdout))
        for scale in SCALES:
            for page in range(start, doc.page_count):
                for bi, si, icon in P.iter_page_icons(doc, page, scale):
                    slots.setdefault((pdf, page, bi, si), []).append(icon)
                    boxes.setdefault((pdf, page, bi), set()).add((pdf, page, bi, si))
        doc.close()
    keys = sorted(slots)
    print(f"слотов {len(keys)}, рамок {len(boxes)}")

    net = IconEmbedder()
    net.load_state_dict(torch.load(args.model, map_location="cpu"))
    net.eval()

    # one embedding per (slot, shrink factor)
    emb = {}
    for f in SHRINK:
        imgs, asps = [], []
        for k in keys:
            icon = slots[k][0]
            h, w = icon.shape[:2]
            imgs.append(shrink_then_fit(icon, f, args.side))
            asps.append(float(np.log(w / h)))
        x = torch.from_numpy(np.stack(imgs)).permute(0, 3, 1, 2)
        a = torch.tensor(asps, dtype=torch.float32)
        out = []
        with torch.no_grad():
            for s in range(0, len(x), 256):
                out.append(net(x[s:s + 256], a[s:s + 256]).numpy())
        emb[f] = np.concatenate(out)
    pos_of = {k: i for i, k in enumerate(keys)}

    # negatives that neither colour nor proportions can settle
    sig = {k: B.signature(slots[k][0]) for k in keys}
    hard = []
    for bkey, ks in boxes.items():
        ks = sorted(ks)
        for a in range(len(ks)):
            for b in range(a + 1, len(ks)):
                sa, sb = sig[ks[a]], sig[ks[b]]
                if (float(np.max(np.abs(sa["avg"] - sb["avg"]))) < 30
                        and abs(sa["logasp"] - sb["logasp"]) < 0.10):
                    hard.append((pos_of[ks[a]], pos_of[ks[b]]))
    print(f"трудных пар (цвет и пропорции не помогают): {len(hard)}\n")

    print(f"вход модели {args.side}x{args.side}, порог {args.threshold}")
    print(f"  {'как нарисованы':<28}{'склейки':>10}{'мин. расст.':>14}")
    for fa in SHRINK:
        for fb in SHRINK:
            if fa > fb:
                continue
            d = np.linalg.norm(emb[fa][[p[0] for p in hard]] -
                               emb[fb][[p[1] for p in hard]], axis=1)
            label = "обе как есть" if fa == fb == 1.0 else f"{fa:g} против {fb:g}"
            print(f"  {label:<28}{(d <= args.threshold).mean()*100:>9.2f}%{d.min():>14.3f}")

    # the same-part side: shrinking must NOT push one part into two rows
    print(f"\n  {'одна деталь, разный размер':<28}{'дубли':>10}{'макс. расст.':>14}")
    for f in SHRINK[1:]:
        d = np.linalg.norm(emb[1.0] - emb[f], axis=1)
        print(f"  {'как есть против ' + format(f, 'g'):<28}"
              f"{(d > args.threshold).mean()*100:>9.2f}%{d.max():>14.3f}")


if __name__ == "__main__":
    main()
