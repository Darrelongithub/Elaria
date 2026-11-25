# ECAPA speaker model — PINNED, do not replace

file:      voxceleb_ECAPA512_LM.onnx
bytes:     24861931
sha256:    d71b85d9b48058ef68004f04f1b78acebefb9dfcf542e19b976a12a5ad1f10b0
repo:      Wespeaker/wespeaker-ecapa-tdnn512-LM
revision:  a2f3dcb1c8702caccc7a55ceb57f5e8d1842112b
license:   weights CC-BY-4.0 (Wespeaker); code Apache-2.0 (wenet-e2e/wespeaker)
attribution: WeSpeaker ECAPA-TDNN, VoxCeleb2, Desplanques et al.
contract:  opset 14, feats float32 [B,T,80] -> embs float32 [B,192]

## Evaluation Speech Samples (`ecapa_eval_samples.npz`)

file:      ecapa_eval_samples.npz
bytes:     511901
sha256:    f86ad1143acabde6d4b77a6d7b833c257606297a0345f9a7a363a699a60f7e0e
source:    speechbrain/speechbrain tests/samples/{ASR,single-mic} (16 kHz mono s16le)
license:   Apache-2.0 (SpeechBrain) / CC0 Public Domain (LibriSpeech)
contents:  spk1_snt1..5 (2.53-3.15s), spk2_snt1..2 (1.76-2.01s), diff_example1 (2.85s)

---

# openWakeWord feature models — PINNED (lane J)

Both files are the upstream artefacts from the **openWakeWord v0.5.1** PyPI
wheel (`openwakeword-0.5.1-py3-none-any.whl`, `openwakeword/resources/models/`).
They are the two feature stages of `wake_guard.OpenWakeWordModel`; the
`openwakeword` *package* is not installed and is not a dependency (its Linux
requires tflite-runtime, which has no CPython 3.14 build — see
`docs/hotword-training-plan.md`).

file:      melspectrogram.onnx
bytes:     1087958
sha256:    ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f
origin:    openWakeWord v0.5.1 (dscripka/openWakeWord), Apache-2.0 code
license:   models are CC-BY-NC-SA-4.0 per the upstream README
contract:  (`input`, float32 [batch, samples]) -> mel frames [time, 1, 1, 32];
           the runtime applies the upstream transform `x/10 + 2`

file:      embedding_model.onnx
bytes:     1326578
sha256:    70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f
origin:    openWakeWord v0.5.1 (Google speech_embedding TFHub module, re-implemented)
license:   models are CC-BY-NC-SA-4.0 per the upstream README
contract:  (`input_1`, float32 [B, 76, 32, 1]) -> embeddings [B, 1, 1, 96];
           windows are 76 mel frames at step 8

---

# "Elaria" wake head — TRAINED HERE (lane J-HEAD, 2026-11-25)

file:      elaria_head.onnx
bytes:     464181
sha256:    a6d295813f3018faa1ae88d808d1946505a72fe9a3ff4f2a0d9c15fbe4eeb1ff
contract:  input float32 **[1, 4, 96]** -> `score` float32 [1, 1] (sigmoid, 0..1)
arch:      Sub/Div (normalization folded in) -> Flatten -> Gemm 384x256 -> ReLU
           -> Gemm 256x64 -> ReLU -> Gemm 64x1 -> Sigmoid; opset 14, ir_version 8
frames:    4 embedding windows == `[hotword] keyword_window_s = 1.0` (the default)
runtime:   `wake_guard.OpenWakeWordModel` — arm with all three keys:
           `keyword_model`, `keyword_melspec_model`, `keyword_embedding_model`

## Training recipe (exactly reproducible)

```sh
# training environment only — NOT a daemon dependency, NOT in pyproject
python3 -m venv /tmp/trainenv
/tmp/trainenv/bin/pip install numpy onnx onnxruntime espeakng-loader

/tmp/trainenv/bin/python scripts/train_elaria_head.py --voices deterministic \
    --positives 1500 --negatives 2400 --epochs 60 --augment 0.08 \
    --hidden 256 --out models/elaria_head.onnx \
    --fixture tests/fixtures/j_elaria_head_holdout.npz \
    --report-json /tmp/j93_numbers.json
```

Run twice → **identical sha256** for both the head and the fixture (verified).
`--voices deterministic` is what makes that true: this espeak-ng build mixes a
random breath component into 174 of the 208 `accent+variant` voices, so only
**34 voices** synthesise byte-identically twice. Shipping the reproducible
recipe costs 5 of the 208 timbres' worth of diversity and gave a slightly
worse head (see below) — reproducibility won, because a recipe whose artefact
nobody can re-derive is a claim, not a recipe. `--voices all` (208 voices) is
the higher-diversity variant; it is not byte-reproducible.

* wall clock 68 s on 2 vCPU (sandbox);
* seed **93** for voice split, clip generation, weight init and augmentation;
* positives: the phrase spoken by the 34 byte-stable espeak-ng voices
  (`en`/`en-us`/`en-gb` × `!v` variants), text ∈ {"Elaria", "hey Elaria",
  "hi Elaria", "okay Elaria", "Elaria,"}, rate 105–205 wpm, pitch 20–80,
  amplitude 80–140, random ±2-semitone pitch/formant shift, 1–2 early
  reflections, peak −20…−3 dBFS, mixed into pink-noise room tone at SNR
  3/6/12/20 dB (and dry), 25% with a music bed;
* negatives: near-words (`malaria`, `area`, `Larry`, `hilary`, `scenario`,
  `Ilaria`, `Alaria`, `el area`, …), an `-aria` name list (Maria, Aria,
  Daria, Lucia, Victoria, …), near-word **sentences**, TV-style speech,
  free speech, multi-voice babble, a music bed, room tone — all through the
  same augmentation chain;
* split **by voice variant**, never by clip: 24 train / 3 val / 7 test
  voices. Val drives early stopping; the test split is scored once;
* head: 2×ReLU MLP (384→256→64→1), Adam (lr 3e-3, batch 128, L2 3e-4),
  BCE, ≤60 epochs, early stop 12 epochs after the best val balanced accuracy,
  embedding-space augmentation (0.08 jitter + 5% frame dropout);
* features: **the runtime's own** `OpenWakeWordModel.embedding_frames` — no
  second extractor exists, so the trainer cannot drift from the daemon.

## Raw numbers — SANDBOX, synthetic only, at the frozen threshold 0.5

Re-derive with the command above; both artefacts are byte-identical run to run.

`keyword_threshold` was **not** touched (still 0.5); nothing was tuned on the
test split.

| Measure | Value |
|---|---|
| held-out test set | 300 positives / 480 negatives, 7 unseen voices |
| **false-reject rate** (held-out positives) | **6.0 %** — misses the pre-committed ≥95 % recall bar |
| **false-accept rate** (held-out negatives) | **4.0 %** |
| test AUC | 0.9880 |
| val balanced accuracy (early-stop metric) | 0.9768 |
| positive score mean / 5th pct | 0.922 / 0.243 |
| negative score mean / 95th pct | 0.041 / 0.108 |
| exported-vs-numpy max abs delta (780 windows) | 3.6e-07, 0 verdict flips |
| `scripts/wake_bench.py --seconds 30` | frames/sec **51.0**, realtime_factor **1.53**, peak_rss_mb **103.5** |

False accepts by negative class (test): near-words **6.4 %**, babble 4.7 %,
free speech 0 %, TV 0 %, music 0 %, ambient 0 %.

**Honest limits — read these before believing the 3.5 %:**

1. Every clip is espeak-ng synthesis. **No real human recording exists in
   this environment**, so this is *not* a Stage-A hardware number. The
   pre-committed bars in `docs/hotword-training-plan.md` (TV soak FA/h,
   recall by distance, near-word ≤5 %) must be measured on the owner's
   ~120 real takes. Two of them already fail on synthetic audio:
   recall is 94.0 % (bar 95 %) and near-words are 6.4 % (bar ≤5 %).
   The 208-voice, non-reproducible variant of this recipe scored better
   (2.0 % FRR / 3.5 % FAR, near 5.3 %); it was traded away for
   reproducibility, and the loss is recorded here rather than hidden.
2. The residual false accepts are dominated by true homophones of "Elaria"
   (`Ilaria`, `Alaria`, `el area`) on **unseen** voices, and the residual
   false rejects are the same phrase delivered by an unseen voice at only
   34 training timbres. The openWakeWord
   paper's answer is the one thing this sandbox cannot do: real positive and
   hard-negative audio. The fix is more real positives, never a higher
   `keyword_threshold` (raising it to 0.9 would make recall worse on real
   audio and is forbidden).
3. A wake hit still grants **nothing**: ECAPA-TDNN verifies the command
   window (`MIN_WINDOW_S` 1.75 s, `ecapa_high` 0.75) exactly as before.
