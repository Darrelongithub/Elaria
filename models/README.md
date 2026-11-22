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

