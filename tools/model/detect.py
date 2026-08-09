"""Find the parts callouts on a page, whatever colour the booklet uses.

The old detector looked for one hard-coded light blue, which is the colour LEGO
happens to use for callout boxes in the Super Yacht booklets. Handed a set
whose *page* is light blue and whose callouts are a slightly darker blue with a
pink border, it flood-filled the entire page and reported one "part" per page.

Nothing about a specific colour is essential. What is essential, and what both
formats share, is the shape of the thing:

  * a callout is a rectangle of FLAT colour — one fill, no gradient, no texture;
  * that fill is not the page background;
  * it holds drawings, so it is not empty either.

So the page tells us its own background (whatever is most of it), flat regions
are found by asking whether each pixel's neighbourhood is uniform, and the ones
that are big, rectangular and non-empty are the callouts. A booklet that
changes its palette next year needs no code change.

One more thing is needed, and it is the same idea the rest of this project
runs on: confirmation from the document. A flat rectangle can also be the side
of a brick in an assembly drawing — a grey cylinder face, a red 2x4 seen
edge-on — and on a single page there is no telling those from a callout. But a
callout fill is the SAME colour on every page of the booklet, and a brick face
is not. So the fill is learned once from a sample of pages and then required.
"""
import numpy as np
from scipy import ndimage

RENDER_SCALE = 3.0
SCALE_REF = 2.0

FLAT_WINDOW = 5        # a fill is flat over at least this square
FLAT_TOL = 8           # and varies by no more than this inside it
BG_TOL = 12            # how close to the page background still counts as page
MIN_FILL = 0.55        # share of its own bounding box a real box occupies
MAX_PAGE_SHARE = 0.55  # anything bigger than this is the page, not a box on it
MIN_CONTENT = 0.01     # a callout holds drawings; an empty panel is not one


def page_background(img, step=7):
    """The colour most of the page is, found rather than assumed."""
    flat = img[::step, ::step].reshape(-1, 3).astype(np.int32)
    key = (flat[:, 0] >> 2) * 4096 + (flat[:, 1] >> 2) * 64 + (flat[:, 2] >> 2)
    vals, counts = np.unique(key, return_counts=True)
    win = vals[int(np.argmax(counts))]
    sel = key == win
    return flat[sel].mean(axis=0)


def flat_mask(img, window=FLAT_WINDOW, tol=FLAT_TOL):
    """Pixels whose neighbourhood is a single colour.

    This is what replaces "is it this exact blue". A printed fill is flat; a
    drawing, a photo or an anti-aliased edge is not.
    """
    g = img.astype(np.float32).mean(axis=2)
    hi = ndimage.maximum_filter(g, size=window)
    lo = ndimage.minimum_filter(g, size=window)
    return (hi - lo) <= tol


def document_fill(doc, render, pages=None, sample=14):
    """The one colour this booklet fills its callouts with.

    Learned rather than configured. Candidate rectangles are collected from a
    spread of pages and their fills tallied by area; a callout fill repeats on
    every page, a brick face does not. Returns None for a document with no
    consistent callout colour, which is the honest answer for a booklet this
    approach cannot read.
    """
    n = doc.page_count if pages is None else pages
    step = max(1, n // sample)
    tally = {}
    for pg in range(0, n, step):
        img = render(doc, pg)
        for (x0, y0, x1, y1), fill in _candidates(img):
            key = tuple((fill // 6).astype(int))
            area = (x1 - x0) * (y1 - y0)
            slot = tally.setdefault(key, [0, 0, np.zeros(3)])
            slot[0] += area
            slot[1] += 1
            slot[2] += fill * area
    if not tally:
        return None
    # seen on several pages, not just large once
    usable = {k: v for k, v in tally.items() if v[1] >= 3}
    if not usable:
        return None
    best = max(usable.values(), key=lambda v: v[0])
    return best[2] / best[0]


def find_callouts(img, scale=RENDER_SCALE, fill=None, fill_tol=18):
    """Bounding boxes of the callout panels, left-to-right and top-to-bottom.

    Pass `fill` (from document_fill) to keep only the panels this booklet
    actually uses for parts; without it every flat rectangle qualifies,
    including the side of a brick in an assembly drawing.
    """
    out = [b for b, f in _candidates(img, scale)
           if fill is None or float(np.max(np.abs(f - fill))) <= fill_tol]

    # a panel drawn inside another panel is not a second callout
    out.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    kept = []
    for b in out:
        if not any(b[0] >= a[0] and b[1] >= a[1] and b[2] <= a[2] and b[3] <= a[3]
                   for a in kept):
            kept.append(b)
    h = img.shape[0]
    kept.sort(key=lambda b: (round(b[1] / max(1, h) * 50), b[0]))
    return kept


def _candidates(img, scale=RENDER_SCALE):
    """Every flat non-background rectangle, with the colour it is filled with."""
    k = scale / SCALE_REF
    min_w, min_h, min_area = 40 * k, 40 * k, 2000 * k * k
    h, w = img.shape[:2]
    page_area = h * w

    bg = page_background(img)
    not_bg = np.max(np.abs(img.astype(np.int32) - bg), axis=-1) > BG_TOL
    candidates = flat_mask(img) & not_bg

    lab, n = ndimage.label(candidates, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop - 1
        x0, x1 = sl[1].start, sl[1].stop - 1
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if bw < min_w or bh < min_h or bw * bh < min_area:
            continue
        if bw * bh > page_area * MAX_PAGE_SHARE:
            continue
        comp = lab[sl] == i
        if comp.sum() / (bw * bh) < MIN_FILL:
            continue
        # a callout holds drawings: some of its inside is not the fill colour
        fill = np.median(img[sl][comp], axis=0)
        inside = np.max(np.abs(img[sl].astype(np.int32) - fill), axis=-1) > 30
        if inside.mean() < MIN_CONTENT:
            continue
        out.append(((x0, y0, x1, y1), fill))
    return out
