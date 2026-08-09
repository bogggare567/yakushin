"""Quality control.

Re-extracts icons from pages the model never trained on, builds the pairs whose
answer is certain, and scores BOTH the shipped algorithm and the model on the
exact same pairs. A model is only worth shipping if it beats the baseline on
both error kinds at once.

  duplicates  one real part split across several rows  (positives judged different)
  merges      several real parts collapsed into one    (negatives judged the same)

Usage: qc.py model.pt file1.pdf [file2.pdf ...] [--holdout 0.2] [--threshold T]
"""
import argparse, json
import numpy as np
import torch
import torch.nn.functional as F
import fitz
from PIL import Image

import pipeline as P
import baseline as B
from model import IconEmbedder, IN_SIDE

SCALES = [3.0, 2.4, 1.9]


HARD_COLOR = 30      # below this, colour cannot tell the two icons apart
HARD_ASPECT = 0.10   # below this, proportions cannot either


def collect(pdfs, holdout):
    """Icons from the held-out tail of each booklet, keyed by physical slot."""
    slots = {}   # (pdf,page,box,slot) -> list of icons, one per scale
    boxes = {}   # (pdf,page,box) -> set of slot keys
    for pdf in pdfs:
        doc = fitz.open(pdf)
        start = int(doc.page_count * (1 - holdout))
        for scale in SCALES:
            for page in range(start, doc.page_count):
                for bi, si, icon in P.iter_page_icons(doc, page, scale):
                    key = (pdf, page, bi, si)
                    slots.setdefault(key, []).append(icon)
                    boxes.setdefault((pdf, page, bi), set()).add(key)
        doc.close()
    return slots, boxes


def make_pairs(slots, boxes):
    pos, neg = [], []
    for key, icons in slots.items():
        for a in range(len(icons)):
            for b in range(a + 1, len(icons)):
                pos.append((key, a, key, b))
    for bkey, keys in boxes.items():
        keys = sorted(keys)
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                for ia in range(len(slots[keys[a]])):
                    for ib in range(len(slots[keys[b]])):
                        neg.append((keys[a], ia, keys[b], ib))
    return pos, neg


def embed_all(net, slots, device):
    keys, imgs, asps, index = [], [], [], {}
    for key, icons in slots.items():
        for i, icon in enumerate(icons):
            h, w = icon.shape[:2]
            im = Image.fromarray(icon.astype(np.uint8)).resize((IN_SIDE, IN_SIDE), Image.BILINEAR)
            index[(key, i)] = len(imgs)
            imgs.append(np.asarray(im, dtype=np.float32) / 255.0)
            asps.append(float(np.log(w / h)))
    x = torch.from_numpy(np.stack(imgs)).permute(0, 3, 1, 2).to(device)
    a = torch.tensor(asps, dtype=torch.float32, device=device)
    out = []
    net.eval()
    with torch.no_grad():
        for s in range(0, len(x), 512):
            out.append(net(x[s:s + 512], a[s:s + 512]).cpu().numpy())
    return np.concatenate(out), index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    slots, boxes = collect(args.pdfs, args.holdout)
    pos, neg = make_pairs(slots, boxes)
    print(f"held-out slots {len(slots)}, boxes {len(boxes)}")
    print(f"certain pairs: {len(pos)} same-part, {len(neg)} different-part\n")

    # ---- baseline: the rule that ships today ----
    sigs = {}
    for key, icons in slots.items():
        for i, icon in enumerate(icons):
            sigs[(key, i)] = B.signature(icon)
    b_dup = sum(0 if B.same_part(sigs[(ka, ia)], sigs[(kb, ib)]) else 1 for ka, ia, kb, ib in pos) / len(pos)
    b_mrg = sum(1 if B.same_part(sigs[(ka, ia)], sigs[(kb, ib)]) else 0 for ka, ia, kb, ib in neg) / len(neg)

    # ---- model ----
    net = IconEmbedder()
    net.load_state_dict(torch.load(args.model, map_location="cpu"))
    emb, index = embed_all(net, slots, "cpu")
    dp = np.array([np.linalg.norm(emb[index[(ka, ia)]] - emb[index[(kb, ib)]]) for ka, ia, kb, ib in pos])
    dn = np.array([np.linalg.norm(emb[index[(ka, ia)]] - emb[index[(kb, ib)]]) for ka, ia, kb, ib in neg])

    thr = args.threshold
    if thr is None:
        best, thr = 1e9, 0.5
        for t in np.linspace(0.02, 1.5, 300):
            e = (dp > t).mean() + (dn <= t).mean()
            if e < best:
                best, thr = e, float(t)

    m_dup = float((dp > thr).mean())
    m_mrg = float((dn <= thr).mean())

    # The overall merge rate is dominated by easy negatives — two parts of
    # obviously different colour or shape. What actually goes wrong in the app
    # is the subset where neither colour nor proportions can help, so measure
    # that separately or the headline number hides it.
    hard = np.array([
        float(np.max(np.abs(sigs[(ka, ia)]["avg"] - sigs[(kb, ib)]["avg"]))) < HARD_COLOR
        and abs(sigs[(ka, ia)]["logasp"] - sigs[(kb, ib)]["logasp"]) < HARD_ASPECT
        for ka, ia, kb, ib in neg])
    b_mrg_h = float(np.array([B.same_part(sigs[(ka, ia)], sigs[(kb, ib)])
                              for ka, ia, kb, ib in neg])[hard].mean()) if hard.any() else 0.0
    m_mrg_h = float((dn[hard] <= thr).mean()) if hard.any() else 0.0

    print(f"{'':<26}{'дубли':>10}{'склейки':>10}{'трудные склейки':>18}")
    print(f"{'алгоритм сейчас':<26}{b_dup*100:>9.2f}%{b_mrg*100:>9.2f}%{b_mrg_h*100:>17.2f}%")
    print(f"{'модель':<26}{m_dup*100:>9.2f}%{m_mrg*100:>9.2f}%{m_mrg_h*100:>17.2f}%")
    print(f"\nпорог модели: {thr:.3f}")
    print(f"трудных пар (цвет <{HARD_COLOR} и пропорции <{HARD_ASPECT}): "
          f"{int(hard.sum())} из {len(neg)}")
    print(f"расстояния: одинаковые детали {dp.mean():.3f} (макс {dp.max():.3f}), "
          f"разные {dn.mean():.3f} (мин {dn.min():.3f})")

    better = (m_dup <= b_dup) and (m_mrg <= b_mrg)
    print("\nВЕРДИКТ:", "модель лучше или не хуже по обоим показателям — можно ставить"
          if better else "модель НЕ лучше — ставить нельзя")

    result = {"baseline": {"duplicate_rate": b_dup, "merge_rate": b_mrg,
                           "merge_rate_hard": b_mrg_h},
              "model": {"duplicate_rate": m_dup, "merge_rate": m_mrg,
                        "merge_rate_hard": m_mrg_h, "threshold": thr},
              "n_pos": len(pos), "n_neg": len(neg), "n_hard": int(hard.sum()),
              "passes": bool(better)}
    if args.json_out:
        json.dump(result, open(args.json_out, "w"), indent=2)
    return 0 if better else 1


if __name__ == "__main__":
    raise SystemExit(main())
