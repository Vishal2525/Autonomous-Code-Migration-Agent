"""REST API for migration runs."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.db.repositories import store
from app.gitops.manager import GitError, GitManager
from app.models.schemas import Run, RunCreate
from app.services import run_service
from app.services.run_service import ServiceError

router = APIRouter(prefix="/api", tags=["runs"])


def _handle(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


async def _run_payload(run: Run) -> dict:
    data = jsonable_encoder(run.model_dump())
    approval = await store.pending_approval(run.run_id)
    data["pending_approval"] = jsonable_encoder(approval.model_dump()) if approval else None
    return data


@router.post("/runs", status_code=201)
async def create_run(payload: RunCreate):
    try:
        run = await run_service.create_run(payload)
    except ServiceError as exc:
        raise _handle(exc)
    return await _run_payload(run)


@router.get("/runs")
async def list_runs():
    runs = await store.list_runs()
    return [jsonable_encoder(r.model_dump()) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return await _run_payload(run)


def _action(fn):
    async def endpoint(run_id: str):
        try:
            run = await fn(run_id)
        except ServiceError as exc:
            raise _handle(exc)
        return await _run_payload(run)

    return endpoint


router.post("/runs/{run_id}/start")(_action(run_service.start_run))
router.post("/runs/{run_id}/pause")(_action(run_service.pause_run))
router.post("/runs/{run_id}/resume")(_action(run_service.resume_run))
router.post("/runs/{run_id}/approve")(_action(run_service.approve_run))
router.post("/runs/{run_id}/reject")(_action(run_service.reject_run))
router.post("/runs/{run_id}/cancel")(_action(run_service.cancel_run))


@router.get("/runs/{run_id}/events")
async def get_events(
    run_id: str,
    after: str | None = Query(default=None, description="Return events after this event id"),
    limit: int = Query(default=200, le=1000),
):
    events = await store.list_events(run_id, after_id=after, limit=limit)
    return jsonable_encoder(events)


@router.get("/runs/{run_id}/tasks")
async def get_tasks(run_id: str):
    tasks = await store.list_tasks(run_id)
    return [jsonable_encoder(t.model_dump()) for t in tasks]


@router.get("/runs/{run_id}/plan")
async def get_plan(run_id: str):
    plan = await store.get_plan(run_id)
    if plan is None:
        raise HTTPException(404, "Plan not created yet")
    tasks = await store.list_tasks(run_id)
    plan["tasks"] = [jsonable_encoder(t.model_dump()) for t in tasks]
    return jsonable_encoder(plan)


@router.get("/runs/{run_id}/report")
async def get_report(run_id: str):
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if not run.report:
        raise HTTPException(404, "Report not generated yet")
    return run.report


@router.get("/runs/{run_id}/tests")
async def get_test_results(run_id: str):
    results = await store.list_test_results(run_id)
    return [jsonable_encoder(r.model_dump()) for r in results]


@router.get("/runs/{run_id}/checkpoints")
async def get_checkpoints(run_id: str):
    checkpoints = await store.list_checkpoints(run_id)
    return [jsonable_encoder(c.model_dump()) for c in checkpoints]


@router.get("/runs/{run_id}/diff")
async def get_diff(run_id: str):
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if not run.repo_dir or not run.baseline_sha or not Path(run.repo_dir).is_dir():
        return {"files": [], "note": "No repository changes yet"}
    try:
        git = GitManager(Path(run.repo_dir))
        names = git.diff_names(run.baseline_sha)
        files = []
        for change in names[:100]:
            patch = ""
            if change["status"] != "deleted":
                patch = git.diff_patch(
                    run.baseline_sha, "HEAD", path=change["path"], max_chars=20000
                )
            files.append({**change, "patch": patch})
        return {"files": files, "baseline": run.baseline_sha, "head": git.current_sha()}
    except GitError as exc:
        raise HTTPException(500, f"Diff failed: {exc}")


@router.get("/runs/{run_id}/files")
async def get_files(run_id: str):
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    files = await store.list_files(run_id)
    status_map: dict[str, str] = {}
    if run.repo_dir and run.baseline_sha and Path(run.repo_dir).is_dir():
        try:
            git = GitManager(Path(run.repo_dir))
            for change in git.diff_names(run.baseline_sha):
                status_map[change["path"]] = change["status"]
        except GitError:
            pass
    for f in files:
        f["change"] = status_map.get(f["path"])
    # include files created during migration that weren't in the original scan
    known = {f["path"] for f in files}
    for path, status in status_map.items():
        if path not in known:
            files.append({"path": path, "category": "source", "language": None,
                          "size": None, "lines": None, "change": status})
    return jsonable_encoder(files)
