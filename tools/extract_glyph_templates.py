"""
Extracts and clusters digit glyphs ("0"-"9" and "x") straight out of a LEGO instruction PDF,
so a reliable digit classifier can be built WITHOUT relying on general-purpose OCR.

Why this exists: Tesseract OCR systematically misread "2" as "7" in the instruction font used
by this PDF (a Stud.io/BrickLink-generated booklet). Since the font is 100% consistent across
the whole document, matching against real glyph bitmaps pulled from the document itself is both
more accurate and much faster/lighter than shipping an OCR engine to the browser.

Workflow to (re)generate webapp/glyph-templates.js for a NEW document/font:
  1. python extract_glyph_templates.py <pdf_path> <out_dir> <start_page> <end_page>
     -> writes out_dir/cluster_NN_nCOUNT.png for every visually-distinct glyph shape found,
        sorted by how often each shape occurred (most common first).
  2. Open the PNGs and note which digit (or "x") each cluster number shows.
  3. Edit the `label_map` dict at the top of export_templates.py to match, then run it to
     produce a new glyph-templates.js.

A page range of a few hundred glyphs is normally enough to find all of 0-9 and "x"; if a digit
never appears in your sample (e.g. no part quantity happened to contain a "9"), widen the page
range, or see export_templates.py for how a missing digit was synthesized as a rotation of
another one as a fallback.
"""
import numpy as np
from PIL import Image
from scipy import ndimage
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_pipeline import render_page, find_blue_boxes, segment_items, split_image_text, BOX_BG, FG_DIFF_THRESHOLD

NORM_W, NORM_H = 22, 30  # must match GLYPH_W/GLYPH_H in webapp/app.js
CLUSTER_MERGE_DIST = 15  # out of NORM_W*NORM_H=660 px, how close two glyph bitmaps must be to merge


def segment_glyphs(txt_part):
    diff = np.abs(txt_part.astype(int) - BOX_BG.astype(int)).max(axis=-1)
    fg = diff > FG_DIFF_THRESHOLD
    fg = ndimage.binary_opening(fg, structure=np.ones((2, 2)))
    labeled, n = ndimage.label(fg)
    glyphs = []
    for i in range(1, n + 1):
        ys, xs = np.where(labeled == i)
        if len(xs) < 5:
            continue
        glyphs.append((xs.min(), ys.min(), xs.max(), ys.max()))
    glyphs.sort(key=lambda g: g[0])
    return glyphs, fg


def normalize_glyph(fg, box, pad=2):
    x0, y0, x1, y1 = box
    crop = fg[y0:y1 + 1, x0:x1 + 1]
    h, w = crop.shape
    scale = min((NORM_W - 2 * pad) / w, (NORM_H - 2 * pad) / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    im = Image.fromarray((crop * 255).astype(np.uint8)).resize((nw, nh), Image.NEAREST)
    canvas = Image.new("L", (NORM_W, NORM_H), 0)
    canvas.paste(im, ((NORM_W - nw) // 2, (NORM_H - nh) // 2))
    return (np.array(canvas) > 127).astype(np.uint8)


def main():
    if len(sys.argv) != 5:
        print(f"Usage: python {sys.argv[0]} <pdf_path> <out_dir> <start_page> <end_page>")
        sys.exit(1)
    pdf_path, out_dir, start, end = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    os.makedirs(out_dir, exist_ok=True)

    import fitz
    doc = fitz.open(pdf_path)
    all_glyphs = []
    for pno in range(start - 1, end):
        arr = render_page(doc, pno)
        for box in find_blue_boxes(arr):
            sub, fgmask, slices = segment_items(arr, box)
            for sl in slices:
                _, txt_part = split_image_text(sub, fgmask, sl)
                if txt_part is None or txt_part.size == 0:
                    continue
                glyphs, fg = segment_glyphs(txt_part)
                for g in glyphs:
                    all_glyphs.append(normalize_glyph(fg, g))
    print(f"collected {len(all_glyphs)} glyphs")

    clusters = []
    for bm in all_glyphs:
        found = next((c for c in clusters if np.count_nonzero(c["bitmap"] != bm) <= CLUSTER_MERGE_DIST), None)
        if found:
            found["count"] += 1
        else:
            clusters.append({"bitmap": bm, "count": 1})

    clusters.sort(key=lambda c: -c["count"])
    print(f"{len(clusters)} distinct glyph shapes")
    for idx, c in enumerate(clusters):
        Image.fromarray((c["bitmap"] * 255).astype(np.uint8)).save(
            os.path.join(out_dir, f"cluster_{idx:02d}_n{c['count']}.png")
        )
    np.savez(os.path.join(out_dir, "clusters.npz"), *[c["bitmap"] for c in clusters])
    print(f"-> {out_dir}/cluster_*.png (inspect these) and clusters.npz (feed to export_templates.py)")


if __name__ == "__main__":
    main()
