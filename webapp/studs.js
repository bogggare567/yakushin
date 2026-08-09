/* How many studs across a part is — "4×6", printed next to it.
 *
 * Two reasons. It is how a person looks for a piece in a pile, and it is the
 * one thing that separates mistakes nothing else can: a 6x6 plate and an 8x8
 * are the same colour, the same proportions, and near-identical once shrunk to
 * 48x48 for the model — but they are two studs apart.
 *
 * This counts the studs. An earlier version measured the outline and worked
 * out a footprint from it, which had two faults: it printed a size for parts
 * that have no studs at all (a curved slope labelled 3x1) and it stayed silent
 * on big plates, where the studs are largest and easiest to see. Both came from
 * measuring the wrong thing.
 *
 * The method needs nothing but the one icon — no drawing scale, no camera
 * angle, no fitting across the document:
 *
 *   - studs sit on a lattice, and a lattice appears in the icon's own
 *     autocorrelation as two repeat vectors u and v: shift the picture by one
 *     of them and it lands back on itself;
 *   - the leftmost and rightmost points of the silhouette are two corners of
 *     the top face, and getting from one to the other is W steps along u and L
 *     steps back along v;
 *   - so  right - left = W*u - L*v,  two equations and two unknowns.
 *
 * Nothing in that decides the answer by a threshold, which is why the counts
 * land within about half a percent of whole numbers. That closeness is then a
 * free check: a part whose numbers come out at 16.48 and 0.49 is not a grid of
 * studs, and gets no answer instead of a guess.
 *
 * Measured over a whole booklet against the same code at full resolution: 46%
 * of parts get a size and 73% of the large ones, with the counts a mean 0.07
 * away from whole.
 */

const STUD_MAX = 24;
const STUD_MIN_LAG = 8;        // a repeat shorter than this is antialiasing
const STUD_FIT_TOL = 0.18;     // how far from whole a count may land
const STUD_MIN_AREA = 20000;   // below this there is too little to correlate
const STUD_CROP = 256;         // the lattice is read from a centre crop this big
const STUD_TOP_PEAKS = 6;      // candidate repeat vectors tried per icon

// Footprints LEGO actually makes. A count landing on 1x7 is a near miss on a
// 1x8, not a discovery — and this number exists to be checked against, so a
// wrong one is worse than none.
const STUD_REAL_SIZES = new Set([
  "1x1", "1x2", "1x3", "1x4", "1x6", "1x8", "1x10", "1x12", "1x14", "1x16",
  "2x2", "2x3", "2x4", "2x6", "2x8", "2x10", "2x12", "2x14", "2x16",
  "3x3", "3x4", "3x6", "3x8",
  "4x4", "4x6", "4x8", "4x10", "4x12",
  "6x6", "6x8", "6x10", "6x12", "6x14", "6x16",
  "8x8", "8x11", "8x16", "16x16",
]);

/** In-place iterative radix-2 FFT over one row of a split-complex array. */
function studFft(re, im, n, off, stride, inverse) {
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      const a = off + i * stride, b = off + j * stride;
      let t = re[a]; re[a] = re[b]; re[b] = t;
      t = im[a]; im[a] = im[b]; im[b] = t;
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (inverse ? 2 : -2) * Math.PI / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = off + (i + k) * stride, b = off + (i + k + len / 2) * stride;
        const xr = re[b] * cr - im[b] * ci;
        const xi = re[b] * ci + im[b] * cr;
        re[b] = re[a] - xr; im[b] = im[a] - xi;
        re[a] += xr; im[a] += xi;
        const nr = cr * wr - ci * wi;
        ci = cr * wi + ci * wr; cr = nr;
      }
    }
  }
}

function studFft2(re, im, n, inverse) {
  for (let y = 0; y < n; y++) studFft(re, im, n, y * n, 1, inverse);
  for (let x = 0; x < n; x++) studFft(re, im, n, x, n, inverse);
  if (inverse) {
    const s = 1 / (n * n);
    for (let i = 0; i < re.length; i++) { re[i] *= s; im[i] *= s; }
  }
}

/** Luminance with the flat background removed, plus the silhouette extremes. */
function studPrepare(canvas) {
  const w = canvas.width, h = canvas.height;
  const data = canvas.getContext("2d").getImageData(0, 0, w, h).data;
  const lum = new Float64Array(w * h);
  const fg = new Uint8Array(w * h);
  let sum = 0, n = 0;
  let xl = -1, xr = -1, yl = 0, yr = 0;
  for (let y = 0, p = 0; y < h; y++) {
    for (let x = 0; x < w; x++, p++) {
      const i = p * 4;
      const d = Math.max(Math.abs(data[i] - BOX_BG[0]), Math.abs(data[i + 1] - BOX_BG[1]),
                         Math.abs(data[i + 2] - BOX_BG[2]));
      if (d <= FG_DIFF_THRESHOLD) continue;
      const v = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      lum[p] = v; fg[p] = 1; sum += v; n++;
      if (xl < 0 || x < xl) { xl = x; yl = y; }
      if (x > xr) { xr = x; yr = y; }
    }
  }
  if (n < 200 || xl < 0 || xr - xl < 16) return null;
  const mean = sum / n;
  for (let p = 0; p < lum.length; p++) lum[p] = fg[p] ? lum[p] - mean : 0;
  return { lum, w, h, left: [xl, yl], right: [xr, yr] };
}

/** Candidate pairs of lattice vectors, from the icon's own autocorrelation. */
function studLattice(prep) {
  // A centre crop, not the whole icon: the lattice is the same everywhere on
  // the part, and the transform below costs four times as much for twice the
  // width. Checked against full resolution — same coverage, 93% the same answer.
  const cw = Math.min(prep.w, STUD_CROP), ch = Math.min(prep.h, STUD_CROP);
  const ox = (prep.w - cw) >> 1, oy = (prep.h - ch) >> 1;
  let n = 1;
  while (n < 2 * Math.max(cw, ch)) n <<= 1;   // pad to twice the crop, so the
  if (n < 64) return null;                    // wrap-around does not fold in
  const re = new Float64Array(n * n), im = new Float64Array(n * n);
  for (let y = 0; y < ch; y++) {
    for (let x = 0; x < cw; x++) re[y * n + x] = prep.lum[(y + oy) * prep.w + x + ox];
  }
  studFft2(re, im, n, false);
  for (let i = 0; i < re.length; i++) {
    re[i] = re[i] * re[i] + im[i] * im[i];
    im[i] = 0;
  }
  studFft2(re, im, n, true);

  // centre on zero shift, and normalise so peak heights are comparable
  const lag = Math.min(120, (n >> 1) - 2);
  const size = 2 * lag + 1;
  const ac = new Float64Array(size * size);
  const peak0 = re[0] || 1;
  for (let dy = -lag; dy <= lag; dy++) {
    for (let dx = -lag; dx <= lag; dx++) {
      const sy = (dy + n) % n, sx = (dx + n) % n;
      ac[(dy + lag) * size + dx + lag] = re[sy * n + sx] / peak0;
    }
  }

  const found = [];
  for (let dy = -lag; dy <= lag; dy++) {
    for (let dx = -lag; dx <= lag; dx++) {
      if (!(dy > 0 || (dy === 0 && dx > 0))) continue;       // half plane only
      const r = Math.hypot(dy, dx);
      if (r < STUD_MIN_LAG || r > lag) continue;
      const i = (dy + lag) * size + dx + lag;
      const v = ac[i];
      let top = true;
      for (let sy = -1; sy <= 1 && top; sy++) {
        for (let sx = -1; sx <= 1; sx++) {
          if (!sy && !sx) continue;
          const yy = dy + sy + lag, xx = dx + sx + lag;
          if (yy < 0 || xx < 0 || yy >= size || xx >= size) continue;
          if (ac[yy * size + xx] > v) { top = false; break; }
        }
      }
      if (top) found.push([v, dx, dy]);
    }
  }
  found.sort((a, b) => b[0] - a[0]);
  const vecs = found.slice(0, STUD_TOP_PEAKS).map(([, dx, dy]) => [dx, dy]);
  const pairs = [];
  for (let i = 0; i < vecs.length; i++) {
    for (let j = i + 1; j < vecs.length; j++) {
      const a = vecs[i], b = vecs[j];
      const cross = Math.abs(a[0] * b[1] - a[1] * b[0]);
      const na = Math.hypot(a[0], a[1]), nb = Math.hypot(b[0], b[1]);
      if (cross / (na * nb + 1e-9) > 0.45) pairs.push([a, b, cross]);
    }
  }
  // Smallest cell first. Twice a lattice vector is also a repeat vector, so a
  // doubled pair fits the picture just as well and reports exactly half the
  // studs — a 2x4 brick came back as 2x1. Peak height cannot tell them apart
  // and neither can how close the counts land to whole numbers; the cell area
  // can, because a harmonic's cell is always larger than the real one.
  pairs.sort((a, b) => a[2] - b[2]);
  return pairs;
}

/** [long, short] in studs, or null when there is no stud grid to count. */
function studMeasure(canvas) {
  if (canvas.width * canvas.height < STUD_MIN_AREA) return null;
  const prep = studPrepare(canvas);
  if (!prep) return null;
  const pairs = studLattice(prep);
  if (!pairs || !pairs.length) return null;

  const dx = prep.right[0] - prep.left[0];
  const dy = prep.right[1] - prep.left[1];
  for (const [u, v] of pairs) {
    // solve  W*u - L*v = right - left
    const det = u[0] * -v[1] - -v[0] * u[1];
    if (Math.abs(det) < 1e-6) continue;
    const W = Math.abs((dx * -v[1] - -v[0] * dy) / det);
    const L = Math.abs((u[0] * dy - u[1] * dx) / det);
    const kw = Math.round(W), kl = Math.round(L);
    const err = Math.max(Math.abs(W - kw), Math.abs(L - kl));
    // Several candidate pairs are tried because the strongest autocorrelation
    // peak is sometimes a diagonal of the lattice rather than a side, and peak
    // height alone cannot tell. The answer can: a wrong pair gives counts
    // nowhere near whole, or a size LEGO does not make. Both are checks the
    // candidate must pass, so trying more pairs cannot invent an answer.
    if (err > STUD_FIT_TOL) continue;
    if (kw < 1 || kl < 1 || kw > STUD_MAX || kl > STUD_MAX) continue;
    const size = [Math.max(kw, kl), Math.min(kw, kl)];
    if (!STUD_REAL_SIZES.has(`${size[1]}x${size[0]}`)) continue;
    return { size, err };
  }
  return null;
}

function studLabel(size) {
  return size ? `${size[0]}×${size[1]}` : "";
}
