"""Python port of the icon-extraction half of webapp/app.js.

Kept deliberately in step with the browser code so anything measured here is
true of what actually ships. Only the *extraction* is ported - finding the
light-blue callout boxes and cutting them into per-part icons. Matching parts
to each other is what the learned model replaces.
"""
import numpy as np
import fitz
from scipy import ndimage

RENDER_SCALE = 3.0          # what the app uses; the dataset also renders others
BOX_BG = np.array([215, 238, 254])
BOX_COLOR_TOL = 14
FG_DIFF_THRESHOLD = 35
SCALE_REF = 2.0


def _size_k(render_scale):
    return render_scale / SCALE_REF


def render_page(doc, page_index, scale=RENDER_SCALE):
    pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return img[:, :, :3] if pix.n == 4 else img


def diff_mask(img, threshold=FG_DIFF_THRESHOLD):
    return np.max(np.abs(img.astype(int) - BOX_BG), axis=-1) > threshold


def find_blue_boxes(img, scale=RENDER_SCALE):
    k = _size_k(scale)
    min_w, min_h, min_area = 40 * k, 40 * k, 400 * k * k
    mask = np.all(np.abs(img.astype(int) - BOX_BG) <= BOX_COLOR_TOL, axis=-1)
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
        if int((lab[sl] == i).sum()) / (bw * bh) < 0.5:
            continue
        out.append((x0, y0, x1, y1))
    # left-to-right, top-to-bottom, so slot identity is stable across scales
    out.sort(key=lambda b: (round(b[1] / max(1, img.shape[0]) * 50), b[0]))
    return out


def _open3(m):
    st = np.ones((3, 3), dtype=bool)
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


def extract_box_icons(img, box, scale=RENDER_SCALE):
    """Returns the icon crops of one callout box, in left-to-right slot order."""
    k = _size_k(scale)
    min_col_gap, min_row_gap = int(round(6 * k)), int(round(2 * k))
    inset = 4
    x0b, y0b, x1b, y1b = box
    x0, y0 = x0b + inset, y0b + inset
    w, h = (x1b - inset) - x0, (y1b - inset) - y0
    if w <= 0 or h <= 0:
        return []
    sub = img[y0:y0 + h, x0:x0 + w]
    fg = _open3(diff_mask(sub))
    out = []
    for cs, ce in find_runs(list(fg.any(axis=0)), min_col_gap):
        if ce - cs < 8:
            continue
        rows = np.where(fg[:, cs:ce].any(axis=1))[0]
        if len(rows) == 0:
            continue
        r0, r1 = rows[0], rows[-1]
        row_fg = fg[r0:r1 + 1, cs:ce].any(axis=1)
        gaps = find_runs(list(~row_fg), min_row_gap)
        if gaps:
            best = max(gaps, key=lambda g: g[1] - g[0])
            split = round((best[0] + best[1]) / 2)
        else:
            split = max(1, (r1 - r0 + 1) - round(h * 0.22))
        icon = sub[r0:r0 + split, cs:ce]
        if icon.shape[0] > 0 and icon.shape[1] > 0:
            out.append(icon)
    return out


def autocrop(icon):
    fg = diff_mask(icon)
    ys, xs = np.where(fg)
    if len(xs) == 0:
        return icon
    pad = 2
    return icon[max(0, ys.min() - pad):min(icon.shape[0] - 1, ys.max() + pad) + 1,
                max(0, xs.min() - pad):min(icon.shape[1] - 1, xs.max() + pad) + 1]


def iter_page_icons(doc, page_index, scale=RENDER_SCALE):
    """Yields (box_index, slot_index, icon) for one page at one render scale."""
    img = render_page(doc, page_index, scale)
    for bi, box in enumerate(find_blue_boxes(img, scale)):
        for si, icon in enumerate(extract_box_icons(img, box, scale)):
            cropped = autocrop(icon)
            if cropped.shape[0] >= 4 and cropped.shape[1] >= 4:
                yield bi, si, cropped
