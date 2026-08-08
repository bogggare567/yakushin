"""The matching rule that ships today (webapp/app.js, v1.7.0), ported so the
model can be judged against it on identical pairs rather than in a vacuum."""
import math
import numpy as np
from PIL import Image
import pipeline as P

SIG_SIZE = 14
SIG_MARGIN = 2
SIG_MAX_SHIFT = 2
SIG_DIST_TOL = 40
COLOR_TOL = 24
COLOR_TOL_STRONG_SHAPE = 40
STRONG_SHAPE_DIST = 20
COLOR_MODE_BIN = 32
COLOR_MODE_AMBIGUOUS_SHARE = 0.10
COLOR_MODE_MERGE_RADIUS = 45
BG = P.BOX_BG


def dominant_color(icon):
    fg = P.diff_mask(icon)
    pix = icon[fg]
    if len(pix) == 0:
        return BG.astype(float)
    keys = ((pix[:, 0] // COLOR_MODE_BIN).astype(np.int64) * 10000 +
            (pix[:, 1] // COLOR_MODE_BIN).astype(np.int64) * 100 +
            (pix[:, 2] // COLOR_MODE_BIN).astype(np.int64))
    uniq, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    b = int(np.argmax(counts))
    if counts[b] / len(pix) >= COLOR_MODE_AMBIGUOUS_SHARE:
        return pix[inv == b].mean(axis=0)
    means = np.array([pix[inv == i].mean(axis=0) for i in range(len(uniq))])
    pi = pix.astype(int)
    best_s, best_c = -1, means[0]
    for m in means:
        s = int((np.max(np.abs(pi - m.astype(int)), axis=1) <= COLOR_MODE_MERGE_RADIUS).sum())
        if s > best_s:
            best_s, best_c = s, m
    near = pix[np.max(np.abs(pi - best_c.astype(int)), axis=1) <= COLOR_MODE_MERGE_RADIUS]
    return near.mean(axis=0) if len(near) else best_c


def signature(icon):
    ch, cw = icon.shape[:2]
    avg = dominant_color(icon)
    scale = min((SIG_SIZE - 2 * SIG_MARGIN) / cw, (SIG_SIZE - 2 * SIG_MARGIN) / ch)
    nw, nh = max(1, round(cw * scale)), max(1, round(ch * scale))
    grid = np.tile(BG.astype(float), (SIG_SIZE, SIG_SIZE, 1))
    ox, oy = (SIG_SIZE - nw) // 2, (SIG_SIZE - nh) // 2
    small = np.asarray(Image.fromarray(icon.astype(np.uint8)).resize((nw, nh), Image.BILINEAR), dtype=float)
    grid[oy:oy + nh, ox:ox + nw] = small
    fg = np.max(np.abs(grid - BG), axis=-1) > P.FG_DIFF_THRESHOLD
    return {"grid": grid, "fg": fg, "avg": avg}


def grid_dist(a, b):
    best = math.inf
    ag, af = a["grid"], a["fg"]
    for dy in range(-SIG_MAX_SHIFT, SIG_MAX_SHIFT + 1):
        for dx in range(-SIG_MAX_SHIFT, SIG_MAX_SHIFT + 1):
            bg = np.zeros_like(ag)
            bf = np.zeros_like(af)
            ys, yd = slice(max(0, -dy), SIG_SIZE - max(0, dy)), slice(max(0, dy), SIG_SIZE - max(0, -dy))
            xs, xd = slice(max(0, -dx), SIG_SIZE - max(0, dx)), slice(max(0, dx), SIG_SIZE - max(0, -dx))
            bg[ys, xs] = b["grid"][yd, xd]
            bf[ys, xs] = b["fg"][yd, xd]
            both = af & bf
            only = af ^ bf
            n = int(both.sum() + only.sum())
            if n == 0:
                continue
            s = float(np.abs(ag[both] - bg[both]).sum())
            best = min(best, (s + int(only.sum()) * 255 * 3) / (n * 3))
    return best


def color_dist(a, b):
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b))))


def same_part(sa, sb):
    """Exactly the shipped findBucket() test."""
    cd = color_dist(sa["avg"], sb["avg"])
    if cd > COLOR_TOL_STRONG_SHAPE:
        return False
    gd = grid_dist(sa, sb)
    if gd > SIG_DIST_TOL:
        return False
    return cd <= (COLOR_TOL_STRONG_SHAPE if gd <= STRONG_SHAPE_DIST else COLOR_TOL)
