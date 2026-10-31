// Synthetic console and R7/R8 DTO grammar. No IPC, network, timer,
// executor, persistence, or desktop notification dispatch lives in this asset.
// The same pure functions are exercised under node in the sandbox tests.

function scenarioNames() {
    return ["idle", "plan", "collision", "injection", "verified", "disconnected", "locked", "company", "class", "unknown"];
}

function scenario(name) {
    var snapshot = {
        synthetic: true,
        name: name,
        locked: false,
        posture: "normal",
        connected: true,
        heading: "nothing moving right now",
        lines: [],
        ask: null
    };
    if (name === "idle") {
        snapshot.lines = ["This is a synthetic rehearsal. Nothing here runs commands."];
    } else if (name === "plan") {
        snapshot.heading = "the plan is on the page first";
        snapshot.lines = [
            "Fixture plan: inspect the synthetic messy folder.",
            "Fixture step: move a synthetic note using the existing hygiene library.",
            "These are display samples, not adjudicated or executable steps."
        ];
    } else if (["collision", "locked", "company", "class", "unknown"].indexOf(name) >= 0) {
        snapshot.heading = "a fixture decision is waiting";
        snapshot.lines = ["Fixture collision: the target name already exists."];
        snapshot.ask = {
            id: "synthetic-ask-1",
            state: "pending",
            planHash: "a".repeat(64),
            ageSeconds: 864090,
            paths: ["synthetic/messy/note.txt", "synthetic/filed/note.txt"],
            disclosure: "Source bytes: sample incoming note\nTarget bytes: sample existing note",
            warning: "Display-only ask. No tier verdict or executable approval exists. "
                + "For T2, informed consent is not a sandboxing guarantee."
        };
        snapshot.locked = name === "locked";
        snapshot.posture = name === "collision" ? "normal" : name;
    } else if (name === "injection") {
        snapshot.heading = "suspected injection in fixture data";
        snapshot.lines = [
            "Fixture oracle preview: refuse the step and record hands.inject.",
            "No detector or executor is connected; this preview does not prove the trap gate."
        ];
    } else if (name === "verified") {
        snapshot.heading = "a verification report, rehearsed";
        snapshot.lines = [
            "Fixture report: two files would be counted after a re-read.",
            "No files were moved or verified by this harness."
        ];
    } else if (name === "disconnected") {
        snapshot.connected = false;
        snapshot.heading = "the fixture feed is disconnected";
        snapshot.lines = ["The outcome is unknown, not done. No decision can be sent."];
    } else {
        throw new Error("unknown synthetic scenario");
    }
    return snapshot;
}

function ageLabel(seconds) {
    if (typeof seconds !== "number" || !isFinite(seconds) || seconds < 0) {
        return "ask age is unknown";
    }
    return "waiting " + Math.floor(seconds / 60) + " minutes; no expiry";
}

function privateCard(snapshot) {
    // Unknown posture is redacted in this synthetic renderer, not inferred as
    // unlocked. This is no claim about the future trusted posture integration.
    if (!snapshot || snapshot.locked !== false || snapshot.connected !== true
            || ["normal", "company", "class"].indexOf(snapshot.posture) < 0) return null;
    return snapshot.ask || null;
}

function notificationPreview(snapshot) {
    // Returns data for an in-console sample label; NEVER calls notify-send.
    if (!privateCard(snapshot) || snapshot.posture !== "normal") return null;
    return "elaria needs a yes";
}

function visibleLines(snapshot) {
    if (!snapshot || snapshot.locked !== false
            || ["normal", "company", "class"].indexOf(snapshot.posture) < 0)
        return ["the private preview is hidden"];
    return snapshot.lines.slice();
}

function inputPreview(text) {
    // Raw capture remains data; routeInput below supplies the separately ruled R7 DTO.
    return {rawText: String(text), notice: "Preview only: input captured; nothing dispatched."};
}

function buttonPreview(label, snapshot) {
    if (label !== "yes" && label !== "no") throw new Error("unknown preview button");
    if (!privateCard(snapshot)) return "There is no visible fixture ask. Nothing dispatched.";
    return "Preview only: " + label + " clicked. No approval or decision was saved.";
}

// DTO only: production authority and persistence belong to the service, not QML.
function routeInput(text, focusedAsk) {
    var raw = String(text);
    var word = raw.trim().toLowerCase();
    if (word === "yes" || word === "no") {
        if (!focusedAsk || focusedAsk.state !== "pending") {
            return {kind: "none", notice: "no ask is selected"};
        }
        return {kind: "decision", decision: word, askId: focusedAsk.id,
            planHash: focusedAsk.planHash, notice: "Synthetic decision DTO only; nothing dispatched."};
    }
    return {kind: "intent", text: raw, notice: "Synthetic intent DTO only; nothing dispatched."};
}
