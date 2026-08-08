"""Builds the training set straight out of the instruction PDFs - no hand
labelling anywhere, because the booklets already contain both kinds of label:

  positives  the same slot rendered at a different scale is, by construction,
             the same part. LEGO itself redraws icons smaller when a callout
             box holds more of them, and that scale variation was measured to
             be the single biggest source of matching errors - so it is
             exactly what the model should learn to ignore.

  negatives  two different slots of the SAME callout box are guaranteed to be
             different parts: a box never lists one part twice.

Usage:  extract_dataset.py out.npz file1.pdf [file2.pdf ...]
"""
import sys, os, time
import numpy as np
import fitz
import pipeline as P

# scales chosen around the app's own 3.0 to span the range LEGO itself uses
SCALES = [3.0, 2.4, 1.9]
SIDE = 32   # network input is SIDE x SIDE


def to_input(icon):
    """Stretch to a square (so thin parts still use the full resolution) and
    return it plus the aspect ratio, which the stretch throws away and the
    model gets back as an explicit number."""
    from PIL import Image
    h, w = icon.shape[:2]
    im = Image.fromarray(icon.astype(np.uint8)).resize((SIDE, SIDE), Image.BILINEAR)
    return np.asarray(im, dtype=np.uint8), float(np.log(w / h))


def main():
    out_path = sys.argv[1]
    pdfs = sys.argv[2:]
    images, aspects, groups, meta = [], [], [], []
    # group id = one physical slot = (pdf, page, box, slot); same id at different
    # scales is a positive pair
    group_of = {}

    for pdf in pdfs:
        doc = fitz.open(pdf)
        name = os.path.basename(pdf)
        t0 = time.time()
        for scale in SCALES:
            for page in range(doc.page_count):
                for bi, si, icon in P.iter_page_icons(doc, page, scale):
                    key = (name, page, bi, si)
                    gid = group_of.setdefault(key, len(group_of))
                    img, asp = to_input(icon)
                    images.append(img)
                    aspects.append(asp)
                    groups.append(gid)
                    meta.append((name, page + 1, bi, si, scale))
                if page % 100 == 0:
                    print(f"  {name} scale {scale} page {page}: {len(images)} icons "
                          f"({time.time()-t0:.0f}s)", flush=True)
        doc.close()

    images = np.stack(images)
    aspects = np.asarray(aspects, dtype=np.float32)
    groups = np.asarray(groups, dtype=np.int64)
    # box id groups slots that share a callout box - those are the safe negatives
    box_of = {}
    boxes = []
    for (name, page, bi, si, scale) in meta:
        boxes.append(box_of.setdefault((name, page, bi), len(box_of)))
    boxes = np.asarray(boxes, dtype=np.int64)
    pages = np.asarray([m[1] for m in meta], dtype=np.int64)
    pdf_ids = np.asarray([pdfs.index([p for p in pdfs if os.path.basename(p) == m[0]][0])
                          for m in meta], dtype=np.int64)

    np.savez_compressed(out_path, images=images, aspects=aspects, groups=groups,
                        boxes=boxes, pages=pages, pdf_ids=pdf_ids,
                        pdf_names=np.array([os.path.basename(p) for p in pdfs]))
    print(f"\nsaved {out_path}")
    print(f"  samples      {len(images)}")
    print(f"  slots        {len(group_of)}   (each seen at {len(SCALES)} scales)")
    print(f"  callout boxes {len(box_of)}")
    multi = sum(1 for b in np.bincount(boxes) if b > 1)
    print(f"  boxes with >1 slot (usable as negatives): {multi}")


if __name__ == "__main__":
    main()
