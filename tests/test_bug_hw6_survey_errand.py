"""BUG-HW6 / FIX-HW6 — surveys must deliver the answer, not just survive.

Owner errand #4 (2026-11-27) ended `budget_exhausted` at 12/12 having read
2 of 32 selected files, never presented a grouping, and let `memory.infer`
auto-store 13 snippet "facts" (mislabelled `kind=preference`) from a survey
the owner never asked to be remembered.

Regression coverage (dispatch `reports/DISPATCH-BUGFIX-7.md`, FIX-HW6):

1. Breadth before depth: a survey errand over a fixture root (many small
   readable files + PDFs + a duplicate inside a zip) completes within the
   DEFAULT 12-step budget, covers every selected candidate with inspection
   metadata first, reads the readable set (duplicate content read ONCE),
   and always runs `content.analyze` + `errand.report`.
2. The report answers the question: named groups (label, member count,
   representative names, evidence basis) cover the readable set, with
   coverage fractions and skips stated honestly. Step/file counts are
   accounting and stay below the answer.
3. Surveys don't seed memory: zero facts stored; candidate inferences live
   in the report as `unconfirmed_candidates`. Content snippets are never
   classified `kind=preference`. An ambiguous grouping axis asks ONE
   question through the existing pending-question seam.
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

from assistant.cli import main as cli_main
from assistant.errand import (
    UntrustedObservation,
    _deterministic_analyze,
    grouping_axis,
    is_survey_instruction,
    skill_memory_infer,
)
from assistant.ipc import call

DUPLICATE_BODY = "duplicate payload shared by loose file and zip member\n"


def _wait_for_status(socket_path: Path, errand_id: int, targets: set[str],
                     *, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = call(socket_path, "errand.status", {"errand_id": errand_id}, timeout=5.0)
        if last["status"] in targets:
            return last
        time.sleep(0.03)
    raise AssertionError(
        f"errand #{errand_id} did not reach {targets} within {timeout}s; "
        f"last={last}"
    )


def _build_survey_fixture(root: Path) -> dict[str, Path]:
    """Many small readable files + PDFs + a duplicate inside a zip."""
    root.mkdir(parents=True, exist_ok=True)
    notes = {}
    for name in ("notes_alpha", "notes_beta", "notes_gamma", "notes_delta"):
        notes[name] = root / f"{name}.txt"
    notes["notes_alpha"].write_text(
        "theme: quiet\nWeekly review notes for alpha.\n", encoding="utf-8")
    notes["notes_beta"].write_text("Project beta review notes.\n", encoding="utf-8")
    notes["notes_gamma"].write_text("Gamma cleanup notes.\n", encoding="utf-8")
    notes["notes_delta"].write_text("Delta handover notes.\n", encoding="utf-8")

    dup_loose = root / "dup_loose.txt"
    dup_loose.write_text(DUPLICATE_BODY, encoding="utf-8")

    summary_pdf = root / "summary.pdf"
    summary_pdf.write_bytes(b"%PDF-1.7\n\xff\xfe binary pdf payload\n")
    appendix_pdf = root / "appendix.pdf"
    appendix_pdf.write_bytes(b"%PDF-1.4\n\xde\xad more binary pdf\n")

    bundle = root / "bundle.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dup_loose.txt", DUPLICATE_BODY)
        zf.writestr("readme_zip.txt", "Notes shipped inside the archive.\n")

    return {
        **notes,
        "dup_loose": dup_loose,
        "summary_pdf": summary_pdf,
        "appendix_pdf": appendix_pdf,
        "bundle": bundle,
        "zip_member_dup": bundle,  # target built below
        "zip_member_readme": bundle,
    }


def _zip_target(bundle: Path, member: str) -> str:
    return f"zip://{bundle}#{member}"


def test_bug_hw6_survey_completes_with_groups_no_memory_and_dedupe(
    tmp_path, config, running_daemon, capsys
):
    daemon, _server = running_daemon
    root = tmp_path / "downloads_survey"
    paths = _build_survey_fixture(root)

    started = call(config.socket_path, "errand.start", {
        "instruction": "Tell me what's there, and group it by what it seems to be for",
        "roots": [str(root)],
        "budget": {"max_api_calls": 0},
    }, timeout=5.0)
    done = _wait_for_status(config.socket_path, started["errand_id"], {"completed"})
    report = done["report"]

    # 1. Completed inside the DEFAULT budget, with the reserved tail run.
    assert done["status"] == "completed", done
    assert report["status"] == "completed"
    assert done["budget"]["steps_done"] <= 12
    skills = [s["skill"] for s in done["steps"]]
    assert "fs.survey" in skills, "breadth sweep must run before depth"
    assert "content.analyze" in skills, "analyze is part of the reserved tail"
    assert "errand.report" in skills, "an errand without its report step is a bug"
    assert skills.index("fs.survey") < skills.index("content.analyze")

    # Breadth covered the whole selected set before any depth read.
    survey_step = next(s for s in done["steps"] if s["skill"] == "fs.survey")
    assert survey_step["result"]["selected"] == 9
    assert survey_step["result"]["metadata_covered"] == 9
    first_read = next(
        i for i, s in enumerate(done["steps"])
        if s["skill"] in ("file.read", "file.inspect", "file.read_batch")
    )
    assert first_read > skills.index("fs.survey")

    # 2. The report states the groups: label, count, names, evidence basis.
    groups = report["groups"]
    assert groups, "grouping ask must produce named groups"
    union = {name for g in groups for name in g["members"]}
    for expected in (
        "notes_alpha.txt", "notes_beta.txt", "notes_gamma.txt",
        "notes_delta.txt", "dup_loose.txt", "summary.pdf", "appendix.pdf",
        "readme_zip.txt",
    ):
        assert expected in union, f"{expected} missing from groups: {union}"
    for group in groups:
        assert group["label"]
        assert group["member_count"] >= 1
        assert group["representative_names"]
        assert group["basis"]["kind"] in ("deterministic", "inferred")
        assert group["basis"]["evidence"]
    assert report["grouping"]["axis"] == "purpose"
    assert report["grouping"]["axis_source"] == "instruction"

    # Honest coverage: full metadata, partial content, skips named.
    coverage = report["coverage"]
    assert coverage["selected"] == 9
    assert coverage["metadata_covered"] == 9
    assert coverage["metadata_fraction"] == 1.0
    assert coverage["content_read"] == 6
    assert 0.0 < coverage["content_fraction"] < 1.0
    assert coverage["duplicates_collapsed"] == 1
    reasons = [s["reason"] for s in coverage["skipped"]]
    assert any("duplicate of" in r for r in reasons)
    assert sum("metadata-only" in r for r in reasons) == 2
    assert "metadata 9/9 (100%)" in report["summary"]
    assert "grouped" in report["summary"]

    # PDFs are covered by inspection: no read/inspect step crowds them in.
    pdf_targets = {str(paths["summary_pdf"]), str(paths["appendix_pdf"])}
    pdf_steps = [
        s for s in done["steps"]
        if s["skill"] in ("file.read", "file.inspect", "file.read_batch")
        and s["args"].get("target") in pdf_targets
    ]
    assert pdf_steps == [], f"metadata-only PDFs must not spend depth steps: {pdf_steps}"

    # Duplicate content: the loose twin and the zip member cost ONE read.
    dup_targets = {
        str(paths["dup_loose"]),
        _zip_target(paths["bundle"], "dup_loose.txt"),
    }
    dup_steps = [
        s for s in done["steps"]
        if s["skill"] in ("file.read", "file.inspect", "file.read_batch")
        and s["args"].get("target") in dup_targets
    ]
    assert len(dup_steps) == 1, f"duplicate must be read once, got: {dup_steps}"
    assert dup_steps[0]["args"]["target"] == str(paths["dup_loose"])

    # 3. Surveys don't seed memory; candidates live in the report only.
    assert daemon.store.list_facts() == []
    held = report["unconfirmed_candidates"]
    assert held, "the survey's content inference must be report-only"
    assert all(c["status"] == "unconfirmed_candidate" for c in held)
    assert any("theme" in c["text"] for c in held)
    assert daemon.store.list_facts() == []

    # Plain status prints the answer (groups + coverage) in words.
    assert cli_main(["errand", "status", str(started["errand_id"])]) == 0
    plain = capsys.readouterr().out
    assert "answer: grouped into" in plain
    assert "PDF documents" in plain
    assert "coverage: metadata 9/9 (100%)" in plain
    assert "duplicate of" in plain
    # Accounting stays below the answer.
    assert plain.index("answer: grouped") < plain.index("report:")


def test_bug_hw6_ambiguous_grouping_axis_asks_one_question(
    tmp_path, config, running_daemon
):
    daemon, _server = running_daemon
    root = tmp_path / "ambiguous_axis"
    root.mkdir()
    (root / "one.txt").write_text("first note\n", encoding="utf-8")
    (root / "two.txt").write_text("second note\n", encoding="utf-8")

    started = call(config.socket_path, "errand.start", {
        "instruction": "Tell me what's there and group everything",
        "roots": [str(root)],
        "budget": {"max_api_calls": 0},
    }, timeout=5.0)
    eid = started["errand_id"]
    paused = _wait_for_status(config.socket_path, eid, {"paused_for_question"})
    pending = [q for q in paused["questions"] if q["status"] == "pending"]
    assert len(pending) == 1, f"exactly ONE axis question expected: {pending}"
    assert "group" in pending[0]["question"].lower()
    assert "format" in (pending[0]["options"] or [])

    answered = call(config.socket_path, "errand.answer", {
        "errand_id": eid,
        "question_id": pending[0]["id"],
        "decision": "answer",
        "answer_text": "file format",
    }, timeout=5.0)
    assert answered["status"] == "answered"

    done = _wait_for_status(config.socket_path, eid, {"completed"})
    report = done["report"]
    assert report["grouping"]["axis_source"] == "owner_answer"
    assert report["grouping"]["axis"] == "format"
    assert report["grouping"]["owner_answer"] == "file format"
    assert report["groups"]
    # Answering the axis question must not write memory either.
    assert daemon.store.list_facts() == []


def test_bug_hw6_large_folder_survey_never_budget_exhausts(
    tmp_path, config, running_daemon
):
    """The owner's failure shape: a normal folder must not end budget_exhausted."""
    daemon, _server = running_daemon
    root = tmp_path / "big_downloads"
    root.mkdir()
    for i in range(40):
        (root / f"doc_{i:02d}.txt").write_text(f"note number {i}\n", encoding="utf-8")

    started = call(config.socket_path, "errand.start", {
        "instruction": "Tell me what's there, and group it by what it seems to be for",
        "roots": [str(root)],
        "budget": {"max_api_calls": 0},
    }, timeout=5.0)
    done = _wait_for_status(config.socket_path, started["errand_id"], {"completed"})
    report = done["report"]

    assert done["status"] == "completed", done
    assert report["status"] == "completed"
    assert any(s["skill"] == "errand.report" for s in done["steps"])
    assert done["budget"]["steps_done"] <= 12

    coverage = report["coverage"]
    assert coverage["selected"] == 32  # discovery cap: the whole selection
    assert coverage["metadata_covered"] == 32
    assert coverage["metadata_fraction"] == 1.0
    assert 0 < coverage["content_read"] <= 32
    assert coverage["skipped"], "un-read files must be named, not silent"
    assert report["groups"]
    union = {n for g in report["groups"] for n in g["members"]}
    assert len(union) == 32
    assert daemon.store.list_facts() == []


def test_bug_hw6_content_snippet_kind_is_never_preference(config):
    from assistant.embeddings import make_embedder
    from assistant.memory import Memory
    from assistant.store import Store

    store = Store(config.db_path)
    try:
        memory = Memory(store, make_embedder(config))
        raw = "Initialize Git is git init\n"
        obs = UntrustedObservation(
            path="/ws/snippets.txt", sha256="b" * 64, byte_start=0,
            byte_end=len(raw), total_size=len(raw), text=raw,
            eof=True, truncated=False,
        )

        # Missing kind: a document-content snippet classifies as observation.
        res = skill_memory_infer(
            memory,
            [{"text": "Initialize Git is git init",
              "evidence_quote": "Initialize Git is git init",
              "evidence_path": obs.path}],
            [obs],
        )
        assert res["stored"], res
        assert res["stored"][0]["kind"] == "observation"

        # Content-alias kinds never coerce to "preference" either.
        res2 = skill_memory_infer(
            memory,
            [{"text": "Setup docs say installers run first", "kind": "note",
              "evidence_quote": "Initialize Git is git init",
              "evidence_path": obs.path}],
            [obs],
        )
        assert res2["stored"]
        assert res2["stored"][0]["kind"] == "observation"

        # Explicit owner-stance kinds still pass through unchanged.
        res3 = skill_memory_infer(
            memory,
            [{"text": "Owner will review installers weekly", "kind": "commitment",
              "evidence_quote": "Initialize Git is git init",
              "evidence_path": obs.path}],
            [obs],
        )
        assert res3["stored"]
        assert res3["stored"][0]["kind"] == "commitment"

        # The deterministic analyzer labels its candidates observations too.
        det = _deterministic_analyze([obs])
        kv_raw = "theme: quiet\n"
        kv_obs = UntrustedObservation(
            path="/ws/kv.txt", sha256="c" * 64, byte_start=0,
            byte_end=len(kv_raw), total_size=len(kv_raw), text=kv_raw,
            eof=True, truncated=False,
        )
        det_kv = _deterministic_analyze([kv_obs])
        assert det_kv["candidate_inferences"]
        assert all(c["kind"] == "observation"
                   for c in det_kv["candidate_inferences"])
        assert all(c["kind"] != "preference"
                   for c in det["candidate_inferences"])
    finally:
        store.close()


def test_bug_hw6_survey_detection_and_axis_helpers():
    # Read-only survey asks (the dispatch's own examples) are gated.
    assert is_survey_instruction(
        "Tell me what's there, and group it by what it seems to be for")
    assert is_survey_instruction("look through my downloads")
    assert is_survey_instruction("group these files")
    assert is_survey_instruction("Please inventory this folder")
    # Explicit inference/memory asks opt back into probationary writes.
    assert not is_survey_instruction(
        "Go through my workspace, read the greenhouse notes, "
        "infer recurring practices, and ask me about any conflicts.")
    assert not is_survey_instruction("scan workshop and ask about conflicts")
    assert not is_survey_instruction("inspect folder and compare notes")
    assert not is_survey_instruction("hello")

    # Axis detection: clear axes run; anything else is genuinely unclear.
    assert grouping_axis("group it by what it seems to be for") == "purpose"
    assert grouping_axis("sort these by folder") == "folder"
    assert grouping_axis("group by file format") == "format"
    assert grouping_axis("group these files") is None
    assert grouping_axis("sort by date") is None
