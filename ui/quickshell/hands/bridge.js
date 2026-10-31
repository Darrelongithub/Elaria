// Transport-independent controller used by the actual QML Socket and node tests.
// Never retries a mutation. Reconnection sends only hands.snapshot.
function disconnectedSnapshot() {
    return {synthetic: true, connected: false, locked: true, posture: "unknown",
        phase: "disconnected", heading: "the synthetic bridge is not connected",
        plan: [], planHash: null, lines: [], events: [], ask: null,
        askAgeSeconds: null, notification: null, metrics: {}};
}

function createController(clientId) {
    var c = {
        clientId: clientId, sequence: 0, connected: false, epoch: null,
        pending: null, uncertain: false, uncertainEpoch: null, snapshot: disconnectedSnapshot(), notice: "Waiting for the synthetic bridge."
    };
    c.disconnect = function(message) {
        var uncertain = this.uncertain || (this.pending && this.pending.mutation);
        if (uncertain && !this.uncertainEpoch) this.uncertainEpoch = this.epoch;
        this.uncertain = !!uncertain;
        this.connected = false;
        this.epoch = null;
        this.pending = null;
        this.snapshot = disconnectedSnapshot();
        this.notice = uncertain ? "Request outcome unknown. Reconnect to inspect; do not replay." : message;
    };
    c.request = function(method, fields, now) {
        if (!this.connected || this.pending) return null;
        var mutation = method !== "hands.snapshot";
        if (mutation && !this.epoch) return null;
        var params = {};
        Object.keys(fields).forEach(function(key) { params[key] = fields[key]; });
        var id = ++this.sequence;
        if (mutation) {
            params.epoch = this.epoch;
            params.nonce = this.clientId + "-" + id;
        }
        this.pending = {id: id, deadline: now + 5000, mutation: mutation};
        return JSON.stringify({id: id, method: method, params: params}) + "\n";
    };
    c.connect = function(now) {
        this.connected = true;
        this.pending = null;
        this.epoch = null;
        this.snapshot = disconnectedSnapshot();
        return this.request("hands.snapshot", {}, now);
    };
    c.receive = function(line) {
        var reply;
        if (typeof line !== "string" || line.length > 262144) {
            this.disconnect("Invalid bridge frame; private content cleared.");
            return false;
        }
        try { reply = JSON.parse(line); }
        catch (e) {
            this.disconnect("Invalid bridge frame; private content cleared.");
            return false;
        }
        if (!reply || typeof reply !== "object" || Array.isArray(reply)) {
            this.disconnect("Invalid bridge frame; private content cleared.");
            return false;
        }
        if (!this.pending || reply.id !== this.pending.id) return false;
        if (reply.ok !== true || !reply.result || reply.result.synthetic !== true
                || typeof reply.result.epoch !== "string" || reply.result.epoch.length !== 32
                || !Array.isArray(reply.result.plan) || !Array.isArray(reply.result.lines)) {
            this.disconnect("The synthetic bridge refused the request; content cleared.");
            return false;
        }
        var s = reply.result;
        this.pending = null;
        this.epoch = s.epoch;
        this.connected = true;
        if (["normal", "company", "class"].indexOf(s.posture) < 0 || s.locked !== false) {
            s.plan = []; s.planHash = null; s.ask = null; s.lines = []; s.events = [];
            s.notification = null; s.heading = "the private console is hidden";
            s.notice = "private content hidden; pending asks are retained";
        } else {
            s.notification = s.posture === "normal" && s.ask ? "elaria needs a yes" : null;
        }
        this.snapshot = s;
        if (this.uncertain && this.uncertainEpoch !== s.epoch) {
            this.notice = "New bridge session; the prior request outcome is unknown. Nothing replayed.";
        } else {
            this.uncertain = false;
            this.uncertainEpoch = null;
            this.notice = s.notice;
        }
        return true;
    };
    c.tick = function(now) {
        if (this.pending && now >= this.pending.deadline) {
            this.disconnect("Bridge reply timed out; content cleared.");
            return false;
        }
        return true;
    };
    c.refresh = function(now) { return this.request("hands.snapshot", {}, now); };
    c.submit = function(dto, fixture, now) {
        if (this.pending) return null;
        if (!this.connected || ["normal", "company", "class"].indexOf(this.snapshot.posture) < 0) {
            this.notice = "private surface unavailable; nothing dispatched";
            return null;
        }
        if (dto.kind === "none") { this.notice = "no ask is selected"; return null; }
        if (dto.kind === "decision") {
            var ask = this.snapshot.ask;
            if (!ask || ask.state !== "pending" || dto.askId !== ask.id
                    || dto.planHash !== ask.planHash || ["yes", "no"].indexOf(dto.decision) < 0) {
                this.notice = "stale or unfocused ask; nothing dispatched";
                return null;
            }
            return this.request("hands.decision", {askId: ask.id, planHash: ask.planHash,
                decision: dto.decision}, now);
        }
        if (dto.kind === "intent") {
            return this.request("hands.intent", {text: dto.text, fixture: fixture}, now);
        }
        return null;
    };
    c.button = function(choice, now) {
        var ask = this.snapshot.ask;
        return this.submit(ask ? {kind: "decision", decision: choice, askId: ask.id,
            planHash: ask.planHash} : {kind: "none"}, "composite", now);
    };
    c.run = function(now) {
        if (this.snapshot.phase !== "ready" || !this.snapshot.planHash) return null;
        return this.request("hands.run", {planHash: this.snapshot.planHash}, now);
    };
    c.posture = function(posture, now) {
        var wire = this.request("hands.posture", {posture: posture}, now);
        // Clear display immediately for a requested locked/unknown mock posture.
        if (wire && ["normal", "company", "class"].indexOf(posture) < 0) {
            this.snapshot = disconnectedSnapshot();
        }
        return wire;
    };
    c.cancel = function(now) { return this.request("hands.cancel", {}, now); };
    return c;
}
