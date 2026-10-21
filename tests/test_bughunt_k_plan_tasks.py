"""BH-K30 (minor batch): plan-build tasks leaked and could strand plans.

`Daemon._plan_tasks` gained an entry per plan build and never removed
one — an unbounded dict in a long-lived daemon. Worse, a build that
failed *before* `Organiser.build_plan`'s own try (e.g. an invalid
root mode) left the daemon-reserved plan row at 'building' forever:
`plan.show` reported a build that would never finish, and only the
CLI's BH-K8 deadline eventually called it stuck.

Fix: tasks remove themselves on completion, and `_run`'s failure path
marks a still-'building' plan failed with the error.
"""

from __future__ import annotations

import asyncio

from assistant.daemon import Daemon


def test_failed_build_marks_plan_failed_and_prunes_task(config, tmp_path,
                                                        monkeypatch):
    config.raw.setdefault("organise", {})["roots"] = [
        {"path": str(tmp_path), "mode": "shadow", "taxonomy": ["Docs"]}]
    daemon = Daemon(config)
    monkeypatch.setattr(
        daemon.organiser, "build_plan",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("boom: bad mode")))

    async def drive():
        out = await daemon._plan_build({})
        plan_id = out["started"][0]["plan_id"]
        task = daemon._plan_tasks.get(plan_id)
        assert task is not None
        await task
        # give done-callbacks a tick
        await asyncio.sleep(0)
        return plan_id

    plan_id = asyncio.run(drive())
    assert plan_id not in daemon._plan_tasks
    plan = daemon.store.get_plan(plan_id)
    assert plan["status"] == "failed", plan
    assert "boom" in (plan.get("error") or "")
    daemon.store.close()
