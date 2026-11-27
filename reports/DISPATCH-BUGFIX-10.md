# DISPATCH-BUGFIX-10 — FIX-HW9: bind her mouth to her words (2026-11-27)

Owner proof (`bugs.md` BUG-HW9): the stored reply and the
played audio are different sentences. Speech synthesis sends
the reply as a conversational user turn into a Gemini Live
AUDIO session; the Live model answers it instead of reading
it. Every spoken reply online is therefore an unrecorded
improvisation. Transcripts in, stored text — both sane. The
mouth is the bug.

## FIX-HW9 — Agent V (voice lane, after FIX-HW8)

> You are Agent V. Fix BUG-HW9. The invariant, however you
> achieve it: **audio that reaches the speaker is verifiably
> the stored reply text, or it is not played.**
>
> 1. **Capture what the render actually said.** The Live
>    transport already requests `output_audio_transcription`;
>    return that transcription with the PCM from
>    `generate_audio` instead of discarding it.
> 2. **Verify before playback.** Speech service compares the
>    render's transcription with the source reply (normalised:
>    case/punctuation-insensitive word sequence; a stated,
>    tested similarity bar — verbatim modulo punctuation is
>    the expectation). Match → play + cache as today. Mismatch
>    → do NOT play it, do NOT cache it as that text's render;
>    journal `speech.mismatch` (source + heard text — her own
>    words, safe to log), and degrade to the existing F33
>    labelled-text outcome ("voice unavailable — reply is
>    shown as text"). No second cloud voice as a fallback
>    (standing amendment); silence-with-a-reason beats a
>    confident wrong voice.
> 3. **Streaming may not bypass the gate.** M-4 chunk streaming
>    currently plays slices while synthesis continues. For
>    reply speech, unverified audio never reaches the ear:
>    buffer the render, verify, then play (or verify
>    incrementally only if the design proves no unverified
>    slice can be audible). State the latency cost honestly.
> 4. **Reduce the divergence at the source too.** Give the
>    Live session a system instruction to read the provided
>    text aloud exactly, word for word, with no response, no
>    additions — but treat this as defence-in-depth only. The
>    acceptance test is the transcription gate (2), because a
>    prompt is a request, not a proof.
> 5. **Cache honesty.** The voice cache is keyed by text; a
>    cached file whose audio was never verified must not be
>    replayed as that text. Verified-only renders enter the
>    cache; pre-fix cache entries are not trusted (note the
>    one-time invalidation in the report — owner clears
>    `voice-cache/` once, guided).
>
> Tests: fake transport returning a divergent transcription
> ("I definitely haven't changed it…" for the Darrel line) →
> nothing played, nothing cached, `speech.mismatch`
> journalled, labelled-text result; faithful transcription →
> played + cached; punctuation-only differences pass;
> streaming path cannot emit audio before the gate. Existing
> tts/voice suites green. Sync `origin/main` first (land after
> FIX-HW8 if both are in flight — same lane, sequential). New
> `arena/*` branch, merged PR or it didn't happen. Never edit
> OWNERS.yaml.
>
> Owner retest: ask "what is my name?" by voice — the spoken
> words must be the stored sentence, word for word. Then the
> fox sentence by voice. If a mismatch is refused to text
> instead, that is the fix working, and the journal line names
> what the voice tried to say instead.
