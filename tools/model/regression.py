"""Do the hand-checked mistakes still happen?

Buckets the whole booklet with a candidate matcher and asks, for every pair in
groundtruth.json, whether the two parts that should be in separate rows ended
up in the same one. This is the check the certain-pair QC structurally cannot
do, because these pairs never share a callout box.

Also reports the price: how many rows the file ends up with. Splitting
everything into its own row would score a perfect zero here and be useless, so
the row count has to be read next to the errors.

Usage: regression.py file.pdf [--color 50] [--aspect 0.25] [--tol 0.20]
"""
import argparse, json, os
import numpy as np
import torch

import baseline as B
import studs_count as SC
from audit import load_icons, embed_batch
from model import IconEmbedder

STUD_MIN_AREA = 20000   # matches webapp/studs.js


def bucket_with_vetoes(emb, cols, asps, tol, color_veto, aspect_veto):
    """Nearest row by the model, but only among rows the vetoes allow.

    A veto is not a tie-breaker applied afterwards: a row that fails it is not
    a candidate at all, otherwise the nearest row could be a vetoed one and the
    icon would open a new row while a perfectly good row sat next to it.
    """
    rows = []
    for i in range(len(emb)):
        best, bd = -1, 9.0
        for r, row in enumerate(rows):
            if color_veto and float(np.max(np.abs(row["col"] - cols[i]))) > color_veto:
                continue
            if aspect_veto and abs(row["asp"] - asps[i]) > aspect_veto:
                continue
            d = float(np.linalg.norm(row["c"] - emb[i]))
            if d < bd:
                bd, best = d, r
        if best >= 0 and bd <= tol:
            rows[best]["idx"].append(i)
        else:
            rows.append({"c": emb[i], "col": cols[i], "asp": asps[i], "idx": [i]})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--truth", default="groundtruth.json")
    ap.add_argument("--model", default="model.pt")
    ap.add_argument("--tol", type=float, default=0.20)
    ap.add_argument("--color", type=float, default=0.0, help="0 = без вето по цвету")
    ap.add_argument("--aspect", type=float, default=0.0, help="0 = без вето по пропорциям")
    ap.add_argument("--pages", type=int, default=400)
    ap.add_argument("--no-studs", action="store_true",
                    help="без шага разделения по шипам — чтобы видеть его вклад")
    args = ap.parse_args()

    truth = json.load(open(args.truth))
    cache = f".icons_{os.path.basename(args.pdf)}.pkl"
    icons, pages_of = load_icons(args.pdf, args.pages, cache)
    ordinal, seen = [], {}
    for p in pages_of:
        seen[p] = seen.get(p, -1) + 1
        ordinal.append(seen[p])
    where = {(p, o): i for i, (p, o) in enumerate(zip(pages_of, ordinal))}

    net = IconEmbedder()
    net.load_state_dict(torch.load(args.model, map_location="cpu"))
    net.eval()
    emb = embed_batch(net, icons)
    cols = np.stack([B.dominant_color(ic) for ic in icons])
    asps = np.array([float(np.log(ic.shape[1] / ic.shape[0])) for ic in icons])

    rows = bucket_with_vetoes(emb, cols, asps, args.tol, args.color, args.aspect)

    # The app does one more thing after matching, and leaving it out of this
    # test was quietly overstating the errors: rows whose measured stud sizes
    # disagree get split. That is a real part of the pipeline, so it belongs
    # here — a harness that models less than the product measures the wrong
    # thing.
    if not args.no_studs:
        extra = []
        for row in rows:
            sizes = {}
            for i in row["idx"]:
                if icons[i].shape[0] * icons[i].shape[1] < STUD_MIN_AREA:
                    continue
                m = SC.measure(icons[i])
                if m:
                    sizes.setdefault(m[0], []).append(i)
            if len(sizes) < 2:
                continue
            ranked = sorted(sizes.values(), key=len, reverse=True)
            for moving in ranked[1:]:
                if len(moving) < 2:
                    continue
                row["idx"] = [i for i in row["idx"] if i not in set(moving)]
                extra.append({"idx": list(moving)})
        rows = rows + extra

    row_of = {}
    for r, row in enumerate(rows):
        for i in row["idx"]:
            row_of[i] = r

    print(f"порог {args.tol}   вето по цвету {args.color or '—'}   "
          f"вето по пропорциям {args.aspect or '—'}")
    print(f"иконок {len(icons)}, строк {len(rows)}\n")

    bad = 0
    for pr in truth["pairs"]:
        ra = {row_of[where[tuple(k)]] for k in pr["a"] if tuple(k) in where}
        rb = {row_of[where[tuple(k)]] for k in pr["b"] if tuple(k) in where}
        both = ra & rb
        mark = "СКЛЕЕНО" if both else "разделено"
        if both:
            bad += 1
        pages = sorted({k[0] for k in pr["a"]})[:3], sorted({k[0] for k in pr["b"]})[:3]
        print(f"  {mark:<10} стр.{pages[0]} против стр.{pages[1]}")

    print(f"\n{len(truth['pairs']) - bad} из {len(truth['pairs'])} исправлено, "
          f"осталось склеенными: {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
