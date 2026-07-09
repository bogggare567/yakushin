/* global pdfjsLib, GLYPH_TEMPLATES, GLYPH_W, GLYPH_H */
pdfjsLib.GlobalWorkerOptions.workerSrc = "https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js";

const RENDER_SCALE = 3.0; // px per pdf point - higher = crisper thumbnails, slower processing
const BOX_BG = [215, 238, 254]; // the light-blue "new parts" callout background color
const BOX_COLOR_TOL = 14; // tolerance for matching the box background color
const FG_DIFF_THRESHOLD = 35; // per-pixel max-channel diff to count as foreground (icon/text) inside a box
const SCALE_REF = 2.0; // the render scale the px-based constants below were tuned at
const SIZE_K = RENDER_SCALE / SCALE_REF;
const MIN_BOX_W = 40 * SIZE_K, MIN_BOX_H = 40 * SIZE_K, MIN_BOX_AREA = 400 * SIZE_K * SIZE_K;
const MIN_COL_GAP = 6 * SIZE_K; // px of background between two item slots
const MIN_ROW_GAP = 2 * SIZE_K; // px of background rows between icon and qty text
const SIG_SIZE = 14; // color-grid signature size (px) used to identify/dedup a part's icon
const SIG_MARGIN = 2; // border reserved inside SIG_SIZE so small shifts stay in-bounds
const SIG_MAX_SHIFT = 2; // px of shift tried in each direction when comparing two signatures
const SIG_DIST_TOL = 40; // max mean color difference (0-255 scale) to call two icons the same part
const COLOR_TOL = 24;
const GLYPH_MIN_GAP = 1; // px of background columns between two digit glyphs
const GLYPH_MAX_DIST_FRAC = 0.22; // fraction of bits mismatched above which a glyph match is untrusted

const pdfInput = document.getElementById("pdf-input");
const fileInfo = document.getElementById("file-info");
const rangeFields = document.getElementById("range-fields");
const pageFrom = document.getElementById("page-from");
const pageTo = document.getElementById("page-to");
const pageTotalLabel = document.getElementById("page-total");
const actionField = document.getElementById("action-field");
const analyzeBtn = document.getElementById("analyze-btn");
const progressWrap = document.getElementById("progress-wrap");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");
const summaryEl = document.getElementById("summary");
const resultsEl = document.getElementById("results");
const viewControls = document.getElementById("view-controls");
const modeListBtn = document.getElementById("mode-list-btn");
const modeStepBtn = document.getElementById("mode-step-btn");
const sortSelect = document.getElementById("sort-select");
const stepModeEl = document.getElementById("step-mode");
const stepPrevBtn = document.getElementById("step-prev");
const stepNextBtn = document.getElementById("step-next");
const stepSlider = document.getElementById("step-slider");
const stepLabel = document.getElementById("step-label");
const stepPageImg = document.getElementById("step-page-img");
const stepCurrentItems = document.getElementById("step-current-items");
const stepRemainingItems = document.getElementById("step-remaining-items");
const stepPagePreview = document.getElementById("step-page-preview");
const zoomOverlay = document.getElementById("zoom-overlay");
const zoomImg = document.getElementById("zoom-img");
const zoomSpinner = document.getElementById("zoom-spinner");
const zoomClose = document.getElementById("zoom-close");
const lanBanner = document.getElementById("lan-banner");
const lanQrBtn = document.getElementById("lan-qr-btn");
const qrOverlay = document.getElementById("qr-overlay");
const qrCanvasHolder = document.getElementById("qr-canvas-holder");
const qrUrl = document.getElementById("qr-url");
const qrClose = document.getElementById("qr-close");

let pdfDoc = null;

const state = {
  buckets: [],
  pageRecords: [],
  from: 1,
  to: 1,
  pagesWithParts: 0,
  mode: "list",
  sortMode: "count-desc",
  stepIndex: 0,
};

pdfInput.addEventListener("change", onPdfSelected);
analyzeBtn.addEventListener("click", runAnalysis);
modeListBtn.addEventListener("click", () => setMode("list"));
modeStepBtn.addEventListener("click", () => setMode("step"));
sortSelect.addEventListener("change", () => {
  state.sortMode = sortSelect.value;
  render();
});
stepPrevBtn.addEventListener("click", () => goToStep(state.stepIndex - 1));
stepNextBtn.addEventListener("click", () => goToStep(state.stepIndex + 1));
stepSlider.addEventListener("input", () => goToStep(parseInt(stepSlider.value, 10)));
stepPagePreview.addEventListener("click", openZoom);
zoomClose.addEventListener("click", closeZoom);
zoomOverlay.addEventListener("click", (e) => { if (e.target === zoomOverlay) closeZoom(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !zoomOverlay.hidden) closeZoom(); });

async function openZoom() {
  const rec = state.pageRecords[state.stepIndex];
  if (!rec) return;
  zoomImg.src = "";
  zoomSpinner.hidden = false;
  zoomOverlay.hidden = false;
  try {
    const dataUrl = await renderPageZoomDataUrl(rec.pageNum);
    zoomImg.src = dataUrl;
  } catch (err) {
    console.error("Не удалось отрисовать страницу крупным планом", err);
    zoomImg.src = rec.thumbDataUrl; // fall back to the already-available thumbnail
  }
  zoomSpinner.hidden = true;
}

function closeZoom() {
  zoomOverlay.hidden = true;
  zoomImg.src = "";
}

async function onPdfSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  fileInfo.textContent = "Открываю PDF…";
  resultsEl.innerHTML = "";
  summaryEl.hidden = true;

  const buf = await file.arrayBuffer();
  pdfDoc = await pdfjsLib.getDocument({ data: buf }).promise;

  fileInfo.textContent = `${file.name} — ${pdfDoc.numPages} стр.`;
  pageTotalLabel.textContent = `всего страниц: ${pdfDoc.numPages}`;
  pageFrom.value = 1;
  pageTo.value = Math.min(pdfDoc.numPages, 150);
  pageFrom.max = pdfDoc.numPages;
  pageTo.max = pdfDoc.numPages;
  rangeFields.hidden = false;
  actionField.hidden = false;
}

async function runAnalysis() {
  if (!pdfDoc) return;
  const from = clamp(parseInt(pageFrom.value, 10) || 1, 1, pdfDoc.numPages);
  const to = clamp(parseInt(pageTo.value, 10) || from, from, pdfDoc.numPages);

  analyzeBtn.disabled = true;
  progressWrap.hidden = false;
  resultsEl.innerHTML = "";
  summaryEl.hidden = true;
  viewControls.hidden = true;
  stepModeEl.hidden = true;
  setProgress(0, "Подготовка…");

  const buckets = [];
  const pageRecords = [];
  const totalPages = to - from + 1;
  let pagesWithParts = 0;

  for (let pageNum = from; pageNum <= to; pageNum++) {
    setProgress((pageNum - from) / totalPages, `Страница ${pageNum} из ${to} (${from}-${to})`);
    try {
      const { items, thumbDataUrl } = await processPage(pageNum);
      if (items.length) pagesWithParts++;
      const pageItems = [];
      for (const it of items) {
        const bucketIdx = addToBuckets(buckets, it, pageNum);
        const qty = it.qty ?? 1;
        pageItems.push({ bucketIdx, qty, unsure: it.unsure || it.qty === null });
      }
      pageRecords.push({ pageNum, thumbDataUrl, items: pageItems });
    } catch (err) {
      console.error("Ошибка на странице", pageNum, err);
    }
    // yield to the UI thread so the progress bar actually animates
    await new Promise((r) => setTimeout(r, 0));
  }

  setProgress(1, "Готово");
  state.buckets = buckets;
  state.pageRecords = pageRecords;
  state.from = from;
  state.to = to;
  state.pagesWithParts = pagesWithParts;
  state.stepIndex = 0;
  viewControls.hidden = false;
  setMode("list");
  analyzeBtn.disabled = false;
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function setProgress(frac, label) {
  progressFill.style.width = `${Math.round(frac * 100)}%`;
  progressLabel.textContent = label;
}

async function processPage(pageNum) {
  const page = await pdfDoc.getPage(pageNum);
  const viewport = page.getViewport({ scale: RENDER_SCALE });
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  await page.render({ canvasContext: ctx, viewport }).promise;

  const full = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const boxes = findBlueBoxes(full, canvas.width, canvas.height);

  const items = [];
  for (const box of boxes) {
    items.push(...extractBoxItems(canvas, ctx, box));
  }
  const thumbDataUrl = makePageThumb(canvas);
  return { items, thumbDataUrl };
}

function makePageThumb(canvas) {
  const targetW = Math.min(900, canvas.width);
  const scale = targetW / canvas.width;
  const tw = Math.round(targetW), th = Math.round(canvas.height * scale);
  const t = document.createElement("canvas");
  t.width = tw; t.height = th;
  t.getContext("2d").drawImage(canvas, 0, 0, tw, th);
  return t.toDataURL("image/jpeg", 0.8);
}

const ZOOM_SCALE = 4.5; // re-rendered on demand for the click-to-zoom overlay

async function renderPageZoomDataUrl(pageNum) {
  const page = await pdfDoc.getPage(pageNum);
  const viewport = page.getViewport({ scale: ZOOM_SCALE });
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
  return canvas.toDataURL("image/jpeg", 0.9);
}

// ---------- box detection (connected components on box-background color) ----------

function findBlueBoxes(imgData, width, height) {
  const { data } = imgData;
  const mask = new Uint8Array(width * height);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    if (
      Math.abs(data[i] - BOX_BG[0]) <= BOX_COLOR_TOL &&
      Math.abs(data[i + 1] - BOX_BG[1]) <= BOX_COLOR_TOL &&
      Math.abs(data[i + 2] - BOX_BG[2]) <= BOX_COLOR_TOL
    ) {
      mask[p] = 1;
    }
  }

  const visited = new Uint8Array(width * height);
  const boxes = [];
  const stack = [];
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      if (!mask[idx] || visited[idx]) continue;
      let minX = x, maxX = x, minY = y, maxY = y, count = 0;
      stack.length = 0;
      stack.push(idx);
      visited[idx] = 1;
      while (stack.length) {
        const cur = stack.pop();
        count++;
        const cx = cur % width, cy = (cur / width) | 0;
        if (cx < minX) minX = cx;
        if (cx > maxX) maxX = cx;
        if (cy < minY) minY = cy;
        if (cy > maxY) maxY = cy;
        if (cx > 0) { const n = cur - 1; if (mask[n] && !visited[n]) { visited[n] = 1; stack.push(n); } }
        if (cx < width - 1) { const n = cur + 1; if (mask[n] && !visited[n]) { visited[n] = 1; stack.push(n); } }
        if (cy > 0) { const n = cur - width; if (mask[n] && !visited[n]) { visited[n] = 1; stack.push(n); } }
        if (cy < height - 1) { const n = cur + width; if (mask[n] && !visited[n]) { visited[n] = 1; stack.push(n); } }
      }
      const w = maxX - minX + 1, h = maxY - minY + 1;
      const area = w * h;
      if (w < MIN_BOX_W || h < MIN_BOX_H || area < MIN_BOX_AREA) continue;
      if (count / area < 0.5) continue;
      boxes.push({ x0: minX, y0: minY, x1: maxX, y1: maxY });
    }
  }
  return boxes;
}

// ---------- item segmentation within a box ----------

function diffMask(data, w, h, threshold) {
  const raw = new Uint8Array(w * h);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    const dr = Math.abs(data[i] - BOX_BG[0]);
    const dg = Math.abs(data[i + 1] - BOX_BG[1]);
    const db = Math.abs(data[i + 2] - BOX_BG[2]);
    raw[p] = Math.max(dr, dg, db) > threshold ? 1 : 0;
  }
  return raw;
}

function binaryOpen3x3(mask, w, h) {
  const eroded = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let all = mask[y * w + x];
      if (all) {
        for (let dy = -1; dy <= 1 && all; dy++) {
          for (let dx = -1; dx <= 1 && all; dx++) {
            const nx = x + dx, ny = y + dy;
            if (nx < 0 || ny < 0 || nx >= w || ny >= h) { all = 0; break; }
            if (!mask[ny * w + nx]) all = 0;
          }
        }
      }
      eroded[y * w + x] = all;
    }
  }
  const dilated = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let any = 0;
      for (let dy = -1; dy <= 1 && !any; dy++) {
        for (let dx = -1; dx <= 1 && !any; dx++) {
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
          if (eroded[ny * w + nx]) any = 1;
        }
      }
      dilated[y * w + x] = any;
    }
  }
  return dilated;
}

// gentler opening for tiny digit strokes: 2x2 structuring element
function binaryOpen2x2(mask, w, h) {
  const eroded = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      eroded[y * w + x] =
        mask[y * w + x] &&
        (x + 1 < w ? mask[y * w + x + 1] : 0) &&
        (y + 1 < h ? mask[(y + 1) * w + x] : 0) &&
        (x + 1 < w && y + 1 < h ? mask[(y + 1) * w + x + 1] : 0)
          ? 1 : 0;
    }
  }
  const dilated = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      dilated[y * w + x] =
        eroded[y * w + x] ||
        (x - 1 >= 0 && eroded[y * w + x - 1]) ||
        (y - 1 >= 0 && eroded[(y - 1) * w + x]) ||
        (x - 1 >= 0 && y - 1 >= 0 && eroded[(y - 1) * w + x - 1])
          ? 1 : 0;
    }
  }
  return dilated;
}

function buildFgMask(imgData, w, h) {
  return binaryOpen3x3(diffMask(imgData.data, w, h, FG_DIFF_THRESHOLD), w, h);
}

function findRuns(boolArr, minGap) {
  const runs = [];
  let inRun = false, start = 0;
  let i = 0;
  const n = boolArr.length;
  while (i < n) {
    if (boolArr[i]) {
      if (!inRun) { inRun = true; start = i; }
      i++;
    } else {
      let j = i;
      while (j < n && !boolArr[j]) j++;
      if (inRun && (j - i) >= minGap) { runs.push([start, i]); inRun = false; }
      i = j;
    }
  }
  if (inRun) runs.push([start, n]);
  return runs;
}

function extractBoxItems(pageCanvas, pageCtx, box) {
  const inset = 4;
  const x0 = box.x0 + inset, y0 = box.y0 + inset;
  const w = (box.x1 - inset) - x0, h = (box.y1 - inset) - y0;
  if (w <= 0 || h <= 0) return [];
  const subData = pageCtx.getImageData(x0, y0, w, h);
  const fg = buildFgMask(subData, w, h);

  const colHasFg = new Array(w).fill(false);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) { if (fg[y * w + x]) { colHasFg[x] = true; break; } }
  }
  const colRuns = findRuns(colHasFg, MIN_COL_GAP);

  const slots = [];
  for (const [cs, ce] of colRuns) {
    if (ce - cs < 8) continue;
    let r0 = -1, r1 = -1;
    for (let y = 0; y < h; y++) {
      let any = false;
      for (let x = cs; x < ce; x++) { if (fg[y * w + x]) { any = true; break; } }
      if (any) { if (r0 === -1) r0 = y; r1 = y; }
    }
    if (r0 === -1) continue;
    slots.push({ cs, ce, r0, r1 });
  }

  const splitHeights = [];
  const partial = slots.map((slot) => {
    const { cs, ce, r0, r1 } = slot;
    const rowHasFg = [];
    for (let y = r0; y <= r1; y++) {
      let any = false;
      for (let x = cs; x < ce; x++) { if (fg[y * w + x]) { any = true; break; } }
      rowHasFg.push(any);
    }
    const gaps = findRuns(rowHasFg.map((v) => !v), MIN_ROW_GAP);
    if (gaps.length) {
      const best = gaps.reduce((a, b) => (b[1] - b[0] > a[1] - a[0] ? b : a));
      const splitRow = Math.round((best[0] + best[1]) / 2);
      splitHeights.push(rowHasFg.length - splitRow);
      return { slot, splitRow };
    }
    return { slot, splitRow: null };
  });

  const medianTextH = splitHeights.length
    ? splitHeights.sort((a, b) => a - b)[Math.floor(splitHeights.length / 2)]
    : Math.round(h * 0.22);

  const results = [];
  for (const { slot, splitRow } of partial) {
    const { cs, ce, r0, r1 } = slot;
    const slotH = r1 - r0 + 1;
    const effSplit = splitRow !== null ? splitRow : Math.max(1, slotH - medianTextH);

    const imgCanvas = document.createElement("canvas");
    imgCanvas.width = ce - cs;
    imgCanvas.height = effSplit;
    imgCanvas.getContext("2d").drawImage(
      pageCanvas, x0 + cs, y0 + r0, ce - cs, effSplit, 0, 0, ce - cs, effSplit
    );

    const txtH = slotH - effSplit;
    let qtyResult = { qty: null, unsure: true };
    if (txtH > 3) {
      qtyResult = readQuantity(subData, w, cs, ce, r0 + effSplit, r0 + slotH - 1);
    }

    results.push({ imgCanvas, qty: qtyResult.qty, unsure: qtyResult.unsure });
  }
  return results;
}

// ---------- digit glyph recognition (template matching, no OCR needed) ----------

const TEMPLATES = GLYPH_TEMPLATES.map((t) => ({ label: t.label, bits: unpackHexBits(t.bits, t.n) }));
const GLYPH_MAX_DIST = Math.round(GLYPH_W * GLYPH_H * GLYPH_MAX_DIST_FRAC);

function unpackHexBits(hexstr, n) {
  const out = new Uint8Array(n);
  let bitIdx = 0;
  for (let i = 0; i < hexstr.length && bitIdx < n; i++) {
    const val = parseInt(hexstr[i], 16);
    for (let b = 3; b >= 0 && bitIdx < n; b--, bitIdx++) {
      out[bitIdx] = (val >> b) & 1;
    }
  }
  return out;
}

function readQuantity(subData, subW, cs, ce, rowStart, rowEnd) {
  const w = ce - cs, h = rowEnd - rowStart + 1;
  if (w <= 0 || h <= 0) return { qty: null, unsure: true };
  const local = new Uint8ClampedArray(w * h * 4);
  const src = subData.data;
  for (let y = 0; y < h; y++) {
    const srcRow = (rowStart + y) * subW + cs;
    for (let x = 0; x < w; x++) {
      const si = (srcRow + x) * 4;
      const di = (y * w + x) * 4;
      local[di] = src[si]; local[di + 1] = src[si + 1]; local[di + 2] = src[si + 2]; local[di + 3] = 255;
    }
  }
  const fg = binaryOpen2x2(diffMask(local, w, h, FG_DIFF_THRESHOLD), w, h);

  const colHasFg = new Array(w).fill(false);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) { if (fg[y * w + x]) { colHasFg[x] = true; break; } }
  }
  const runs = findRuns(colHasFg, GLYPH_MIN_GAP);
  if (!runs.length) return { qty: null, unsure: true };

  let label = "";
  let anyUnsure = false;
  for (const [gs, ge] of runs) {
    let r0 = -1, r1 = -1;
    for (let y = 0; y < h; y++) {
      let any = false;
      for (let x = gs; x < ge; x++) { if (fg[y * w + x]) { any = true; break; } }
      if (any) { if (r0 === -1) r0 = y; r1 = y; }
    }
    if (r0 === -1) continue;
    const normalized = resizeGlyph(fg, w, gs, ge, r0, r1);
    const { bestLabel, bestDist } = classifyGlyph(normalized);
    if (bestDist > GLYPH_MAX_DIST) { anyUnsure = true; continue; }
    label += bestLabel;
  }

  // drop trailing "x" marker(s); keep only leading digits
  const digits = label.replace(/x+$/i, "");
  if (!/^\d+$/.test(digits)) return { qty: null, unsure: true };
  return { qty: parseInt(digits, 10), unsure: anyUnsure };
}

function resizeGlyph(fg, fgW, x0, x1, y0, y1) {
  const srcW = x1 - x0, srcH = y1 - y0 + 1;
  const pad = 2;
  const scale = Math.min((GLYPH_W - 2 * pad) / srcW, (GLYPH_H - 2 * pad) / srcH);
  const nw = Math.max(1, Math.round(srcW * scale));
  const nh = Math.max(1, Math.round(srcH * scale));
  const ox = Math.floor((GLYPH_W - nw) / 2), oy = Math.floor((GLYPH_H - nh) / 2);
  const out = new Uint8Array(GLYPH_W * GLYPH_H);
  for (let y = 0; y < nh; y++) {
    const sy = Math.min(srcH - 1, Math.floor(y / scale));
    for (let x = 0; x < nw; x++) {
      const sx = Math.min(srcW - 1, Math.floor(x / scale));
      out[(oy + y) * GLYPH_W + (ox + x)] = fg[(y0 + sy) * fgW + (x0 + sx)];
    }
  }
  return out;
}

function classifyGlyph(bits) {
  let bestLabel = "?", bestDist = Infinity;
  for (const t of TEMPLATES) {
    let d = 0;
    for (let i = 0; i < bits.length; i++) if (bits[i] !== t.bits[i]) d++;
    if (d < bestDist) { bestDist = d; bestLabel = t.label; }
  }
  return { bestLabel, bestDist };
}

// ---------- autocrop + hashing + bucketing ----------

function autocropCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
  let minX = width, maxX = -1, minY = height, maxY = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const dr = Math.abs(data[i] - BOX_BG[0]);
      const dg = Math.abs(data[i + 1] - BOX_BG[1]);
      const db = Math.abs(data[i + 2] - BOX_BG[2]);
      if (Math.max(dr, dg, db) > FG_DIFF_THRESHOLD) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  if (maxX < 0) return canvas;
  const pad = 2;
  minX = Math.max(0, minX - pad); minY = Math.max(0, minY - pad);
  maxX = Math.min(width - 1, maxX + pad); maxY = Math.min(height - 1, maxY + pad);
  const w = maxX - minX + 1, h = maxY - minY + 1;
  const out = document.createElement("canvas");
  out.width = w; out.height = h;
  out.getContext("2d").drawImage(canvas, minX, minY, w, h, 0, 0, w, h);
  return out;
}

// Same LEGO part rendered on different pages can land 1-2px apart within its cell
// (box layout shifts slightly depending on how many sibling items share it), so plain
// pixel/gradient hashing sees "different" parts. Comparing small color grids across a
// handful of shift offsets and keeping the best alignment makes matching shift-tolerant.
function computeSignature(canvas) {
  const cw = canvas.width, ch = canvas.height;
  const octx = canvas.getContext("2d");
  const odata = octx.getImageData(0, 0, cw, ch).data;
  let rSum = 0, gSum = 0, bSum = 0, cnt = 0;
  for (let i = 0; i < odata.length; i += 4) {
    const dr = Math.abs(odata[i] - BOX_BG[0]), dg = Math.abs(odata[i + 1] - BOX_BG[1]), db = Math.abs(odata[i + 2] - BOX_BG[2]);
    if (Math.max(dr, dg, db) > FG_DIFF_THRESHOLD) { rSum += odata[i]; gSum += odata[i + 1]; bSum += odata[i + 2]; cnt++; }
  }
  const avgColor = cnt > 0 ? [rSum / cnt, gSum / cnt, bSum / cnt] : [BOX_BG[0], BOX_BG[1], BOX_BG[2]];

  const scale = Math.min((SIG_SIZE - 2 * SIG_MARGIN) / cw, (SIG_SIZE - 2 * SIG_MARGIN) / ch);
  const nw = Math.max(1, Math.round(cw * scale)), nh = Math.max(1, Math.round(ch * scale));
  const norm = document.createElement("canvas");
  norm.width = SIG_SIZE; norm.height = SIG_SIZE;
  const nctx = norm.getContext("2d");
  nctx.fillStyle = `rgb(${BOX_BG[0]},${BOX_BG[1]},${BOX_BG[2]})`;
  nctx.fillRect(0, 0, SIG_SIZE, SIG_SIZE);
  nctx.imageSmoothingEnabled = true;
  const ox = Math.floor((SIG_SIZE - nw) / 2), oy = Math.floor((SIG_SIZE - nh) / 2);
  nctx.drawImage(canvas, 0, 0, cw, ch, ox, oy, nw, nh);

  const { data } = nctx.getImageData(0, 0, SIG_SIZE, SIG_SIZE);
  const grid = new Uint8ClampedArray(SIG_SIZE * SIG_SIZE * 3);
  const fgGrid = new Uint8Array(SIG_SIZE * SIG_SIZE);
  for (let p = 0, i = 0; p < SIG_SIZE * SIG_SIZE; p++, i += 4) {
    grid[p * 3] = data[i]; grid[p * 3 + 1] = data[i + 1]; grid[p * 3 + 2] = data[i + 2];
    const dr = Math.abs(data[i] - BOX_BG[0]), dg = Math.abs(data[i + 1] - BOX_BG[1]), db = Math.abs(data[i + 2] - BOX_BG[2]);
    fgGrid[p] = Math.max(dr, dg, db) > FG_DIFF_THRESHOLD ? 1 : 0;
  }
  return { grid, fgGrid, avgColor };
}

// Mean absolute color difference between two signature grids, minimized over small
// (dx, dy) offsets so a 1-2px rendering shift doesn't register as a different part.
// Only pixels that are part of the actual icon (in either grid) count - background-vs-
// background agreement is free and must not dilute genuine content differences.
function gridDist(a, b) {
  let best = Infinity;
  for (let dy = -SIG_MAX_SHIFT; dy <= SIG_MAX_SHIFT; dy++) {
    for (let dx = -SIG_MAX_SHIFT; dx <= SIG_MAX_SHIFT; dx++) {
      let sum = 0, n = 0, uncovered = 0;
      for (let y = 0; y < SIG_SIZE; y++) {
        const sy = y + dy;
        for (let x = 0; x < SIG_SIZE; x++) {
          const sx = x + dx;
          const aFg = a.fgGrid[y * SIG_SIZE + x];
          const outOfBounds = sy < 0 || sy >= SIG_SIZE || sx < 0 || sx >= SIG_SIZE;
          const bFg = outOfBounds ? 0 : b.fgGrid[sy * SIG_SIZE + sx];
          if (!aFg && !bFg) continue;
          if (aFg && (outOfBounds || !bFg)) { uncovered++; n++; continue; }
          if (!aFg && bFg) { uncovered++; n++; continue; }
          const ia = (y * SIG_SIZE + x) * 3, ib = (sy * SIG_SIZE + sx) * 3;
          sum += Math.abs(a.grid[ia] - b.grid[ib]) + Math.abs(a.grid[ia + 1] - b.grid[ib + 1]) + Math.abs(a.grid[ia + 2] - b.grid[ib + 2]);
          n++;
        }
      }
      if (n === 0) continue;
      // treat "content on one side, background on the other" as a large mismatch (255)
      const avg = (sum + uncovered * 255 * 3) / (n * 3);
      if (avg < best) best = avg;
    }
  }
  return best;
}

function colorDist(a, b) {
  return Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]), Math.abs(a[2] - b[2]));
}

function findBucket(buckets, sig) {
  return buckets.find(
    (b) => colorDist(b.avgColor, sig.avgColor) <= COLOR_TOL && gridDist(b, sig) <= SIG_DIST_TOL
  );
}

function addToBuckets(buckets, item, pageNum) {
  const cropped = autocropCanvas(item.imgCanvas);
  const sig = computeSignature(cropped);

  let bucket = findBucket(buckets, sig);
  if (!bucket) {
    bucket = {
      grid: sig.grid,
      fgGrid: sig.fgGrid,
      avgColor: sig.avgColor,
      count: 0,
      unsure: false,
      pages: new Set(),
      thumbUrl: cropped.toDataURL("image/png"),
    };
    buckets.push(bucket);
  }
  if (item.qty === null) {
    bucket.unsure = true;
    bucket.count += 1; // best-effort fallback so totals aren't silently short
  } else {
    if (item.unsure) bucket.unsure = true;
    bucket.count += item.qty;
  }
  bucket.pages.add(pageNum);
  return buckets.indexOf(bucket);
}

// ---------- sorting ----------

function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  const d = max - min;
  if (d !== 0) {
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      default: h = (r - g) / d + 4;
    }
    h *= 60;
  }
  return [h, s, l * 100];
}

// grayscale/near-neutral colors have no meaningful hue, so group them by
// lightness after every hue bucket instead of scattering them at hue 0 (red)
function colorSortKey(avgColor) {
  const [h, s, l] = rgbToHsl(avgColor);
  return s < 0.15 ? 400 + l : h;
}

function sortEntries(entries, mode, getBucket, getCount, getFirstPage) {
  const arr = entries.slice();
  switch (mode) {
    case "count-asc":
      arr.sort((a, b) => getCount(a) - getCount(b));
      break;
    case "color":
      arr.sort((a, b) => colorSortKey(getBucket(a).avgColor) - colorSortKey(getBucket(b).avgColor));
      break;
    case "page":
      arr.sort((a, b) => getFirstPage(a) - getFirstPage(b));
      break;
    case "count-desc":
    default:
      arr.sort((a, b) => getCount(b) - getCount(a));
  }
  return arr;
}

function sortBuckets(buckets, mode) {
  return sortEntries(
    buckets, mode,
    (b) => b,
    (b) => b.count,
    (b) => Math.min(...b.pages)
  );
}

// ---------- rendering ----------

function render() {
  if (state.mode === "step") renderStepMode();
  else renderListMode();
}

function setMode(mode) {
  state.mode = mode;
  modeListBtn.classList.toggle("active", mode === "list");
  modeStepBtn.classList.toggle("active", mode === "step");
  resultsEl.hidden = mode !== "list";
  stepModeEl.hidden = mode !== "step";
  render();
}

function goToStep(idx) {
  state.stepIndex = clamp(idx, 0, state.pageRecords.length - 1);
  renderStepMode();
}

function makePartCard(bucket, qty, unsure, pages) {
  const card = document.createElement("div");
  card.className = "part-card";
  const pagesArr = pages.slice().sort((x, y) => x - y);
  card.innerHTML = `
    <img src="${bucket.thumbUrl}" alt="деталь" loading="lazy" />
    <div class="part-qty ${unsure ? "unsure" : ""}">×${qty}${unsure ? " ?" : ""}</div>
    <div class="part-pages">стр. ${summarizePages(pagesArr)}</div>
  `;
  return card;
}

function summarizePages(pages) {
  if (pages.length <= 6) return pages.join(", ");
  return `${pages[0]}…${pages[pages.length - 1]} (${pages.length} стр.)`;
}

function renderListMode() {
  const { buckets, from, to, pagesWithParts, pageRecords } = state;
  const totalUnique = buckets.length;
  const totalBricks = buckets.reduce((s, b) => s + b.count, 0);
  summaryEl.hidden = false;
  summaryEl.innerHTML = `
    <div>Страницы: <b>${from}–${to}</b></div>
    <div>Страниц с новыми деталями: <b>${pagesWithParts}</b> из ${pageRecords.length}</div>
    <div>Уникальных деталей: <b>${totalUnique}</b></div>
    <div>Всего деталей: <b>${totalBricks}</b></div>
  `;

  const sorted = sortBuckets(buckets, state.sortMode);
  resultsEl.innerHTML = "";
  for (const b of sorted) {
    resultsEl.appendChild(makePartCard(b, b.count, b.unsure, Array.from(b.pages)));
  }
}

function renderStepMode() {
  const { buckets, pageRecords, stepIndex } = state;
  if (!pageRecords.length) return;
  const rec = pageRecords[stepIndex];

  stepSlider.max = String(pageRecords.length - 1);
  stepSlider.value = String(stepIndex);
  stepLabel.textContent = `Страница ${rec.pageNum} (шаг ${stepIndex + 1} из ${pageRecords.length})`;
  stepPageImg.src = rec.thumbDataUrl;
  stepPrevBtn.disabled = stepIndex === 0;
  stepNextBtn.disabled = stepIndex === pageRecords.length - 1;

  const currentEntries = sortEntries(
    rec.items, state.sortMode,
    (it) => buckets[it.bucketIdx],
    (it) => it.qty,
    () => rec.pageNum
  );
  stepCurrentItems.innerHTML = "";
  for (const it of currentEntries) {
    stepCurrentItems.appendChild(makePartCard(buckets[it.bucketIdx], it.qty, it.unsure, [rec.pageNum]));
  }

  // Starts at the *next* page on purpose: this page's own needs are already
  // shown above, so "remaining" means "still needed after this step" and
  // correctly empties out once you're on the last page of the range.
  const remaining = new Map(); // bucketIdx -> { qty, unsure, pages: Set }
  for (let i = stepIndex + 1; i < pageRecords.length; i++) {
    for (const it of pageRecords[i].items) {
      const cur = remaining.get(it.bucketIdx) || { qty: 0, unsure: false, pages: new Set() };
      cur.qty += it.qty;
      if (it.unsure) cur.unsure = true;
      cur.pages.add(pageRecords[i].pageNum);
      remaining.set(it.bucketIdx, cur);
    }
  }
  const remainingEntries = sortEntries(
    Array.from(remaining.entries()), state.sortMode,
    ([idx]) => buckets[idx],
    ([, v]) => v.qty,
    ([, v]) => Math.min(...v.pages)
  );
  stepRemainingItems.innerHTML = "";
  for (const [idx, v] of remainingEntries) {
    stepRemainingItems.appendChild(makePartCard(buckets[idx], v.qty, v.unsure, Array.from(v.pages)));
  }
}

// ---------- LAN sharing (open on phone over Wi-Fi) ----------

let qrLibPromise = null;
function loadQrLib() {
  if (window.qrcode) return Promise.resolve();
  if (!qrLibPromise) {
    qrLibPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "vendor/qrcode.js";
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  return qrLibPromise;
}

function isLanAddress() {
  const h = location.hostname;
  return location.protocol.startsWith("http") && h !== "" && h !== "localhost" && h !== "127.0.0.1";
}

function initLanBanner() {
  if (!isLanAddress()) return;
  lanBanner.hidden = false;
}

async function showQr() {
  await loadQrLib();
  const url = location.href;
  const qr = window.qrcode(0, "M");
  qr.addData(url);
  qr.make();
  qrCanvasHolder.innerHTML = qr.createSvgTag(6, 8);
  qrUrl.textContent = url;
  qrOverlay.hidden = false;
}

lanQrBtn.addEventListener("click", showQr);
qrClose.addEventListener("click", () => { qrOverlay.hidden = true; });
qrOverlay.addEventListener("click", (e) => { if (e.target === qrOverlay) qrOverlay.hidden = true; });

initLanBanner();
