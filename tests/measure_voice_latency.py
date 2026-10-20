"""Manual harness: ack latency for the §18 budget (VOICE-BUGTEST.md).

Not collected by pytest (no `test_` prefix). Everything is mocked and every path
is a temp dir: `PYTHONPATH=src python tests/measure_voice_latency.py`.
"""
import json
import os
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

TMP = Path(tempfile.mkdtemp(prefix="vb-measure-")) / "run"
TMP.mkdir(parents=True)
BIN = TMP / "bin"
BIN.mkdir()
(BIN / "fake-play").write_text("#!/bin/sh\nexit 0\n")
(BIN / "fake-play").chmod(0o755)

from assistant.config import load_config
from assistant.store import Store
from assistant.tts import SpeechService


class EchoClient:
    mode = "live"

    def __init__(self, config):
        self.config = config
        self.pcm = struct.pack("<4800h", *([3000 if i % 2 else -3000 for i in range(4800)]))
        self.calls = []

    def can_speak(self):
        return True

    def voice_request(self, text, *, voice=None):
        g = self.config.section("gemini")
        return {"model": g.get("gemini_voice_model") or g.get("model_voice") or "gemini-3.8-live", "voice_name": str(voice or g["voice"] or "Flare"),
                "response_modalities": ["AUDIO"], "text": text}

    def generate_voice(self, text, *, voice=None, correlation_id="-"):
        self.calls.append(text)
        return {"pcm": self.pcm, "sample_rate": 24000,
                "voice_name": self.voice_request(text)["voice_name"], "usage": {}}


def mkcfg(player):
    config = load_config()
    config.raw["tts"] = {**config.raw["tts"], "backend": "mock", "voice_id": "elaria-vb",
                         "player": player, "cache_dir": str(TMP / "cache"),
                         "audition_dir": str(TMP / "auditions")}
    return config


def bench(fn, n=200):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        out = fn()
        xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    return {"median_ms": round(statistics.median(xs), 3),
            "p95_ms": round(xs[int(len(xs) * 0.95) - 1], 3),
            "max_ms": round(xs[-1], 3), "out": out}


print("=== A. in-process, Flare online, player exits immediately (real fork+exec) ===")
config = mkcfg(f"{BIN}/fake-play")
store = Store(TMP / "a.db")
client = EchoClient(config)
speech = SpeechService(config, store, client=client, is_online=lambda: True)

cold = bench(lambda: speech.play_ack("on_it"))
print("cold (nothing warmed)      :", json.dumps({k: v for k, v in cold.items() if k != 'out'}),
      "cache_miss =", cold["out"]["cache_miss"])
t0 = time.perf_counter()
warmed = speech.warm_ack_cache()
warm_ms = round((time.perf_counter() - t0) * 1000, 1)
print(f"warm-up of 4 acks          : {warm_ms} ms total, "
      f"{round(warm_ms / 4, 1)} ms/ack (off the hot path)")
warm = bench(lambda: speech.play_ack("on_it"))
print("warm                       :", json.dumps({k: v for k, v in warm.items() if k != 'out'}),
      "cached =", warm["out"]["cached"], "played =", warm["out"]["played"])

restarted = SpeechService(config, Store(TMP / "a.db"), client=EchoClient(config),
                          is_online=lambda: True)
print("after daemon restart       :", json.dumps({k: v for k, v in
      bench(lambda: restarted.play_ack("on_it")).items() if k != 'out'}))

config.raw["tts"] = {**config.section("tts"), "length_scale": 1.0}   # dormant-only change
print("after dormant length_scale :", json.dumps({k: v for k, v in
      bench(lambda: restarted.play_ack("on_it")).items() if k != 'out'}),
      "<- VB-2: cache_miss forever")
t0 = time.perf_counter()
restarted.warm_ack_cache()
print("re-warm cost (the fix)     :", round((time.perf_counter() - t0) * 1000, 1), "ms")

print("\n=== B. player=None (Waybar-only box: lookup cost alone) ===")
config2 = mkcfg("none")
s2 = SpeechService(config2, Store(TMP / "b.db"), client=EchoClient(config2),
                   is_online=lambda: True)
s2.warm_ack_cache()
print("warm lookup, no player     :", json.dumps({k: v for k, v in
      bench(lambda: s2.play_ack("done")).items() if k != 'out'}))

print("\n=== C. end-to-end over a real daemon socket (IPC + handler + play) ===")
home = TMP / "home"
(home / ".config" / "assistant").mkdir(parents=True)
(home / ".config" / "assistant" / "config.toml").write_text(
    "[tts]\n"
    f'player = "{BIN}/fake-play"\n'
    'backend = "mock"\nvoice_id = "elaria-vb"\n'
    'online_voice = "local"\noffline_voice = "local"\n'   # dormant route: only way to
    # produce audio with a mocked cloud; identity is not under test here
)
env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
       "XDG_DATA_HOME": str(TMP / "xdg-data"), "XDG_STATE_HOME": str(TMP / "xdg-state"),
       "XDG_RUNTIME_DIR": str(TMP / "xdg-run"), "PYTHONPATH": str(REPO / "src"),
       "GEMINI_MODE": "mock", "ASSIST_FIXTURES": str(TMP / "fixtures")}
for key in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
    Path(env[key]).mkdir(parents=True, exist_ok=True)
proc = subprocess.Popen([sys.executable, "-m", "assistant.daemon"], env=env,
                        cwd=str(REPO), stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True)
try:
    sock = Path(env["XDG_RUNTIME_DIR"]) / "assistant.sock"
    for _ in range(100):
        if sock.exists():
            break
        time.sleep(0.05)
    from assistant.ipc import call as ipc_call

    ipc_call(sock, "speech.warm", {}, timeout=15.0)
    xs = []
    for _ in range(120):
        t0 = time.perf_counter()
        out = ipc_call(sock, "ack", {"kind": "on_it"}, timeout=5.0)
        xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    print("ack over IPC, warm         :",
          f"median={statistics.median(xs):.2f}ms p95={xs[int(len(xs)*0.95)-1]:.2f}ms "
          f"max={xs[-1]:.2f}ms  budget=300ms")
    print("   handler reported        :", json.dumps(
        {k: out["speech"][k] for k in ("cached", "backend", "voice_id")}))
    os.remove(Path(env["XDG_DATA_HOME"]) / "assistant" / "voice-cache" / "__none__") \
        if False else None
    # cold-cache case: point the daemon at an empty cache dir via a fresh data dir
    print("   budget verdict           :",
          "PASS" if xs[int(len(xs) * 0.95) - 1] < 300 else "FAIL")
finally:
    proc.kill()
    proc.wait(timeout=5)

print("\n=== D. offline: what the hotkey path costs when nothing speaks ===")
s3 = SpeechService(mkcfg("none"), Store(TMP / "d.db"), client=EchoClient(config),
                  is_online=lambda: False)
print("offline play_ack           :", json.dumps({k: v for k, v in
      bench(lambda: s3.play_ack("checkin")).items() if k != 'out'}),
      "muted =", s3.play_ack("checkin")["muted"])
