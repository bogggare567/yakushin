"""The digit shapes, and the pieces of the pipeline that need no PDF.

Small on purpose: enough to catch the two ways this half breaks silently — the
template file moving or changing format, and the run-finding that every split
in the extractor is built on.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import glyphs as G
import pipeline as P


def test_templates_load():
    assert len(G.TEMPLATES) >= 10, "мало шаблонов цифр"
    labels = {lab for lab, _ in G.TEMPLATES}
    assert "x" in labels, 'нет шаблона "x" — количества не прочитать'
    assert labels & set("0123456789"), "нет ни одной цифры"
    for lab, bits in G.TEMPLATES:
        assert bits.shape == (G.GLYPH_W * G.GLYPH_H,), f"размер шаблона {lab}"


def test_a_template_recognises_itself():
    """Rendered back at its own size, a template must be its own nearest match.

    Not a tautology: it goes through the same normalise() the real reader uses,
    so this fails if that scaling ever stops being the inverse of how the
    templates were made.
    """
    for lab, bits in G.TEMPLATES:
        mask = bits.reshape(G.GLYPH_H, G.GLYPH_W)
        ys, xs = np.where(mask)
        if not len(xs):
            continue
        got, dist = G.classify(mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
        assert dist <= G.ICON_DIST, f"{lab} не узнаёт сам себя: {got} на {dist}"


def test_find_runs():
    assert P.find_runs([1, 1, 0, 0, 0, 1, 1], 2) == [(0, 2), (5, 7)]
    # a gap shorter than the minimum is not a gap
    assert P.find_runs([1, 1, 0, 1, 1], 3) == [(0, 5)]
    assert P.find_runs([0, 0, 0], 1) == []


def test_looks_like_part_rejects_a_speck():
    bg = np.array([215, 238, 254])
    icon = np.tile(bg.astype(np.uint8), (40, 40, 1))
    icon[19:21, 19:21] = [0, 0, 0]      # four black pixels and nothing else
    assert not P.looks_like_part(icon, bg, 1.5)


def test_looks_like_part_accepts_a_drawn_block():
    bg = np.array([215, 238, 254])
    icon = np.tile(bg.astype(np.uint8), (60, 90, 1))
    icon[10:50, 10:80] = [200, 60, 60]
    icon[10:20, 10:80] = [240, 110, 110]   # a lit top face, as a drawing has
    assert P.looks_like_part(icon, bg, 1.5)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  ПАДАЕТ  {name}: {e}")
    sys.exit(1 if failed else 0)
