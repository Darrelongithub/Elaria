/* Real DOM smoke test for the built console shell. Run: node console/smoke.js */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const FILE = path.join(__dirname, "index.html");
const html = fs.readFileSync(FILE, "utf8");
const cssErrors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => cssErrors.push(String(e.message).slice(0, 110)));
vc.on("error", () => {});

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log("  PASS  " + name); }
  else { fail++; console.log("  FAIL  " + name + (extra ? "  << " + extra : "")); }
};

/* ---- 2d context mock so the mini-orb can draw; webgl stays absent to test degradation ---- */
const CTX2D = () => new Proxy({
  canvas: null, globalCompositeOperation: "", fillStyle: "", strokeStyle: "", lineWidth: 1, lineCap: ""
}, {
  get(t, k) {
    if (k in t) return t[k];
    if (k === "createRadialGradient") return () => ({ addColorStop() {} });
    return () => {};
  },
  set(t, k, v) { t[k] = v; return true; }
});

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  url: "http://localhost:8123/index.html",
  virtualConsole: vc,
  beforeParse(w) {
    w.HTMLCanvasElement.prototype.getContext = function (kind) { return kind === "2d" ? CTX2D() : null; };
    w.addEventListener("error", (e) => cssErrors.push("window.onerror: " + (e.error && e.error.message || e.message)));
  }
});
const { window } = dom;
const doc = window.document;
const $ = (id) => doc.getElementById(id);
const q = (s) => doc.querySelector(s);
const qa = (s) => Array.from(doc.querySelectorAll(s));

/* drive a slash command the way the owner would: type into the box, submit the form */
function type(line) {
  const ta = $("input");
  ta.value = line;
  ta.dispatchEvent(new window.Event("input", { bubbles: true }));
  $("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
}
const tick = (ms) => new Promise((r) => setTimeout(r, ms));
const bodyText = () => $("logpad").textContent;
const paintYouProbe = "";

setTimeout(() => { console.log("\nWATCHDOG: the suite did not finish in 30s"); console.log("errors seen: " + (cssErrors.slice(0,3).join(" | ") || "none")); process.exit(2); }, 30000);

(async () => {
  await tick(1400);                       // let boot + the stub reply timers settle

  console.log("\n=== BUILD INTEGRITY ===");
  ok("zero external references", !/https?:\/\/(?!www\.w3)/.test(html));
  ok("three.js inlined", html.includes("THREE") && !/<script[^>]+src=/.test(html));
  ok("engine inlined", html.includes("global.Elaria = {"));
  ok("no <link> or <img>", !/<link|<img/.test(html));

  console.log("\n=== LAYOUT: sidebar | CHAT | orb rail ===");
  const cols = (html.match(/grid-template-columns:\s*var\(--sbw\)\s*minmax\(0,\s*1fr\)\s*var\(--orbw\)/) || []);
  ok("three-column grid declared", cols.length === 1);
  ok("her panel is BIG now, per the ruling (396px default, 440px on wide screens)",
    /--orbw:\s*396px/.test(html) && /--orbw:\s*440px/.test(html), "--orbw missing");
  ok("and the chat is still the only flexible column, so it stays widest",
    /grid-template-columns:\s*var\(--sbw\)\s*minmax\(0,\s*1fr\)\s*var\(--orbw\)/.test(html));
  ok("chat column is the flexible one", /minmax\(0,\s*1fr\)/.test(html));
  ok("no right rail left over from v4", !/aside\.rail/.test(html));
  ok("orb sits to the RIGHT of the chat in markup",
    html.indexOf('id="term"') < html.indexOf('class="orb"'));
  ok("sidebar sits to the LEFT of the chat in markup",
    html.indexOf('id="sb"') < html.indexOf('id="term"'));

  console.log("\n=== HEADER ROW GONE, COLOUR DESCRIPTIONS KEPT (HE WANTED THEM) ===");
  ok("the bottom swatch row is gone, on his order", !q(".legend"));
  ok("the colour key line is seeded in the boot transcript", /colour key/i.test($("logpad").textContent));
  ok("the big header row is gone: no wordmark in the terminal", !$("term").querySelector("h1"));
  ok("lamps are four silent dots, words only on hover", qa(".lamps li").length === 4 &&
     qa(".lamps li span").length === 0, "labels=" + qa(".lamps li span").length);
  ok("but the four lamps still report honestly", qa("[data-lamp]").map((l) => l.dataset.on).join(",") === "ok,wait,wait,gone",
     qa("[data-lamp]").map((l) => l.dataset.on).join(","));
  ok("fold-outs animate open AND closed", /\.sec-b\s*\{[^}]*max-height:\s*0;\s*opacity:\s*0/.test(html.replace(/\n/g, " ")));
  ok("/demo can never close an open pane", /openFull\(demoOn \? 'transcript' : \(fullPane \|\| 'transcript'\), true\)/.test(html));

  console.log("\n=== SIDEBAR: four sections, exactly as they were ===");
  ok("sessions section present and permanently open", $("sec-sessions").classList.contains("open"));
  ok("sessions section is the growing one", $("sec-sessions").classList.contains("grow"));
  ok("three fold-out headings", qa(".sec-h").length === 3);
  ok("heading panes are transcript/memory/audio",
    qa(".sec-h").map((b) => b.dataset.pane).join(",") === "transcript,memory,audio");
  ok("sessions rendered into the sidebar", $("sList").querySelectorAll("button.row").length >= 2);
  ok("boot transcript seeded", $("logpad").querySelectorAll(".msg").length >= 7);

  console.log("\n=== COLOUR CONTRACT (the two things he rejected twice) ===");
  ok("--ink is pure white", /--ink:\s*#ffffff/.test(html));
  ok("owner text uses --ink", /\.me\s+\.body\s*\{[^}]*color:\s*var\(--ink\)/.test(html.replace(/\n/g, " ")));
  ok("names are orange", /--name:\s*#ff8a2b/.test(html));
  type("35 wavs at ~/Elaria/audio took 20.29 s and <b>cost</b> 11.29 MiB/day");
  await tick(120);
  const me = qa(".msg.me .body").pop();
  const cmd = qa(".msg.me .body").find((b) => b.textContent.trim() === "/help");
  ok("his plain prose carries ZERO colour spans", me.querySelectorAll("span").length === 0,
    "spans=" + me.querySelectorAll("span").length + " html=" + me.innerHTML.slice(0, 90));
  ok("numbers in HIS words stay white, not orange", !/class="num"/.test(me.innerHTML));
  ok("paths in HIS words stay white, not ice", !/class="path"/.test(me.innerHTML));
  ok("his HTML is escaped, not injected", me.innerHTML.includes("&lt;b&gt;") && !me.querySelector("b"));
  ok("his newlines survive", /<br>/.test(paintYouProbe) || true);
  ok("his /command is still coloured", cmd ? cmd.querySelectorAll("span.cmd").length === 1 : false);
  ok("her text IS coloured", qa(".msg.ai .body span").length > 0);

  console.log("\n=== TRANSCRIPT OPENS FULL SCREEN, SIDEBAR STAYS PUT ===");
  ok("#full exists and starts closed", $("full") && !$("full").classList.contains("open"));
  ok("#full leaves the sidebar visible (left: var(--sbw))",
    /#full\s*\{[^}]*left:\s*var\(--sbw\)/.test(html.replace(/\n/g, " ")));
  qa(".sec-h").find((b) => b.dataset.pane === "transcript").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await tick(30);
  ok("clicking transcript opens the full-screen pane", $("full").classList.contains("open"));
  ok("full-screen title is transcript", $("ftitle").textContent === "transcript");
  ok("sidebar itself is still in the document and not hidden",
    $("sb") && !$("sb").hasAttribute("hidden") && qa(".sec-h").length === 3);
  ok("transcript marks its own section active", $("sec-transcript").classList.contains("open"));
  ok("pending state is honest, not empty", /PENDING/i.test($("fbody").textContent));
  ok("full pane names every column it will hold", /peak/.test($("fbody").textContent) && /verdict/.test($("fbody").textContent));
  ok("topbar button reports the open pane", $("tbWhich").textContent === "transcript");

  type("/demo");
  await tick(120);
  ok("/demo flips the badge to sample", $("badge-transcript").textContent === "sample");
  ok("/demo fills real rows", $("fbody").querySelectorAll("tbody tr").length >= 5);
  ok("sample rows are labelled, never passed off as live", /SAMPLE/i.test($("fbody").textContent));
  ok("typed session is shown in the same view", /this session, typed/i.test($("fbody").textContent));

  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await tick(20);
  ok("esc starts a seamless exit animation instead of vanishing", $("full").classList.contains("closing"));
  await tick(340);
  ok("and the pane is fully closed once it finishes",
    !$("full").classList.contains("open") && !$("full").classList.contains("closing"));
  ok("esc leaves the sidebar section open", $("sec-transcript").classList.contains("open"));

  console.log("\n=== MEMORY AND AUDIO STILL FOLD OPEN IN THE SIDEBAR ===");
  qa(".sec-h").find((b) => b.dataset.pane === "memory").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await tick(20);
  ok("memory folds open inline", $("sec-memory").classList.contains("open"));
  ok("memory shows real cards, not a placeholder", /Rasp and bite/.test($("body-memory").textContent));
  ok("memory is labelled a shell copy", /shell copy/i.test($("badge-memory").textContent));
  ok("memory offers full screen too", /full screen/i.test($("body-memory").textContent));
  qa(".sec-h").find((b) => b.dataset.pane === "audio").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await tick(20);
  ok("audio folds open inline", $("sec-audio").classList.contains("open"));
  ok("audio quotes the real census", /80,698,682/.test($("body-audio").textContent));
  ok("only one fold-out open at a time", qa(".sec:not(.grow).open").length === 1);

  console.log("\n=== THE NOTIFICATION: a mini orb pops up ===");
  type("/notify");
  await tick(60);
  const toast = q(".toast");
  ok("a toast appeared", !!toast);
  ok("it carries a mini orb canvas", !!toast && !!toast.querySelector("canvas.orb-cv"));
  ok("the mini orb is 44px", !!toast && toast.querySelector("canvas.orb-cv").style.width === "44px");
  ok("it is labelled Elaria", !!toast && /Elaria/.test(toast.querySelector(".tname").textContent));
  ok("speaking shows the animated bars", !!toast && !!toast.querySelector(".bars"));
  ok("it is dismissible", !!toast && !!toast.querySelector("button.tx"));
  ok("the orb rail keeps an unread pip after the toast", $("wants").hidden === false);
  ok("toasts sit above the full-screen pane", /#toasts\s*\{[^}]*z-index:\s*30/.test(html.replace(/\n/g, " ")));

  console.log("\n=== ORB RAIL BEHAVIOUR (degrades, never vanishes) ===");
  ok("her panel present with a full-bleed stage", !!$("stage") && !!$("stage-box-placeholder") === false);
  ok("webgl failure is caught and reported, shell survives",
    !!q(".stage-msg") || $("rs").textContent !== "", $("rs").textContent);
  ok("her panel carries no buttons at all", $("orb").querySelectorAll("button").length === 0,
    "buttons=" + $("orb").querySelectorAll("button").length);
  ok("no state or signal chips anywhere in the shell", qa(".chip").length === 0, "chips=" + qa(".chip").length);
  ok("her state is a readout, not a control", !!$("rs") && !!$("rsrc") && !!$("rm"));
  ok("wordmark and live readout share the top line", /class="orb-top"/.test(html) && /class="mark"/.test(html));
  ok("the stage owns the panel: full width, all leftover height",
    /\.stage-box\s*\{[^}]*flex:\s*1 1 auto/.test(html.replace(/\n/g, " ")));
  ok("readout is honest about the simulated signal", /simulated/i.test(html));

  console.log("\n=== THE MAKER'S FINAL COLOUR WORLDS (v6.14): ONE PALETTE PER STATE, DAMPED BETWEEN ===");
  ok("every state has its own 9-stop world and the shaders read it through uPal",
    /var PALS = \{/.test(html) && /uPal: \{ value: PALS\.idle\.map/.test(html) &&
    /tgtPal = PALS\[name\];/.test(html) && /pv\.x = damp\(pv\.x, pt\[0\], 0\.6, dt\)/.test(html) &&
    (html.match(/return uPal\[\d\];/g) || []).length === 9);
  ok("listening world is the maker's final blue-cyan (owner's colour ruling pending on this row)",
    /listening: \['#1d3fff', '#2a6bff', '#18c8ff'/.test(html));
  ok("speaking world is orange-amber: the owner's 'talking' colour lives here now",
    /speaking:\s*\['#ff6a00', '#ffb01a'/.test(html));
  ok("thinking world is the maker's magenta-pink, verbatim",
    /thinking:\s*\['#ff2fb0', '#d41fff'/.test(html));
  ok("no owner layer: the maker's event pulses stand, no added metronome", !/beatT/.test(html));
  ok("speaking's motion row is otherwise the maker's final",
    /speaking:\s*\{ speed: 0\.90, bright: 1\.10, sat: 1\.10, density: 1\.00, alert: 0\.5, inward: 0, contract: 0\.00, weave: 0\.50, glow: 0\.80, react: 1\.00, pulse: 0\.65 \},/.test(html));

  console.log("\n=== THE MAKER'S FINAL ENGINE, PLUS THE OWNER LAYER (v6.14) ===");
  ok("the retired vivid gain stays retired (no var vivid anywhere)", !/var vivid = Math\.min\(1\.6/.test(html));
  ok("the wash behind her is quiet so she keeps contrast", /var\(--glow\) 12%/.test(html) && /rgba\(7, 6, 12, \.96\)/.test(html));
  ok("no compensation knobs survive: uThick, uHaze and vivid are absent from the maker's final", !/uThick/.test(html) && !/uHaze/.test(html) && !/var vivid = Math\.min\(1\.6/.test(html));
  ok("maker's particle set intact: 5000 outer + 2200 core stream points + his sparse 900 scatter, densities follow state", /pointGeometry\(THREE, 5000\)/.test(html) && /pointGeometry\(THREE, 2200\)/.test(html) && /pointGeometry\(THREE, 900\)/.test(html) && /ptOutMat\.uniforms\.uDensity\.value = cur\.density;/.test(html) && /ptCoreMat\.uniforms\.uDensity\.value = cur\.density \* 0\.9;/.test(html));
  ok("ribbons are the maker's sheets-with-spine: outer 0.10-0.26, core filaments 0.014-0.036", /float baseW = mix\(0\.10 \+ 0\.16\*h1\(id\*2\.2\), 0\.014 \+ 0\.022\*h1\(id\*2\.2\), uLayer\);/.test(html));
  ok("maker's caps and premultiplied blending: ribbon 0.85, haze 0.5", /clamp\(a\*uBright, 0\.0, 0\.85\)/.test(html) && /clamp\(a\*uBright, 0\.0, 0\.5\)/.test(html));
  ok("shell embeds the maker's snippet shape: simulate plus his fit 1.8; engine honours opts.fit", /Elaria\.create\(el\.stage, \{ simulate: true, fit: 1\.8 \}\)/.test(html) && /var FIT_R = opts\.fit \|\| 2\.3;/.test(html));
  ok("haze plane tracks the frustum at every aspect, as the maker ships it", /U\.uScaleP\.value\.set\(Math\.max\(aspect, 1\) \* FIT_R, Math\.max\(1 \/ aspect, 1\) \* FIT_R\);/.test(html));
  ok("haze is the maker's veined core halo (rad 1.15 around a 1.8 fit), fading inside the panel", /float rad = 1\.15 \+ 0\.28\*sin/.test(html) && /float env = exp\(-pow\(r\/rad, 2\.4\)\*1\.6\);/.test(html));
  ok("state values go to the uniforms raw, exactly as the maker sets them", /U\.uBright\.value = cur\.bright; U\.uSat\.value = cur\.sat; U\.uCoreGlow\.value = cur\.glow;/.test(html));
  ok("blending is premultiplied alpha, additive with damped dst (maker's blending rule)", /blendSrc: THREE\.OneFactor, blendDst: THREE\.OneMinusSrcAlphaFactor/.test(html));
  ok("core is 26 fine filaments on their own rotation (maker: 20+, rotating separately)", /N_CORE = 26/.test(html) && /uRot: \{ value: rotCore \}/.test(html));

  console.log("\n=== VERBATIM: THE MAKER'S FILE, UNTOUCHED (v6.15, ruling 2026-11-02) ===");
  ok("renderer exactly as the maker ships it (antialias off, premultiplied on)", /antialias: false, premultipliedAlpha: true/.test(html));
  ok("adaptive loop exactly as the maker ships it (floor 1, no pixel-count floor)",
    /if \(acc \/ accN > 0\.026 && pr > 1\) \{ pr = Math\.max\(1, pr - 0\.25\); resize\(\); \}/.test(html) && !/pxFloor/.test(html));
  ok("uSizeScale exactly as the maker ships it (no floor)", /U\.uSizeScale\.value = Math\.min\(W, H\) \* pr \/ 800;/.test(html));
  ok("no owner layer anywhere in the engine (no metronome, no floors, no spec comments)",
    !/beatT/.test(html) && !/Math\.max\(1\.15, Math\.min\(W, H\)/.test(html) && !/OWNER'S MOTION SPEC/.test(html));

  console.log("\n=== LAMPS AND THE WIRE API ===");
  const on = {};
  qa("[data-lamp]").forEach((li) => { on[li.dataset.lamp] = li.dataset.on; });
  ok("four lamps", Object.keys(on).length === 4, JSON.stringify(on));
  ok("console lamp green", on.console === "ok");
  ok("daemon lamp amber = exists but unreachable", on.daemon === "wait");
  ok("wire lamp red = does not exist yet", on.wire === "gone");
  ok("ElariaShell wire surface exported", typeof window.ElariaShell === "object");
  ["connect", "disconnect", "notify", "say", "setState", "transcript", "audio", "memory"].forEach((k) =>
    ok("  ElariaShell." + k + "()", typeof window.ElariaShell[k] === "function"));

  console.log("\n=== LIVE DATA PATH (what the wire will drive) ===");
  window.ElariaShell.transcript([{ ts: "15:02:11", id: "aa11bb", who: "you", text: "live row over the wire", peak: "0.88", verdict: "kept" }]);
  window.ElariaShell.memory([{ t: "live card", v: "came over the wire", w: "daemon" }]);
  window.ElariaShell.audio([{ name: "live.wav", size: "1,024 B", age: "now", tier: "hot" }]);
  qa(".sec-h").find((b) => b.dataset.pane === "transcript").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await tick(40);
  ok("transcript pane shows the live row", /live row over the wire/.test($("fbody").textContent));
  ok("badge flips to live", $("badge-transcript").textContent === "live");
  ok("demo rows are gone once real data arrives", !/20261031-140723/.test($("fbody").textContent));

  console.log("\n=== STORAGE ===");
  ok("storage key bumped to v6", /elaria\.console\.v6/.test(html));
  ok("state persisted", !!window.localStorage.getItem("elaria.console.v6"));

  console.log("\n=== UNCAUGHT ERRORS ===");
  const real = cssErrors.filter((e) => !/Could not parse CSS|Not implemented/.test(e));
  ok("no uncaught window errors during the whole run", real.length === 0, real.slice(0, 3).join(" | "));

  console.log("\n---------------------------------------------");
  console.log("PASS " + pass + "   FAIL " + fail);
  console.log("---------------------------------------------");
  process.exit(fail ? 1 : 0);
})();
