// Copies every UI string (7 languages) from the website's frontend/i18n.js
// into src/strings.json, so the app and the site always say the same thing.
//   node scripts/sync-strings.js
const fs = require("fs");
const path = require("path");

const store = {};
global.window = { addEventListener() {}, dispatchEvent() {} };
global.localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
global.document = {
  documentElement: { setAttribute() {}, lang: "en", dir: "ltr" },
  querySelectorAll: () => [], getElementById: () => null, addEventListener() {},
  dispatchEvent() {}, head: { appendChild() {} }, createElement: () => ({ style: {} }),
};
global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };

require(path.join(__dirname, "..", "..", "frontend", "i18n.js"));
const out = { languages: window.LANGUAGES, strings: window.STRINGS };
fs.writeFileSync(path.join(__dirname, "..", "src", "strings.json"), JSON.stringify(out));
const counts = Object.fromEntries(Object.entries(out.strings).map(([k, v]) => [k, Object.keys(v).length]));
console.log("languages:", out.languages.map(l => l.code).join(", "), "| keys per language:", counts);
