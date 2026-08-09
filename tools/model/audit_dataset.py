"""Is the training set clean?

Every label here is produced by a rule rather than by a person, which is what
makes the set possible at all — and also what makes it worth auditing, because
a rule that is wrong is wrong thousands of times without anyone noticing.

Two rules, two ways they can break:

  ПОЛОЖИТЕЛЬНЫЕ  "the same slot at another scale is the same part". This holds
                 only if slot number 3 of a box means the same part at every
                 scale. If the box is cut into a different number of slots at
                 one scale, the numbering shifts and the model is being taught
                 that two unrelated parts are identical — the worst possible
                 lesson, taught silently.

  ОТРИЦАТЕЛЬНЫЕ  "two slots of one box are different parts". This holds only if
                 each slot is one part. If a single icon gets cut in half, the
                 two halves become a certain-different pair, and the model is
                 taught to split one part in two — which is the bug the whole
                 project is fighting.

Neither needs labels to check. The first is a counting question. The second is
answered by the parts themselves: two slots of one box that look the same,
have the same colour and the same measured stud size were almost certainly one
part before something cut it.

Usage: audit_dataset.py file1.pdf [file2.pdf ...]
"""
import argparse
from collections import defaultdict

import numpy as np
import torch
import fitz

import baseline as B
import pipeline as P
import studs_count as SC
from model import IconEmbedder, IN_SIDE
from PIL import Image

SCALES = [3.0, 2.4, 1.9]
SAME_EMB = 0.12       # closer than this and two icons are the same picture
SAME_COLOUR = 8.0     # and the same colour


def embed(net, icons):
    imgs, asps = [], []
    for icon in icons:
        h, w = icon.shape[:2]
        im = Image.fromarray(icon.astype(np.uint8)).resize((IN_SIDE, IN_SIDE), Image.BILINEAR)
        imgs.append(np.asarray(im, dtype=np.float32) / 255.0)
        asps.append(float(np.log(w / h)))
    x = torch.from_numpy(np.stack(imgs)).permute(0, 3, 1, 2)
    a = torch.tensor(asps, dtype=torch.float32)
    out = []
    with torch.no_grad():
        for s in range(0, len(x), 256):
            out.append(net(x[s:s + 256], a[s:s + 256]).numpy())
    return np.concatenate(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    net = IconEmbedder()
    net.load_state_dict(torch.load("model.pt", map_location="cpu"))
    net.eval()

    slots_per_box = defaultdict(dict)      # (pdf,page,box) -> {scale: n slots}
    box_icons = defaultdict(list)          # (pdf,page,box) -> [(slot, icon)] at 3.0
    for pdf in args.pdfs:
        doc = fitz.open(pdf)
        name = pdf.split("/")[-1]
        for scale in SCALES:
            counts = defaultdict(int)
            for page in range(doc.page_count):
                for bi, si, icon in P.iter_page_icons(doc, page, scale):
                    counts[(name, page, bi)] += 1
                    if scale == SCALES[0]:
                        box_icons[(name, page, bi)].append((si, icon))
            for k, v in counts.items():
                slots_per_box[k][scale] = v
        doc.close()
        print(f"  {name}: рамок {sum(1 for k in slots_per_box if k[0] == name)}", flush=True)

    # ---- 1. does a slot number mean the same part at every scale? ----
    mismatch = [(k, v) for k, v in slots_per_box.items()
                if len(set(v.values())) > 1 or len(v) < len(SCALES)]
    total_boxes = len(slots_per_box)
    bad_slots = sum(max(v.values()) for _, v in mismatch)
    all_slots = sum(max(v.values()) for v in slots_per_box.values())
    print(f"\n=== ПОЛОЖИТЕЛЬНЫЕ: одинаковая ли нарезка во всех масштабах")
    print(f"  рамок {total_boxes}, из них режутся по-разному: {len(mismatch)} "
          f"({len(mismatch)/max(1,total_boxes)*100:.1f}%)")
    print(f"  затронуто слотов: {bad_slots} из {all_slots} "
          f"({bad_slots/max(1,all_slots)*100:.1f}%)")
    for k, v in mismatch[:args.show]:
        print(f"    {k[0][:18]} стр.{k[1]+1} рамка {k[2]}: "
              + ", ".join(f"{s}->{n}" for s, n in sorted(v.items())))

    # ---- 2. are two slots of one box ever the same part? ----
    print(f"\n=== ОТРИЦАТЕЛЬНЫЕ: не разрезана ли одна деталь надвое")
    suspects, pairs_total = [], 0
    for key, entries in box_icons.items():
        if len(entries) < 2:
            continue
        icons = [ic for _, ic in entries]
        emb = embed(net, icons)
        cols = [B.dominant_color(ic) for ic in icons]
        for a in range(len(icons)):
            for b in range(a + 1, len(icons)):
                pairs_total += 1
                d = float(np.linalg.norm(emb[a] - emb[b]))
                c = float(np.max(np.abs(cols[a] - cols[b])))
                if d < SAME_EMB and c < SAME_COLOUR:
                    suspects.append((d, c, key, entries[a][0], entries[b][0]))
    suspects.sort()
    print(f"  пар «разные детали» внутри рамок: {pairs_total}")
    print(f"  из них выглядят одинаково: {len(suspects)} "
          f"({len(suspects)/max(1,pairs_total)*100:.2f}%)")
    for d, c, key, sa, sb in suspects[:args.show]:
        print(f"    {key[0][:18]} стр.{key[1]+1} рамка {key[2]}: слоты {sa} и {sb}, "
              f"расстояние {d:.3f}, цвет {c:.0f}")


if __name__ == "__main__":
    main()
