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
TOP_PEAKS = 6         # candidate repeat vectors considered per icon

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


def lattice(icon, lag=120):
    """The two repeat vectors of the stud grid, from this icon's autocorrelation.

    One icon at a time, deliberately. An earlier version summed these over a
    whole callout box to get more signal, and found directions that were not
    even mirror images of each other: icons in a box are different shapes, and
    adding their autocorrelations smears every peak away.
    """
    fg = P.diff_mask(icon)
    if fg.sum() < MIN_PIXELS:
        return None
    lum = icon.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    lum = lum - lum[fg].mean()
    lum[~fg] = 0.0
    h, w = lum.shape
    F = np.fft.rfft2(lum, s=(2 * h, 2 * w))
    ac = np.fft.fftshift(np.fft.irfft2(F * np.conj(F), s=(2 * h, 2 * w)))
    lag = int(min(lag, h - 1, w - 1))
    if lag < MIN_LAG + 2:
        return None
    win = ac[h - lag:h + lag + 1, w - lag:w + lag + 1]
    win = win / (win[lag, lag] + 1e-9)

    yy, xx = np.mgrid[-lag:lag + 1, -lag:lag + 1]
    rr = np.hypot(yy, xx)
    peak = np.ones_like(win, dtype=bool)
    for sy in (-1, 0, 1):
        for sx in (-1, 0, 1):
            if sy or sx:
                peak &= win >= np.roll(np.roll(win, sy, 0), sx, 1)
    # half plane only: autocorrelation is symmetric through the origin
    peak &= (rr >= MIN_LAG) & (rr <= lag) & ((yy > 0) | ((yy == 0) & (xx > 0)))
    ys, xs = np.nonzero(peak)
    if len(ys) < 2:
        return None
    order = sorted(zip(-win[ys, xs], yy[ys, xs], xx[ys, xs]))[:TOP_PEAKS]
    vecs = [np.array([float(vx), float(vy)]) for _, vy, vx in order]
    pairs = []
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            a, b = vecs[i], vecs[j]
            cross = abs(a[0] * b[1] - a[1] * b[0])
            if cross / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9) > 0.45:
                pairs.append((cross, a, b))
    # Smallest cell first: twice a lattice vector is also a repeat vector, so a
    # doubled pair fits just as well and reports exactly half the studs.
    pairs.sort(key=lambda t: t[0])
    return [(a, b) for _, a, b in pairs] or None


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
        if a < 1 or b < 1 or a > MAX_STUDS or b > MAX_STUDS:
            continue
        size = (max(a, b), min(a, b))
        if size not in REAL_SIZES:
            continue
        return size, err
    return None
