"""Durable cloud-work queue (Phase 8, §13.9: queue, don't fail).

Offline-capable work stays local and immediate. Work that genuinely
needs Gemini or the outside world becomes a SQLite job with its raw
material attached. On reconnect, transcription and parked judgement
drain automatically; downloads/web/installs/external actions remain
awaiting explicit owner approval. Nothing cloud-bound fails silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import asr
from .cleanup import CleanupPass
from .cost import iso_now
from .inbox import append_cloud_transcript
from .modes import looks_like_network_failure
from .organiser import OrganiserService

APPROVAL_KINDS = {"external_action", "download", "web", "install_tool"}
ACTIVE_STATUSES = {"pending", "running", "awaiting_approval", "approved"}


def capability_for(kind: str) -> dict:
    if kind in APPROVAL_KINDS:
        return {"execution": "approval-required", "local": False}
    if kind in ("cloud_transcription", "transcript_cleanup", "plan_tiers", "chat"):
        return {"execution": "auto-on-reconnect", "local": False}
    return {"execution": "local", "local": True}


class CloudQueue:
    def __init__(self, config, store, client, mode_manager=None):
        self.config = config
        self.store = store
        self.client = client
        self.mode_manager = mode_manager

    # -- enqueue ---------------------------------------------------------------
    def _find_active(self, kind: str, key: str, value) -> dict | None:
        for job in self.store.list_cloud_jobs(limit=500):
            if job["kind"] != kind or job["status"] not in ACTIVE_STATUSES:
                continue
            try:
                payload = json.loads(job["payload_json"])
            except ValueError:
                continue
            if payload.get(key) == value:
                return job
        return None

    def enqueue(self, kind: str, payload: dict, *, requires_approval: bool | None = None) -> int:
        approval = kind in APPROVAL_KINDS if requires_approval is None else requires_approval
        return self.store.enqueue_cloud_job(
            ts=iso_now(), kind=kind, payload_json=json.dumps(payload),
            requires_approval=approval,
            status="awaiting_approval" if approval else "pending")

    def enqueue_transcription(self, transcript_id: int, audio_path: str | None,
                              language: str, session_id: str | None = None) -> int:
        existing = self._find_active("cloud_transcription", "transcript_id", transcript_id)
        if existing:
            return int(existing["id"])
        return self.enqueue("cloud_transcription", {
            "transcript_id": transcript_id, "audio_path": audio_path,
            "language": language, "session_id": session_id,
        })

    def enqueue_cleanup(self, transcript_id: int) -> int:
        existing = self._find_active("transcript_cleanup", "transcript_id", transcript_id)
        if existing:
            return int(existing["id"])
        return self.enqueue("transcript_cleanup", {"transcript_id": transcript_id})

    def enqueue_plan_tiers(self, root: str, source_plan_id: int | None = None) -> int:
        return self.enqueue("plan_tiers", {"root": root, "source_plan_id": source_plan_id})

    def enqueue_chat(self, text: str, prompt: str, conversation_id: int | None = None) -> int:
        return self.enqueue("chat", {"text": text, "prompt": prompt,
                                     "conversation_id": conversation_id})

    def enqueue_external(self, action: str, description: str,
                         payload: dict | None = None) -> int:
        return self.enqueue("external_action", {
            "action": action, "description": description, **(payload or {}),
        }, requires_approval=True)

    # -- inspection / approval -----------------------------------------------------
    def list_jobs(self, status: str | None = None, limit: int = 100) -> list[dict]:
        jobs = []
        for job in self.store.list_cloud_jobs(status, limit):
            item = dict(job)
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except ValueError:
                item["payload"] = {}
            if item.get("result_json"):
                try:
                    item["result"] = json.loads(item["result_json"])
                except ValueError:
                    item["result"] = item["result_json"]
            jobs.append(item)
        return jobs

    def approve(self, job_id: int) -> dict:
        job = self.store.get_cloud_job(job_id)
        if job is None:
            raise ValueError(f"no cloud job {job_id}")
        if job["status"] != "awaiting_approval":
            raise ValueError(f"job {job_id} is {job['status']}, not awaiting approval")
        self.store.update_cloud_job(
            job_id, status="approved",
            result_json=json.dumps({"approved": True, "approved_at": iso_now()}))
        return self.store.get_cloud_job(job_id) or {}

    # -- drain -----------------------------------------------------------------------
    def drain(self, *, limit: int = 50, force: bool = False) -> dict:
        mode = None
        if self.mode_manager is not None:
            mode_status = self.mode_manager.status()
            mode = mode_status.effective_mode
            if mode_status.is_offline and not force:
                result = self._empty_result(skipped_offline=True, mode=mode)
                result["summary"] = "Still offline. Queued cloud work is waiting."
                return result

        result = self._empty_result(mode=mode)
        existing = self.store.list_cloud_jobs(limit=500)
        # Jobs enqueued as external work start life awaiting approval; a
        # reconnect summary must still name them rather than pretend the
        # queue fully drained.
        result["awaiting_approval"] = sum(
            1 for j in existing if j["status"] == "awaiting_approval")
        candidates = [j for j in existing
                      if j["status"] in ("pending", "approved")][:limit]
        for job in candidates:
            job_id = int(job["id"])
            if job["requires_approval"] and job["status"] != "approved":
                # Conditional claim: only the drain that actually moved the
                # job to awaiting_approval reports it (BH-C3).
                if not self.store.claim_cloud_job(
                        job_id, to_status="awaiting_approval",
                        from_statuses=("pending",), increment_attempts=False):
                    continue
                result["awaiting_approval"] += 1
                result["jobs"].append({"id": job_id, "kind": job["kind"],
                                        "status": "awaiting_approval"})
                continue
            # THE claim: pending/approved -> running in one atomic UPDATE, so
            # a second drain that listed the same candidate skips it instead
            # of running the job twice (BH-C3).
            if not self.store.claim_cloud_job(job_id):
                continue
            try:
                payload = json.loads(job["payload_json"])
                outcome = self._handle(job["kind"], payload, approved=job["status"] == "approved")
            except Exception as exc:
                if looks_like_network_failure(exc):
                    if self.mode_manager is not None:
                        self.mode_manager.observe_failure(exc, "queue drain")
                    self.store.update_cloud_job(job_id, status="pending", error=str(exc))
                    result["network_stopped"] = True
                    result["jobs"].append({"id": job_id, "kind": job["kind"],
                                            "status": "pending", "error": str(exc)})
                    break
                self.store.update_cloud_job(job_id, status="failed", error=str(exc),
                                            completed_ts=iso_now())
                result["failed"] += 1
                result["jobs"].append({"id": job_id, "kind": job["kind"],
                                        "status": "failed", "error": str(exc)})
                continue
            self.store.update_cloud_job(job_id, status="done",
                                        result_json=json.dumps(outcome),
                                        completed_ts=iso_now())
            result["done"] += 1
            result["jobs"].append({"id": job_id, "kind": job["kind"],
                                    "status": "done", "result": outcome})
        result["processed"] = result["done"] + result["failed"]
        result["counts"] = self.store.cloud_job_counts()
        result["summary"] = self.summary_text(result)
        return result

    @staticmethod
    def _empty_result(*, skipped_offline: bool = False, mode: str | None = None) -> dict:
        return {"mode": mode, "skipped_offline": skipped_offline, "processed": 0,
                "done": 0, "failed": 0, "awaiting_approval": 0,
                "network_stopped": False, "jobs": [], "counts": {}, "summary": ""}

    @staticmethod
    def summary_text(result: dict) -> str:
        parts = []
        if result.get("done"):
            parts.append(f"{result['done']} queued item(s) completed")
        if result.get("failed"):
            parts.append(f"{result['failed']} failed and kept for inspection")
        if result.get("awaiting_approval"):
            parts.append(f"{result['awaiting_approval']} external item(s) still need approval")
        if result.get("network_stopped"):
            parts.append("draining stopped because the network dropped again")
        if not parts:
            return "Back online. Nothing was queued."
        return "Back online. " + "; ".join(parts) + "."

    # -- handlers -----------------------------------------------------------------------
    def _handle(self, kind: str, payload: dict, *, approved: bool = False) -> dict:
        if kind == "cloud_transcription":
            return self._cloud_transcription(payload)
        if kind == "transcript_cleanup":
            return self._transcript_cleanup(payload)
        if kind == "plan_tiers":
            return self._plan_tiers(payload)
        if kind == "chat":
            return self._chat(payload)
        if kind in APPROVAL_KINDS:
            if not approved:
                raise RuntimeError("external action reached handler without approval")
            return {
                "approved": True,
                "executed": False,
                "note": ("Approval recorded. Phase 8 does not auto-run downloads, "
                         "web actions or installers; run the approved action explicitly."),
                "action": payload.get("action"),
            }
        raise ValueError(f"unknown cloud job kind {kind!r}")

    def _cloud_transcription(self, payload: dict) -> dict:
        transcript_id = int(payload["transcript_id"])
        row = self.store.get_transcript(transcript_id)
        if row is None:
            raise ValueError(f"transcript {transcript_id} no longer exists")
        audio = Path(str(payload.get("audio_path") or row.get("audio_path") or "")).expanduser()
        if not audio.exists():
            self.store.set_transcript_cloud_status(transcript_id, "cloud_failed")
            raise FileNotFoundError(f"saved raw audio is missing: {audio}")
        backend = asr.GeminiBatchBackend(self.client, self.config)
        transcript = backend.transcribe(str(audio), str(payload.get("language") or row["language"]))
        if not transcript.text.strip():
            raise RuntimeError("Gemini batch returned an empty transcript")
        self.store.update_transcript_cloud(
            transcript_id, text=transcript.text, backend=transcript.backend,
            model=self.config.model_for_role("transcribe_batch"),
            confidence=transcript.confidence)
        if row.get("inbox_path") and Path(row["inbox_path"]).exists():
            append_cloud_transcript(Path(row["inbox_path"]), cloud_text=transcript.text,
                                    offline_text=row.get("offline_text") or row.get("raw_text"))
        return {"transcript_id": transcript_id, "backend": transcript.backend,
                "chars": len(transcript.text)}

    def _transcript_cleanup(self, payload: dict) -> dict:
        transcript_id = int(payload["transcript_id"])
        row = self.store.get_transcript(transcript_id)
        if row is None:
            raise ValueError(f"transcript {transcript_id} no longer exists")
        result = CleanupPass(self.config, self.client).run(row["raw_text"] or "")
        if result.cleaned is not None or result.divergence_pct is not None:
            self.store.update_transcript_cleanup(
                transcript_id, cleaned_text=result.cleaned,
                divergence_pct=result.divergence_pct, flagged=result.flagged,
                model=result.model)
        return {"transcript_id": transcript_id, "flagged": result.flagged,
                "reason": result.reason}

    def _plan_tiers(self, payload: dict) -> dict:
        root = str(payload.get("root") or "")
        spec = next((r for r in self.config.organise_roots() if r["path"] == root), None)
        if spec is None:
            raise ValueError(f"organise root no longer configured: {root}")
        result = OrganiserService(self.config, self.store, self.client).build_plan(
            spec, with_llm_tiers=True)
        return {"source_plan_id": payload.get("source_plan_id"),
                "new_plan_id": result["plan_id"], "root": root}

    def _chat(self, payload: dict) -> dict:
        result = self.client.generate("chat", str(payload.get("prompt") or payload.get("text") or ""))
        conversation_id = payload.get("conversation_id")
        if conversation_id:
            self.store.add_message(int(conversation_id), iso_now(), "assistant",
                                   result.text, "gemini-queued")
        return {"reply": result.text, "model": result.model}
