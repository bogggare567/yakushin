"""Silhouette geometry for measuring a part's size in studs.

The size in studs is what the matcher keeps getting wrong — a 6x6 plate put in
with an 8x8 — and it is also the most useful thing to print next to a part,
because "4x6 plate" is how a person actually looks for one in a pile.

Nobody is going to label three thousand icons, so it has to be measured. The
booklet is drawn in one fixed isometric view, which makes the geometry rigid:
for a top face spanned by W and L studs,

    silhouette width            = scale * (W + L)
    right corner - left corner  = scale * ISO_RATIO * (W - L)

This file is only the measuring end of that. The scale is unknown and differs
from box to box, and recovering it is done globally over the whole document in
studs_global.py — see there for why box-by-box does not work.

Three earlier attempts at the same thing are recorded in the README with the
numbers that killed them: two-dimensional autocorrelation peaks, greatest
common divisor of the corner drops, and one-dimensional correlation along the
now-known lattice direction.
"""
import numpy as np

import pipeline as P

MAX_STUDS = 24
# Vertical step over horizontal one. The booklet is drawn with one fixed
# camera, so this is a single number for the whole document rather than
# something to estimate per box — measured at 0.442 on both booklets (10th to
# 90th percentile 0.415..0.463) from the principal axis of long thin parts,
# which follows a lattice direction without needing any unit or stud count.
ISO_RATIO = 0.442


def foreground(icon):
    return P.diff_mask(icon)


def _detail(icon):
    """Luminance with the flat background taken out."""
    lum = icon.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    fg = foreground(icon)
    if fg.sum() < 20:
        return None
    lum = lum - lum[fg].mean()
    lum[~fg] = 0.0
    return lum


def corners(icon):
    """(width, right corner minus left corner) of the silhouette, in pixels.

    Measured between two corners of the top face, never from its topmost point.
    The topmost pixel of a studded part is the top of a stud, which sticks up
    above the face by a fixed amount — an offset that is not a whole number of
    steps and quietly broke an earlier version of this, reading 1x6 plates as
    5x1. Both numbers here are differences between two corners, so it cancels:

        width               = a * (W + L)
        right corner - left = a * ISO_RATIO * (W - L)

    The leftmost column of a plate is a short vertical edge — the corner of the
    top face, with the thickness below it — so its top is the corner wanted,
    and that holds for a brick too, where the thickness is much larger.
    """
    fg = foreground(icon)
    if fg.sum() < 20:
        return None
    ys, xs = np.nonzero(fg)
    xl, xr = xs.min(), xs.max()
    y_left = float(ys[xs == xl].min())
    y_right = float(ys[xs == xr].min())
    width = float(xr - xl)
    if width < 4:
        return None
    return width, y_right - y_left
