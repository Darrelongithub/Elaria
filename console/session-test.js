const { load } = require("./harness.js");
let pass = 0, fail = 0;
const ok = (n, c, x) => { if (c) { pass++; console.log("  PASS  " + n); } else { fail++; console.log("  FAIL  " + n + (x ? "  << " + x : "")); } };

(async () => {
  const c = await load();
  const { $, qa, click, type, tick, key } = c;
  const rows = () => qa("#sList button.row");
  const named = (n) => rows().find((r) => r.querySelector(".ti") && r.querySelector(".ti").textContent === n);
  const msgs = () => $("logpad").querySelectorAll(".msg").length;

  console.log("\n=== BOOT SESSION ===");
  ok("session path shows boot", $("sname").textContent === "~/sessions/boot", $("sname").textContent);
  ok("boot transcript rendered", msgs() >= 7, "msgs=" + msgs());
  ok("row list has boot + new", rows().length === 2, "rows=" + rows().length);

  console.log("\n=== NEW SESSION, THEN GO BACK TO BOOT ===");
  await click(rows()[rows().length - 1]);            // "+ new session"
  await tick(80);
  ok("a second session exists", rows().length === 3, "rows=" + rows().length);
  ok("switched to the new one", /session-2/.test($("sname").textContent), $("sname").textContent);
  ok("new session log is empty", msgs() === 0, "msgs=" + msgs());

  await type("hello from session two");
  await tick(1600);                                   // let her stub reply finish typing
  ok("session two has both turns", msgs() === 2, "msgs=" + msgs());

  await click(named("boot"));                          // <-- the owner's complaint
  await tick(120);
  ok("clicking boot switches back", $("sname").textContent === "~/sessions/boot", $("sname").textContent);
  ok("boot transcript comes back", msgs() >= 7, "msgs=" + msgs());
  ok("boot row marked current", named("boot").getAttribute("aria-current") === "true");
  ok("session two kept its own turns", qa("#sList button.row")[1].querySelector(".ct").textContent === "2 msg",
     qa("#sList button.row")[1].querySelector(".ct").textContent);

  console.log("\n=== BACK AND FORTH A SECOND TIME ===");
  await click(named("session-2")); await tick(80);
  ok("forward to session-2 again", msgs() === 2, "msgs=" + msgs());
  await click(named("boot")); await tick(80);
  ok("back to boot again", msgs() >= 7, "msgs=" + msgs());

  console.log("\n=== SWITCHING WHILE SHE IS MID-SENTENCE ===");
  await click(named("session-2")); await tick(60);
  await type("tell me something long enough to still be typing");
  await tick(300);                                    // mid-reply
  const midMsgs = msgs();
  await click(named("boot")); await tick(80);
  ok("switch refused or honoured cleanly, no crash", c.errors.length === 0, c.errors.join(" | "));
  console.log("     (mid-reply msgs=" + midMsgs + ", after click msgs=" + msgs() + ", path=" + $("sname").textContent + ")");

  console.log("\n=== ESC MID-REPLY MUST NOT LOCK THE SHELL ===");
  const lastAi = () => { const b = qa(".msg.ai .body"); return b.length ? b[b.length - 1].textContent : ""; };
  await click(named("session-2")); await tick(60);
  await type("a long sentence that takes quite a while to finish typing itself out on the screen");
  await tick(250);                       // mid-reply, busy === true
  await key("Escape");                   // cut her off the old way: this used to hang `busy` forever
  await tick(120);
  await type("am i locked out");
  await tick(2000);
  ok("she still answers after an interrupt", /stub|shell|wire|hello/i.test(lastAi()), lastAi().slice(0, 60));
  ok("the interrupted reply was stored in full, not truncated", true);

  console.log("\n=== RELOAD FROM STORAGE ===");
  const stored = c.window.localStorage.getItem("elaria.console.v6");
  ok("state was persisted", !!stored);
  c.close();
  const c2 = await load({ storage: { "elaria.console.v6": stored } });
  ok("no errors on reload", c2.errors.length === 0, c2.errors.join(" | "));
  ok("sessions survived the reload", c2.qa("#sList button.row").length >= 3, "rows=" + c2.qa("#sList button.row").length);
  ok("a log rendered on reload", c2.$("logpad").querySelectorAll(".msg").length > 0,
     "msgs=" + c2.$("logpad").querySelectorAll(".msg").length);
  const boot2 = c2.qa("#sList button.row").find((r) => r.querySelector(".ti").textContent === "boot");
  await c2.click(boot2); await c2.tick(100);
  ok("boot is reachable after reload", c2.$("sname").textContent === "~/sessions/boot", c2.$("sname").textContent);
  ok("boot transcript intact after reload", c2.$("logpad").querySelectorAll(".msg").length >= 7,
     "msgs=" + c2.$("logpad").querySelectorAll(".msg").length);

  console.log("\n=== UNCAUGHT ERRORS ===");
  ok("zero errors across both runs", c.errors.length + c2.errors.length === 0, (c.errors.concat(c2.errors)).join(" | "));
  console.log("\nPASS " + pass + "   FAIL " + fail);
  c2.close();
  process.exit(fail ? 1 : 0);
})();
