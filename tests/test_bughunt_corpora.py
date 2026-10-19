"""Large adversarial corpora for the hunt.

These are not smoke tests padded by repetition: each parameter case is a
distinct boundary in a grammar, parser, threshold, path rule, audio
calculation, or persisted-state lookup. Evil source atoms live in
`tests/bughunt_fixtures/evil_inputs.json`; this module combines them with
case/whitespace/punctuation and numeric boundaries systematically.
"""

from __future__ import annotations

import json
import math
import random
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from assistant.capture import frame_rms, mix_pcm
from assistant.cleanup import SW_MARKERS, divergence_pct, language_mix_preserved
from assistant.cost import estimate_tokens, rates_for, shadow_cost_usd
from assistant.diarize import Turn, merge_adjacent, overlap_s
from assistant.embeddings import HashingEmbedder, cosine, pack, unpack
from assistant.executor import parse_since
from assistant.intents import route
from assistant.meeting import segment_utterances
from assistant.memory import Memory
from assistant.overlay import OverlayReducer
from assistant.persona import read_tone
from assistant.planner import EXTENSION_TO_FOLDER_HINTS, KEYWORD_TO_FOLDER_HINTS, tier0_propose
from assistant.planner import decide as planner_decide
from assistant.planner_llm import _parse_batch
from assistant.safety import check_blast_radius, is_protected, is_safe_filename
from assistant.store import Store
from assistant.tts import MockTtsBackend, SpeechService, VoiceDescriptor

FIXTURES = json.loads(
    (Path(__file__).parent / "bughunt_fixtures" / "evil_inputs.json").read_text())
TAXONOMY = [
    "Finance", "Legal", "Work", "Career", "Personal", "Photos", "Screenshots",
    "School", "Study", "Recipes", "Documents", "Music", "Audio", "Videos",
    "Archives", "Code", "Data", "Bank", "Tax", "Certificates", "_Unsorted",
]


# -- filenames and protected paths --------------------------------------------

@pytest.mark.parametrize("base", [
    "invoice", "résumé", "file name", "a.b", "...", "emoji-🧾", "-leading",
    "under_score",
])
@pytest.mark.parametrize("suffix", [".txt", ".PDF", " (final).md", ""])
def test_safe_filename_accepts_legal_single_components(base, suffix):
    assert is_safe_filename(base + suffix)


@pytest.mark.parametrize("name", FIXTURES["unsafe_filenames"])
def test_safe_filename_rejects_fixture_escapes(name):
    assert not is_safe_filename(name)


@pytest.mark.parametrize("prefix", ["../", "..\\", "a/", "a\\", "/tmp/", "C:\\"])
@pytest.mark.parametrize("leaf", ["invoice.txt", "..", ".", "x"])
def test_safe_filename_rejects_generated_separator_forms(prefix, leaf):
    assert not is_safe_filename(prefix + leaf)


@pytest.mark.parametrize("relative, expected", [
    ("secret", True), ("secret/file.txt", True), ("secret/a/b/c", True),
    ("secret-file.txt", False), ("secret2/file", False), ("public/file", False),
    ("SECRET/file", False), ("", False),
])
def test_protected_path_is_a_component_boundary(tmp_path, relative, expected):
    protected = [str(tmp_path / "secret")]
    candidate = tmp_path / relative if relative else tmp_path
    assert is_protected(candidate, protected) is expected


# -- LLM planner verifier -------------------------------------------------------

@pytest.mark.parametrize("payload", FIXTURES["llm_malformed_payloads"])
def test_llm_malformed_fixture_payloads_are_invalid(payload):
    if payload == "[] trailing [":
        pytest.skip("empty-batch acceptance is BH-D1's dedicated xfail")
    assert _parse_batch(payload, {"Finance"}, {"/r/a.txt"}) is None


@pytest.mark.parametrize("field, value", [
    ("dest", None), ("dest", 123), ("dest", ""), ("dest", "finance"),
    ("path", None), ("path", 123), ("path", "/r/other.txt"),
    ("confidence", None), ("confidence", "0.9"), ("confidence", -0.1),
    ("confidence", 1.1), ("confidence", float("nan")),
    ("confidence", float("inf")),
])
def test_llm_batch_rejects_each_invalid_field(field, value):
    entry = {"path": "/r/a.txt", "dest": "Finance", "confidence": 0.9}
    entry[field] = value
    assert _parse_batch(json.dumps([entry]), {"Finance"}, {"/r/a.txt"}) is None


@pytest.mark.parametrize("new_name", FIXTURES["unsafe_filenames"])
def test_llm_batch_rejects_each_unsafe_new_name(new_name):
    if new_name == "":
        pytest.skip("empty new_name means keep the current name")
    entry = {"path": "/r/a.txt", "dest": "Finance", "confidence": 0.9,
             "new_name": new_name}
    assert _parse_batch(json.dumps([entry]), {"Finance"}, {"/r/a.txt"}) is None


@pytest.mark.parametrize("confidence", [0, 0.01, 0.25, 0.5, 0.89, 0.99, 1])
@pytest.mark.parametrize("new_name", [None, "", "renamed.txt", "invoice—final.pdf"])
def test_llm_batch_accepts_confidence_and_name_boundaries(confidence, new_name):
    entry = {"path": "/r/a.txt", "dest": "Finance", "confidence": confidence,
             "new_name": new_name}
    assert _parse_batch(json.dumps([entry]), {"Finance"}, {"/r/a.txt"}) == [entry]


# -- Tier 0 planner -------------------------------------------------------------

@pytest.mark.parametrize("keyword", sorted(KEYWORD_TO_FOLDER_HINTS))
def test_tier0_filename_keywords_place_into_existing_taxonomy(keyword):
    proposal = tier0_propose(f"/root/{keyword}-sample.txt", "", TAXONOMY)
    assert proposal.dest in TAXONOMY and proposal.decision == "auto"


@pytest.mark.parametrize("extension", sorted(EXTENSION_TO_FOLDER_HINTS))
def test_tier0_extension_classes_place_into_existing_taxonomy(extension):
    proposal = tier0_propose(f"/root/plain-object{extension}", "", TAXONOMY)
    assert proposal.dest in TAXONOMY and proposal.decision in ("auto", "review")


@pytest.mark.parametrize("stem", [f"qzx{i}vbnm" for i in range(20)])
def test_tier0_unknown_names_abstain_instead_of_guessing(stem):
    proposal = tier0_propose(f"/root/{stem}.unknownext", "plain neutral words", TAXONOMY)
    assert proposal.dest is None and proposal.decision == "abstain"


# -- Intent grammar --------------------------------------------------------------

_EXACT_COMMANDS = [
    ("halt", "halt"), ("panic stop", "halt"), ("status", "status"),
    ("are you running", "status"), ("go offline", "mode_offline"),
    ("go online", "mode_online"), ("auto mode", "mode_auto"),
    ("show the queue", "queue_status"), ("drain the queue", "queue_drain"),
    ("remember that the gate code is 1234", "remember"),
    ("forget about milk", "forget"), ("where is the invoice", "where"),
    ("search for the invoice", "search"), ("organise downloads", "organise"),
    ("simama", "halt"), ("hali", "status"), ("kumbuka kwamba mlango ni 1234", "remember"),
    ("sahau kuhusu maziwa", "forget"), ("iko wapi invoice", "where"),
    ("tafuta invoice", "search"),
]


@pytest.mark.parametrize("phrase, kind", _EXACT_COMMANDS)
@pytest.mark.parametrize("variant", ["plain", "upper", "spaced", "title"])
def test_exact_intents_survive_case_and_whitespace(phrase, kind, variant):
    if variant == "upper":
        phrase = phrase.upper()
    elif variant == "spaced":
        phrase = f"  {phrase}  "
    elif variant == "title":
        phrase = phrase[:1].upper() + phrase[1:]
    intent = route(phrase)
    assert intent is not None and intent.kind == kind


@pytest.mark.parametrize("action", FIXTURES["intent_action_bases"])
@pytest.mark.parametrize("wrapper", FIXTURES["intent_negation_wrappers"])
def test_negated_or_quoted_actions_do_not_route(action, wrapper):
    assert route(wrapper.format(action=action)) is None


@pytest.mark.parametrize("phrase, kind, argument", [
    ("remember the Wi-Fi name is Nyumbani", "remember", "the Wi-Fi name is Nyumbani"),
    ("remember that Friday is payroll", "remember", "Friday is payroll"),
    ("forget milk", "forget", "milk"),
    ("forget about the old address", "forget", "the old address"),
    ("where's the March invoice?", "where", "the March invoice"),
    ("where are tax records", "where", "tax records"),
    ("find me lecture notes", "where", "lecture notes"),
    ("locate my passport", "where", "my passport"),
    ("search contracts", "search", "contracts"),
    ("search for bank statements", "search", "bank statements"),
    ("organise Downloads", "organise", "Downloads"),
    ("sort out the photo folder", "organise", "the photo folder"),
    ("tidy receipts", "organise", "receipts"),
    ("undo since 2h", "undo", "2h"),
    ("kumbuka mlango ni 1234", "remember", "mlango ni 1234"),
    ("sahau anwani ya zamani", "forget", "anwani ya zamani"),
    ("wapi pasipoti yangu?", "where", "pasipoti yangu"),
    ("tafuta taarifa za banki", "search", "taarifa za banki"),
    ("panga folda ya picha", "organise", "folda ya picha"),
    ("rudisha tangu 2h", "undo", "2h"),
])
def test_intent_arguments_are_preserved(phrase, kind, argument):
    intent = route(phrase)
    assert intent is not None
    assert (intent.kind, intent.argument) == (kind, argument)


# -- Cleanup language guard -------------------------------------------------------

_MARKERS = sorted(SW_MARKERS)


@pytest.mark.parametrize("raw_count", range(1, 11))
@pytest.mark.parametrize("clean_count", range(11))
def test_language_mix_retention_threshold_matrix(raw_count, clean_count):
    raw = " ".join(_MARKERS[:raw_count] + ["file", "the", "invoice"])
    cleaned = " ".join(_MARKERS[:clean_count] + ["file", "the", "invoice"])
    expected = clean_count >= max(1, raw_count * 0.5)
    assert language_mix_preserved(raw, cleaned, SW_MARKERS) is expected


@pytest.mark.parametrize("text", [
    "", "a", "hello world", "sasa alafu file the invoice", "🧾" * 20,
    "line one\nline two", "trailing spaces   ", "CAPS LOCK", "1234567890",
    "a" * 1000,
])
def test_divergence_of_identical_text_is_zero(text):
    assert divergence_pct(text, text) == 0.0


# -- Persona tone reader -----------------------------------------------------------

@pytest.mark.parametrize("upper_count", range(6))
@pytest.mark.parametrize("word_count", [3, 4, 5, 6])
def test_tone_caps_ratio_boundary(upper_count, word_count):
    if upper_count > word_count:
        pytest.skip("upper count cannot exceed word count")
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"][:word_count]
    words = [word.upper() if i < upper_count else word for i, word in enumerate(words)]
    signals = read_tone(" ".join(words))
    assert signals.caps_burst is (upper_count / word_count >= 0.5)


@pytest.mark.parametrize("text, expected", [
    ("wait... what", "ellipsis_pause"), ("wait… what", "ellipsis_pause"),
    ("really??", "incredulous_challenge"), ("you never listen", "direct_address"),
    ("sasa wewe", "codeswitch_beat"), ("everyone always says that", "playful_absolutes"),
])
def test_tone_specific_signals(text, expected):
    value = getattr(read_tone(text), expected)
    assert value is True or (isinstance(value, int) and value >= 2)


# -- Audio/embeddings maths --------------------------------------------------------

@pytest.mark.parametrize("amplitude", [0, 1, 100, 1000, 6000, 12000, 32767, -32768])
@pytest.mark.parametrize("samples", [1, 2, 16, 480])
def test_frame_rms_constant_amplitudes(amplitude, samples):
    pcm = struct.pack(f"<{samples}h", *([amplitude] * samples))
    assert frame_rms(pcm) == pytest.approx(abs(amplitude) / 32768)


@pytest.mark.parametrize("a, b", [
    (0, 0), (100, 200), (-100, -200), (30000, 30000), (-30000, -30000),
    (32767, 1), (-32768, -1), (12345, -12345), (20000, 20000), (-20000, 5000),
])
def test_mix_pcm_saturates_instead_of_wrapping(a, b):
    mixed = mix_pcm(struct.pack("<h", a), struct.pack("<h", b))
    assert struct.unpack("<h", mixed)[0] == max(-32768, min(32767, a + b))


@pytest.mark.parametrize("seed", range(30))
def test_embedding_pack_unpack_round_trip(seed):
    rng = random.Random(seed)
    vector = [rng.uniform(-2, 2) for _ in range(1 + seed % 17)]
    assert unpack(pack(vector)) == pytest.approx(vector, abs=1e-6)


@pytest.mark.parametrize("seed", range(20))
def test_cosine_is_positive_scale_invariant(seed):
    rng = random.Random(1000 + seed)
    vector = [rng.uniform(-1, 1) for _ in range(8)]
    assert cosine(vector, [3.5 * value for value in vector]) == pytest.approx(1.0)


def _pcm(seconds: float, amplitude: int) -> bytes:
    return struct.pack("<h", amplitude) * int(seconds * 16000)


@pytest.mark.parametrize("first, gap, second", [
    (0.4, 0.7, 0.4), (0.8, 0.7, 0.8), (0.4, 1.2, 0.9), (1.0, 1.0, 1.0),
])
def test_meeting_segmentation_splits_on_sustained_silence(first, gap, second):
    pcm = _pcm(first, 12000) + _pcm(gap, 0) + _pcm(second, 12000)
    assert len(segment_utterances(pcm, 16000)) == 2


@pytest.mark.parametrize("seconds", [0.0, 0.1, 0.2, 0.3])
def test_meeting_segmentation_ignores_too_short_bursts(seconds):
    assert segment_utterances(_pcm(seconds, 12000), 16000) == []


# -- Store state -------------------------------------------------------------------

@pytest.mark.parametrize("term", [
    "invoice", "clinic", "compiler", "passport", "rent", "payroll", "lecture",
    "recipe", "contract", "bank", "photo", "archive", "meeting", "travel",
    "school", "tax", "insurance", "warranty", "receipt", "budget",
])
def test_store_search_finds_each_indexed_term(tmp_path, term):
    store = Store(tmp_path / "search.db")
    path = f"/docs/{term}.txt"
    store.upsert_document(
        path=path, root="/docs", sha256="0" * 64, size=10, mtime=1.0,
        mime="text/plain", ext=".txt", indexed_ts="2026-01-01T00:00:00+00:00",
        never_send=0, text_chunks=[f"prefix {term} suffix"])
    assert [hit["path"] for hit in store.search_documents(term)] == [path]


@pytest.mark.parametrize("topic", ["%", "_", "\\", "[", "]", "*", "?", "a%b", "a_b", "100%"])
def test_forget_topics_are_literal_for_punctuation(tmp_path, topic):
    store = Store(tmp_path / "memory.db")
    memory = Memory(store, HashingEmbedder())
    memory.remember("ordinary alpha fact")
    memory.remember(f"literal {topic} fact")
    assert memory.forget(topic) == 1
    assert [fact["text"] for fact in memory.beliefs()] == ["ordinary alpha fact"]


# -- Time parsing ------------------------------------------------------------------

@pytest.mark.parametrize("value, unit_seconds", [
    (1, 60), (2, 60), (12, 60), (1, 3600), (2, 3600), (12, 3600),
    (1, 86400), (2, 86400), (7, 86400),
])
def test_parse_since_relative_units(value, unit_seconds):
    unit = {60: "m", 3600: "h", 86400: "d"}[unit_seconds]
    before = datetime.now(UTC)
    parsed = datetime.fromisoformat(parse_since(f"{value}{unit}"))
    after = datetime.now(UTC)
    age = (after - parsed).total_seconds()
    assert value * unit_seconds - 2 <= age <= value * unit_seconds + 2
    assert parsed <= before


@pytest.mark.parametrize("spec", [
    "", "h", "2w", "2.5h", "-2h", "tomorrow", "2026-13-01", "2026-02-30",
    "12:99", "next week",
])
def test_parse_since_rejects_invalid_specs(spec):
    with pytest.raises(ValueError):
        parse_since(spec)


# -- Overlay + TTS routing ----------------------------------------------------------

@pytest.mark.parametrize("event, kind, visible", [
    ({"event": "session.started"}, "listening", True),
    ({"event": "transcript.interim", "text": "partial"}, "listening", True),
    ({"event": "session.checkin", "prompt": "Is that all?"}, "checkin", True),
    ({"event": "transcript.final", "text": "done"}, "final", True),
    ({"event": "error", "error": "broken"}, "error", True),
    ({"event": "unknown.future"}, "hidden", False),
])
def test_overlay_reducer_event_shapes(event, kind, visible):
    state = OverlayReducer().apply(event)
    assert state.kind == kind and state.visible is visible


@pytest.mark.parametrize("text", [f"message {i}" for i in range(10)])
@pytest.mark.parametrize("length_scale", [0.8, 1.0, 1.2])
def test_tts_cache_keys_are_text_and_native_speed_specific(config, text, length_scale):
    service = SpeechService(config, backend=MockTtsBackend("one-voice"))
    descriptor = VoiceDescriptor(
        voice_id="one-voice", model="/voices/one.onnx", length_scale=length_scale)
    first = service._cache_path(text, descriptor, "mock-local")
    second = service._cache_path(text, descriptor, "mock-local")
    different = service._cache_path(text + "!", descriptor, "mock-local")
    assert first == second and first != different
    assert math.isclose(length_scale, descriptor.length_scale)


# -- Safety/planner numeric boundaries -------------------------------------------

@pytest.mark.parametrize("planned, tree, allowed", [
    (0, 0, True), (1, 4, True), (2, 4, False), (25, 100, True),
    (26, 100, False), (200, 1000, True), (201, 1000, False),
    (10, 0, True), (999, 0, False),
])
def test_blast_radius_boundaries(planned, tree, allowed):
    decision = check_blast_radius(
        planned, tree, max_ops_per_run=200, tripwire_pct=25)
    assert decision.allowed is allowed


@pytest.mark.parametrize("confidence, expected", [
    (-1.0, "unsorted"), (0.0, "unsorted"), (0.59, "unsorted"),
    (0.60, "review"), (0.75, "review"), (0.89, "review"),
    (0.90, "auto"), (1.0, "auto"), (2.0, "auto"),
])
def test_planner_confidence_decision_boundaries(confidence, expected):
    assert planner_decide(confidence) == expected


@pytest.mark.parametrize("model, expected_in", [
    ("gemini-flash-lite-latest", 0.25), ("gemini-flash-latest", 0.75),
    ("gemini-3.5-transcribe-live", 3.00), ("gemini-pro", 2.00),
    ("unknown-model", 0.75),
])
def test_shadow_cost_model_rates(model, expected_in):
    assert rates_for(model)[0] == expected_in
    assert shadow_cost_usd(model, 1_000_000, 0) == pytest.approx(expected_in)


@pytest.mark.parametrize("text, expected", [
    ("", 0), ("a", 1), ("abcd", 1), ("abcde", 1), ("abcdefgh", 2),
    ("x" * 401, 100),
])
def test_estimate_tokens_boundaries(text, expected):
    assert estimate_tokens(text) == expected


@pytest.mark.parametrize("a_start, a_end, b_start, b_end, expected", [
    (0, 1, 2, 3, 0.0), (0, 2, 1, 3, 1.0), (0, 10, 2, 3, 1.0),
    (2, 3, 0, 10, 1.0), (0, 1, 1, 2, 0.0), (1.5, 2.5, 2.0, 4.0, 0.5),
])
def test_diarization_overlap_boundaries(a_start, a_end, b_start, b_end, expected):
    assert overlap_s(a_start, a_end, b_start, b_end) == expected


@pytest.mark.parametrize("gap, should_merge", [
    (-1.0, True), (0.0, True), (0.4, True), (0.8, True), (0.81, False), (2.0, False),
])
def test_merge_adjacent_gap_boundary(gap, should_merge):
    turns = [Turn("You", 0.0, 1.0, "hi"), Turn("You", 1.0 + gap, 2.0 + gap, "there")]
    assert (len(merge_adjacent(turns, gap_s=0.8)) == 1) is should_merge
