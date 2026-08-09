"""Did the old rule get these right, and the model lose it?

The model replaced a 14x14 colour grid. It is much better on the pairs both can
be measured on — but the hand-checked mistakes are a class neither was measured
on, and a 14x14 grid compared pixel-by-pixel is, for all its faults, sensitive
to fine surface detail in a way a 32x32 net with three poolings is not.

If the old rule separates what the model merges, the answer is not a better net
but keeping the part of the old rule that still earns its place.

Usage: compare_old.py file.pdf [--truth groundtruth.json]
"""
import argparse, json, os
import numpy as np
import torch

import baseline as B
from audit import load_icons, embed_batch
from model import IconEmbedder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--truth", default="groundtruth.json")
    ap.add_argument("--pages", type=int, default=400)
    args = ap.parse_args()

    icons, pages_of = load_icons(args.pdf, args.pages, f".icons_{os.path.basename(args.pdf)}.pkl")
    ordinal, seen = [], {}
    for p in pages_of:
        seen[p] = seen.get(p, -1) + 1
        ordinal.append(seen[p])
    where = {(p, o): i for i, (p, o) in enumerate(zip(pages_of, ordinal))}

    net = IconEmbedder()
    net.load_state_dict(torch.load("model.pt", map_location="cpu"))
    net.eval()
    emb = embed_batch(net, icons)

    print(f"  {'страницы':<26}{'модель':>9}{'сетка 14x14':>14}{'старое правило':>17}")
    kept = 0
    truth = json.load(open(args.truth))
    for pr in truth["pairs"]:
        ia = [where[tuple(k)] for k in pr["a"] if tuple(k) in where]
        ib = [where[tuple(k)] for k in pr["b"] if tuple(k) in where]
        if not ia or not ib:
            continue
        dm = min(float(np.linalg.norm(emb[x] - emb[y])) for x in ia for y in ib)
        sa = [B.signature(icons[x]) for x in ia]
        sb = [B.signature(icons[y]) for y in ib]
        dg = min(B.grid_dist(x, y) for x in sa for y in sb)
        same = any(B.same_part(x, y) for x in sa for y in sb)
        if not same:
            kept += 1
        lbl = f"{sorted({k[0] for k in pr['a']})[:2]}/{sorted({k[0] for k in pr['b']})[:2]}"
        print(f"  {lbl:<26}{dm:>9.3f}{dg:>14.1f}{('склеит' if same else 'разделит'):>17}")

    print(f"\nстарое правило разделяет {kept} из {len(truth['pairs'])} "
          f"(порог сетки {B.SIG_DIST_TOL})")


if __name__ == "__main__":
    main()
