"""
Reference/debug implementation of the parts-list extraction pipeline used by webapp/app.js.

This is a Python port of the exact same algorithm the browser app runs, kept around so the
detection logic can be tuned and validated offline (fast iteration, real error messages,
no browser needed) before porting changes back into app.js by hand.

Usage:
    python pdf_pipeline.py <pdf_path> <out_dir> <start_page> <end_page>

Requires: pymupdf, numpy, pillow, scipy, pytesseract (+ the `tesseract` binary on PATH).
See requirements.txt. OCR is only used here for quick sanity checks - the real webapp
does NOT use OCR (see extract_glyph_templates.py for why, and how the digit templates
in webapp/glyph-templates.js were generated instead).
"""
import fitz
import numpy as np
from PIL import Image
from scipy import ndimage
import sys, os, json

BOX_BG = np.array([215, 238, 254])  # the light-blue "new parts" callout background color
BG_TOL = 10  # tolerance for matching the box background color
FG_DIFF_THRESHOLD = 35  # per-pixel max-channel diff to count as foreground (icon/text)


def render_page(doc, idx, zoom=2.0):
    p = doc[idx]
    pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return np.array(img)


def find_blue_boxes(arr):
    diff = np.abs(arr.astype(int) - BOX_BG.astype(int))
    mask = np.all(diff <= BG_TOL, axis=-1)
    labeled, n = ndimage.label(mask)
    boxes = []
    for i in range(1, n + 1):
        ys, xs = np.where(labeled == i)
        if len(xs) < 400:
            continue
        x0, x1 = xs.min(), xs.max()
        y0, y1 = ys.min(), ys.max()
        area = (x1 - x0) * (y1 - y0)
        fill_ratio = len(xs) / max(area, 1)
        if fill_ratio < 0.5:
            continue
        if (x1 - x0) < 40 or (y1 - y0) < 40:
            continue
        boxes.append((x0, y0, x1, y1))
    return boxes


def segment_items(arr, box):
    x0, y0, x1, y1 = box
    inset = 4
    sub = arr[y0 + inset:y1 - inset, x0 + inset:x1 - inset]
    diff = np.abs(sub.astype(int) - BOX_BG.astype(int)).max(axis=-1)
    fgmask = diff > FG_DIFF_THRESHOLD
    fgmask = ndimage.binary_opening(fgmask, structure=np.ones((3, 3)))

    col_has_fg = fgmask.any(axis=0)
    items = []
    in_run = False
    start = 0
    min_gap = 6
    cols = col_has_fg.shape[0]
    i = 0
    while i < cols:
        if col_has_fg[i]:
            if not in_run:
                in_run = True
                start = i
            i += 1
        else:
            j = i
            while j < cols and not col_has_fg[j]:
                j += 1
            if in_run and (j - i) >= min_gap:
                items.append((start, i))
                in_run = False
            i = j
    if in_run:
        items.append((start, cols))

    slices = []
    for (cs, ce) in items:
        if ce - cs < 8:
            continue
        item_fg = fgmask[:, cs:ce]
        row_has_fg = item_fg.any(axis=1)
        rows = np.where(row_has_fg)[0]
        if len(rows) == 0:
            continue
        slices.append((cs, ce, rows.min(), rows.max()))
    return sub, fgmask, slices


def split_image_text(sub, fgmask, sl):
    cs, ce, r0, r1 = sl
    item_fg = fgmask[r0:r1 + 1, cs:ce]
    row_has_fg = item_fg.any(axis=1)
    n = len(row_has_fg)
    min_gap_rows = 2
    gaps = []
    i = 0
    while i < n:
        if not row_has_fg[i]:
            j = i
            while j < n and not row_has_fg[j]:
                j += 1
            if (j - i) >= min_gap_rows:
                gaps.append((i, j))
            i = j
        else:
            i += 1
    if not gaps:
        return sub[r0:r1 + 1, cs:ce], None
    best = max(gaps, key=lambda g: g[1] - g[0])
    split_row = (best[0] + best[1]) // 2
    img_part = sub[r0:r0 + split_row, cs:ce]
    txt_part = sub[r0 + split_row:r1 + 1, cs:ce]
    return img_part, txt_part


def ocr_qty(txt_img_arr):
    """Quick OCR sanity check only - NOT what the webapp actually uses (see module docstring)."""
    import pytesseract
    if txt_img_arr is None or txt_img_arr.size == 0:
        return None
    im = Image.fromarray(txt_img_arr).resize(
        (txt_img_arr.shape[1] * 4, txt_img_arr.shape[0] * 4), Image.LANCZOS
    )
    txt = pytesseract.image_to_string(im, config="--psm 7 -c tessedit_char_whitelist=0123456789x")
    return txt.strip()


def autocrop(img_arr):
    diff = np.abs(img_arr.astype(int) - BOX_BG.astype(int))
    bgmask = np.all(diff <= BG_TOL, axis=-1)
    fgmask = ~bgmask
    ys, xs = np.where(fgmask)
    if len(xs) == 0:
        return img_arr
    pad = 2
    y0, y1 = max(0, ys.min() - pad), min(img_arr.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(img_arr.shape[1], xs.max() + pad)
    return img_arr[y0:y1, x0:x1]


def process_range(pdf_path, start_page, end_page, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    results = []
    for pno in range(start_page - 1, end_page):
        arr = render_page(doc, pno)
        boxes = find_blue_boxes(arr)
        for bi, box in enumerate(boxes):
            sub, fgmask, slices = segment_items(arr, box)
            for si, sl in enumerate(slices):
                img_part, txt_part = split_image_text(sub, fgmask, sl)
                qty = ocr_qty(txt_part)
                cropped = autocrop(img_part)
                if cropped.size == 0:
                    continue
                fname = f"p{pno + 1}_b{bi}_i{si}.png"
                Image.fromarray(cropped).save(os.path.join(out_dir, fname))
                results.append({"page": pno + 1, "box": bi, "item": si, "qty_raw": qty, "thumb": fname})
    return results


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(f"Usage: python {sys.argv[0]} <pdf_path> <out_dir> <start_page> <end_page>")
        sys.exit(1)
    pdf_path, out_dir, start, end = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    res = process_range(pdf_path, start, end, out_dir)
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(f"Processed pages {start}-{end}, found {len(res)} items -> {out_dir}")
