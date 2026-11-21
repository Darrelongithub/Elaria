/* Shared jsdom harness for the console shell. node console/harness.js runs the checks in a test file.
   Usage:  const { load } = require('./harness.js');
           const ctx = await load();            // boots the built index.html in a real DOM
           ctx.type('/demo'); await ctx.tick(50);
           ctx.$('logpad').textContent          // assertions against rendered output, not source
   Needs:  npm install --prefix console jsdom                       */
const fs = require("fs");
const path = require("path");

function requireJsdom() {
  return require("jsdom");
}

const CTX2D = () => new Proxy({
  globalCompositeOperation: "", fillStyle: "", strokeStyle: "", lineWidth: 1, lineCap: ""
}, {
  get(t, k) {
    if (k in t) return t[k];
    if (k === "createRadialGradient" || k === "createLinearGradient") return () => ({ addColorStop() {} });
    if (k === "measureText") return () => ({ width: 10 });
    return () => {};
  },
  set(t, k, v) { t[k] = v; return true; }
});

async function load(opts) {
  opts = opts || {};
  const { JSDOM, VirtualConsole } = requireJsdom();
  const file = opts.file || path.join(__dirname, "index.html");
  const html = fs.readFileSync(file, "utf8");
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => {
    const m = (e.stack || e.message || "");
    if (/Could not parse CSS|Not implemented/.test(m)) return;   // jsdom gaps, not shell defects
    errors.push(m.split("\n").slice(0, 4).join(" | "));
  });
  vc.on("error", () => {});

  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url: "http://localhost:8123/index.html",
    virtualConsole: vc,
    beforeParse(w) {
      w.HTMLCanvasElement.prototype.getContext = (k) => (k === "2d" ? CTX2D() : null);
      if (opts.storage) for (const [k, v] of Object.entries(opts.storage)) w.localStorage.setItem(k, v);
      w.addEventListener("error", (e) => errors.push("window.onerror: " + ((e.error && e.error.message) || e.message)));
    }
  });
  const { window } = dom;
  const doc = window.document;
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(opts.settle || 1400);

  return {
    window, doc, html, errors, tick,
    $: (id) => doc.getElementById(id),
    q: (s) => doc.querySelector(s),
    qa: (s) => Array.from(doc.querySelectorAll(s)),
    click(node) { node.dispatchEvent(new window.MouseEvent("click", { bubbles: true })); return tick(40); },
    key(k) { doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true })); return tick(30); },
    async type(line) {
      const ta = doc.getElementById("input");
      ta.value = line;
      ta.dispatchEvent(new window.Event("input", { bubbles: true }));
      doc.getElementById("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
      await tick(140);
    },
    close() { try { dom.window.close(); } catch (e) { /* already gone */ } }
  };
}

module.exports = { load };
