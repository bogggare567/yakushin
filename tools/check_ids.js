/* Every element app.js reaches for must exist in the page.
 *
 * This exists because of a real failure, and a nasty one: app.js takes its
 * element handles at the top level, so one missing id throws before any of the
 * setup below it runs — no sync, no library, no update check — and the page
 * still looks fine. It happened while adding the zoom controls, and the only
 * symptom was that the phone stopped receiving anything at all.
 *
 * Static on purpose: no browser, no dependencies, runs in a second.
 */
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "webapp/index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "webapp/app.js"), "utf8");

const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
const missing = [];
for (const m of js.matchAll(/getElementById\(\s*"([^"]+)"\s*\)/g)) {
  if (!ids.has(m[1])) missing.push(m[1]);
}

// and the other way round for the handful the code assigns into, so a rename
// in the HTML that nothing reads is at least visible
const unusedNote = [...ids].filter((id) => !js.includes(`"${id}"`) && !html.includes(`for="${id}"`));

if (missing.length) {
  console.error("В index.html нет элементов, которые ищет app.js:");
  for (const id of new Set(missing)) console.error("  #" + id);
  process.exit(1);
}
console.log(`ok: все ${ids.size} id на месте (${unusedNote.length} не упоминаются в app.js — это нормально для разметки)`);
