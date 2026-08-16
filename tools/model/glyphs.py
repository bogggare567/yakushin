"""The digit shapes the booklets print, read from the file the app itself uses.

webapp/glyph-templates.js is the single copy: a second table here would drift
from it silently, and then the training pipeline would be cutting callouts by
one alphabet while the shipped app cut them by another.
"""
import os
import re

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_JS = os.path.join(_HERE, "..", "..", "webapp", "glyph-templates.js")

GLYPH_W, GLYPH_H = 22, 30
MAX_DIST = round(GLYPH_W * GLYPH_H * 0.22)        # the quantity reader's tolerance
ICON_DIST = round(GLYPH_W * GLYPH_H * 0.145)      # "this shape IS a digit"


def _unpack(hex_bits, n):
    out = np.zeros(n, dtype=np.uint8)
    i = 0
    for ch in hex_bits:
        v = int(ch, 16)
        for shift in (3, 2, 1, 0):
            if i < n:
                out[i] = (v >> shift) & 1
                i += 1
    return out


def _load():
    src = open(_TEMPLATE_JS, encoding="utf-8").read()
    pairs = re.findall(r'label:\s*"(.+?)",\s*bits:\s*"([0-9a-f]+)"', src)
    if not pairs:
        raise RuntimeError(f"нет шаблонов цифр в {_TEMPLATE_JS}")
    return [(lab, _unpack(bits, GLYPH_W * GLYPH_H)) for lab, bits in pairs]


TEMPLATES = _load()


def normalise(mask):
    """A component's own pixels, scaled into the template's box the same way
    resizeGlyphMask() does in the browser."""
    sh, sw = mask.shape
    pad = 2
    scale = min((GLYPH_W - 2 * pad) / sw, (GLYPH_H - 2 * pad) / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    ox, oy = (GLYPH_W - nw) // 2, (GLYPH_H - nh) // 2
    out = np.zeros((GLYPH_H, GLYPH_W), dtype=np.uint8)
    ys = np.minimum(sh - 1, (np.arange(nh) / scale).astype(int))
    xs = np.minimum(sw - 1, (np.arange(nw) / scale).astype(int))
    out[oy:oy + nh, ox:ox + nw] = mask[np.ix_(ys, xs)]
    return out.ravel()


def classify(mask):
    """(label, distance in mismatched bits) against the nearest template."""
    bits = normalise(mask)
    best_label, best_dist = "?", 10 ** 9
    for label, tpl in TEMPLATES:
        d = int(np.count_nonzero(bits != tpl))
        if d < best_dist:
            best_label, best_dist = label, d
    return best_label, best_dist
