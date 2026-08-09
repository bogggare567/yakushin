"""Manual audit of a whole booklet.

Buckets every icon in the file exactly the way the app does, then puts two
questions to the eye instead of to a metric:

  СКЛЕЙКИ   for each row, split its members in two and measure the gap. A row
            holding two genuinely different parts splits cleanly; a row holding
            one part re-drawn at several sizes does not.
  ДУБЛИ     for each pair of rows, the distance between their centres. The
            closest pairs are where one part was split across two rows.

Both lists are written out as contact sheets, so the answer is looked at rather
than trusted. Icons and vectors are cached, because the ranking gets re-run far
more often than the PDF changes.

Usage: audit.py file.pdf [--tol 0.20] [--pages 400] [--top 24] [--out audit]
"""
import argparse, os, pickle
import numpy as np
import torch
import fitz
from PIL import Image, ImageDraw

import pipeline as P
import baseline as B
from model import IconEmbedder, IN_SIDE


def embed_batch(net, icons):
    imgs, asps = [], []
    for icon in icons:
        h, w = icon.shape[:2]
        im = Image.fromarray(icon.astype(np.uint8)).resize((IN_SIDE, IN_SIDE), Image.BILINEAR)
        imgs.append(np.asarray(im, dtype=np.float32) / 255.0)
        asps.append(float(np.log(w / h)))
    x = torch.from_numpy(np.stack(imgs)).permute(0, 3, 1, 2)
    a = torch.tensor(asps, dtype=torch.float32)
    out = []
    with torch.no_grad():
        for s in range(0, len(x), 256):
            out.append(net(x[s:s + 256], a[s:s + 256]).numpy())
    return np.concatenate(out)


def load_icons(pdf, pages, cache):
    """(icons, page numbers) for the whole file, cached on disk."""
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            d = pickle.load(f)
        if d["pdf"] == pdf and d["pages"] == pages:
            print(f"кэш: {len(d['icons'])} иконок")
            return d["icons"], d["pages_of"]
    doc = fitz.open(pdf)
    n = min(pages, doc.page_count)
    icons, pages_of = [], []
    for p in range(n):
        for bi, si, icon in P.iter_page_icons(doc, p):
            icons.append(icon)
            pages_of.append(p + 1)
        if (p + 1) % 50 == 0:
            print(f"  стр. {p+1}/{n}, иконок {len(icons)}", flush=True)
    doc.close()
    with open(cache, "wb") as f:
        pickle.dump({"pdf": pdf, "pages": pages, "icons": icons, "pages_of": pages_of}, f)
    return icons, pages_of


def bucket(emb, tol):
    """Greedy nearest-centre grouping — the same order the app walks icons in,
    so a row here is the row the user sees."""
    rows = []            # each: {"c": representative vector, "idx": [...]}
    for i, e in enumerate(emb):
        best, bd = -1, 9.0
        for r, row in enumerate(rows):
            d = float(np.linalg.norm(row["c"] - e))
            if d < bd:
                bd, best = d, r
        if best >= 0 and bd <= tol:
            rows[best]["idx"].append(i)
        else:
            rows.append({"c": e, "idx": [i]})
    return rows


def two_means(E, iters=25):
    """Split a row in two, seeded at its two most distant members."""
    if len(E) < 2:
        return None
    D = np.linalg.norm(E[:, None] - E[None], axis=2)
    a, b = np.unravel_index(np.argmax(D), D.shape)
    ca, cb = E[a].copy(), E[b].copy()
    lab = None
    for _ in range(iters):
        da = np.linalg.norm(E - ca, axis=1)
        db = np.linalg.norm(E - cb, axis=1)
        new = (db < da)
        if lab is not None and (new == lab).all():
            break
        lab = new
        if lab.all() or not lab.any():
            break
        ca = E[~lab].mean(0); ca /= np.linalg.norm(ca) or 1
        cb = E[lab].mean(0);  cb /= np.linalg.norm(cb) or 1
    if lab is None or lab.all() or not lab.any():
        return None
    return lab, float(np.linalg.norm(ca - cb))


def sheet(path, groups, icons, cell=110, pad=26):
    """groups: list of (title, [ (caption, icon_index), ... , None(spacer), ... ])"""
    rows = len(groups)
    widest = max((len(g[1]) for g in groups), default=1)
    W = 300 + widest * (cell + 8)
    H = rows * (cell + pad + 18) + 10
    img = Image.new("RGB", (W, H), (24, 26, 32))
    dr = ImageDraw.Draw(img)
    y = 8
    for title, items in groups:
        for ln, line in enumerate(title.split("\n")):
            dr.text((8, y + 6 + ln * 13), line, fill=(226, 230, 240))
        x = 300
        for it in items:
            if it is None:
                dr.line([(x + cell // 2, y), (x + cell // 2, y + cell)], fill=(240, 120, 90), width=3)
                x += cell + 8
                continue
            cap, gi = it
            ic = Image.fromarray(icons[gi].astype(np.uint8))
            ic.thumbnail((cell, cell))
            img.paste(ic, (x + (cell - ic.width) // 2, y + (cell - ic.height) // 2))
            dr.text((x + 2, y + cell + 4), cap, fill=(150, 200, 255))
            x += cell + 8
        y += cell + pad + 18
    img.save(path)
    print("  ->", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--tol", type=float, default=0.20)
    ap.add_argument("--pages", type=int, default=400)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out", default="audit")
    ap.add_argument("--model", default="model.pt")
    ap.add_argument("--only", default="", help="показать только эти строки, крупно")
    ap.add_argument("--cell", type=int, default=110)
    args = ap.parse_args()

    cache = f".icons_{os.path.basename(args.pdf)}.pkl"
    icons, pages_of = load_icons(args.pdf, args.pages, cache)
    net = IconEmbedder()
    net.load_state_dict(torch.load(args.model, map_location="cpu"))
    net.eval()
    emb = embed_batch(net, icons)
    rows = bucket(emb, args.tol)
    print(f"\nиконок {len(icons)}, строк {len(rows)}, порог {args.tol}\n")

    # ---- merges: rows that fall apart into two ----
    cand = []
    for r, row in enumerate(rows):
        idx = row["idx"]
        if len(idx) < 2:
            continue
        res = two_means(emb[idx])
        if res is None:
            continue
        lab, gap = res
        na, nb = int((~lab).sum()), int(lab.sum())
        cand.append((gap, r, lab, na, nb))
    cand.sort(reverse=True)
    if args.only:
        want = {int(t) for t in args.only.replace(",", " ").split()}
        cand = [c for c in cand if c[1] in want]
    print(f"=== СКЛЕЙКИ: {min(args.top, len(cand))} самых подозрительных строк")
    print(f"  {'строка':>7}{'шт':>5}{'разрыв':>9}{'цвет':>7}{'проп.':>7}  страницы")
    groups = []
    for gap, r, lab, na, nb in cand[:args.top]:
        idx = np.array(rows[r]["idx"])
        pgs = sorted({pages_of[i] for i in idx})
        # what a colour or proportions veto would see between the two halves
        ca = np.mean([B.dominant_color(icons[i]) for i in idx[~lab]], axis=0)
        cb = np.mean([B.dominant_color(icons[i]) for i in idx[lab]], axis=0)
        cdist = float(np.max(np.abs(ca - cb)))
        aa = np.mean([np.log(icons[i].shape[1] / icons[i].shape[0]) for i in idx[~lab]])
        ab = np.mean([np.log(icons[i].shape[1] / icons[i].shape[0]) for i in idx[lab]])
        adist = abs(float(aa - ab))
        head = (f"строка {r}  ×{len(idx)}\nразрыв {gap:.3f}   {na} / {nb}\n"
                f"цвет {cdist:.0f}  проп. {adist:.2f}\nстр. " +
                ",".join(str(p) for p in pgs[:8]) + ("…" if len(pgs) > 8 else ""))
        print(f"  {r:>7}{len(idx):>5}{gap:>9.3f}{cdist:>7.0f}{adist:>7.2f}  {pgs[:8]}")
        cap_n = 8 if args.only else 5
        left = [i for i in idx[~lab]][:cap_n]
        right = [i for i in idx[lab]][:cap_n]
        items = [(f"стр.{pages_of[i]}", i) for i in left] + [None] + [(f"стр.{pages_of[i]}", i) for i in right]
        groups.append((head, items))
    if groups:
        sheet(f"{args.out}_merges.png", groups, icons, cell=args.cell)

    if args.only:
        return
    # ---- duplicates: two rows that are the same part ----
    C = np.stack([emb[row["idx"]].mean(0) for row in rows])
    C /= np.linalg.norm(C, axis=1, keepdims=True)
    D = np.linalg.norm(C[:, None] - C[None], axis=2)
    np.fill_diagonal(D, 9)
    pairs = [(float(D[i, j]), i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))]
    pairs.sort()
    print(f"\n=== ДУБЛИ: {args.top} ближайших пар строк")
    groups = []
    for d, i, j in pairs[:args.top]:
        print(f"  строки {i:>4} ×{len(rows[i]['idx']):<4} и {j:>4} ×{len(rows[j]['idx']):<4}  расстояние {d:.3f}")
        head = f"строки {i} и {j}\nрасстояние {d:.3f}\n×{len(rows[i]['idx'])} и ×{len(rows[j]['idx'])}"
        left = rows[i]["idx"][:4]
        right = rows[j]["idx"][:4]
        items = [(f"стр.{pages_of[k]}", k) for k in left] + [None] + [(f"стр.{pages_of[k]}", k) for k in right]
        groups.append((head, items))
    if groups:
        sheet(f"{args.out}_dupes.png", groups, icons)


if __name__ == "__main__":
    main()
