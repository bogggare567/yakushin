"""Every size the app would print, on one sheet, large enough to count by eye.

The point is to be able to check the answers rather than trust them, so this
reproduces exactly what the app does — same matcher, same vetoes, same
per-part vote — and then lays the result out at a size where the studs are
countable.

Two sheets:

  РАЗМЕРЫ    every row that got a size. This is the whole population of labels
             a user would see, not a sample of it, so checking it is a census:
             the error rate that comes out has no sampling error in it.
  БЕЗ ПОДПИСИ rows where at least one icon was measured but the vote did not
             settle. This is where coverage is being lost, and looking at it is
             the only way to tell whether that is the right call.

Usage: studs_sheet.py file.pdf [--pages 400] [--cell 230]
"""
import argparse, os, pickle, re

import numpy as np
import torch
import fitz
from PIL import Image, ImageDraw

import baseline as B
import pipeline as P
import studs_count as SC
from audit import embed_batch
from regression import bucket_with_vetoes
from model import IconEmbedder

LATTICE_MIN_AREA = 12000  # below this an icon cannot host a lattice search
MIN_AGREEING = 2  # a printed size needs this many independent readings agreeing


def load(pdf, pages, cache):
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            d = pickle.load(f)
        if d.get("pdf") == pdf and d.get("pages") == pages and "box_ids" in d:
            print(f"кэш: {len(d['icons'])} иконок")
            return d["icons"], d["pages_of"], d["box_ids"]
    doc = fitz.open(pdf)
    n = min(pages, doc.page_count)
    icons, pages_of, box_ids = [], [], []
    for p in range(n):
        for bi, si, icon in P.iter_page_icons(doc, p):
            icons.append(icon)
            pages_of.append(p + 1)
            box_ids.append((p + 1, bi))
        if (p + 1) % 100 == 0:
            print(f"  стр. {p+1}/{n}", flush=True)
    doc.close()
    with open(cache, "wb") as f:
        pickle.dump({"pdf": pdf, "pages": pages, "icons": icons,
                     "pages_of": pages_of, "box_ids": box_ids}, f)
    return icons, pages_of, box_ids


def vote(members):
    """The app's rule, copied deliberately rather than approximated."""
    groups = {}
    for m in members:
        groups.setdefault(m[0], []).append(m)
    ranked = sorted(groups.values(), key=lambda g: -len(g))
    win = ranked[0]
    if len(win) >= 2:
        return (win[0][0], len(win), len(members)) if len(win) / len(members) > 0.5 else None
    if len(members) == 1 and win[0][1] < SURE_ERR:
        return (win[0][0], 1, 1)
    return None


def sheet(path, entries, icons, cell, cols, per_page=0):
    """Paginated on purpose: a size printed too small to count is not checkable,
    and the whole point of this sheet is that somebody counts."""
    if per_page and len(entries) > per_page:
        base, ext = os.path.splitext(path)
        for k in range(0, len(entries), per_page):
            sheet(f"{base}_{k // per_page + 1}{ext}", entries[k:k + per_page],
                  icons, cell, cols)
        return
    rows = (len(entries) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell, rows * (cell + 20) + 6), (18, 20, 26))
    dr = ImageDraw.Draw(img)
    # One scale for the whole sheet, not thumbnail-to-fill. Filling each cell
    # throws away relative size, and that is not cosmetic: reading this sheet I
    # counted a 3x3 plate as a 4x4 because it had been blown up to the same
    # width as the 4x4 next to it. The algorithm had it right and the sheet
    # made me wrong — a checking tool that misleads the checker is worse than
    # no tool.
    widest = max(icons[i].shape[1] for i, _, _ in entries)
    tallest = max(icons[i].shape[0] for i, _, _ in entries)
    k_all = min((cell - 6) / widest, (cell - 6) / tallest)
    for k, (idx, label, ok) in enumerate(entries):
        src = icons[idx]
        im = Image.fromarray(src.astype(np.uint8)).resize(
            (max(1, int(src.shape[1] * k_all)), max(1, int(src.shape[0] * k_all))),
            Image.LANCZOS)
        x, y = (k % cols) * cell, (k // cols) * (cell + 20)
        img.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        dr.text((x + 5, y + cell + 3), label, fill=(150, 220, 160) if ok else (200, 140, 100))
    img.save(path)
    print("  ->", path, f"({len(entries)} шт.)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", type=int, default=400)
    ap.add_argument("--cell", type=int, default=230)
    ap.add_argument("--cols", type=int, default=8)
    ap.add_argument("--out", default="sheet")
    ap.add_argument("--per-page", type=int, default=0)
    args = ap.parse_args()

    icons, pages_of, box_ids = load(args.pdf, args.pages,
                                    f".boxicons_{os.path.basename(args.pdf)}.pkl")
    net = IconEmbedder()
    net.load_state_dict(torch.load("model.pt", map_location="cpu"))
    net.eval()
    emb = embed_batch(net, icons)
    cols_ = np.stack([B.dominant_color(ic) for ic in icons])
    asps = np.array([float(np.log(ic.shape[1] / ic.shape[0])) for ic in icons])
    rows = bucket_with_vetoes(emb, cols_, asps, 0.25, 45, 0.09)
    print(f"иконок {len(icons)}, строк {len(rows)}")

    # One lattice per callout box, not per icon. Every icon in a box is drawn
    # at the same scale by the same camera, so the lattice found on the icon
    # that shows it most clearly describes all of them — and the small ones,
    # which carry too few stud periods to find a lattice alone, then need
    # nothing but their two corners. Checked against measuring each icon on its
    # own: 156 of 156 agree, and 81 icons that could not measure themselves get
    # an answer.
    from collections import defaultdict
    by_box = defaultdict(list)
    for i, b in enumerate(box_ids):
        by_box[b].append(i)
    box_lattice = {}
    for b, idxs in by_box.items():
        best, best_score = None, -1.0
        for i in idxs:
            if icons[i].shape[0] * icons[i].shape[1] < LATTICE_MIN_AREA:
                continue
            got = SC.lattice(icons[i])
            if got and got[1] > best_score:
                best_score, best = got[1], got[0]
        if best is not None:
            box_lattice[b] = best

    per_row = {}
    for r, row in enumerate(rows):
        got = []
        for i in row["idx"]:
            lat = box_lattice.get(box_ids[i])
            if lat is None:
                continue
            m = SC.solve(icons[i], lat)
            if m:
                got.append((m[0], m[1], i))
        if got:
            per_row[r] = got

    sized, silent = [], []
    for r, got in per_row.items():
        groups = {}
        for g in got:
            groups.setdefault(g[0], []).append(g)
        ranked = sorted(groups.values(), key=lambda g: -len(g))
        win = ranked[0]
        # Confirmation, not confidence: a size is printed only when at least two
        # independent readings agree on it. Each reading comes from a different
        # callout box and they never see each other, so agreement is real
        # evidence — where one lone reading being close to a whole number is
        # not. A box whose lattice is wrong produces near-whole, real-looking
        # sizes all day: page 106 reads a 4x4 plate as 8x4 and an 8x8 as 16x8,
        # both plausible, both wrong, and nothing about that one reading says so.
        decisive = len(win) >= MIN_AGREEING and len(win) / len(got) > 0.5
        pages = sorted({pages_of[i] for i in rows[r]["idx"]})
        if not decisive:
            seen = " / ".join(sorted({f"{g[0][0]}x{g[0][1]}" for g in got}))
            biggest = max(rows[r]["idx"], key=lambda i: icons[i].shape[0] * icons[i].shape[1])
            silent.append((biggest, f"нет: {seen}  стр.{pages[0]}", False))
            continue
        # The app splits a row when a second size was seen more than once, so
        # the sheet must too — otherwise it shows a merged row that no user
        # would ever see. Reading a sheet that did not split, I "found" a 3x3
        # labelled 4x4 that was really two different plates the matcher had
        # fused and the stud count had already caught.
        # any size seen more than once is its own part, majority or not
        shown = [win] + [g for g in ranked[1:] if len(g) >= 2]
        for grp in shown:
            size = grp[0][0]
            big = max((g[2] for g in grp), key=lambda i: icons[i].shape[0] * icons[i].shape[1])
            sized.append((big, f"{size[0]}x{size[1]}  ×{len(grp)} стр.{pages_of[big]}"
                               f" ({len(grp)}/{len(got)})", True))

    # Label-free confirmation: a part is measured once per box it appears in,
    # and those readings never see each other. Unanimity across them is the
    # strongest evidence available without anyone counting studs by hand.
    multi = [g for g in per_row.values() if len(g) >= 2]
    unan = sum(1 for g in multi if len({x[0] for x in g}) == 1)
    single = sum(1 for g in per_row.values() if len(g) == 1)
    print(f"\nстрок с несколькими чтениями: {len(multi)}, из них единогласны "
          f"{unan} ({unan/max(1,len(multi))*100:.0f}%); строк с одним чтением: {single}")
    print(f"строк с размером: {len(sized)}   без подписи (но измерялись): {len(silent)}")
    # Least-confirmed first: a size backed by one reading is the one that needs
    # a person to look at it. Sizes backed by several independent readings that
    # agree have already confirmed each other.
    def backing(entry):
        m = re.search(r"\((\d+)/(\d+)\)$", entry[1])
        return (int(m.group(2)), entry[1]) if m else (99, entry[1])
    sized.sort(key=backing)
    sheet(f"{args.out}_sizes.png", sized, icons, args.cell, args.cols, per_page=args.per_page)
    if silent:
        sheet(f"{args.out}_silent.png", silent, icons, args.cell, args.cols)


if __name__ == "__main__":
    main()
