"""F29 console is not a second mouth. All runtime fixtures are synthetic."""
import shutil
import subprocess
from pathlib import Path

import pytest
from test_console_wire_bridge import ANSWER, FakeRPC, hello, read_until, running, send, wire
from test_console_wire_bridge import bridge_module as bridge

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('audio', ['https://invalid.example/not-fetched.wav', {'pcm': 'synthetic'}])
async def test_reply_audio_is_dropped_by_bridge(audio):
    rpc = FakeRPC(result={**ANSWER, 'audio': audio})
    async with running(rpc) as instance, wire(instance) as ws:
        await hello(ws)
        await read_until(ws, 'hello-ok')
        await send(ws)
        reply, _ = await read_until(ws, 'reply')
        assert reply['text'] == ANSWER['reply'] and 'audio' not in reply
        assert rpc.says[0][1]['speak'] is False and rpc.says[0][1]['history_limit'] == 1


def test_f29_renderer_audio_drop_and_levels_only_speaking():
    if not shutil.which('node') or not (ROOT / 'console/node_modules/jsdom').exists():
        pytest.skip('local-only DOM gate needs console jsdom dependency')
    result = subprocess.run(['node', 'console/audio-owner-test.js'], cwd=ROOT,
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_f29_no_client_playback_path_and_engine_unchanged():
    import hashlib

    source = (ROOT / 'console/src/shell.js').read_text()
    assert 'F29: daemon gateway is sole playback owner' in source
    assert 'new Audio(' not in source and '.play(' not in source and 'V.attachElement(' not in source
    assert 'rep.audio' not in source and 'audio: m.audio' not in source
    assert hashlib.sha256((ROOT / 'console/elaria-visualizer.js').read_bytes()).hexdigest() == bridge.ENGINE_SHA
