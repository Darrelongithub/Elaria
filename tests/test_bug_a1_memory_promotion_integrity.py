"""BUG-A1 · memory promotion integrity — regression reproductions (P0).

Three reproduced defects from `reports/BUGHUNT-A-20261126.md`:

1. Gap/clarifying answers promoted an UNRELATED inferred fact to
   `source='stated', confidence=1.0` (`errand.py` linked the most recent
   inferred record when a question had no linked fact).
2. Conflict answers ignored `answer_text` and promoted the losing tentative
   "may be <a>" text verbatim to `source='stated'`.
3. `skill_memory_infer()` bypassed `Memory.propose_inferred()` tombstones and
   deduplication, so an owner-rejected inference was re-inserted as active
   on the very next errand over the same folder.

All three drive the REAL `ErrandRunner`/`Store`/`Memory` stack (no stubs),
mirroring the sandbox reproductions from the hunt.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from assistant.embeddings import make_embedder
from assistant.errand import ErrandRunner
from assistant.memory import Memory
from assistant.safety_journal import JournalLog
from assistant.store import Store


def _make_runner(config, tmp_path):
    store = Store(config.db_path)
    memory = Memory(store, make_embedder(config))
    journal = JournalLog(tmp_path / "safety_journal.jsonl")
    runner = ErrandRunner(
        config,
        store,
        memory,
        safety_journal=journal,
        is_offline=lambda: True,  # deterministic: local structural pass only
    )
    return runner, store, memory, journal


async def _wait_status(store, errand_id, targets, *, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        row = store.get_errand(int(errand_id))
        status = row["status"] if row else None
        last = status
        if status in targets:
            return status
        if status in {"failed", "cancelled"} and status not in targets:
            raise AssertionError(f"errand #{errand_id} ended as {status}")
        await asyncio.sleep(0.02)
    raise AssertionError(f"errand #{errand_id} did not reach {targets}; last={last}")


def _pending_question(store, errand_id):
    questions = store.list_pending_questions(errand_id=int(errand_id), status="pending")
    assert questions, f"errand #{errand_id} has no pending question"
    question = dict(questions[0])
    question["candidate_fact_ids"] = json.loads(
        question.get("candidate_fact_ids_json") or "[]")
    return question


def test_bug_a1_gap_answer_never_promotes_unrelated_inference(config, tmp_path):
    workspace = tmp_path / "gap_ws"
    workspace.mkdir()
    (workspace / "a.txt").write_text(
        "preferred_substrate: coco_coir\n", encoding="utf-8")
    (workspace / "b.txt").write_text(
        "preferred_substrate: coco_coir\nshipping_address: TBD\n",
        encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(workspace)]

    async def _scenario():
        runner, store, _memory, _journal = _make_runner(config, tmp_path)
        try:
            started = runner.start(
                "inspect workspace and infer preferences",
                roots=[str(workspace)],
            )
            eid = started["errand_id"]
            await _wait_status(store, eid, {"paused_for_question"})
            question = _pending_question(store, eid)
            # The gap question names no inferred fact — a question may only
            # ever promote facts it names.
            assert question["kind"] == "clarify"
            assert question["candidate_fact_ids"] == []
            assert question.get("attribute") == "shipping_address"

            res = await runner.answer(
                eid,
                question_id=int(question["id"]),
                decision="confirm",
                answer_text="123 Kenyatta Ave",
                owner_uid=os.getuid(),
            )
            facts = {int(f["id"]): f for f in store.list_facts(active_only=False)}
            # The owner's gap answer becomes a fact for the gap attribute…
            assert res["promoted_fact_ids"], res
            for fid in res["promoted_fact_ids"]:
                promoted = facts[fid]
                assert promoted["source"] == "stated"
                assert float(promoted["confidence"]) == 1.0
                assert "shipping_address" in promoted["text"]
                assert "123 Kenyatta Ave" in promoted["text"]
            # …and the unrelated coco_coir inference was NOT promoted.
            substrate = next(
                f for f in facts.values() if "coco_coir" in f["text"])
            assert substrate["source"] == "inferred"
            assert float(substrate["confidence"]) < 1.0
            await _wait_status(store, eid, {"completed"})
        finally:
            await runner.aclose()
            store.close()

    asyncio.run(_scenario())


def test_bug_a1_gap_bare_confirm_creates_nothing_and_promotes_nothing(config, tmp_path):
    workspace = tmp_path / "gap_bare_ws"
    workspace.mkdir()
    (workspace / "a.txt").write_text(
        "preferred_substrate: coco_coir\n", encoding="utf-8")
    (workspace / "b.txt").write_text(
        "preferred_substrate: coco_coir\nshipping_address: TBD\n",
        encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(workspace)]

    async def _scenario():
        runner, store, _memory, _journal = _make_runner(config, tmp_path)
        try:
            started = runner.start(
                "inspect workspace and infer preferences",
                roots=[str(workspace)],
            )
            eid = started["errand_id"]
            await _wait_status(store, eid, {"paused_for_question"})
            question = _pending_question(store, eid)
            res = await runner.answer(
                eid,
                question_id=int(question["id"]),
                decision="confirm",
                answer_text="",
                owner_uid=os.getuid(),
            )
            assert res["promoted_fact_ids"] == []
            substrate = next(
                f for f in store.list_facts(active_only=False)
                if "coco_coir" in f["text"])
            assert substrate["source"] == "inferred"
            await _wait_status(store, eid, {"completed"})
        finally:
            await runner.aclose()
            store.close()

    asyncio.run(_scenario())


def test_bug_a1_conflict_confirm_reflects_owners_chosen_value(config, tmp_path):
    workspace = tmp_path / "conflict_ws"
    workspace.mkdir()
    (workspace / "a.txt").write_text(
        "irrigation_schedule: dawn\n", encoding="utf-8")
    (workspace / "b.txt").write_text(
        "irrigation_schedule: dusk\n", encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(workspace)]

    async def _scenario():
        runner, store, _memory, _journal = _make_runner(config, tmp_path)
        try:
            started = runner.start(
                "inspect workspace and infer preferences",
                roots=[str(workspace)],
            )
            eid = started["errand_id"]
            await _wait_status(store, eid, {"paused_for_question"})
            question = _pending_question(store, eid)
            assert question["kind"] == "conflict"
            assert question["candidate_fact_ids"], (
                "the conflict question must name the tentative inference")
            # The owner picks <b>; promotion must reflect the owner's choice.
            res = await runner.answer(
                eid,
                question_id=int(question["id"]),
                decision="confirm",
                answer_text="dusk",
                owner_uid=os.getuid(),
            )
            assert res["promoted_fact_ids"]
            facts = list(store.list_facts(active_only=False))
            stated = [f for f in facts if f["source"] == "stated"]
            assert any(
                f["text"] == "irrigation_schedule is dusk"
                and float(f["confidence"]) == 1.0
                for f in stated), [f["text"] for f in stated]
            # The losing tentative "may be dawn" text is never promoted verbatim…
            assert not any("may be dawn" in f["text"] for f in stated)
            # …and is retired to the tombstoned/deactivated pool instead.
            tentative = next(
                f for f in facts
                if int(f["id"]) in set(question["candidate_fact_ids"]))
            assert tentative["source"] == "inferred"
            assert int(tentative["active"]) == 0
            await _wait_status(store, eid, {"completed"})
        finally:
            await runner.aclose()
            store.close()

    asyncio.run(_scenario())


def test_bug_a1_rejected_inference_stays_tombstoned_on_rerun(config, tmp_path):
    workspace = tmp_path / "tombstone_ws"
    workspace.mkdir()
    (workspace / "notes.txt").write_text(
        "finish_oil: tung_oil\n", encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(workspace)]

    async def _scenario():
        runner, store, memory, _journal = _make_runner(config, tmp_path)
        try:
            first = runner.start(
                "inspect workspace and infer preferences",
                roots=[str(workspace)],
            )
            first_eid = first["errand_id"]
            await _wait_status(store, first_eid, {"completed"})
            inferred = [
                f for f in store.list_facts(active_only=True)
                if f["source"] == "inferred" and "tung_oil" in f["text"]
            ]
            assert inferred, "first errand should store the inference"
            assert memory.reject_inference(int(inferred[0]["id"]))
            assert not any(
                "tung_oil" in f["text"]
                for f in store.list_facts(active_only=True))

            # The very next errand over the same folder must not resurrect
            # the owner-rejected claim.
            second = runner.start(
                "inspect workspace and infer preferences",
                roots=[str(workspace)],
            )
            second_eid = second["errand_id"]
            await _wait_status(store, second_eid, {"completed"})
            assert not any(
                "tung_oil" in f["text"]
                for f in store.list_facts(active_only=True)), (
                "owner-rejected inference was resurrected by a rerun")
        finally:
            await runner.aclose()
            store.close()

    asyncio.run(_scenario())
