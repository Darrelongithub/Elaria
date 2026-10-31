// Test instrument only, not shipped task execution. Uses the actual QML JS over AF_UNIX.
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const readline = require('readline');
const vm = require('vm');
const {once} = require('events');
const [ui, endpoint, mode, choice] = process.argv.slice(2);
vm.runInThisContext(fs.readFileSync(ui + '/harness.js', 'utf8'));
vm.runInThisContext(fs.readFileSync(ui + '/bridge.js', 'utf8'));
const c = createController('node-synthetic');
let socket, lines;
const methods = [];
async function send(frame) {
    assert(frame, c.notice);
    methods.push(JSON.parse(frame).method);
    const response = once(lines, 'line');
    socket.write(frame);
    const [line] = await response;
    assert(c.receive(line), line);
    return c.snapshot;
}
async function open() {
    socket = net.createConnection(endpoint);
    socket.setTimeout(5000, () => socket.destroy(new Error('test socket timed out')));
    lines = readline.createInterface({input: socket});
    await once(socket, 'connect');
    return send(c.connect(Date.now()));
}
async function main() {
    await open();
    assert.strictEqual(c.snapshot.posture, 'unknown');
    assert.strictEqual(c.snapshot.planHash, null);
    await send(c.posture('normal', Date.now()));
    assert.strictEqual(c.submit(routeInput(' YES ', null), 'composite', Date.now()), null);
    assert.strictEqual(c.notice, 'no ask is selected');
    await send(c.submit(routeInput('Arrange the synthetic fixture.', null),
        mode === 'trap' ? 'trap' : 'composite', Date.now()));
    assert.strictEqual(c.snapshot.phase, 'ready');
    assert.strictEqual(c.snapshot.plan.length, 2);
    assert.strictEqual(c.snapshot.metrics.runnerInvocations, 0);
    assert.strictEqual(c.snapshot.metrics.operationRows, 0);
    await send(c.request('hands.run', {planHash: '0'.repeat(64)}, Date.now()));
    assert.strictEqual(c.snapshot.phase, 'ready');
    assert.strictEqual(c.snapshot.metrics.operationRows, 0);
    await send(c.run(Date.now()));
    if (mode === 'trap') {
        assert.strictEqual(c.snapshot.phase, 'ended');
        assert(c.snapshot.lines.some(x => x.includes('suspected injection')));
        assert(c.snapshot.events.includes('hands.inject · inject'));
        assert.strictEqual(c.snapshot.metrics.runnerInvocations, 0);
        assert.strictEqual(c.snapshot.metrics.operationRows, 0);
    } else {
        assert.strictEqual(c.snapshot.phase, 'parked');
        assert.strictEqual(c.snapshot.metrics.operationRows, 1);
        assert.strictEqual(c.snapshot.metrics.runnerInvocations, 1);
        assert.strictEqual(notificationPreview(c.snapshot), 'elaria needs a yes');
        const ask = c.snapshot.ask;
        assert.strictEqual(ask.planHash, c.snapshot.planHash);
        assert.strictEqual(c.submit({...routeInput('yes', ask), planHash:'0'.repeat(64)},
            'composite', Date.now()), null);
        await send(c.request('hands.decision', {askId: ask.id, planHash:'0'.repeat(64),
            decision:'yes'}, Date.now()));
        assert.strictEqual(c.snapshot.ask.id, ask.id);
        assert.strictEqual(c.snapshot.metrics.operationRows, 1);
        await send(c.submit(routeInput('no thanks', ask), 'composite', Date.now()));
        assert.strictEqual(c.snapshot.ask.id, ask.id); // ordinary intent cannot replace a parked ask
        if (mode === 'postures') {
            for (const p of ['company', 'class', 'locked', 'unknown', 'unsupported', null, [], 'normal']) {
                await send(c.posture(p, Date.now()));
                const visible = ['normal', 'company', 'class'].includes(p);
                assert.strictEqual(privateCard(c.snapshot) !== null, visible);
                assert.strictEqual(c.snapshot.notification, p === 'normal' ? 'elaria needs a yes' : null);
                assert.strictEqual(c.snapshot.metrics.desktopNotifications, 0);
                if (!visible) {
                    assert.strictEqual(c.snapshot.planHash, null);
                    assert.deepStrictEqual(c.snapshot.plan, []);
                    assert.deepStrictEqual(c.snapshot.lines, []);
                    assert.deepStrictEqual(c.snapshot.events, []);
                    assert.strictEqual(c.button('yes', Date.now()), null);
                    await send(c.request('hands.decision', {askId:ask.id, planHash:ask.planHash,
                        decision:'yes'}, Date.now()));
                    assert.strictEqual(c.snapshot.metrics.operationRows, 1);
                }
            }
            assert.strictEqual(c.snapshot.ask.id, ask.id);
        }
        const frame = mode === 'typed'
            ? c.submit(routeInput(choice === 'yes' ? '  YEſ  ' : '  nO  ', c.snapshot.ask), 'composite', Date.now())
            : c.button(choice, Date.now());
        if (mode === 'lost-reply') {
            methods.push(JSON.parse(frame).method);
            const ended = once(socket, 'end');
            socket.write(frame);
            await ended; // server intentionally drops the acknowledgement AFTER applying
            c.disconnect('Disconnected');
            assert(c.notice.includes('outcome unknown'));
            assert.strictEqual(c.snapshot.ask, null);
            const before = methods.length;
            await open();
            assert.deepStrictEqual(methods.slice(before), ['hands.snapshot']);
        } else {
            await send(frame);
        }
        assert.strictEqual(c.snapshot.phase, choice === 'yes' ? 'complete' : 'ended');
        assert.strictEqual(c.snapshot.ask, null);
        assert.strictEqual(c.snapshot.metrics.operationRows, choice === 'yes' ? 2 : 1);
        assert.strictEqual(c.snapshot.metrics.runnerInvocations, choice === 'yes' ? 2 : 1);
        assert.strictEqual(c.button('yes', Date.now()), null);
        if (mode !== 'lost-reply') {
            socket.end();
            c.disconnect('Disconnected');
            const before = methods.length;
            await open();
            assert.deepStrictEqual(methods.slice(before), ['hands.snapshot']);
            assert.strictEqual(c.snapshot.metrics.operationRows, choice === 'yes' ? 2 : 1);
        }
    }
    assert.strictEqual(c.snapshot.metrics.desktopNotifications, 0);
    assert.strictEqual(c.snapshot.metrics.liveModelCalls, 0);
    assert.strictEqual(c.snapshot.metrics.taskProcessSpawns, 0);
    assert.strictEqual(c.snapshot.metrics.telemetryDropped, 0);
    socket.end();
    process.stdout.write(JSON.stringify({snapshot: c.snapshot, methods}));
}
main().catch(error => { console.error(error); if (socket) socket.destroy(); process.exitCode = 1; });
