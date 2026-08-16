/* Takes the pictures in docs/screenshots/ from the running app.
 *
 * They come out of the real thing, on a real booklet, rather than being drawn
 * by hand — so a screenshot in the README cannot quietly stop matching what
 * the program does. Chrome's own --screenshot fires at load and catches the
 * app mid-thought; this waits until the page says it is ready.
 *
 * Usage:  node tools/screenshots.js <port> [name ...]
 *   needs a lan_server.py serving webapp/ on that port, with _shot.html and a
 *   booklet at /_book.pdf. Neither is in the repository: the booklets are
 *   licensed for personal use and the harness is generated.
 */
const fs = require("fs");
const path = require("path");
const puppeteer = require("/tmp/node_modules/puppeteer-core");

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const OUT = path.join(__dirname, "..", "docs", "screenshots");

const SHOTS = {
  list:        { url: "shot=list",                          w: 1280, h: 900 },
  page:        { url: "shot=page&part=0",                   w: 1280, h: 900 },
  "page-zoom": { url: "shot=page&part=0&zoom=3",            w: 1280, h: 900 },
  qr:          { url: "shot=qr",                            w: 1280, h: 900 },
  loader:      { url: "shot=loader",                        w: 1280, h: 560 },
  phone:       { url: "shot=list", remote: true,            w: 390, h: 844 },
  "phone-page":{ url: "shot=page&part=0", remote: true,     w: 390, h: 844 },
  "phone-zoom":{ url: "shot=page&part=0&zoom=2.6", remote: true, w: 390, h: 844 },
};

(async () => {
  const port = process.argv[2] || "8976";
  const want = process.argv.slice(3);
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2"],
  });

  for (const [name, cfg] of Object.entries(SHOTS)) {
    if (want.length && !want.includes(name)) continue;
    const page = await browser.newPage();
    await page.setViewport({ width: cfg.w, height: cfg.h, deviceScaleFactor: 2,
                             isMobile: !!cfg.remote, hasTouch: !!cfg.remote });
    const url = `http://127.0.0.1:${port}/_shot.html?${cfg.url}${cfg.remote ? "&remote=1" : ""}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    try {
      await page.waitForFunction("document.body.dataset.ready === '1'", { timeout: 180000 });
    } catch (e) {
      console.error(`  ${name}: не дождался готовности — ${await page.title()}`);
      await page.close();
      continue;
    }
    await new Promise((r) => setTimeout(r, 900));   // let the last transition settle
    const file = path.join(OUT, `${name}.png`);
    await page.screenshot({ path: file });
    console.log(`  ok  ${name}  ${(fs.statSync(file).size / 1024) | 0} КБ`);
    await page.close();
  }
  await browser.close();
})();
