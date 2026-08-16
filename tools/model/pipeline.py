"""Python port of the icon-extraction half of webapp/app.js.

Kept deliberately in step with the browser code so anything measured here is
true of what actually ships. Only the *extraction* is ported - finding the
light-blue callout boxes and cutting them into per-part icons. Matching parts
to each other is what the learned model replaces.
"""
import numpy as np
import fitz
from scipy import ndimage

import detect as D
import glyphs as G

RENDER_SCALE = 3.0          # what the app uses; the dataset also renders others
BOX_BG = np.array([215, 238, 254])
BOX_COLOR_TOL = 14
FG_DIFF_THRESHOLD = 35
SCALE_REF = 2.0
MAX_GLYPH_ASPECT = 1.6      # wider than tall is not a digit


def _size_k(render_scale):
    return render_scale / SCALE_REF


def render_page(doc, page_index, scale=RENDER_SCALE):
    pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return img[:, :, :3] if pix.n == 4 else img


def diff_mask(img, threshold=FG_DIFF_THRESHOLD):
    return np.max(np.abs(img.astype(int) - BOX_BG), axis=-1) > threshold


def box_background(img, box):
    """What the icons inside this box sit on.

    Usually the box's own fill, but for a booklet that draws callouts as a bare
    frame it is the page colour showing through. Either way it is whatever most
    of the inside is, which needs no assumption about which of the two it is.
    """
    x0, y0, x1, y1 = box
    inner = img[y0 + 3:y1 - 2, x0 + 3:x1 - 2]
    if inner.size == 0:
        return None
    flat = inner.reshape(-1, 3).astype(np.int32)
    key = (flat[:, 0] >> 3) * 4096 + (flat[:, 1] >> 3) * 64 + (flat[:, 2] >> 3)
    vals, counts = np.unique(key, return_counts=True)
    sel = key == vals[int(np.argmax(counts))]
    return flat[sel].mean(axis=0)


def _page_background(img, step=9):
    """The colour most of the page is, so we can tell what shows through."""
    flat = img[::step, ::step].reshape(-1, 3).astype(np.int32)
    key = (flat[:, 0] >> 3) * 4096 + (flat[:, 1] >> 3) * 64 + (flat[:, 2] >> 3)
    vals, counts = np.unique(key, return_counts=True)
    sel = key == vals[int(np.argmax(counts))]
    return flat[sel].mean(axis=0)


def learn_callout_colour(doc, scale=RENDER_SCALE, sample=10):
    """The colour THIS booklet fills its callouts with.

    Hard-coding the yacht booklets' light blue meant the training pipeline
    could not see a single callout in 6540963, whose panels are 178,215,243 —
    so every part in that booklet was missing from the dataset while the app
    itself, which learns the colour, had been reading it for weeks.
    """
    fill = D.document_fill(doc, lambda d, p: render_page(d, p, scale), sample=sample)
    return BOX_BG if fill is None else np.asarray(fill)


def find_blue_boxes(img, scale=RENDER_SCALE, bg=None):
    bg = BOX_BG if bg is None else np.asarray(bg)
    k = _size_k(scale)
    min_w, min_h, min_area = 40 * k, 40 * k, 400 * k * k
    # a box on the page, not the page itself: without this the page background
    # colour scores as one perfect rectangle per page
    max_area = img.shape[0] * img.shape[1] * 0.55
    mask = np.all(np.abs(img.astype(int) - bg) <= BOX_COLOR_TOL, axis=-1)
    lab, _ = ndimage.label(mask, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop - 1
        x0, x1 = sl[1].start, sl[1].stop - 1
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if bw < min_w or bh < min_h or bw * bh < min_area:
            continue
        if bw * bh > max_area:
            continue
        # Two shapes count as a callout, because booklets draw them both ways:
        # a filled panel, or a bare rectangular FRAME. One set draws its
        # callouts as a thin white outline with the page's own grey showing
        # through the middle — there is no fill to find at all, and looking for
        # one missed every parts callout in the book.
        comp = lab[sl] == i
        filled = comp.mean() >= 0.5
        edges = (comp[0].mean(), comp[-1].mean(), comp[:, 0].mean(), comp[:, -1].mean())
        frame = min(edges) >= 0.7
        if not (filled or frame):
            continue
        # A callout holds drawings. A solid dark blob in an assembly picture is
        # also a large flat rectangle, and without this it passes — which is
        # what made "guess the callout colour by counting boxes" pick near-black
        # for the yacht booklets.
        inside = np.max(np.abs(img[sl].astype(int) - bg), axis=-1) > 30
        if inside.mean() < 0.02:
            continue
        out.append((x0, y0, x1, y1))
    # left-to-right, top-to-bottom, so slot identity is stable across scales
    out.sort(key=lambda b: (round(b[1] / max(1, img.shape[0]) * 50), b[0]))
    return out


def _open3(m):
    st = np.ones((3, 3), dtype=bool)
    return ndimage.binary_dilation(ndimage.binary_erosion(m, st, border_value=0), st, border_value=0)


def _open2(m):
    st = np.ones((2, 2), dtype=bool)
    return ndimage.binary_dilation(ndimage.binary_erosion(m, st, border_value=0), st, border_value=0)


def find_runs(arr, min_gap):
    runs, n, in_run, start, i = [], len(arr), False, 0, 0
    while i < n:
        if arr[i]:
            if not in_run:
                in_run, start = True, i
            i += 1
        else:
            j = i
            while j < n and not arr[j]:
                j += 1
            if in_run and (j - i) >= min_gap:
                runs.append((start, i))
                in_run = False
            i = j
    if in_run:
        runs.append((start, n))
    return runs


def _components(mask):
    """8-connected components with their bounding boxes, as the browser's
    findGlyphComponents returns them."""
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        comp = lab[sl] == i
        out.append({
            "minY": sl[0].start, "maxY": sl[0].stop - 1,
            "minX": sl[1].start, "maxX": sl[1].stop - 1,
            "mask": comp, "size": int(comp.sum()),
        })
    return out


def band_has_digit(fg, r0, r1, k):
    """Is there a recognisable printed digit in this band of ink?

    Only ever asked of bands the callout has already nominated as its lines of
    type, so the tolerance is the reader's own rather than the strict one.
    """
    sh = r1 - r0 + 1
    if sh < 4:
        return False
    min_gh, min_gw = 8 * k, 2 * k
    for c in _components(fg[r0:r1 + 1]):
        gw, gh = c["maxX"] - c["minX"] + 1, c["maxY"] - c["minY"] + 1
        if gh < sh * 0.5 or gw < min_gw or gw > gh * MAX_GLYPH_ASPECT:
            continue
        label, dist = G.classify(c["mask"])
        if label.isdigit() and dist <= G.MAX_DIST:
            return True
    return False


def box_row_groups(fg, k):
    """Cut a callout into its rows of items, before anything looks at columns.

    A callout is not always one row: 6540963 prints eight parts as two rows of
    four, and projecting that whole box onto its columns merges the top row's
    part with the bottom row's. Which bands are lines of type is decided by the
    callout itself - two rows print their quantities at the same size, so the
    lines of type are the small bands that REPEAT at one height.
    """
    h = fg.shape[0]
    min_row_gap = max(1, int(round(2 * k)))
    bands = find_runs(list(fg.any(axis=1)), min_row_gap)
    if len(bands) < 3:
        return [(0, h - 1)]

    max_label_h = 8 * k * 2.5
    small = [b for b in bands if (b[1] - b[0]) <= max_label_h]
    best = []
    for cand in small:
        ch = cand[1] - cand[0]
        group = [b for b in small if abs((b[1] - b[0]) - ch) <= ch * 0.25]
        if len(group) > len(best):
            best = group
    if len(best) < 2:
        return [(0, h - 1)]
    if not any(band_has_digit(fg, b[0], b[1] - 1, k) for b in best):
        return [(0, h - 1)]

    is_label = {b[0] for b in best}
    groups, start = [], None
    for bs, be in bands:
        if start is None:
            start = bs
        if bs in is_label:
            groups.append((start, be - 1))
            start = None
    if start is not None:
        groups.append((start, h - 1))
    return groups or [(0, h - 1)]


def split_slot_by_labels(fg, slot, k):
    """One item per printed quantity, for callouts whose rows overlap so far
    that no gap between them exists at all. Returns None when fewer than two
    quantities are found, which is the ordinary one-part case."""
    cs, ce, r0, r1 = slot
    sw, sh = ce - cs, r1 - r0 + 1
    if sw < 8 or sh < 8:
        return None
    local = fg[r0:r1 + 1, cs:ce]
    min_gh, min_gw = 8 * k * 0.6, 2 * k

    glyphs, rest = [], []
    for c in _components(local):
        gw, gh = c["maxX"] - c["minX"] + 1, c["maxY"] - c["minY"] + 1
        ok = (gh >= min_gh and gw >= min_gw and gw <= gh * MAX_GLYPH_ASPECT
              and gh <= sh * 0.2)
        if ok:
            label, dist = G.classify(c["mask"])
            if dist <= G.MAX_DIST:
                c["glyph"] = label
                glyphs.append(c)
                continue
        rest.append(c)
    if len(glyphs) < 2:
        return None

    glyphs.sort(key=lambda c: c["minX"])
    bands = []
    for g in glyphs:
        gh = g["maxY"] - g["minY"] + 1
        hit = None
        for b in bands:
            overlap = min(b["maxY"], g["maxY"]) - max(b["minY"], g["minY"]) + 1
            if overlap > min(b["maxY"] - b["minY"] + 1, gh) * 0.4 and g["minX"] - b["maxX"] < gh * 1.2:
                hit = b
                break
        if hit:
            hit["maxX"] = max(hit["maxX"], g["maxX"])
            hit["minY"] = min(hit["minY"], g["minY"])
            hit["maxY"] = max(hit["maxY"], g["maxY"])
            hit["text"] += g["glyph"]
        else:
            bands.append({"minX": g["minX"], "maxX": g["maxX"], "minY": g["minY"],
                          "maxY": g["maxY"], "text": g["glyph"]})

    heights = sorted(b["maxY"] - b["minY"] + 1 for b in bands)
    med_h = heights[len(heights) // 2]
    kept = [b for b in bands
            if med_h * 0.75 <= (b["maxY"] - b["minY"] + 1) <= med_h * 1.25
            and any(ch.isdigit() for ch in b["text"])]
    i = 0
    while i < len(kept):
        j = i + 1
        while j < len(kept):
            a, b = kept[i], kept[j]
            dx = max(0, max(b["minX"] - a["maxX"], a["minX"] - b["maxX"]))
            dy = max(0, max(b["minY"] - a["maxY"], a["minY"] - b["maxY"]))
            if dx < med_h * 1.5 and dy < med_h * 0.5:
                a["minX"], a["maxX"] = min(a["minX"], b["minX"]), max(a["maxX"], b["maxX"])
                a["minY"], a["maxY"] = min(a["minY"], b["minY"]), max(a["maxY"], b["maxY"])
                a["text"] += b["text"]
                kept.pop(j)
            else:
                j += 1
        i += 1
    if len(kept) < 2:
        return None

    groups = [dict(minX=l["minX"], maxX=l["maxX"], minY=l["minY"], maxY=l["maxY"], label=l)
              for l in kept]
    for c in rest + [b for b in bands if b not in kept]:
        best_i, best_cost = 0, 10 ** 9
        for idx, l in enumerate(kept):
            dx = max(0, max(l["minX"] - c["maxX"], c["minX"] - l["maxX"]))
            if c["maxY"] <= l["minY"]:
                dy = l["minY"] - c["maxY"]
            elif c["minY"] > l["maxY"]:
                dy = (c["minY"] - l["maxY"]) * 3      # a label above its ink is far away
            else:
                dy = 0
            if dx + dy < best_cost:
                best_cost, best_i = dx + dy, idx
        g = groups[best_i]
        g["minX"], g["maxX"] = min(g["minX"], c["minX"]), max(g["maxX"], c["maxX"])
        g["minY"], g["maxY"] = min(g["minY"], c["minY"]), max(g["maxY"], c["maxY"])

    out = [(cs + g["minX"], cs + g["maxX"] + 1, r0 + g["minY"], r0 + g["maxY"],
            max(1, g["label"]["minY"] - g["minY"])) for g in groups]
    out.sort(key=lambda p: (p[2], p[0]))
    return out


def looks_like_part(icon, bg, k):
    """Is this crop a drawing of a part at all?

    Three things get this far without being parts: the printed quantity itself
    when the split left nothing above it, thin rules and flat bars of page
    furniture, and specks.
    """
    h, w = icon.shape[:2]
    min_side, min_area = 9 * k, 60 * k * k
    if w < min_side or h < min_side:
        return False
    mask = _open2(np.max(np.abs(icon.astype(int) - bg), axis=-1) > FG_DIFF_THRESHOLD)
    n = int(mask.sum())
    if n == 0:
        return False
    ys, xs = np.where(mask)
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    if min(bw, bh) < min_side or n < min_area:
        return False
    digit_ink = 0
    for c in _components(mask):
        if c["size"] / n < 0.05:
            continue
        label, dist = G.classify(c["mask"])
        if label.isdigit() and dist <= G.ICON_DIST:
            digit_ink += c["size"]
    return digit_ink / n < 0.55


def extract_box_icons(img, box, scale=RENDER_SCALE, bg=None):
    """The icon crops of one callout box, in reading order.

    Mirrors webapp/app.js: rows first, then columns inside a row, then the
    quantities themselves where the rows overlap, and finally a check that what
    is left looks like a drawing rather than type.
    """
    k = _size_k(scale)
    min_col_gap = int(round(6 * k))
    min_row_gap = max(1, int(round(2 * k)))
    inset = 4
    x0b, y0b, x1b, y1b = box
    x0, y0 = x0b + inset, y0b + inset
    w, h = (x1b - inset) - x0, (y1b - inset) - y0
    if w <= 0 or h <= 0:
        return []
    sub = img[y0:y0 + h, x0:x0 + w]
    inner = box_background(img, box)
    if inner is None:
        inner = BOX_BG if bg is None else np.asarray(bg)
    fg = _open3(np.max(np.abs(sub.astype(int) - inner), axis=-1) > FG_DIFF_THRESHOLD)

    out = []
    for br0, br1 in box_row_groups(fg, k):
        band = fg[br0:br1 + 1]
        if band.shape[0] < 4:
            continue
        slots = []
        for cs, ce in find_runs(list(band.any(axis=0)), min_col_gap):
            if ce - cs < 8:
                continue
            rows = np.where(band[:, cs:ce].any(axis=1))[0]
            if len(rows) == 0:
                continue
            slots.append((cs, ce, br0 + int(rows[0]), br0 + int(rows[-1])))

        pieces, split_heights = [], []
        for cs, ce, r0, r1 in slots:
            row_fg = fg[r0:r1 + 1, cs:ce].any(axis=1)
            first = int(np.argmax(row_fg))
            last = len(row_fg) - 1 - int(np.argmax(row_fg[::-1]))
            gaps = [g for g in find_runs(list(~row_fg), min_row_gap)
                    if g[0] > first and g[1] < last]
            split = None
            if gaps:
                best = max(gaps, key=lambda g: g[1] - g[0])
                split = int(round((best[0] + best[1]) / 2))
                split_heights.append(len(row_fg) - split)
            by_label = split_slot_by_labels(fg, (cs, ce, r0, r1), k)
            if by_label:
                pieces.extend(by_label)
            else:
                pieces.append((cs, ce, r0, r1, split))
        median_text_h = (sorted(split_heights)[len(split_heights) // 2]
                         if split_heights else int(round(band.shape[0] * 0.22)))

        for cs, ce, r0, r1, split in pieces:
            eff = split if split is not None else max(1, (r1 - r0 + 1) - median_text_h)
            icon = sub[r0:r0 + eff, cs:ce]
            if icon.shape[0] <= 0 or icon.shape[1] <= 0:
                continue
            if not looks_like_part(icon, inner, k):
                continue
            out.append(icon)
    return out


def autocrop(icon, bg=None):
    bg = BOX_BG if bg is None else np.asarray(bg)
    fg = np.max(np.abs(icon.astype(int) - bg), axis=-1) > FG_DIFF_THRESHOLD
    ys, xs = np.where(fg)
    if len(xs) == 0:
        return icon
    pad = 2
    return icon[max(0, ys.min() - pad):min(icon.shape[0] - 1, ys.max() + pad) + 1,
                max(0, xs.min() - pad):min(icon.shape[1] - 1, xs.max() + pad) + 1]


_COLOUR_CACHE = {}


def callout_colour_for(doc):
    """This booklet's callout colour, learned once and remembered.

    Every tool in here walks a document page by page, and learning the colour
    per page would mean rendering ten sample pages per page walked. Caching it
    is also what lets those tools keep calling iter_page_icons() with no colour
    argument and still be right about a booklet that is not the yacht.
    """
    key = (getattr(doc, "name", None), doc.page_count)
    if key not in _COLOUR_CACHE:
        _COLOUR_CACHE[key] = learn_callout_colour(doc)
    return _COLOUR_CACHE[key]


def iter_page_icons(doc, page_index, scale=RENDER_SCALE, bg=None):
    """Yields (box_index, slot_index, icon) for one page at one render scale.

    `bg` is this booklet's callout colour; left out, it is learned from the
    document rather than assumed to be the yacht booklets' light blue.
    """
    if bg is None:
        bg = callout_colour_for(doc)
    img = render_page(doc, page_index, scale)
    for bi, box in enumerate(find_blue_boxes(img, scale, bg)):
        inner = box_background(img, box)
        for si, icon in enumerate(extract_box_icons(img, box, scale, bg)):
            cropped = autocrop(icon, inner)
            if cropped.shape[0] >= 4 and cropped.shape[1] >= 4:
                yield bi, si, cropped
