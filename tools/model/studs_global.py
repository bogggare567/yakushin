"""Solve every part's size and every box's scale at once.

Estimating the drawing scale box by box does not work: a box holds five or six
icons, the scale is free, and several different scales explain them about
equally well. Two earlier attempts failed exactly there — autocorrelation peaks
that were not even mirror images, and a step search that read 1x8 plates as
7x1.

The way out is that the booklet says the same thing many times. One part appears
in dozens of boxes at dozens of scales, and the matcher already knows which
icons are the same part. So for every icon:

    width           = scale(its box) * (W + L)(its part)
    right - left    = scale(its box) * ISO_RATIO * (W - L)(its part)

Every box scale is shared by the icons in it, every part size is shared by the
icons of it, and with a thousand icons over four hundred boxes the system is
enormously over-determined. Solved by alternating least squares, which is the
same shape as calibrating a camera from repeated views.

One freedom is left over: multiplying every scale by c and dividing every size
by c fits equally well. That is settled at the end by the only thing that can
settle it — sizes have to be whole numbers, and W+L and W-L have to agree on
being both even or both odd. Searching one number for the best whole-number
agreement across the whole booklet is a far stronger constraint than anything
available inside a single box.

Usage: studs_global.py file.pdf [--tol 0.25] [--sheet studs_global.png]
"""
import argparse, json, os
import numpy as np
import torch
from PIL import Image, ImageDraw

import baseline as B
import studs as S
import pipeline as P
from audit import embed_batch
from regression import bucket_with_vetoes
from model import IconEmbedder
import fitz

MAX_TOTAL = 24     # the largest W+L worth entertaining


def load(pdf, pages, cache):
    """Icons plus which page and which callout box each came from."""
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            import pickle
            d = pickle.load(f)
        if d.get("pdf") == pdf and d.get("pages") == pages and "box_ids" in d:
            print(f"кэш: {len(d['icons'])} иконок")
            return d["icons"], d["pages_of"], d["box_ids"]
    doc = fitz.open(pdf)
    n = min(pages, doc.page_count)
    icons, pages_of, box_ids = [], [], []
    for p in range(n):
        for bi, si, icon in P.iter_page_icons(doc, p):
            icons.append(icon)
            pages_of.append(p + 1)
            box_ids.append((p + 1, bi))
        if (p + 1) % 100 == 0:
            print(f"  стр. {p+1}/{n}", flush=True)
    doc.close()
    import pickle
    with open(cache, "wb") as f:
        pickle.dump({"pdf": pdf, "pages": pages, "icons": icons,
                     "pages_of": pages_of, "box_ids": box_ids}, f)
    return icons, pages_of, box_ids


def solve(width, ydiff, box_of, row_of, n_boxes, n_rows, iters=60):
    """Alternating least squares for scale-per-box and size-per-part."""
    scale = np.ones(n_boxes)
    size = np.ones(n_rows)        # W + L
    diff = np.zeros(n_rows)       # W - L
    R = S.ISO_RATIO
    for _ in range(iters):
        # parts, given the scales
        for arr, obs, k in ((size, width, 1.0), (diff, ydiff, R)):
            num = np.zeros(n_rows)
            den = np.zeros(n_rows)
            np.add.at(num, row_of, k * scale[box_of] * obs)
            np.add.at(den, row_of, (k * scale[box_of]) ** 2)
            arr[:] = np.where(den > 0, num / np.maximum(den, 1e-9), arr)
        # scales, given the parts
        pred_w = size[row_of]
        pred_d = R * diff[row_of]
        num = np.zeros(n_boxes)
        den = np.zeros(n_boxes)
        np.add.at(num, box_of, pred_w * width + pred_d * ydiff)
        np.add.at(den, box_of, pred_w ** 2 + pred_d ** 2)
        scale[:] = np.where(den > 0, num / np.maximum(den, 1e-9), scale)
    return scale, size, diff


def pick_global_scale(size, diff, weight):
    """The one number left free, chosen so the sizes come out whole.

    Scanned over the range the data itself implies rather than a guessed one:
    the smallest part in a booklet is a 1x1, so W+L is at least 2, and nothing
    is larger than about 2*MAX_STUDS. An earlier version searched 0.25..4 and
    settled on the edge of its own range, reporting parts as 137x18.
    """
    use = weight > 0
    lo = 2.0 / max(size[use].max(), 1e-9)
    hi = 2.0 * MAX_TOTAL / max(np.percentile(size[use], 5), 1e-9)
    best, best_score = None, -1e18
    for c in np.arange(lo, hi, (hi - lo) / 12000):
        s, d = size * c, diff * c
        ks, kd = np.round(s), np.round(d)
        ok = ((np.abs(s - ks) < 0.15) & (np.abs(d - kd) < 0.15)
              & ((ks + kd) % 2 == 0) & (ks >= 2) & (ks <= 2 * S.MAX_STUDS)
              & (np.abs(kd) < ks))
        # the share of parts explained, not the count: a scale that makes
        # everything huge would otherwise win by having more chances to be
        # near a whole number
        score = float((weight * ok).sum() / max(weight.sum(), 1e-9))
        if score > best_score:
            best_score, best = score, float(c)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--model", default="model.pt")
    ap.add_argument("--tol", type=float, default=0.25)
    ap.add_argument("--color", type=float, default=45)
    ap.add_argument("--aspect", type=float, default=0.15)
    ap.add_argument("--pages", type=int, default=400)
    ap.add_argument("--sheet", default="studs_global.png")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    icons, pages_of, box_ids = load(args.pdf, args.pages,
                                    f".boxicons_{os.path.basename(args.pdf)}.pkl")
    net = IconEmbedder()
    net.load_state_dict(torch.load(args.model, map_location="cpu"))
    net.eval()
    emb = embed_batch(net, icons)
    cols = np.stack([B.dominant_color(ic) for ic in icons])
    asps = np.array([float(np.log(ic.shape[1] / ic.shape[0])) for ic in icons])
    rows = bucket_with_vetoes(emb, cols, asps, args.tol, args.color, args.aspect)
    row_of = np.zeros(len(icons), dtype=int)
    for r, row in enumerate(rows):
        for i in row["idx"]:
            row_of[i] = r

    uniq_boxes = {b: i for i, b in enumerate(sorted(set(box_ids)))}
    box_of = np.array([uniq_boxes[b] for b in box_ids])

    cs = [S.corners(ic) for ic in icons]
    keep = np.array([c is not None for c in cs])
    width = np.array([c[0] if c else 0.0 for c in cs])
    ydiff = np.array([c[1] if c else 0.0 for c in cs])
    print(f"иконок {len(icons)}, строк {len(rows)}, рамок {len(uniq_boxes)}, "
          f"пригодных силуэтов {int(keep.sum())}")

    k = np.where(keep)[0]
    scale, size, diff = solve(width[k], ydiff[k], box_of[k], row_of[k],
                              len(uniq_boxes), len(rows))
    resid = np.abs(width[k] - scale[box_of[k]] * size[row_of[k]]) / np.maximum(width[k], 1)
    print(f"невязка по ширине: медиана {np.median(resid)*100:.1f}%, "
          f"90% {np.percentile(resid,90)*100:.1f}%")

    weight = np.zeros(len(rows))
    np.add.at(weight, row_of[k], 1.0)
    c = pick_global_scale(size, diff, weight)
    s, d = size * c, diff * c
    ks, kd = np.round(s), np.round(d)
    ok = ((np.abs(s - ks) < 0.15) & (np.abs(d - kd) < 0.15)
          & ((ks + kd) % 2 == 0) & (ks >= 2) & (np.abs(kd) < ks))
    W = ((ks + kd) / 2).astype(int)
    L = ((ks - kd) / 2).astype(int)
    got = {r: (int(max(W[r], L[r])), int(min(W[r], L[r]))) for r in range(len(rows)) if ok[r]}
    covered = sum(weight[r] for r in got)
    print(f"общий множитель {c:.4f}")
    print(f"строк с целым размером: {len(got)} из {len(rows)} "
          f"({covered/max(1,weight.sum())*100:.0f}% деталей)")

    hist = {}
    for r, v in got.items():
        hist[v] = hist.get(v, 0) + 1
    print("\nчаще всего:")
    for v, n in sorted(hist.items(), key=lambda kv: -kv[1])[:16]:
        print(f"   {v[0]}x{v[1]:<3} {n} строк")

    # contact sheet, biggest rows first so the common parts get checked
    order = sorted(got, key=lambda r: -weight[r])[:81]
    cell, ncol = 130, 9
    nrow = (len(order) + ncol - 1) // ncol
    img = Image.new("RGB", (ncol * cell, nrow * (cell + 20) + 6), (22, 24, 30))
    dr = ImageDraw.Draw(img)
    for i, r in enumerate(order):
        ic = Image.fromarray(icons[rows[r]["idx"][0]].astype(np.uint8))
        ic.thumbnail((cell - 8, cell - 8))
        x, y = (i % ncol) * cell, (i // ncol) * (cell + 20)
        img.paste(ic, (x + (cell - ic.width) // 2, y + (cell - ic.height) // 2))
        dr.text((x + 5, y + cell + 3), f"{got[r][0]}x{got[r][1]}  x{int(weight[r])}",
                fill=(150, 220, 160))
    img.save(args.sheet)
    print(f"\n-> {args.sheet}")

    if args.out:
        json.dump({"pdf": os.path.basename(args.pdf),
                   "sizes": {f"{pages_of[rows[r]['idx'][0]]}:{r}": got[r] for r in got}},
                  open(args.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
