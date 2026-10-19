"""Phase 5 (§16/§3.8/§13.4): memory, hybrid recall, ladder-climbing ask.

Done-when under test: "where's that invoice from March" answered
LOCALLY (asserted: zero llm_calls), open questions escalate with
assembled context, and memory obeys §16 (stated>inferred+evidence,
inspectable, forgettable)."""

from pathlib import Path

import pytest

from assistant.embeddings import HashingEmbedder, backfill_embeddings, cosine, pack, unpack
from assistant.intents import route
from assistant.memory import Memory
from assistant.organiser import OrganiserService
from assistant.store import Store

TAXONOMY = ["Finance", "Work", "_Unsorted", "_Conflicts"]


def make_memory(tmp_path):
    store = Store(tmp_path / "t.db")
    return Memory(store, HashingEmbedder()), store


def test_hashing_embedder_deterministic_and_normalised():
    emb = HashingEmbedder()
    first, second = emb.embed(["invoice from kamau"]), emb.embed(["invoice from kamau"])
    assert first == second
    assert cosine(first[0], first[0]) == pytest.approx(1.0, abs=1e-5)
    assert cosine(first[0], emb.embed(["sourdough bread recipe"])[0]) < 0.9
    assert unpack(pack(first[0])) == pytest.approx(first[0], abs=1e-6)


def test_stated_facts_inspectable_and_forgettable(tmp_path):
    memory, _store = make_memory(tmp_path)
    memory.remember("Invoices are filed by issuer, not by month", kind="preference")
    memory.remember("My accountant is Wanjiru")
    beliefs = memory.beliefs()
    assert len(beliefs) == 2 and all(b["source"] == "stated" for b in beliefs)
    assert memory.forget("Wanjiru") == 1
    assert [b["text"] for b in memory.beliefs()] == [
        "Invoices are filed by issuer, not by month"]
    assert memory.forget(f"#{beliefs[0]['id']}") == 1
    assert memory.beliefs() == []


def test_inferred_facts_must_show_evidence(tmp_path):
    memory, _store = make_memory(tmp_path)
    with pytest.raises(ValueError, match="evidence"):
        memory.remember("probably likes tea", source="inferred", confidence=0.4)
    fact_id = memory.remember("files invoices by issuer", source="inferred",
                              confidence=0.7,
                              evidence="filed that way 11 times in the index")
    fact = memory.beliefs()[0]
    assert fact["id"] == fact_id and fact["confidence"] == 0.7


def indexed_corpus(config, tmp_path):
    root = tmp_path / "docs"
    root.mkdir(parents=True)
    (root / "invoice-kamau-march-2026.txt").write_text(
        "Invoice 1042 Kamau Ltd March services total KES 45000")
    (root / "invoice-kamau-june-2026.txt").write_text(
        "Invoice 1099 Kamau Ltd June services")
    (root / "bread-recipe.txt").write_text("sourdough starter flour water salt bake")
    config.raw["organise"] = {**config.raw["organise"], "roots": [
        {"path": str(root), "mode": "shadow", "taxonomy": TAXONOMY}]}
    store = Store(tmp_path / "t.db")
    OrganiserService(config, store).index_roots()  # embeds on index by default
    return Memory(store, HashingEmbedder()), store, root


def test_where_question_answers_locally(config, tmp_path):
    memory, _store, _root = indexed_corpus(config, tmp_path)
    answer = memory.answer_where("invoice kamau march")
    assert answer and "invoice-kamau-march-2026" in answer.splitlines()[1]
    assert memory.answer_where("quantum chromodynamics textbook") is None  # no bluffing


def test_hybrid_recall_ranks_filename_and_content(config, tmp_path):
    memory, _store, _root = indexed_corpus(config, tmp_path)
    hits = memory.recall("kamau invoice")
    paths = [Path(h.ref).name for h in hits if h.source == "document"]
    assert paths and paths[0].startswith("invoice-kamau")


def test_backfill_embeds_all_chunks(tmp_path):
    store = Store(tmp_path / "t.db")
    doc_id = store.upsert_document(
        path="/x/a.txt", root="/x", sha256="s", size=3, mtime=1.0, mime=None,
        ext=".txt", indexed_ts="t", never_send=0, text_chunks=["hello world"])
    assert doc_id and backfill_embeddings(store, HashingEmbedder()) == 1
    assert store.embedded_chunks()


# -- intents: narrow on purpose ------------------------------------------------------
@pytest.mark.parametrize("text,kind", [
    ("status", "status"), ("halt", "halt"), ("cost", "cost"),
    ("where's that invoice from March", "where"),
    ("find the contract", "where"), ("search for payslips", "search"),
    ("remember that I file by issuer", "remember"),
    ("forget about the boat", "forget"), ("undo since 2h", "undo"),
    ("organise downloads", "organise"), ("sort out Documents", "organise"),
])
def test_intent_ladder_matches(text, kind):
    intent = route(text)
    assert intent is not None and intent.kind == kind


@pytest.mark.parametrize("text", [
    "what do you think about my filing system, honestly?",
    "write me a poem about invoices",
    "should I quit my job and farm",
    "statuses of the realm in medieval poetry",
])
def test_open_ended_goes_to_the_model(text):
    assert route(text) is None  # narrow: ambiguity climbs the ladder (§13.4)


def test_remember_intent_carries_the_fact():
    intent = route("remember that Wanjiru handles my taxes")
    assert intent.argument == "Wanjiru handles my taxes"


# -- daemon ask: local vs model, ledgered honesty ---------------------------------------
def test_ask_where_makes_zero_model_calls(config, tmp_path, running_daemon):
    from assistant.ipc import call

    daemon, _server = running_daemon
    # index the corpus into the DAEMON's store
    root = tmp_path / "docs2"
    root.mkdir(parents=True)
    (root / "invoice-kamau-march.txt").write_text("Invoice Kamau March KES 45000")
    daemon.config.raw["organise"] = {**daemon.config.raw["organise"], "roots": [
        {"path": str(root), "mode": "shadow", "taxonomy": TAXONOMY}]}
    call(config.socket_path, "index.run", timeout=60.0)
    before = daemon.store.llm_summary()["calls"]
    reply = call(config.socket_path, "ask", {"text": "where's that invoice from March?"},
                 timeout=30.0)
    assert reply["via"] == "local-memory"
    assert "invoice-kamau-march" in reply["reply"]
    assert daemon.store.llm_summary()["calls"] == before  # ZERO tokens spent
    # and the exchange itself became memory
    messages = daemon.store.recent_messages(4)
    assert any(m["role"] == "user" for m in messages)
    assert any(m["via"] == "local-memory" for m in messages)


def test_ask_remember_and_open_chat_paths(config, running_daemon):
    from assistant.ipc import call

    daemon, _server = running_daemon
    reply = call(config.socket_path, "ask",
                 {"text": "remember that I hate notifications after 22:00"}, timeout=30.0)
    assert reply["via"] == "local-intent"
    assert any("22:00" in f["text"] for f in daemon.memory.beliefs())

    before = daemon.store.llm_summary()["calls"]
    reply = call(config.socket_path, "ask",
                 {"text": "give me honest advice about pricing freelance work"}, timeout=60.0)
    assert reply["via"] == "gemini"  # open judgement is what the model is FOR
    assert daemon.store.llm_summary()["calls"] > before


def test_cli_memory_round_trip(tmp_path):
    import os
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "assistant.cli", *args],
                              check=False, capture_output=True, text=True, env=env,
                              timeout=60)

    assert cli("remember", "the boat is called Mvua").returncode == 0
    out = cli("memory")
    assert "Mvua" in out.stdout
    assert cli("forget", "boat").returncode == 0
    assert "Mvua" not in cli("memory").stdout
