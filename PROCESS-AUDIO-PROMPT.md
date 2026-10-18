# Prompt for the audio-processing chat

Copy everything in the block below into the other chat (the one with the audio files in git).

---

```
You are processing a corpus of MY OWN voice notes so I can build a voice
profile for a personal assistant I'm designing. Work locally, be rigorous,
and follow the privacy rules strictly.

INPUT
- The audio files in this repo (voice notes, mostly .opus) are recordings
  of ME speaking to a friend. Only process files where I am the speaker.
  If any file is someone else, music, or silence, list it as excluded and
  do not analyse it further.

PRIVACY RULES (non-negotiable)
- NEVER transcribe conversation content into your report. No quotes, no
  summaries of what I talked about, no names, no topics.
- Output ONLY aggregate measurements: durations, counts, acoustic statistics.
- Do not upload the audio anywhere. If a tool needs to be installed, tell
  me first instead of installing silently.
- The goal is a voiceprint + delivery profile. NOT voice cloning — do not
  attempt to synthesise my voice.

TASKS
1. INVENTORY: list every audio file with format, duration, sample rate.
   Report: file count, total duration, duration range, excluded files.
2. SPEECH vs SILENCE: for my files, measure speech ratio, pause count,
   average pause length, and longest pauses (e.g. ffmpeg silencedetect or
   librosa). Report aggregates, not per-file detail beyond a summary table.
3. DELIVERY PROFILE: estimate speaking pace (words/minute — you may
   transcribe LOCALLY only to count words; delete/discard transcripts,
   never show them to me or include them in any output), pitch (F0)
   median and range, energy/RMS profile, and how pace/pitch vary across
   files (my "variance").
4. VOICEPRINT: using a speaker-embedding model that runs locally
   (e.g. SpeechBrain ECAPA-TDNN via python), compute one embedding per
   usable file. Report: embedding model name/version, embedding dimension,
   mean pairwise cosine similarity between my files (consistency), and
   save the mean embedding (centroid) to voiceprint.json.
5. FALSE-TRIGGER CORPUS: report total hours of my natural speech available
   as a negative test set for wake-word detection (all files combined).

DELIVERABLES (create these files and also show them to me)
A. `voice_profile_report.md` — the aggregate numbers above, plus a short
   "confidence & limits" section (what was measurable, what wasn't, audio
   quality caveats).
B. `voiceprint.json` — { model, dimension, centroid: [ ...floats... ],
   mean_pairwise_cosine, file_count, total_speech_seconds }
C. A TOML block in EXACTLY this shape, filled with measured values
   (use "unknown" with a one-line reason where a value can't be measured):

[spoken_delivery]
status = "calibrated-from-voice-corpus"
corpus_files = <int>
corpus_speech_minutes = <float>
pace_wpm = <int or "unknown">
pace_variability = "<low|medium|high>"
pause_style = "<measured description, e.g. 'short frequent pauses, avg 0.4s'>"
pitch_median_hz = <int or "unknown">
pitch_range = "<e.g. 'wide — expressive' or 'narrow — flat'>"
energy_curve = "<e.g. 'rises into punchlines' or 'even'>"
speech_ratio_pct = <float>
voiceprint_model = "<model name>"
voiceprint_consistency = <float 0-1>
false_trigger_corpus_hours = <float>

END your reply with the TOML block in a single code fence, so I can copy it
cleanly. Start by confirming the file inventory before doing heavy work.
```

---

## What to bring back here

From that chat, copy back **either**:

- the final TOML block (smallest option — I paste it straight into `humour.toml`), and/or
- `voice_profile_report.md` and `voiceprint.json` as file attachments.

Then I'll merge the measured values into §13.10's design and the `[spoken_delivery]` section, and update the blueprint's activation thresholds from guesses to your actual numbers.
