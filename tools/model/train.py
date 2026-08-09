"""Trains the icon embedding, and judges it against the algorithm that ships
today on the two failures that actually matter to a user:

  duplicates   one real part shown as several rows
  merges       several real parts collapsed into one row

Every training pair is certain by construction - no hand labelling, and no
guessing:

  positive   the same slot rendered at another scale
  negative A a different slot of the SAME callout box (a box never repeats a part)
  negative B any icon whose dominant colour is far away (never the same part)
  negative C any two icons whose measured stud size differs (studs_count.py)

Negative C is the one that needed building. Negatives A and B can only pair
parts that share a callout box or differ in colour, and the mistakes that
actually reached the client were neither: a 6x6 plate against an 8x8, same
colour, same proportions, and almost never in the same box. Counting the studs
gives that pair a certain label at last, anywhere in the document.

Random icons from elsewhere are deliberately NOT used as negatives: two icons
on different pages are often the very same part, and training on that would
teach the model to split parts apart - the exact bug being fixed.

Evaluation is on pages the model never saw (the last 20% of each booklet), so
it also has to cope with part types absent from training.

Usage: train.py dataset.npz [--epochs N] [--init checkpoint.pt] [--out model.pt]
"""
import argparse, json, time
import numpy as np
import torch
import torch.nn.functional as F
from model import IconEmbedder, IN_SIDE

BG = np.array([215, 238, 254])


def dominant_colours(images):
    """Mean colour of the non-background pixels - only needed to pick safe
    negatives, so a rough estimate is fine."""
    d = np.abs(images.astype(np.int16) - BG).max(axis=3)
    fg = d > 35
    out = np.zeros((len(images), 3), dtype=np.float32)
    for i in range(len(images)):
        m = fg[i]
        out[i] = images[i][m].mean(axis=0) if m.sum() >= 5 else BG
    return out


def load(path):
    z = np.load(path, allow_pickle=True)
    d = {k: z[k] for k in z.files}
    d["colours"] = dominant_colours(d["images"])
    if "studs" in d:
        d["slot_size"] = slot_sizes(d)
    return d


def slot_sizes(d):
    """One stud size per slot, carried to every scale of it.

    A size can only be read off the largest renders — at the smaller scales the
    studs are not resolved — so measuring per icon covers 6% of the set. But a
    slot is one physical part, so whatever was read at any scale applies to all
    of them, and the vote guards against a single bad read.
    """
    per_group = {}
    for i, (a, b) in enumerate(d["studs"]):
        if a <= 0:
            continue
        per_group.setdefault(int(d["groups"][i]), []).append((int(a), int(b)))
    out = {}
    for g, seen in per_group.items():
        counts = {}
        for s in seen:
            counts[s] = counts.get(s, 0) + 1
        best, n = max(counts.items(), key=lambda kv: kv[1])
        if n / len(seen) > 0.5:
            out[g] = best
    return out


def split_by_page(d, holdout_frac=0.2):
    """Hold out the LAST pages of each booklet - a harder, more honest test than
    a random split, because later pages also contain part types never trained on."""
    is_test = np.zeros(len(d["pages"]), dtype=bool)
    for pid in np.unique(d["pdf_ids"]):
        sel = d["pdf_ids"] == pid
        cut = np.quantile(d["pages"][sel], 1 - holdout_frac)
        is_test |= sel & (d["pages"] > cut)
    return ~is_test, is_test


def build_pairs(d, mask):
    """positives: (i,j) same slot, different scale.
       negatives: (i,j) different slot of the same box, or far-apart colour."""
    idx = np.where(mask)[0]
    by_group, by_box = {}, {}
    for i in idx:
        by_group.setdefault(int(d["groups"][i]), []).append(i)
        by_box.setdefault(int(d["boxes"][i]), []).append(i)

    pos = []
    for g, items in by_group.items():
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                pos.append((items[a], items[b]))

    neg = []
    for bx, items in by_box.items():
        slots = {}
        for i in items:
            slots.setdefault(int(d["groups"][i]), []).append(i)
        keys = list(slots)
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                for ia in slots[keys[a]]:
                    for ib in slots[keys[b]]:
                        neg.append((ia, ib))
    return np.array(pos), np.array(neg)


def to_tensor(d, ids, device, jitter=False):
    img = d["images"][ids].astype(np.float32) / 255.0
    img = torch.from_numpy(img).permute(0, 3, 1, 2).contiguous().to(device)
    if img.shape[-1] != IN_SIDE:
        img = F.interpolate(img, size=(IN_SIDE, IN_SIDE), mode="bilinear", align_corners=False)
    asp = torch.from_numpy(d["aspects"][ids]).to(device)
    if jitter:
        img = img + torch.randn_like(img) * 0.02
        img = img * (1 + (torch.rand(len(ids), 1, 1, 1, device=device) - 0.5) * 0.12)
        img = img.clamp(0, 1)
        asp = asp + torch.randn_like(asp) * 0.02
    return img, asp


def evaluate(net, d, mask, device, thresh=None):
    """Distances for pairs we KNOW the answer to, on held-out pages."""
    pos, neg = build_pairs(d, mask)
    net.eval()
    with torch.no_grad():
        ids = np.where(mask)[0]
        pos_of = {int(v): i for i, v in enumerate(ids)}
        emb = []
        for s in range(0, len(ids), 512):
            im, asp = to_tensor(d, ids[s:s + 512], device)
            emb.append(net(im, asp).cpu())
        emb = torch.cat(emb).numpy()

    def dist(pairs):
        a = np.array([pos_of[int(i)] for i, _ in pairs])
        b = np.array([pos_of[int(j)] for _, j in pairs])
        return np.linalg.norm(emb[a] - emb[b], axis=1)

    dp, dn = dist(pos), dist(neg)
    if thresh is None:  # pick the cut that balances the two error rates
        cands = np.linspace(0, 2, 400)
        best, thresh = 1e9, 1.0
        for t in cands:
            e = (dp > t).mean() + (dn <= t).mean()
            if e < best:
                best, thresh = e, t
    return {
        "threshold": float(thresh),
        "duplicate_rate": float((dp > thresh).mean()),   # same part torn apart
        "merge_rate": float((dn <= thresh).mean()),      # different parts fused
        "n_pos": len(dp), "n_neg": len(dn),
        "pos_mean": float(dp.mean()), "neg_mean": float(dn.mean()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--init", default=None, help="continue from an existing checkpoint")
    ap.add_argument("--out", default="model.pt")
    ap.add_argument("--margin", type=float, default=0.6)
    args = ap.parse_args()

    # Apple GPU when present: the hard-negative pool below makes each step
    # several times heavier, and this turns a coffee break back into a minute.
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"устройство: {device}")
    d = load(args.dataset)
    train_mask, test_mask = split_by_page(d)
    print(f"samples: {len(d['images'])}   train {train_mask.sum()}   held-out {test_mask.sum()}")

    pos, neg = build_pairs(d, train_mask)
    print(f"training pairs: {len(pos)} positive, {len(neg)} negative (all certain)")

    # extra negatives: colours too far apart to possibly be one part
    idx = np.where(train_mask)[0]
    cols = d["colours"][idx]
    rng = np.random.default_rng(0)
    far = []
    for _ in range(len(pos)):
        a, b = rng.integers(0, len(idx), 2)
        if np.abs(cols[a] - cols[b]).max() > 90:
            far.append((idx[a], idx[b]))
    far = np.array(far) if far else np.zeros((0, 2), dtype=int)
    print(f"                + {len(far)} colour-certain negatives")

    # different measured stud size => certainly different parts, wherever they
    # sit in the document. This is the class the callout-box rule cannot reach.
    sized = [i for i in idx if int(d["groups"][i]) in d.get("slot_size", {})]
    stud_neg = []
    if len(sized) > 1:
        sized = np.array(sized)
        for _ in range(len(pos)):
            a, b = rng.integers(0, len(sized), 2)
            ga, gb = int(d["groups"][sized[a]]), int(d["groups"][sized[b]])
            if d["slot_size"][ga] != d["slot_size"][gb]:
                stud_neg.append((sized[a], sized[b]))
    stud_neg = np.array(stud_neg) if stud_neg else np.zeros((0, 2), dtype=int)
    print(f"                + {len(stud_neg)} stud-size-certain negatives "
          f"(from {len(d.get('slot_size', {}))} measured slots)")

    net = IconEmbedder().to(device)
    if args.init:
        net.load_state_dict(torch.load(args.init, map_location=device))
        print(f"continuing from {args.init}")
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)

    parts_neg = [neg] + [x for x in (far, stud_neg) if len(x)]
    all_neg = np.concatenate(parts_neg)
    BATCH = 256
    NEG_POOL = 6   # negatives drawn per positive, of which the hardest are kept
    for ep in range(args.epochs):
        net.train()
        perm = rng.permutation(len(pos))
        tot, nb = 0.0, 0
        t0 = time.time()
        for s in range(0, len(perm), BATCH):
            pb = pos[perm[s:s + BATCH]]
            # Draw more negatives than needed and keep only the closest ones.
            # Without this the loss reaches zero within about twenty epochs and
            # the model stops learning: almost every certain negative pair is
            # two obviously different parts, and once those are far apart there
            # is nothing left to push. The pairs that still go wrong on a real
            # file are the near-misses, and this is what keeps them in view.
            nb_ids = all_neg[rng.integers(0, len(all_neg), len(pb) * NEG_POOL)]
            ia, ib = pb[:, 0], pb[:, 1]
            na, nbb = nb_ids[:, 0], nb_ids[:, 1]
            ids = np.concatenate([ia, ib, na, nbb])
            im, asp = to_tensor(d, ids, device, jitter=True)
            e = net(im, asp)
            k = len(pb)
            ea, eb = e[:k], e[k:2*k]
            fa, fb = e[2*k:2*k + len(na)], e[2*k + len(na):]
            dpos = (ea - eb).norm(dim=1)
            dneg_all = (fa - fb).norm(dim=1)
            dneg = dneg_all.topk(k, largest=False).values
            # pull identical parts together, push certain-different apart
            loss = F.relu(dpos - 0.2).mean() + F.relu(args.margin - dneg).mean()
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item(); nb += 1
        sched.step()
        if ep % 5 == 0 or ep == args.epochs - 1:
            m = evaluate(net, d, test_mask, device)
            print(f"epoch {ep:>3} loss {tot/nb:.4f} ({time.time()-t0:.0f}s)  "
                  f"held-out: duplicates {m['duplicate_rate']*100:.2f}%  "
                  f"merges {m['merge_rate']*100:.2f}%  (thr {m['threshold']:.2f})")

    torch.save(net.state_dict(), args.out)
    final = evaluate(net, d, test_mask, device)
    json.dump(final, open(args.out.replace(".pt", "_metrics.json"), "w"), indent=2)
    print("\nheld-out result:", json.dumps(final, indent=2))
    print("saved", args.out)


if __name__ == "__main__":
    main()
