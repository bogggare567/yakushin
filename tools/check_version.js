/* The version the app announces and the version it checks against must agree.
 *
 * webapp/version.json is what a running copy fetches from GitHub to decide
 * whether it is out of date. If it is left behind APP_VERSION, nobody is ever
 * told there is an update; if it runs ahead, every copy claims to be old
 * forever. Both are silent, and both have happened here — version.json sat at
 * 2.2.0 while the app said 3.6.0.
 */
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const js = fs.readFileSync(path.join(root, "webapp/app.js"), "utf8");
const json = JSON.parse(fs.readFileSync(path.join(root, "webapp/version.json"), "utf8"));

const m = js.match(/APP_VERSION\s*=\s*"([^"]+)"/);
if (!m) { console.error("в app.js нет APP_VERSION"); process.exit(1); }
if (m[1] !== json.version) {
  console.error(`расходятся: app.js ${m[1]}, version.json ${json.version}`);
  process.exit(1);
}
console.log(`ok: версия ${m[1]} совпадает в app.js и version.json`);
