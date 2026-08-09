"""Count the studs on a part, from that part alone.

The size in studs is what the matcher keeps getting wrong — a 6x6 plate put in
with an 8x8 — and it is how a person actually looks for a piece in a pile. It
is also, as the client pointed out, nonsense to print for a part with no studs,
and embarrassing to be unable to print for a big plate, where the studs are
largest of all.

Both faults came from measuring the outline and inferring a footprint from it.
This measures the studs themselves, and needs nothing outside the one icon: no
drawing scale, no camera tilt, no fitting across the document.

  * studs form a lattice, and a lattice shows up in the icon's own
    autocorrelation as two repeat vectors u and v — shift the picture by one of
    those and it lands back on itself;
  * the leftmost and rightmost points of the silhouette are two corners of the
    top face, and getting from one to the other is W steps along u and L steps
    back along v;
  * so  right - left = W*u - L*v,  two equations in two unknowns, and the two
    counts fall straight out.

Nothing here has a threshold that decides the answer, which is why the counts
land within about half a percent of whole numbers. That closeness is not used
to produce them, so it is a free check on them: a part whose numbers come out
at 16.48 and 0.49 is not a rectangular grid of studs and gets no answer.

Earlier attempts are recorded in the README with the numbers that ended them.
The one that got closest is worth naming: reconstructing the top face from the
camera tilt and warping it to a square, so the studs would line up with the
axes. They did not — the warped face came out with the studs running diagonally
across it, which is how it became clear that the edges of the face and the
directions of the stud lattice are not the same pair of directions.
"""
import numpy as np

import pipeline as P

MAX_STUDS = 24
MIN_LAG = 8           # a repeat shorter than this is antialiasing, not studs
FIT_TOL = 0.18        # how far from whole a count may land
MIN_PIXELS = 200      # smaller than this and there is nothing to correlate
STRONG_PEAK = 0.20    # a repeat vector must be this fraction of the best peak
SQUARE_TOL = 0.80     # the two lattice vectors must be near equal in length
TOP_PEAKS = 8         # candidate repeat vectors considered per icon

# Footprints LEGO actually makes. A count landing on 1x7 is a near miss on a
# 1x8, not a discovery, and this number exists to be checked against — a wrong
# one is worse than none.
REAL_SIZES = {
    (1, 1), (2, 1), (3, 1), (4, 1), (6, 1), (8, 1), (10, 1), (12, 1), (14, 1), (16, 1),
    (2, 2), (3, 2), (4, 2), (6, 2), (8, 2), (10, 2), (12, 2), (14, 2), (16, 2),
    (3, 3), (4, 3), (6, 3), (8, 3),
    (4, 4), (6, 4), (8, 4), (10, 4), (12, 4),
    (6, 6), (8, 6), (10, 6), (12, 6), (14, 6), (16, 6),
    (8, 8), (11, 8), (16, 8), (16, 16),
}


def _sample(ac, lag, x, y):
    """Bilinear read of the autocorrelation at a fractional shift."""
    if abs(x) > lag - 1 or abs(y) > lag - 1:
        return None
    x0, y0 = int(np.floor(x)), int(np.floor(y))
    fx, fy = x - x0, y - y0
    i, j = y0 + lag, x0 + lag
    return float(ac[i, j] * (1 - fx) * (1 - fy) + ac[i, j + 1] * fx * (1 - fy)
                 + ac[i + 1, j] * (1 - fx) * fy + ac[i + 1, j + 1] * fx * fy)


def score_lattice(ac, lag, peaks, u, v):
    """How well one candidate lattice explains the whole autocorrelation.

    Two halves, and both are needed:

      support   every point the lattice predicts should actually be a repeat.
                A lattice half the true size predicts twice as many points, and
                the extra ones sit between real studs where nothing repeats.
      coverage  every strong peak that is there should be a point of the
                lattice. A lattice twice the true size explains only every
                other peak and misses the rest.

    Ranking candidates by cell area instead of by this was what made the
    counter unstable: the same part measured at three render sizes came back
    with three different answers 72% of the time, because the ordering, not the
    picture, was deciding.
    """
    pred, support = [], []
    for m in range(-3, 4):
        for n in range(-3, 4):
            if m == 0 and n == 0:
                continue
            x, y = m * u[0] + n * v[0], m * u[1] + n * v[1]
            if np.hypot(x, y) < MIN_LAG:
                continue
            s = _sample(ac, lag, x, y)
            if s is None:
                continue
            pred.append((x, y))
            support.append(s)
    if len(support) < 3:
        return -1.0

    hit = 0
    for py, px, _ in peaks:
        if any(abs(px - x) <= 2.5 and abs(py - y) <= 2.5 for x, y in pred):
            hit += 1
    coverage = hit / max(1, len(peaks))
    return float(np.mean(support)) * coverage


def lattice(icon, lag=120):
    """The stud grid of this icon, as two repeat vectors, or None.

    One icon at a time, deliberately. An earlier version summed the
    autocorrelation over a whole callout box to get more signal, and found
    directions that were not even mirror images of each other: icons in a box
    are different shapes, and adding their autocorrelations smears every peak.
    """
    fg = P.diff_mask(icon)
    if fg.sum() < MIN_PIXELS:
        return None
    lum = icon.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    lum = lum - lum[fg].mean()
    lum[~fg] = 0.0
    h, w = lum.shape
    F = np.fft.rfft2(lum, s=(2 * h, 2 * w))
    full = np.fft.fftshift(np.fft.irfft2(F * np.conj(F), s=(2 * h, 2 * w)))
    lag = int(min(lag, h - 1, w - 1))
    if lag < MIN_LAG + 2:
        return None
    ac = full[h - lag:h + lag + 1, w - lag:w + lag + 1]
    ac = ac / (ac[lag, lag] + 1e-9)

    yy, xx = np.mgrid[-lag:lag + 1, -lag:lag + 1]
    rr = np.hypot(yy, xx)
    peak = np.ones_like(ac, dtype=bool)
    for sy in (-1, 0, 1):
        for sx in (-1, 0, 1):
            if sy or sx:
                peak &= ac >= np.roll(np.roll(ac, sy, 0), sx, 1)
    # half plane only: autocorrelation is symmetric through the origin
    peak &= (rr >= MIN_LAG) & (rr <= lag - 2) & ((yy > 0) | ((yy == 0) & (xx > 0)))
    ys, xs = np.nonzero(peak)
    if len(ys) < 2:
        return None
    vals = ac[ys, xs]
    keep = vals >= STRONG_PEAK * vals.max()
    ys, xs, vals = ys[keep], xs[keep], vals[keep]
    if len(ys) < 2:
        return None
    order = np.argsort(-vals)[:TOP_PEAKS]
    peaks = [(float(yy[ys[i], xs[i]]), float(xx[ys[i], xs[i]]), float(vals[i])) for i in order]
    vecs = [np.array([px, py]) for py, px, _ in peaks]

    best, best_score = None, -1.0
    seen = set()
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            a, b = vecs[i], vecs[j]
            cross = abs(a[0] * b[1] - a[1] * b[0])
            if cross / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9) <= 0.3:
                continue
            u, v = reduce_basis(a, b)
            # Studs sit on a SQUARE grid, and this projection maps a square to
            # a rhombus — equal sides. Measured over the whole booklet, real
            # lattices come out between 0.87 and 1.0; the one part that was
            # getting a size with no studs at all, a curved slope whose ridges
            # repeat in one direction only, sits at 0.36. This is a property of
            # the drawing rather than a tuned threshold.
            lu, lv = np.linalg.norm(u), np.linalg.norm(v)
            if min(lu, lv) / max(lu, lv, 1e-9) < SQUARE_TOL:
                continue
            key = (round(u[0]), round(u[1]), round(v[0]), round(v[1]))
            if key in seen:
                continue
            seen.add(key)
            sc = score_lattice(ac, lag, peaks, u, v)
            if sc > best_score:
                best_score, best = sc, (u, v)
    if best is None or best_score <= 0:
        return None
    return [best]


def reduce_basis(u, v):
    """The two shortest vectors of the lattice these two span (Gauss reduction).

    This is what fixes the counts coming out as (W+L, L). A diagonal of the
    lattice cell is a perfectly good repeat vector, and the cell it spans with
    one of the sides has exactly the same area as the real cell — so "prefer the
    smallest cell" could not tell them apart and a 2x4 brick was reported 6x2.
    Reduction removes the choice: any basis of a lattice, diagonal or not,
    reduces to the same shortest pair.
    """
    u, v = np.array(u, float), np.array(v, float)
    for _ in range(50):
        if np.dot(u, u) > np.dot(v, v):
            u, v = v, u
        m = round(float(np.dot(u, v) / max(np.dot(u, u), 1e-9)))
        if m == 0:
            break
        v = v - m * u
    return u, v


def face_corners(icon):
    """Left and right corners of the top face."""
    fg = P.diff_mask(icon)
    if fg.sum() < MIN_PIXELS:
        return None
    ys, xs = np.nonzero(fg)
    xl, xr = int(xs.min()), int(xs.max())
    if xr - xl < 16:
        return None
    return (np.array([float(xl), float(ys[xs == xl].min())]),
            np.array([float(xr), float(ys[xs == xr].min())]))


def measure(icon):
    """((long, short), distance from whole) or None when there is no stud grid.

    Several candidate pairs of repeat vectors are tried, not just the two
    strongest peaks. The strongest peak is sometimes a diagonal of the lattice
    rather than a side, and there is no way to tell which from the peak height
    alone — but there is from the answer: a wrong pair gives counts nowhere near
    whole numbers, or a size LEGO does not make. Both are checks the candidate
    has to pass rather than knobs, so trying more pairs cannot invent an answer,
    only find one that was already there.
    """
    pairs = lattice(icon)
    corners = face_corners(icon)
    if not pairs or corners is None:
        return None
    left, right = corners
    for u, v in pairs:
        A = np.stack([u, -v], axis=1)
        if abs(float(np.linalg.det(A))) < 1e-6:
            continue
        try:
            counts = np.abs(np.linalg.solve(A, right - left))
        except np.linalg.LinAlgError:
            continue
        k = np.round(counts)
        err = float(np.max(np.abs(counts - k)))
        if err > FIT_TOL:
            continue
        a, b = int(k[0]), int(k[1])
        # Both sides must be at least 2. With a count of 1 the lattice takes
        # exactly one step in that direction and nothing confirms it — the
        # answer rests on a single unverified vector. That is how a smooth
        # white wedge with no studs at all came back "8x1". Real 1xN plates
        # lose out too, but they were already almost never measurable: one row
        # of studs gives no second direction to find.
        if a < 2 or b < 2 or a > MAX_STUDS or b > MAX_STUDS:
            continue
        size = (max(a, b), min(a, b))
        if size not in REAL_SIZES:
            continue
        return size, err
    return None
