/* Part-recognition model, run in plain JavaScript.
 *
 * A small convolutional network turns a part icon into a 48-number vector, so
 * that two pictures of the SAME part land close together even when the booklet
 * drew them at different sizes, and two different parts land far apart. It
 * replaces a pile of hand-written rules (pixel grids, surface texture, stud
 * counting) that all failed for the same reason: LEGO redraws icons at
 * whatever size fits the box, and that variation was larger than the
 * difference between two genuinely different parts.
 *
 * Measured on pages the model was never trained on:
 *     rows for one part (duplicates)   7.76%  ->  0.66%
 *     several parts in one row (merges) 1.92%  ->  0.47%
 *
 * Deliberately no ML runtime: the weights are a 66KB float32 blob and the few
 * operations needed (3x3 convolution, ReLU, max-pool, one dense layer) are
 * written out below. That keeps the app dependency-free and fully offline.
 * BatchNorm was folded into the convolution weights when exporting, which is
 * why only conv + bias appears here.
 */

const PARTMODEL_URL = "vendor/partmodel.bin";
const PM_SIDE = 32;      // icons are stretched to this square
const PM_EMB = 48;
// [out channels, in channels] of each 3x3 convolution, then the dense layer
const PM_LAYERS = [[8, 3], [16, 8], [32, 16], [32, 32]];
const PM_FC = [PM_EMB, 33];   // 32 pooled channels + the aspect-ratio number

let partModel = null;      // set once loaded; null means "fall back to the old rules"
let partModelPromise = null;

function loadPartModel() {
  if (partModelPromise) return partModelPromise;
  partModelPromise = fetch(PARTMODEL_URL)
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error("no model file"))))
    .then((buf) => {
      const f = new Float32Array(buf);
      let o = 0;
      const take = (n) => { const s = f.subarray(o, o + n); o += n; return s; };
      const layers = PM_LAYERS.map(([cout, cin]) => ({
        cout, cin, w: take(cout * cin * 9), b: take(cout),
      }));
      const fc = { w: take(PM_FC[0] * PM_FC[1]), b: take(PM_FC[0]) };
      if (o !== f.length) throw new Error(`model size mismatch: used ${o} of ${f.length}`);
      partModel = { layers, fc };
      return partModel;
    })
    .catch((err) => {
      console.warn("Модель распознавания деталей не загрузилась, работаю по старым правилам", err);
      partModel = null;
      return null;
    });
  return partModelPromise;
}

// 3x3 convolution, stride 1, zero padding 1. Loop order is weight-stationary:
// each weight is read once and applied along a whole row, which is what makes
// this fast enough in plain JS for a couple of thousand icons.
function pmConv3x3(inp, cin, h, w, layer) {
  const { cout, w: kern, b: bias } = layer;
  const out = new Float32Array(cout * h * w);
  const plane = h * w;
  for (let oc = 0; oc < cout; oc++) {
    const ob = oc * plane;
    out.fill(bias[oc], ob, ob + plane);
    for (let ic = 0; ic < cin; ic++) {
      const ib = ic * plane;
      const wb = (oc * cin + ic) * 9;
      for (let ky = -1; ky <= 1; ky++) {
        const ys = Math.max(0, -ky), ye = Math.min(h, h - ky);
        for (let kx = -1; kx <= 1; kx++) {
          const wv = kern[wb + (ky + 1) * 3 + (kx + 1)];
          if (wv === 0) continue;
          const xs = Math.max(0, -kx), xe = Math.min(w, w - kx);
          for (let y = ys; y < ye; y++) {
            const orow = ob + y * w, irow = ib + (y + ky) * w + kx;
            for (let x = xs; x < xe; x++) out[orow + x] += wv * inp[irow + x];
          }
        }
      }
    }
  }
  return out;
}

function pmReluMaxPool2(inp, c, h, w) {
  const oh = h >> 1, ow = w >> 1;
  const out = new Float32Array(c * oh * ow);
  for (let ch = 0; ch < c; ch++) {
    const ib = ch * h * w, ob = ch * oh * ow;
    for (let y = 0; y < oh; y++) {
      const r0 = ib + (y * 2) * w, r1 = r0 + w, orow = ob + y * ow;
      for (let x = 0; x < ow; x++) {
        const x2 = x * 2;
        const m = Math.max(inp[r0 + x2], inp[r0 + x2 + 1], inp[r1 + x2], inp[r1 + x2 + 1]);
        out[orow + x] = m > 0 ? m : 0;
      }
    }
  }
  return out;
}

/** canvas (any size) -> 48-number unit vector, or null if the model is absent. */
function partEmbedding(canvas) {
  if (!partModel) return null;
  const cw = canvas.width, ch = canvas.height;

  // Stretch to a square rather than letterbox: letterboxing is what the old
  // signature did, and it spent almost the whole image on padding for long
  // thin parts. The aspect ratio it discards is fed in separately below.
  const sq = document.createElement("canvas");
  sq.width = PM_SIDE; sq.height = PM_SIDE;
  const sctx = sq.getContext("2d", { willReadFrequently: true });
  sctx.imageSmoothingEnabled = true;
  sctx.drawImage(canvas, 0, 0, cw, ch, 0, 0, PM_SIDE, PM_SIDE);
  const px = sctx.getImageData(0, 0, PM_SIDE, PM_SIDE).data;

  const plane = PM_SIDE * PM_SIDE;
  const x = new Float32Array(3 * plane);
  for (let p = 0, i = 0; p < plane; p++, i += 4) {
    x[p] = px[i] / 255;
    x[plane + p] = px[i + 1] / 255;
    x[2 * plane + p] = px[i + 2] / 255;
  }
  return partEmbeddingFromTensor(x, Math.log(cw / ch));
}

/** The network itself: channel-planar input in 0..1, plus the aspect number.
 *  Split out from partEmbedding so it can be checked against PyTorch directly. */
function partEmbeddingFromTensor(input, logAspect) {
  if (!partModel) return null;
  let x = input;
  let c = 3, h = PM_SIDE, w = PM_SIDE;
  for (let li = 0; li < 3; li++) {
    x = pmConv3x3(x, c, h, w, partModel.layers[li]);
    c = partModel.layers[li].cout;
    x = pmReluMaxPool2(x, c, h, w);
    h >>= 1; w >>= 1;
  }
  x = pmConv3x3(x, c, h, w, partModel.layers[3]);
  c = partModel.layers[3].cout;

  // ReLU then global average over each channel
  const pooled = new Float32Array(c + 1);
  const hw = h * w;
  for (let ci = 0; ci < c; ci++) {
    let s = 0;
    for (let i = ci * hw, e = i + hw; i < e; i++) s += x[i] > 0 ? x[i] : 0;
    pooled[ci] = s / hw;
  }
  pooled[c] = logAspect;   // the aspect ratio the stretch threw away

  const { w: fw, b: fb } = partModel.fc;
  const emb = new Float32Array(PM_EMB);
  let norm = 0;
  for (let o = 0; o < PM_EMB; o++) {
    let s = fb[o];
    const row = o * (c + 1);
    for (let i = 0; i <= c; i++) s += fw[row + i] * pooled[i];
    emb[o] = s; norm += s * s;
  }
  norm = Math.sqrt(norm) || 1;
  for (let o = 0; o < PM_EMB; o++) emb[o] /= norm;
  return emb;
}

function embeddingDistance(a, b) {
  let s = 0;
  for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; s += d * d; }
  return Math.sqrt(s);
}
