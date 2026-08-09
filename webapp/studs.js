/* How many studs across a part is — "4x6", printed next to it.
 *
 * Two reasons this exists. It is how a person actually looks for a piece in a
 * pile, and it is the one thing that separates the mistakes nothing else could:
 * a 6x6 plate and an 8x8 are the same colour, the same proportions, and once
 * squashed to 48x48 very nearly the same picture, so neither the model nor the
 * colour and proportion checks can tell them apart. Their sizes differ by two
 * studs and that is not subtle at all.
 *
 * The booklet never states a size, so it has to be measured. The drawing is a
 * fixed isometric view, which makes the geometry rigid: for a top face spanned
 * by W and L studs,
 *
 *     silhouette width            = scale * (W + L)
 *     right corner - left corner  = scale * ISO_RATIO * (W - L)
 *
 * Both are differences between two corners, so the height of a stud — which
 * sticks up above the face by a fixed amount — cancels out of them. Measuring
 * from the topmost pixel instead was tried and read 1x6 plates as 5x1.
 *
 * The catch is `scale`, which changes from one callout box to the next: LEGO
 * draws icons smaller when a box is crowded. Estimating it inside a single box
 * does not work — five icons and a free scale have several answers that fit
 * about equally well. What does work is that the booklet repeats itself. One
 * part appears in dozens of boxes, the matcher already knows which icons are
 * the same part, and so every box scale and every part size can be solved
 * together across the whole document. That fit is accurate to 0.2% of the
 * width, which is far better than anything a single box gives.
 *
 * One freedom is left: multiplying every scale by c and dividing every size by
 * c fits identically. It is settled by the only thing that can settle it —
 * sizes are whole numbers of studs — by trying values of c and keeping the one
 * that makes the largest share of parts come out whole.
 *
 * Not every part gets an answer, and that is deliberate. The formula describes
 * a rectangular footprint; a slope, a bracket or a round part does not have
 * one, and those come out non-whole and are left blank rather than guessed. On
 * the two booklets measured, 41% and 63% of parts get a size, and those are the
 * common ones — the top rows of the list are almost all covered.
 */

// Vertical step over horizontal one. The booklet uses one fixed camera, so this
// is a single number for the whole document rather than something to fit:
// measured at 0.442 and 0.460 on the two booklets, from the principal axis of
// long thin parts, which follows a lattice direction directly.
const STUD_ISO_RATIO = 0.45;
const STUD_MAX = 24;
const STUD_FIT_TOL = 0.12;      // how far from whole a size may be, in studs
const STUD_SPLIT_GAP = 0.75;    // sizes this far apart are different parts

/** Silhouette width and the drop between its left and right corners, in pixels. */
function studMetrics(canvas) {
  const w = canvas.width, h = canvas.height;
  if (!w || !h) return null;
  const data = canvas.getContext("2d").getImageData(0, 0, w, h).data;
  let xl = -1, xr = -1, yl = 0, yr = 0;
  for (let x = 0; x < w && xl < 0; x++) {
    for (let y = 0; y < h; y++) {
      const i = (y * w + x) * 4;
      const d = Math.max(Math.abs(data[i] - BOX_BG[0]), Math.abs(data[i + 1] - BOX_BG[1]),
                         Math.abs(data[i + 2] - BOX_BG[2]));
      if (d > FG_DIFF_THRESHOLD) { xl = x; yl = y; break; }
    }
  }
  for (let x = w - 1; x >= 0 && xr < 0; x--) {
    for (let y = 0; y < h; y++) {
      const i = (y * w + x) * 4;
      const d = Math.max(Math.abs(data[i] - BOX_BG[0]), Math.abs(data[i + 1] - BOX_BG[1]),
                         Math.abs(data[i + 2] - BOX_BG[2]));
      if (d > FG_DIFF_THRESHOLD) { xr = x; yr = y; break; }
    }
  }
  if (xl < 0 || xr <= xl + 3) return null;
  return { width: xr - xl, ydiff: yr - yl };
}

/** Box scales and part sizes, solved together. `items`: {box, row, width, ydiff}. */
function solveStudSizes(items, nRows) {
  const boxIndex = new Map();
  for (const it of items) if (!boxIndex.has(it.box)) boxIndex.set(it.box, boxIndex.size);
  const nBoxes = boxIndex.size;
  if (!items.length || !nBoxes) return null;

  // Alternating least squares in log space: log width = log scale + log size.
  // Logs keep it linear, and each side is then just an average.
  const boxOf = items.map((it) => boxIndex.get(it.box));
  const logW = items.map((it) => Math.log(Math.max(it.width, 1)));
  const logScale = new Float64Array(nBoxes);
  const logSize = new Float64Array(nRows);
  const num = new Float64Array(Math.max(nBoxes, nRows));
  const cnt = new Float64Array(Math.max(nBoxes, nRows));
  for (let pass = 0; pass < 200; pass++) {
    num.fill(0); cnt.fill(0);
    for (let i = 0; i < items.length; i++) {
      num[items[i].row] += logW[i] - logScale[boxOf[i]];
      cnt[items[i].row]++;
    }
    for (let r = 0; r < nRows; r++) if (cnt[r]) logSize[r] = num[r] / cnt[r];
    num.fill(0); cnt.fill(0);
    for (let i = 0; i < items.length; i++) {
      num[boxOf[i]] += logW[i] - logSize[items[i].row];
      cnt[boxOf[i]]++;
    }
    for (let b = 0; b < nBoxes; b++) if (cnt[b]) logScale[b] = num[b] / cnt[b];
  }

  const scale = Array.from(logScale, Math.exp);
  const size = Array.from(logSize, Math.exp);
  const weight = new Float64Array(nRows);
  for (const it of items) weight[it.row]++;

  // the one free number: the value that makes the most parts come out whole
  let live = [];
  for (let r = 0; r < nRows; r++) if (weight[r] > 0) live.push(r);
  if (!live.length) return null;
  let maxSize = 0, total = 0;
  for (const r of live) { maxSize = Math.max(maxSize, size[r]); total += weight[r]; }
  const lo = 2 / maxSize;
  const hi = 2 * STUD_MAX / Math.max(1e-9, Math.min(...live.map((r) => size[r])));
  let bestC = null, bestScore = -1;
  const steps = 12000;
  for (let s = 0; s <= steps; s++) {
    const c = lo + (hi - lo) * s / steps;
    let hit = 0;
    for (const r of live) {
      const v = size[r] * c, k = Math.round(v);
      if (k >= 2 && k <= 2 * STUD_MAX && Math.abs(v - k) < STUD_FIT_TOL) hit += weight[r];
    }
    if (hit > bestScore) { bestScore = hit; bestC = c; }
  }
  if (bestC === null || bestScore / total < 0.15) return null;

  // per-icon size, each against its own box's scale — this is what makes a row
  // holding two different parts visible: its members disagree.
  const perIcon = items.map((it, i) => it.width / scale[boxOf[i]] * bestC);

  // W - L per row, from the corner drop, using the same box scales.
  //
  // The camera tilt is fitted rather than assumed. It is one fixed number per
  // document, but it is not the same number in every document — measured at
  // 0.442 in one booklet and 0.460 in another — and with it hard-coded, one
  // booklet's parts kept missing the whole-number test by a hair. Searching it
  // is cheap: W+L does not depend on it, so only this half is refitted.
  const rowDrop = new Float64Array(nRows), rowN = new Float64Array(nRows);
  for (let i = 0; i < items.length; i++) {
    rowDrop[items[i].row] += items[i].ydiff / scale[boxOf[i]] * bestC;
    rowN[items[i].row]++;
  }
  let bestRatio = STUD_ISO_RATIO, bestRatioHits = -1;
  for (let r0 = 0.38; r0 <= 0.52; r0 += 0.001) {
    let hits = 0;
    for (const r of live) {
      if (!rowN[r]) continue;
      const s = size[r] * bestC, d = rowDrop[r] / rowN[r] / r0;
      const ks = Math.round(s), kd = Math.round(d);
      if (Math.abs(s - ks) < STUD_FIT_TOL && Math.abs(d - kd) < 0.25
          && (ks + kd) % 2 === 0 && Math.abs(kd) < ks) hits += weight[r];
    }
    if (hits > bestRatioHits) { bestRatioHits = hits; bestRatio = r0; }
  }
  const dnum = new Float64Array(nRows), dcnt = new Float64Array(nRows);
  for (let i = 0; i < items.length; i++) {
    dnum[items[i].row] += items[i].ydiff / (scale[boxOf[i]] * bestRatio) * bestC;
    dcnt[items[i].row]++;
  }

  const sizes = new Array(nRows).fill(null);
  for (const r of live) {
    const s = size[r] * bestC, d = dcnt[r] ? dnum[r] / dcnt[r] : 0;
    const ks = Math.round(s), kd = Math.round(d);
    // W and L are whole, so their sum and difference are both even or both odd
    if (Math.abs(s - ks) >= STUD_FIT_TOL || Math.abs(d - kd) >= 0.3) continue;
    if ((ks + kd) % 2 !== 0 || ks < 2 || Math.abs(kd) >= ks) continue;
    const a = (ks + kd) / 2, b = (ks - kd) / 2;
    if (a < 1 || b < 1 || a > STUD_MAX || b > STUD_MAX) continue;
    const found = [Math.max(a, b), Math.min(a, b)];
    if (isRealStudSize(found)) sizes[r] = found;
  }
  return { sizes, perIcon, anchor: bestC, ratio: bestRatio, covered: bestScore / total };
}

// Footprints LEGO actually makes. A measurement that lands on 1x7 or 1x9 is a
// near miss on a 1x8, not a discovery — those sizes do not exist. Since this
// number is meant as a cross-check, a wrong one is worse than none, so anything
// off the list is dropped rather than shown.
const STUD_REAL_SIZES = new Set([
  "1x1", "1x2", "1x3", "1x4", "1x6", "1x8", "1x10", "1x12", "1x14", "1x16",
  "2x2", "2x3", "2x4", "2x6", "2x8", "2x10", "2x12", "2x14", "2x16",
  "3x3", "3x4", "3x6", "3x8",
  "4x4", "4x6", "4x8", "4x10", "4x12",
  "6x6", "6x8", "6x10", "6x12", "6x14", "6x16",
  "8x8", "8x11", "8x16", "16x16",
]);

function isRealStudSize(size) {
  return !!size && STUD_REAL_SIZES.has(`${Math.min(size[0], size[1])}x${Math.max(size[0], size[1])}`);
}

function studLabel(size) {
  return size ? `${size[0]}×${size[1]}` : "";
}
