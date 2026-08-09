"""Freeze hand-checked mistakes into a ground-truth file.

The pairs the model gets wrong are the ones the booklets cannot label by
themselves: a 6x6 plate against an 8x8, a smooth tile against a studded plate.
Those two almost never share a callout box, so no amount of automatic pair
building will ever produce them, and the certain-pair QC scores a clean 0%
while the real file is visibly wrong.

The only source of truth for that class is somebody looking. This writes what
was looked at into a file, so it is checked on every future model instead of
being re-discovered by the client.

Each entry: one row the app produced, split into the two parts it should have
been, identified as (page, position on page) so it survives re-extraction.

Usage: make_groundtruth.py file.pdf --rows "64 58 83 ..." [--out groundtruth.json]
"""
import argparse, json, os, pickle
import numpy as np
import torch

from audit import load_icons, embed_batch, bucket, two_means
from model import IconEmbedder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--rows", required=True, help="номера строк, признанные склейками")
    ap.add_argument("--tol", type=float, default=0.20)
    ap.add_argument("--pages", type=int, default=400)
    ap.add_argument("--note", default="")
    ap.add_argument("--model", default="model.pt")
    ap.add_argument("--out", default="groundtruth.json")
    args = ap.parse_args()

    cache = f".icons_{os.path.basename(args.pdf)}.pkl"
    icons, pages_of = load_icons(args.pdf, args.pages, cache)
    # position of each icon within its own page, so an entry survives re-extraction
    ordinal, seen = [], {}
    for p in pages_of:
        seen[p] = seen.get(p, -1) + 1
        ordinal.append(seen[p])

    net = IconEmbedder()
    net.load_state_dict(torch.load(args.model, map_location="cpu"))
    net.eval()
    emb = embed_batch(net, icons)
    rows = bucket(emb, args.tol)

    want = {int(t) for t in args.rows.replace(",", " ").split()}
    out = {"pdf": os.path.basename(args.pdf), "note": args.note, "pairs": []}
    for r in sorted(want):
        idx = np.array(rows[r]["idx"])
        res = two_means(emb[idx])
        if res is None:
            print(f"  строка {r}: не делится, пропускаю")
            continue
        lab, gap = res
        a = [[int(pages_of[i]), int(ordinal[i])] for i in idx[~lab]]
        b = [[int(pages_of[i]), int(ordinal[i])] for i in idx[lab]]
        out["pairs"].append({"row": int(r), "gap": round(float(gap), 3), "a": a, "b": b})
        print(f"  строка {r:>4}: {len(a)} против {len(b)}, разрыв {gap:.3f}")

    with open(args.out, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"\n{len(out['pairs'])} проверенных вручную склеек -> {args.out}")


if __name__ == "__main__":
    main()
