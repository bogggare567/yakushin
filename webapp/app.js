/* global pdfjsLib, GLYPH_TEMPLATES, GLYPH_W, GLYPH_H */
pdfjsLib.GlobalWorkerOptions.workerSrc = "https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js";

const APP_VERSION = "1.4.0";
const VERSION_CHECK_URL = "https://raw.githubusercontent.com/bogggare567/yakushin/main/webapp/version.json";

const RENDER_SCALE = 3.0; // px per pdf point - higher = crisper thumbnails, slower processing
const BOX_BG = [215, 238, 254]; // the light-blue "new parts" callout background color
const BOX_COLOR_TOL = 14; // tolerance for matching the box background color
const FG_DIFF_THRESHOLD = 35; // per-pixel max-channel diff to count as foreground (icon/text) inside a box
const SCALE_REF = 2.0; // the render scale the px-based constants below were tuned at
const SIZE_K = RENDER_SCALE / SCALE_REF;
const MIN_BOX_W = 40 * SIZE_K, MIN_BOX_H = 40 * SIZE_K, MIN_BOX_AREA = 400 * SIZE_K * SIZE_K;
const MIN_COL_GAP = 6 * SIZE_K; // px of background between two item slots
const MIN_ROW_GAP = 2 * SIZE_K; // px of background rows between icon and qty text
const MIN_GLYPH_W = 5 * SIZE_K, MIN_GLYPH_H = 8 * SIZE_K; // below this a "glyph" is noise, not a digit
const SIG_SIZE = 14; // color-grid signature size (px) used to identify/dedup a part's icon
const SIG_MARGIN = 2; // border reserved inside SIG_SIZE so small shifts stay in-bounds
const SIG_MAX_SHIFT = 2; // px of shift tried in each direction when comparing two signatures
const SIG_DIST_TOL = 40; // max mean color difference (0-255 scale) to call two icons the same part
const COLOR_TOL = 24;
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
const lanBannerSubtitle = document.getElementById("lan-banner-subtitle");
const lanQrBtn = document.getElementById("lan-qr-btn");
const qrOverlay = document.getElementById("qr-overlay");
const qrCanvasHolder = document.getElementById("qr-canvas-holder");
const qrUrl = document.getElementById("qr-url");
const qrClose = document.getElementById("qr-close");
const updateBanner = document.getElementById("update-banner");
const updateText = document.getElementById("update-text");
const updateLink = document.getElementById("update-link");
const setupPanelEl = document.getElementById("setup-panel");
const sidebarNewBtn = document.getElementById("sidebar-new-btn");
const sidebarSessionsEl = document.getElementById("sidebar-sessions");

let pdfDoc = null;

// Session library (IndexedDB): remembers analyzed PDFs locally so you don't
// have to re-pick the same file and range every time - resuming restores
// the page position, sort, and which parts you've already tapped as found.
let currentSessionId = null;
let currentPdfName = null;
let currentFileKey = null; // fingerprint (name+size) the PDF blob is stored under - shared across sessions of the same file
let currentPdfBytesForSession = null;
let currentPdfFilePersisted = false; // whether currentFileKey's PDF blob is already saved in IndexedDB
let sessionCreatedAt = null;
let sessionNameOverride = null;
let pendingResumeCollected = null;
let pendingResumeState = null; // {sortMode, mode, stepIndex}
let resumeAfterReselect = false; // true while waiting for the user to manually re-pick a session's PDF (cache miss)

// LAN sync (see tools/lan_server.py): lets a second device on the same
// Wi-Fi act as a remote control (step navigation, sort, mode) and/or as the
// source (hand over the PDF + page range). Plain static hosting (GitHub
// Pages, file://, vanilla `python -m http.server`) has no such API, so this
// stays fully inert there - detectSync() below just fails quietly.
let syncAvailable = false;
let suppressSyncPush = false;
let lastSyncedStateVersion = -1;
let lastLoadedPdfVersion = -1;
let lastAnalyzedKey = "";

const state = {
  buckets: [],
  pageRecords: [],
  from: 1,
  to: 1,
  pagesWithParts: 0,
  mode: "list",
  sortMode: "color-groups",
  stepIndex: 0,
  collected: new Set(), // bucket indices the user has tapped as "already found"
};

pdfInput.addEventListener("change", onPdfSelected);
analyzeBtn.addEventListener("click", runAnalysis);
modeListBtn.addEventListener("click", () => setMode("list"));
modeStepBtn.addEventListener("click", () => setMode("step"));
sortSelect.addEventListener("change", () => {
  state.sortMode = sortSelect.value;
  render();
  pushSyncState();
  saveSessionMeta();
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

  // picking a file fresh always starts a brand new session, never continues one -
  // unless we're waiting for a manual re-pick to resume a session whose cached
  // PDF blob got evicted (resumeSession() sets resumeAfterReselect for that case)
  if (resumeAfterReselect) {
    resumeAfterReselect = false;
  } else {
    currentSessionId = null;
    sessionCreatedAt = null;
    sessionNameOverride = null;
    pendingResumeCollected = null;
    pendingResumeState = null;
  }
  currentPdfFilePersisted = false;
  currentPdfName = file.name;
  currentFileKey = fileKeyFor(file.name, file.size);

  const buf = await file.arrayBuffer();
  if (syncAvailable) pushSyncedPdf(file, buf.slice(0)); // fire-and-forget; pdfjs may transfer buf below
  currentPdfBytesForSession = buf.slice(0); // kept until first analysis, then persisted
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
  progressFill.classList.add("is-active");
  resultsEl.innerHTML = "";
  summaryEl.hidden = true;
  viewControls.hidden = true;
  stepModeEl.hidden = true;
  setProgress(0, "Подготовка…");
  state.collected.clear();
  if (pendingResumeCollected) {
    for (const idx of pendingResumeCollected) state.collected.add(idx);
  }

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
  progressFill.classList.remove("is-active");
  state.buckets = buckets;
  state.pageRecords = pageRecords;
  state.from = from;
  state.to = to;
  state.pagesWithParts = pagesWithParts;
  state.stepIndex = 0;
  viewControls.hidden = false;
  setupPanelEl.hidden = true;

  if (!currentSessionId) {
    currentSessionId = crypto.randomUUID();
    sessionCreatedAt = Date.now();
  }
  if (!currentPdfFilePersisted && currentPdfBytesForSession && currentFileKey) {
    // Several sessions can point at the same physical file (same name+size,
    // e.g. re-analyzing different page ranges of one big instruction PDF) -
    // storing it under a content fingerprint instead of the session id means
    // only one copy of a 100+MB file ever sits in IndexedDB, however many
    // sessions use it. Without this, every fresh analysis wrote a full new
    // copy and storage (and each write) ballooned within a few tries.
    //
    // Not awaited on purpose: writing a 100+MB blob to IndexedDB can take a
    // real amount of time, and blocking here made the UI look hung right as
    // results were ready to show. It runs in the background instead; if the
    // tab closes before it finishes, only local caching is lost, not the
    // just-computed results.
    const bytesToSave = currentPdfBytesForSession, keyToSave = currentFileKey;
    hasSessionFile(keyToSave)
      .then((exists) => (exists ? null : putSessionFile(keyToSave, bytesToSave)))
      .catch((err) => console.error("Не удалось сохранить PDF сессии локально (возможно, не хватило места)", err));
    currentPdfFilePersisted = true;
  }

  if (pendingResumeState) {
    if (pendingResumeState.sortMode) { state.sortMode = pendingResumeState.sortMode; sortSelect.value = pendingResumeState.sortMode; }
    if (typeof pendingResumeState.stepIndex === "number") state.stepIndex = clamp(pendingResumeState.stepIndex, 0, pageRecords.length - 1);
    setMode(pendingResumeState.mode || "list");
    pendingResumeState = null;
  } else {
    setMode("list"); // also broadcasts the fresh range/mode to any synced devices
  }
  pendingResumeCollected = null;

  await saveSessionMeta();
  renderLibrary();
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

  // Segment by actual connected components, not column projection: a stray
  // speck (JPEG noise, or a sliver of the icon bleeding into a fallback-
  // placed text crop) can sit in the same column range as a real glyph
  // without touching it. Column projection would fuse it into that glyph's
  // bounding box and distort the shape; components keep it separate so the
  // size filter below can drop it cleanly.
  const components = findGlyphComponents(fg, w, h)
    .filter((c) => (c.maxX - c.minX + 1) >= MIN_GLYPH_W && (c.maxY - c.minY + 1) >= MIN_GLYPH_H)
    .sort((a, b) => a.minX - b.minX);
  if (!components.length) return { qty: null, unsure: true };

  let label = "";
  let anyUnsure = false;
  for (const comp of components) {
    const { mask, cw, ch } = componentLocalMask(comp, w);
    const normalized = resizeGlyphMask(mask, cw, ch);
    const { bestLabel, bestDist } = classifyGlyph(normalized);
    if (bestDist > GLYPH_MAX_DIST) { anyUnsure = true; continue; }
    label += bestLabel;
  }

  // drop trailing "x" marker(s); keep only leading digits
  const digits = label.replace(/x+$/i, "");
  if (!/^\d+$/.test(digits)) return { qty: null, unsure: true };
  return { qty: parseInt(digits, 10), unsure: anyUnsure };
}

// 8-connected flood fill so a diagonally-touching antialiased stroke still
// counts as one component; each result carries its own tight bbox + pixels.
function findGlyphComponents(fg, w, h) {
  const visited = new Uint8Array(w * h);
  const components = [];
  const stack = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const start = y * w + x;
      if (!fg[start] || visited[start]) continue;
      let minX = x, maxX = x, minY = y, maxY = y;
      const pixels = [];
      stack.length = 0; stack.push(start); visited[start] = 1;
      while (stack.length) {
        const cur = stack.pop();
        const cx = cur % w, cy = (cur / w) | 0;
        pixels.push(cur);
        if (cx < minX) minX = cx; if (cx > maxX) maxX = cx;
        if (cy < minY) minY = cy; if (cy > maxY) maxY = cy;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (!dx && !dy) continue;
            const nx = cx + dx, ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
            const n = ny * w + nx;
            if (fg[n] && !visited[n]) { visited[n] = 1; stack.push(n); }
          }
        }
      }
      components.push({ minX, maxX, minY, maxY, pixels });
    }
  }
  return components;
}

// Builds a dense mask containing only this component's own pixels, sized to
// its tight bbox - so a nearby unrelated blob can never leak into its shape.
function componentLocalMask(comp, fgW) {
  const cw = comp.maxX - comp.minX + 1, ch = comp.maxY - comp.minY + 1;
  const mask = new Uint8Array(cw * ch);
  for (const idx of comp.pixels) {
    const x = idx % fgW, y = (idx / fgW) | 0;
    mask[(y - comp.minY) * cw + (x - comp.minX)] = 1;
  }
  return { mask, cw, ch };
}

function resizeGlyphMask(mask, srcW, srcH) {
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
      out[(oy + y) * GLYPH_W + (ox + x)] = mask[sy * srcW + sx];
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
const COLOR_MODE_BIN = 32; // quantization step for finding the icon's dominant color
const COLOR_MODE_AMBIGUOUS_SHARE = 0.10; // below this, no single bin is trustworthy on its own
const COLOR_MODE_MERGE_RADIUS = 45; // chebyshev color-distance (0-255) used by the mode-seek fallback

function computeSignature(canvas) {
  const cw = canvas.width, ch = canvas.height;
  const octx = canvas.getContext("2d");
  const odata = octx.getImageData(0, 0, cw, ch).data;

  // The part's true base color is found as the *dominant* (most common,
  // coarsely-quantized) color among the icon's foreground pixels - not a
  // fixed region. Two simpler ideas were tried and rejected on real data:
  // a center-weighted sample can land squarely on a technic connector's
  // dark axle-hole marking (samples the wrong thing entirely); averaging
  // every foreground pixel (even after eroding away the outline) can get
  // diluted by ring/groove shading details scattered across the whole
  // surface. Dominant-color-by-quantization is robust to both because
  // minority detail pixels - wherever they sit - just don't outnumber the
  // part's own face. Verified against ~800 real icons across 300 pages:
  // median winning bin covers 38% of the icon, only ~2% of icons are
  // ambiguous (<10%), and it fixed concrete cases the other two got wrong.
  const bins = new Map(); // quantized key -> {n, rSum, gSum, bSum}
  const fgPixels = []; // flat [r,g,b, r,g,b, ...] - only walked again for the rare ambiguous fallback below
  let fgCount = 0;
  for (let i = 0; i < odata.length; i += 4) {
    const r = odata[i], g = odata[i + 1], b = odata[i + 2];
    const dr = Math.abs(r - BOX_BG[0]), dg = Math.abs(g - BOX_BG[1]), db = Math.abs(b - BOX_BG[2]);
    if (Math.max(dr, dg, db) <= FG_DIFF_THRESHOLD) continue;
    fgCount++;
    fgPixels.push(r, g, b);
    const key = ((r / COLOR_MODE_BIN) | 0) * 10000 + ((g / COLOR_MODE_BIN) | 0) * 100 + ((b / COLOR_MODE_BIN) | 0);
    let entry = bins.get(key);
    if (!entry) { entry = { n: 0, rSum: 0, gSum: 0, bSum: 0 }; bins.set(key, entry); }
    entry.n++; entry.rSum += r; entry.gSum += g; entry.bSum += b;
  }
  let avgColor;
  if (fgCount === 0) {
    avgColor = [BOX_BG[0], BOX_BG[1], BOX_BG[2]];
  } else {
    let best = null;
    for (const entry of bins.values()) if (!best || entry.n > best.n) best = entry;
    if (best.n / fgCount >= COLOR_MODE_AMBIGUOUS_SHARE) {
      avgColor = [best.rSum / best.n, best.gSum / best.n, best.bSum / best.n];
    } else {
      // No bin dominates: a curved or translucent part (a round dome, say)
      // shades continuously, splitting its true surface color across many
      // adjacent small bins, while a single dark groove/shadow bin can still
      // "win" outright - real case: a lime-green translucent dome averaged
      // out to near-black RGB(6,10,8) this way. Mode-seek instead: score
      // each bin's neighborhood by how many foreground pixels sit within
      // COLOR_MODE_MERGE_RADIUS of it, and average that whole neighborhood
      // around the highest-scoring center. Distance is always measured from
      // one fixed center (never chained bin-to-bin), so it can't drift all
      // the way from a bright face to an unrelated dark shadow.
      avgColor = modeSeekColor(bins, fgPixels);
    }
  }

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

function modeSeekColor(bins, fgPixels) {
  let bestScore = -1, bestCenter = null;
  for (const entry of bins.values()) {
    const cr = entry.rSum / entry.n, cg = entry.gSum / entry.n, cb = entry.bSum / entry.n;
    let score = 0;
    for (let i = 0; i < fgPixels.length; i += 3) {
      const dr = Math.abs(fgPixels[i] - cr), dg = Math.abs(fgPixels[i + 1] - cg), db = Math.abs(fgPixels[i + 2] - cb);
      if (Math.max(dr, dg, db) <= COLOR_MODE_MERGE_RADIUS) score++;
    }
    if (score > bestScore) { bestScore = score; bestCenter = [cr, cg, cb]; }
  }
  let rSum = 0, gSum = 0, bSum = 0, n = 0;
  for (let i = 0; i < fgPixels.length; i += 3) {
    const dr = Math.abs(fgPixels[i] - bestCenter[0]), dg = Math.abs(fgPixels[i + 1] - bestCenter[1]), db = Math.abs(fgPixels[i + 2] - bestCenter[2]);
    if (Math.max(dr, dg, db) <= COLOR_MODE_MERGE_RADIUS) { rSum += fgPixels[i]; gSum += fgPixels[i + 1]; bSum += fgPixels[i + 2]; n++; }
  }
  return n > 0 ? [rSum / n, gSum / n, bSum / n] : bestCenter;
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

// Named color families for the grouped view - distinguishes e.g. red from
// magenta/purple instead of just placing them at nearby points on one
// continuous hue line (the client's own request after trying the plain
// "по цвету" sort). Brown/tan gets its own bucket since it's really just a
// low-saturation, low/mid-lightness orange and would otherwise land next to
// bright oranges despite reading as a completely different color.

// Classifies only the colors where a *fixed* rule genuinely makes sense -
// black/white/gray/brown are about lightness and saturation, not hue
// position, so there's no reason to cluster them dynamically. Everything
// else (real hue-bearing color) returns null and is left to clusterByHue()
// below, which groups whatever hues are actually present in this analysis
// instead of forcing them into fixed red/orange/yellow/... windows - the
// client's own request after "по цвету" grouping still lumped e.g. lime
// green in with either yellow or green depending on which side of a fixed
// boundary it happened to fall on.
function fixedColorCategory(avgColor) {
  const [h, s, l] = rgbToHsl(avgColor);
  // Below ~15% (or above ~90%) lightness, hue/saturation are numerically
  // unstable - a few units of RGB noise swings "saturation" wildly even
  // though the color reads as unambiguous black/white to the eye (verified:
  // real near-black parts measuring RGB like [10,15,27] compute a
  // deceptive s=0.46 from pure noise). Lightness overrides in that range -
  // *unless* the channel spread is too big to be noise: a genuine dark
  // reddish-brown pin measured RGB(54,26,12) (spread 42) and was wrongly
  // forced to black, while real near-black noise on this file topped out
  // at a spread of ~22 (and consistently skews blue, not warm/brown) - 30
  // sits with margin on both sides of that real-data gap.
  if (l < 15) {
    const spread = Math.max(...avgColor) - Math.min(...avgColor);
    if (spread < 30) return "Чёрный";
  }
  if (l > 90) return "Белый";
  // LEGO's signature "(dark) bluish gray" carries noticeably more saturation
  // than a neutral gray (verified on real data: s up to ~0.2, hue ~205-225)
  // but reads as gray to every LEGO builder, not blue - widen the gray net
  // specifically in that hue band rather than globally.
  const grayThreshold = h >= 195 && h <= 235 ? 0.22 : 0.13;
  if (s < grayThreshold) {
    if (l > 82) return "Белый";
    if (l < 25) return "Чёрный";
    return "Серый";
  }
  // Lower bound extended down from 18 to 10 to catch the dark-reddish-brown
  // case above once it escapes the black override (real example: l=12.8).
  if (h >= 18 && h < 50 && l >= 10 && l <= 62 && s < 0.65) return "Коричневый / тан";
  // Plain LEGO "Tan" is a much lighter, brighter beige than the dark/medium
  // brown above (verified on real parts: RGB ~236,212,167 -> h=39.5deg,
  // s=0.6-0.7, l=79%) - well past the l<=62 cutoff, so it fell through to
  // Orange/Yellow instead (~22% of a real-file sample landed here wrong).
  // True vivid orange at this hue sits at l~63-64% with s>0.8, so gating on
  // l>68 keeps it out while still catching the light-tan cluster up to white.
  if (h >= 30 && h < 46 && l > 68 && l <= 88) return "Коричневый / тан";
  return null; // chromatic - let clusterByHue() decide where it lands
}

// Reference points used only to *name* a hue cluster after the fact (and to
// order clusters left-to-right red->...->magenta) - not fixed boundaries.
const HUE_ANCHORS = [
  { hue: 0, name: "Красный", prefix: "красно" },
  { hue: 25, name: "Оранжевый", prefix: "оранжево" },
  { hue: 55, name: "Жёлтый", prefix: "жёлто" },
  { hue: 130, name: "Зелёный", prefix: "зелено" },
  { hue: 190, name: "Голубой", prefix: "голубо" },
  { hue: 220, name: "Синий", prefix: "сине" },
  { hue: 275, name: "Фиолетовый", prefix: "фиолетово" },
  { hue: 320, name: "Пурпурный / розовый", prefix: "пурпурно" },
];

function hueDist(a, b) {
  const d = Math.abs(a - b) % 360;
  return Math.min(d, 360 - d);
}

// Names a cluster by its centroid hue: close enough to one named anchor ->
// use that name outright; sitting clearly between two -> a compound name
// ("Жёлто-зелёный" etc.), which is how a person would actually describe a
// lime-green part anyway.
function nameForHue(h) {
  const withDist = HUE_ANCHORS.map((a) => ({ ...a, d: hueDist(a.hue, h) })).sort((a, b) => a.d - b.d);
  const nearest = withDist[0], second = withDist[1];
  if (nearest.d <= 18) return nearest.name;
  let [lo, hi] = [nearest, second].sort((a, b) => a.hue - b.hue);
  if (lo.name === "Красный" && hi.name === "Пурпурный / розовый") { [lo, hi] = [hi, lo]; }
  return `${lo.prefix[0].toUpperCase()}${lo.prefix.slice(1)}-${hi.name.toLowerCase()}`;
}

const MIN_HUE_GAP = 22; // degrees of empty hue-space that triggers a cluster split
const MIN_CLUSTER_SIZE = 2; // distinct parts below this get folded into their nearest neighbor

// Groups chromatic items { hue, weight } by where the hues actually cluster
// in *this* analysis, rather than fixed windows. Returns [[name, items[], centroidHue], ...].
function clusterByHue(items) {
  if (!items.length) return [];
  const sorted = items.slice().sort((a, b) => a.hue - b.hue);
  const n = sorted.length;

  // Cut the hue circle at its single largest empty stretch so a run of reds
  // spanning the 350deg-10deg seam doesn't get spuriously split in two.
  let cutIdx = 0, maxGap = -1;
  for (let i = 0; i < n; i++) {
    const cur = sorted[i].hue;
    const next = sorted[(i + 1) % n].hue;
    const gap = i === n - 1 ? 360 - cur + next : next - cur;
    if (gap > maxGap) { maxGap = gap; cutIdx = (i + 1) % n; }
  }
  const linear = sorted.slice(cutIdx).concat(sorted.slice(0, cutIdx));
  let prevHue = null, offset = 0;
  const unrolled = linear.map((it) => {
    let uh = it.hue + offset;
    if (prevHue !== null && uh < prevHue) { offset += 360; uh += 360; }
    prevHue = uh;
    return { ...it, uh };
  });

  const clusters = [[unrolled[0]]];
  for (let i = 1; i < unrolled.length; i++) {
    if (unrolled[i].uh - unrolled[i - 1].uh >= MIN_HUE_GAP) clusters.push([]);
    clusters[clusters.length - 1].push(unrolled[i]);
  }

  const centroidOf = (c) => {
    const totalWeight = c.reduce((s, it) => s + it.weight, 0);
    return (((c.reduce((s, it) => s + it.uh * it.weight, 0) / totalWeight) % 360) + 360) % 360;
  };
  let named = clusters.map((c) => ({ items: c, centroid: centroidOf(c), name: nameForHue(centroidOf(c)) }));

  // Fold away small clusters that only exist *between* two named colors -
  // that's the new thing dynamic clustering enables (a lime-green splinter
  // between yellow and green), so it's the only kind worth a minimum size
  // before it earns a heading. A cluster that lands close to an established
  // color (Red, Blue, ...) keeps its heading however few items it has -
  // same as the old fixed categories always did.
  for (let i = named.length - 1; i >= 0 && named.length > 1; i--) {
    if (!named[i].name.includes("-") || named[i].items.length >= MIN_CLUSTER_SIZE) continue;
    const distPrev = i > 0 ? named[i].items[0].uh - named[i - 1].items[named[i - 1].items.length - 1].uh : Infinity;
    const distNext = i < named.length - 1 ? named[i + 1].items[0].uh - named[i].items[named[i].items.length - 1].uh : Infinity;
    const target = distPrev <= distNext ? i - 1 : i + 1;
    const merged = named[target].items.concat(named[i].items).sort((a, b) => a.uh - b.uh);
    named[target] = { items: merged, centroid: centroidOf(merged), name: nameForHue(centroidOf(merged)) };
    named.splice(i, 1);
  }

  return named.map((g) => [g.name, g.items, g.centroid]);
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

const ACHROMATIC_ORDER = ["Чёрный", "Серый", "Белый", "Коричневый / тан"];

// Groups entries into color families: black/white/gray/brown use the fixed
// lightness-based rule (display order fixed too), everything else clusters
// dynamically by whatever hues are actually present in this analysis, sorted
// red->...->magenta by centroid. Returns [[name, entries[]], ...].
function groupByColor(entries, getBucket, getCount) {
  const fixedGroups = new Map();
  const chromatic = [];
  for (const e of entries) {
    const avgColor = getBucket(e).avgColor;
    const fixed = fixedColorCategory(avgColor);
    if (fixed) {
      if (!fixedGroups.has(fixed)) fixedGroups.set(fixed, []);
      fixedGroups.get(fixed).push(e);
    } else {
      const [h] = rgbToHsl(avgColor);
      chromatic.push({ e, hue: h, weight: getCount(e) });
    }
  }

  const ordered = [];
  for (const cat of ACHROMATIC_ORDER) {
    if (fixedGroups.has(cat)) ordered.push([cat, fixedGroups.get(cat)]);
  }

  const clusters = clusterByHue(chromatic).sort((a, b) => a[2] - b[2]);
  const byName = new Map(); // merge same-named clusters, in the rare case two land on one name
  for (const [name, items] of clusters) {
    if (!byName.has(name)) byName.set(name, []);
    byName.get(name).push(...items.map((it) => it.e));
  }
  for (const [name, arr] of byName) ordered.push([name, arr]);

  for (const [, arr] of ordered) arr.sort((a, b) => getCount(b) - getCount(a));
  return ordered;
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
  pushSyncState();
  saveSessionMeta();
}

function goToStep(idx) {
  state.stepIndex = clamp(idx, 0, state.pageRecords.length - 1);
  renderStepMode();
  pushSyncState();
  saveSessionMeta();
}

function makePartCard(bucket, qty, unsure, pages, bucketIdx) {
  const card = document.createElement("div");
  card.className = "part-card" + (state.collected.has(bucketIdx) ? " collected" : "");
  const pagesArr = pages.slice().sort((x, y) => x - y);
  card.innerHTML = `
    <img src="${bucket.thumbUrl}" alt="деталь" loading="lazy" />
    <div class="part-qty ${unsure ? "unsure" : ""}">×${qty}${unsure ? " ?" : ""}</div>
    <div class="part-pages">стр. ${summarizePages(pagesArr)}</div>
  `;
  // Click to mark a part as already collected while building - purely a
  // visual crossed-out/dimmed toggle so you can tell at a glance what's
  // still left to find in the pile. Saved into the session, so it survives reopening.
  card.addEventListener("click", () => {
    if (state.collected.has(bucketIdx)) state.collected.delete(bucketIdx);
    else state.collected.add(bucketIdx);
    card.classList.toggle("collected", state.collected.has(bucketIdx));
    saveSessionMeta();
  });
  return card;
}

function summarizePages(pages) {
  if (pages.length <= 6) return pages.join(", ");
  return `${pages[0]}…${pages[pages.length - 1]} (${pages.length} стр.)`;
}

// Shared by the overview list and both step-mode lists: renders either a
// flat sorted grid, or - when sortMode is "color-groups" - a stack of
// named color sections, each its own mini grid sorted by count descending.
function renderPartCards(container, entries, sortMode, accessors) {
  const { getBucket, getCount, getUnsure, getPages, getBucketIdx, getFirstPage } = accessors;
  container.innerHTML = "";
  if (sortMode === "color-groups") {
    container.classList.add("grouped");
    const groups = groupByColor(entries, getBucket, getCount);
    for (const [category, groupEntries] of groups) {
      const heading = document.createElement("h4");
      heading.className = "color-group-heading";
      heading.textContent = `${category} (${groupEntries.length})`;
      container.appendChild(heading);
      const grid = document.createElement("div");
      grid.className = "results";
      for (const e of groupEntries) {
        grid.appendChild(makePartCard(getBucket(e), getCount(e), getUnsure(e), getPages(e), getBucketIdx(e)));
      }
      container.appendChild(grid);
    }
  } else {
    container.classList.remove("grouped");
    const sorted = sortEntries(entries, sortMode, getBucket, getCount, getFirstPage);
    for (const e of sorted) {
      container.appendChild(makePartCard(getBucket(e), getCount(e), getUnsure(e), getPages(e), getBucketIdx(e)));
    }
  }
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

  renderPartCards(resultsEl, buckets, state.sortMode, {
    getBucket: (b) => b,
    getCount: (b) => b.count,
    getUnsure: (b) => b.unsure,
    getPages: (b) => Array.from(b.pages),
    getBucketIdx: (b) => buckets.indexOf(b),
    getFirstPage: (b) => Math.min(...b.pages),
  });
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

  renderPartCards(stepCurrentItems, rec.items, state.sortMode, {
    getBucket: (it) => buckets[it.bucketIdx],
    getCount: (it) => it.qty,
    getUnsure: (it) => it.unsure,
    getPages: () => [rec.pageNum],
    getBucketIdx: (it) => it.bucketIdx,
    getFirstPage: () => rec.pageNum,
  });

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
  renderPartCards(stepRemainingItems, Array.from(remaining.entries()), state.sortMode, {
    getBucket: ([idx]) => buckets[idx],
    getCount: ([, v]) => v.qty,
    getUnsure: ([, v]) => v.unsure,
    getPages: ([, v]) => Array.from(v.pages),
    getBucketIdx: ([idx]) => idx,
    getFirstPage: ([, v]) => Math.min(...v.pages),
  });
}

// ---------- session library (IndexedDB) ----------
// Two object stores: "sessions" holds small metadata (updated on every mode
// switch / step move / sort change / collected-toggle) and "sessionFiles"
// holds the heavy PDF ArrayBuffer separately, written once per file so we
// never rewrite tens of MB just because the user tapped one part card.

const DB_NAME = "lego-parts-finder";
const DB_VERSION = 1;
const STORE_SESSIONS = "sessions";
const STORE_FILES = "sessionFiles";
let dbPromise = null;

function openDB() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_SESSIONS)) db.createObjectStore(STORE_SESSIONS, { keyPath: "id" });
        if (!db.objectStoreNames.contains(STORE_FILES)) db.createObjectStore(STORE_FILES, { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbPromise;
}

function reqToPromise(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function dbStore(name, mode) {
  const db = await openDB();
  return db.transaction(name, mode).objectStore(name);
}

async function getAllSessions() {
  try {
    const store = await dbStore(STORE_SESSIONS, "readonly");
    const all = await reqToPromise(store.getAll());
    return all.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  } catch (err) {
    console.error("Не удалось прочитать список сессий", err);
    return [];
  }
}

async function putSessionMeta(meta) {
  const store = await dbStore(STORE_SESSIONS, "readwrite");
  await reqToPromise(store.put(meta));
}

function fileKeyFor(name, size) {
  return `${name}::${size}`;
}

async function putSessionFile(key, buf) {
  const store = await dbStore(STORE_FILES, "readwrite");
  await reqToPromise(store.put({ id: key, buf }));
}

async function hasSessionFile(key) {
  try {
    const store = await dbStore(STORE_FILES, "readonly");
    const count = await reqToPromise(store.count(key));
    return count > 0;
  } catch (err) {
    return false;
  }
}

async function getSessionFile(key) {
  try {
    const store = await dbStore(STORE_FILES, "readonly");
    const rec = await reqToPromise(store.get(key));
    return rec ? rec.buf : null;
  } catch (err) {
    console.error("Не удалось прочитать сохранённый PDF сессии", err);
    return null;
  }
}

async function deleteSession(id) {
  const sessions = await getAllSessions();
  const target = sessions.find((s) => s.id === id);
  const sessStore = await dbStore(STORE_SESSIONS, "readwrite");
  await reqToPromise(sessStore.delete(id));
  if (target) {
    // legacy sessions (saved before file-dedup) stored their blob under the
    // session id itself, not a fileKey - fileKey ?? id covers both.
    const key = target.fileKey || target.id;
    const stillUsed = sessions.some((s) => s.id !== id && (s.fileKey || s.id) === key);
    if (!stillUsed) {
      const fileStore = await dbStore(STORE_FILES, "readwrite");
      await reqToPromise(fileStore.delete(key));
    }
  }
}

function defaultSessionName() {
  const base = (currentPdfName || "PDF").replace(/\.pdf$/i, "");
  return `${base}, стр. ${state.from}–${state.to}`;
}

async function saveSessionMeta() {
  if (!currentSessionId) return;
  const meta = {
    id: currentSessionId,
    fileKey: currentFileKey,
    name: sessionNameOverride || defaultSessionName(),
    pdfName: currentPdfName,
    createdAt: sessionCreatedAt || Date.now(),
    updatedAt: Date.now(),
    from: state.from,
    to: state.to,
    sortMode: state.sortMode,
    mode: state.mode,
    stepIndex: state.stepIndex,
    totalSteps: state.pageRecords.length,
    totalParts: state.buckets.length,
    collected: Array.from(state.collected),
  };
  try {
    await putSessionMeta(meta);
  } catch (err) {
    console.error("Не удалось сохранить сессию локально", err);
  }
  renderLibrary();
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function timeAgo(ts) {
  if (!ts) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60) return "только что";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} мин назад`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour} ч назад`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 30) return `${diffDay} дн назад`;
  const diffMonth = Math.floor(diffDay / 30);
  if (diffMonth < 12) return `${diffMonth} мес назад`;
  return `${Math.floor(diffMonth / 12)} г назад`;
}

function renderLibrary() {
  getAllSessions().then((sessions) => {
    sidebarSessionsEl.innerHTML = "";
    if (!sessions.length) {
      const empty = document.createElement("div");
      empty.className = "sidebar-empty";
      empty.textContent = "Пока нет сессий — загрузите PDF, чтобы начать.";
      sidebarSessionsEl.appendChild(empty);
      return;
    }
    for (const meta of sessions) sidebarSessionsEl.appendChild(makeSessionRow(meta));
  });
}

function makeSessionRow(meta) {
  const row = document.createElement("div");
  row.className = "session-row" + (meta.id === currentSessionId ? " active" : "");
  row.setAttribute("role", "button");
  row.setAttribute("tabindex", "0");
  row.setAttribute("aria-current", meta.id === currentSessionId ? "true" : "false");

  const totalSteps = meta.totalSteps || 0;
  const pageProgress = totalSteps > 0 ? Math.round(((meta.stepIndex + 1) / totalSteps) * 100) : 0;
  const totalParts = meta.totalParts || 0;
  const collectedCount = (meta.collected || []).length;

  row.innerHTML = `
    <div class="session-row-name" contenteditable="false" spellcheck="false" title="Двойной клик, чтобы переименовать"></div>
    <div class="session-row-meta">
      <div class="session-row-progress-bar"><div class="session-row-progress-fill" style="width:${pageProgress}%"></div></div>
      <span>${collectedCount}/${totalParts}</span>
    </div>
    <button type="button" class="session-row-delete" title="Удалить сессию" aria-label="Удалить сессию">✕</button>
  `;
  row.title = `${meta.pdfName || ""} · стр. ${meta.from}–${meta.to} · ${timeAgo(meta.updatedAt)}`;

  // The name fills most of the row, so a single click on it has to still
  // navigate (like clicking anywhere else on the row) - only a deliberate
  // double-click opens it up for renaming. A plain click-to-edit here made
  // most clicks on a session silently do nothing instead of switching to it.
  const nameEl = row.querySelector(".session-row-name");
  nameEl.textContent = meta.name;
  nameEl.addEventListener("dblclick", (e) => {
    e.stopPropagation();
    nameEl.contentEditable = "true";
    nameEl.focus();
    const range = document.createRange();
    range.selectNodeContents(nameEl);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  });
  nameEl.addEventListener("click", (e) => {
    if (nameEl.contentEditable === "true") e.stopPropagation();
  });
  nameEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); nameEl.blur(); }
    if (e.key === "Escape") { e.preventDefault(); nameEl.textContent = meta.name; nameEl.blur(); }
  });
  nameEl.addEventListener("blur", async () => {
    nameEl.contentEditable = "false";
    const fallback = `${(meta.pdfName || "PDF").replace(/\.pdf$/i, "")}, стр. ${meta.from}–${meta.to}`;
    const newName = nameEl.textContent.trim() || fallback;
    nameEl.textContent = newName;
    if (newName !== meta.name) {
      meta.name = newName;
      meta.updatedAt = Date.now();
      await putSessionMeta(meta);
      if (currentSessionId === meta.id) sessionNameOverride = newName;
    }
  });

  row.querySelector(".session-row-delete").addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm(`Удалить сессию «${meta.name}»?`)) return;
    const wasCurrent = currentSessionId === meta.id;
    await deleteSession(meta.id);
    if (wasCurrent) startNewSession();
    else renderLibrary();
  });

  row.addEventListener("click", () => {
    if (meta.id !== currentSessionId) resumeSession(meta.id);
  });
  row.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && document.activeElement === row) {
      e.preventDefault();
      if (meta.id !== currentSessionId) resumeSession(meta.id);
    }
  });

  return row;
}

// Resets to a blank setup screen, same as a fresh page load - used by the
// sidebar's "+ Новая сессия" button and after deleting the active session.
function startNewSession() {
  currentSessionId = null;
  currentPdfName = null;
  currentFileKey = null;
  currentPdfBytesForSession = null;
  currentPdfFilePersisted = false;
  sessionCreatedAt = null;
  sessionNameOverride = null;
  pendingResumeCollected = null;
  pendingResumeState = null;
  resumeAfterReselect = false;
  pdfDoc = null;

  pdfInput.value = "";
  fileInfo.textContent = "";
  rangeFields.hidden = true;
  actionField.hidden = true;
  progressWrap.hidden = true;

  state.buckets = [];
  state.pageRecords = [];
  state.collected.clear();
  summaryEl.hidden = true;
  viewControls.hidden = true;
  resultsEl.innerHTML = "";
  resultsEl.hidden = true;
  stepModeEl.hidden = true;

  setupPanelEl.hidden = false;
  renderLibrary();
}

sidebarNewBtn.addEventListener("click", startNewSession);

async function resumeSession(id) {
  const sessions = await getAllSessions();
  const meta = sessions.find((s) => s.id === id);
  if (!meta) return;

  // clear whatever the previously-open session left on screen before
  // switching, so nothing stale is visible while the new one loads
  state.buckets = [];
  state.pageRecords = [];
  state.collected.clear();
  summaryEl.hidden = true;
  viewControls.hidden = true;
  resultsEl.innerHTML = "";
  resultsEl.hidden = true;
  stepModeEl.hidden = true;
  setupPanelEl.hidden = false;

  currentSessionId = meta.id;
  currentPdfName = meta.pdfName;
  currentFileKey = meta.fileKey || meta.id; // legacy sessions stored the blob under the session id itself
  sessionCreatedAt = meta.createdAt;
  sessionNameOverride = meta.name;
  pendingResumeState = { sortMode: meta.sortMode, mode: meta.mode, stepIndex: meta.stepIndex };
  pendingResumeCollected = meta.collected || [];
  renderLibrary(); // reflect the new active row right away, don't wait for analysis to finish

  const bytes = await getSessionFile(currentFileKey);
  if (!bytes) {
    // the PDF blob got evicted (storage cleared / quota pressure) - keep the
    // session id and pending resume state, but ask the user to re-pick the
    // same file; onPdfSelected() will detect resumeAfterReselect and continue
    resumeAfterReselect = true;
    currentPdfFilePersisted = false;
    pageFrom.value = meta.from;
    pageTo.value = meta.to;
    rangeFields.hidden = false;
    actionField.hidden = false;
    fileInfo.textContent = `Файл «${meta.pdfName}» не найден в локальном хранилище — выберите его заново, чтобы продолжить сессию.`;
    pdfInput.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }

  currentPdfFilePersisted = true;
  currentPdfBytesForSession = null;
  fileInfo.textContent = `Открываю «${meta.pdfName}»…`;
  pdfDoc = await pdfjsLib.getDocument({ data: bytes }).promise;
  fileInfo.textContent = `${meta.pdfName} — ${pdfDoc.numPages} стр.`;
  pageTotalLabel.textContent = `всего страниц: ${pdfDoc.numPages}`;
  pageFrom.value = meta.from;
  pageTo.value = meta.to;
  pageFrom.max = pdfDoc.numPages;
  pageTo.max = pdfDoc.numPages;
  rangeFields.hidden = false;
  actionField.hidden = false;

  await runAnalysis();
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
renderLibrary();

// ---------- update check ----------

// A static site can't safely rewrite its own files from the browser, so this
// can only check-and-notify, not silently self-update. Failing silently
// (offline, GitHub unreachable, blocked by a firewall) is intentional - this
// must never get in the way of using the app itself.
function isNewerVersion(remote, local) {
  const r = remote.split(".").map(Number);
  const l = local.split(".").map(Number);
  for (let i = 0; i < Math.max(r.length, l.length); i++) {
    const rv = r[i] || 0, lv = l[i] || 0;
    if (rv > lv) return true;
    if (rv < lv) return false;
  }
  return false;
}

async function checkForUpdate() {
  try {
    const res = await fetch(VERSION_CHECK_URL, { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (data.version && isNewerVersion(data.version, APP_VERSION)) {
      updateText.textContent = `У вас v${APP_VERSION}, на GitHub — v${data.version}`;
      updateBanner.hidden = false;
    }
  } catch (e) {
    // offline, or fetch blocked (e.g. opened via file:// in a stricter browser) - not worth surfacing
  }
}

checkForUpdate();

// ---------- LAN sync (remote control + shared PDF source) ----------

function syncPayload() {
  return {
    pdfVersion: lastLoadedPdfVersion,
    from: state.from || parseInt(pageFrom.value, 10) || null,
    to: state.to || parseInt(pageTo.value, 10) || null,
    mode: state.mode,
    sortMode: state.sortMode,
    stepIndex: state.stepIndex,
  };
}

async function pushSyncState() {
  if (!syncAvailable || suppressSyncPush) return;
  try {
    const res = await fetch("/api/state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(syncPayload()),
    });
    if (res.ok) {
      const data = await res.json();
      lastSyncedStateVersion = data.version; // so the next poll doesn't re-apply our own echo
    }
  } catch (e) {
    // offline mid-session - this push is just lost, next user action retries
  }
}

async function pushSyncedPdf(file, buf) {
  try {
    const res = await fetch("/api/pdf", {
      method: "POST",
      headers: { "X-File-Name": encodeURIComponent(file.name) },
      body: buf,
    });
    if (res.ok) {
      const data = await res.json();
      lastLoadedPdfVersion = data.version;
      pushSyncState();
    }
  } catch (e) {
    // the other device just won't receive this file - not fatal
  }
}

async function detectSync() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (typeof data.version !== "number") return;
    syncAvailable = true;
    lastSyncedStateVersion = data.version;
    lanBannerSubtitle.textContent = "Устройства синхронизированы: страница, сортировка и файл общие";
    setInterval(syncTick, 1500);
  } catch (e) {
    // not served via tools/lan_server.py - plain static hosting, sync stays off
  }
}

async function syncTick() {
  try {
    const [stateRes, metaRes] = await Promise.all([
      fetch("/api/state", { cache: "no-store" }),
      fetch("/api/pdf/meta", { cache: "no-store" }),
    ]);
    const stateData = stateRes.ok ? await stateRes.json() : null;
    const meta = metaRes.ok ? await metaRes.json() : null;
    const d = (stateData && stateData.data) || {};

    if (meta && meta.hasFile && meta.version !== lastLoadedPdfVersion) {
      await adoptSyncedPdf(meta, d);
    }

    if (stateData && stateData.version > lastSyncedStateVersion) {
      lastSyncedStateVersion = stateData.version;
      applyRemoteNav(d);
    }
  } catch (e) {
    // transient network hiccup - next tick tries again
  }
}

async function adoptSyncedPdf(meta, remoteState) {
  suppressSyncPush = true;
  try {
    const res = await fetch("/api/pdf", { cache: "no-store" });
    if (!res.ok) return;
    const buf = await res.arrayBuffer();
    pdfDoc = await pdfjsLib.getDocument({ data: buf }).promise;
    lastLoadedPdfVersion = meta.version;
    fileInfo.textContent = `${decodeURIComponent(meta.name || "instructions.pdf")} — ${pdfDoc.numPages} стр. (с другого устройства)`;
    pageFrom.max = pdfDoc.numPages; pageTo.max = pdfDoc.numPages;
    pageFrom.value = remoteState.from || 1;
    pageTo.value = remoteState.to || Math.min(pdfDoc.numPages, 150);
    rangeFields.hidden = false;
    actionField.hidden = false;
  } catch (err) {
    console.error("Не удалось получить PDF с другого устройства", err);
    return;
  } finally {
    suppressSyncPush = false;
  }
  if (remoteState.from && remoteState.to) await maybeAutoAnalyze(remoteState);
}

async function maybeAutoAnalyze(remoteState) {
  const key = `${lastLoadedPdfVersion}:${remoteState.from}:${remoteState.to}`;
  if (key === lastAnalyzedKey || !pdfDoc) return;
  lastAnalyzedKey = key;
  suppressSyncPush = true;
  try {
    pageFrom.value = remoteState.from;
    pageTo.value = remoteState.to;
    await runAnalysis();
  } finally {
    suppressSyncPush = false;
  }
  applyRemoteNav(remoteState);
}

function applyRemoteNav(d) {
  suppressSyncPush = true;
  try {
    if (d.sortMode && d.sortMode !== state.sortMode) {
      state.sortMode = d.sortMode;
      sortSelect.value = d.sortMode;
    }
    if (state.pageRecords.length) {
      if (d.mode && d.mode !== state.mode) setMode(d.mode);
      else if (typeof d.stepIndex === "number" && d.stepIndex !== state.stepIndex) goToStep(d.stepIndex);
      else render();
    } else if (d.from && d.to && pdfDoc) {
      maybeAutoAnalyze(d);
    }
  } finally {
    suppressSyncPush = false;
  }
}

detectSync();
