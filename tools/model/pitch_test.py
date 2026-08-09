"""Can the stud grid itself be measured?

What is left after colour and proportions is almost all one thing: the same
shape with a different number of studs. A 6x6 plate and an 8x8 plate are the
same colour, the same proportions and, once the icon is squashed to 32x32, very
nearly the same picture.

But studs are a regular grid, and the number of them across the part is exactly
what a spatial frequency measures — and a frequency counted per part width does
not change when the booklet draws the part smaller. That is the one property
this whole problem needs.

An earlier attempt at this counted studs as an integer and was abandoned: the
count wandered by ten on one part. This measures the grid instead of counting
it, so blur costs sharpness rather than a whole stud.

Reports the gap on the hand-checked mistakes against the spread on parts that
are certainly the same, which is the only comparison that decides anything.

Usage: pitch_test.py file.pdf [file2.pdf ...]
"""
import argparse, json, os
import numpy as np
import fitz
from PIL import Image

import pipeline as P
from audit import load_icons

GRID = 64          # the icon is measured on this square
LOW = 2            # ignore the overall silhouette
HIGH = 16          # and anything finer than the studs can be


def lattice(icon):
    """Two numbers: how many stud-periods fit across the part, and how clearly.

    The icon is stretched to a square first, so the answer is per part width
    rather than per pixel — that is what makes it survive the booklet redrawing
    the same part at half the size.
    """
    im = Image.fromarray(icon.astype(np.uint8)).convert("L").resize((GRID, GRID), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float64)
    a -= a.mean()
    a *= np.outer(np.hanning(GRID), np.hanning(GRID))   # no edge-ringing peaks
    F = np.abs(np.fft.fftshift(np.fft.fft2(a)))
    c = GRID // 2
    yy, xx = np.mgrid[-c:c, -c:c]
    rr = np.hypot(yy, xx)
    band = (rr >= LOW) & (rr <= HIGH)
    if not band.any() or F[band].max() <= 0:
        return 0.0, 0.0
    F = F.copy()
    F[~band] = 0
    k = int(np.argmax(F))
    peak = float(rr.flat[k])
    # how much the grid stands out from everything else at that scale
    strength = float(F.flat[k] / (F[band].mean() + 1e-9))
    return peak, strength


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--truth", default="groundtruth.json")
    ap.add_argument("--pages", type=int, default=400)
    ap.add_argument("--holdout", type=float, default=0.2)
    args = ap.parse_args()

    icons, pages_of = load_icons(args.pdf, args.pages, f".icons_{os.path.basename(args.pdf)}.pkl")
    ordinal, seen = [], {}
    for p in pages_of:
        seen[p] = seen.get(p, -1) + 1
        ordinal.append(seen[p])
    where = {(p, o): i for i, (p, o) in enumerate(zip(pages_of, ordinal))}
    feats = [lattice(ic) for ic in icons]

    print("=== проверенные вручную склейки: что показывает решётка")
    print(f"  {'страницы':<28}{'шаг A':>8}{'шаг B':>8}{'разница':>10}{'чёткость':>20}")
    gaps = []
    for pr in json.load(open(args.truth))["pairs"]:
        fa = [feats[where[tuple(k)]] for k in pr["a"] if tuple(k) in where]
        fb = [feats[where[tuple(k)]] for k in pr["b"] if tuple(k) in where]
        if not fa or not fb:
            continue
        pa, sa = np.mean([f[0] for f in fa]), np.mean([f[1] for f in fa])
        pb, sb = np.mean([f[0] for f in fb]), np.mean([f[1] for f in fb])
        lbl = f"{sorted({k[0] for k in pr['a']})[:2]}/{sorted({k[0] for k in pr['b']})[:2]}"
        print(f"  {lbl:<28}{pa:>8.1f}{pb:>8.1f}{abs(pa-pb):>10.1f}{sa:>10.1f}{sb:>10.1f}")
        gaps.append(abs(pa - pb))

    # the price: the same slot drawn at three sizes must give the same answer
    doc = fitz.open(args.pdf)
    start = int(doc.page_count * (1 - args.holdout))
    slots = {}
    for scale in (3.0, 2.4, 1.9):
        for page in range(start, doc.page_count):
            for bi, si, icon in P.iter_page_icons(doc, page, scale):
                slots.setdefault((page, bi, si), []).append(lattice(icon)[0])
    doc.close()
    spread = np.array([max(v) - min(v) for v in slots.values() if len(v) > 1])
    print(f"\n=== одна и та же деталь в трёх масштабах ({len(spread)} слотов)")
    print(f"  разброс шага: среднее {spread.mean():.2f}  "
          f"95% {np.percentile(spread,95):.2f}  99% {np.percentile(spread,99):.2f}  "
          f"макс {spread.max():.2f}")
    print(f"\n  {'вето при разнице':>18}{'ложных разрывов':>18}{'пойманных склеек':>20}")
    for t in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        print(f"  {t:>18.1f}{(spread > t).mean()*100:>17.2f}%"
              f"{(np.array(gaps) > t).mean()*100:>19.0f}%")


if __name__ == "__main__":
    main()
