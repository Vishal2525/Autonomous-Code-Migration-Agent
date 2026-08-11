"""PHASE 1 — INDEXING: clone, scan, AST-analyze, build graphs and summaries.

Everything here is deterministic except one optional LLM call that writes the
free-text repository purpose / folder responsibilities into the index.
"""
from __future__ import annotations

import json
import re

from app.agent import prompts
from app.agent.progress import set_phase_progress
from app.db.repositories import store
from app.gitops.manager import GitManager
from app.indexing.ast_analyzer import PythonAnalyzer
from app.indexing.cloner import clone_repository
from app.indexing.graph import build_dependency_graph, dependency_docs
from app.indexing.scanner import build_tree, scan_repository
from app.indexing.summarizer import build_index_document, render_repo_summary
from app.llm.base import LLMMessage
from app.logging_config import get_logger
from app.models.enums import EventType, Phase
from app.models.schemas import Checkpoint
from app.tools.registry import ToolContext, ToolError
from app.tools.test_tools import run_tests_impl

log = get_logger("phase.indexing")


def _parse_json_loosely(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def run(ctx: ToolContext, llm, run) -> None:
    ctx.phase = Phase.INDEXING
    await ctx.emit(EventType.PHASE_STARTED, "Indexing repository", {"phase": "INDEXING"})

    # 1. clone (skipped when the working copy already exists — resume case)
    if not ctx.repo_dir.exists():
        await clone_repository(run.repository_url, ctx.repo_dir)
        await ctx.emit(EventType.LOG, f"Repository cloned into workspace")
    await set_phase_progress(ctx.run_id, Phase.INDEXING, 0.2)

    # 2. git baseline + migration branch
    git = GitManager(ctx.repo_dir)
    baseline = git.ensure_repo(run.run_id)
    ctx.git = git
    await store.update_run(
        ctx.run_id,
        workspace=str(ctx.workspace_dir),
        repo_dir=str(ctx.repo_dir),
        baseline_sha=baseline,
        head_sha=baseline,
    )

    # 3. scan + classify files
    files = scan_repository(ctx.repo_dir)
    await store.save_files(ctx.run_id, [dict(f) for f in files])
    await store.update_run(ctx.run_id, **{"counters.files_indexed": len(files)})
    await ctx.emit(EventType.LOG, f"Scanned {len(files)} files")
    await set_phase_progress(ctx.run_id, Phase.INDEXING, 0.35)

    # 4. deterministic AST analysis of Python sources
    py_paths = [
        f["path"] for f in files
        if f["language"] == "python" and f["category"] in ("source", "test", "dependency")
    ]
    analyzer = PythonAnalyzer(ctx.repo_dir, py_paths)
    analyses = analyzer.analyze_all()
    syntax_errors = [p for p, a in analyses.items() if a.get("error")]
    if syntax_errors:
        await ctx.emit(
            EventType.LOG, f"Files with parse errors during indexing: {syntax_errors}"
        )

    # 5. dependency graph (forward + reverse)
    deps, reverse = build_dependency_graph(analyses)
    await store.save_dependencies(ctx.run_id, dependency_docs(deps, reverse))
    await ctx.emit(
        EventType.LOG,
        f"Dependency graph built for {len(analyses)} Python files",
    )
    await set_phase_progress(ctx.run_id, Phase.INDEXING, 0.5)

    # 6. tiered summaries (L1 + L2)
    tree = build_tree(files)
    index_doc = build_index_document(
        ctx.run_id, run.repository_url, ctx.repo_dir, files, analyses, tree
    )

    # optional LLM enrichment — one call, deterministic fallback on any failure
    if llm is not None:
        try:
            system, user = prompts.enrichment_prompt(
                render_repo_summary(index_doc), index_doc.get("readme_head", "")
            )
            response = await llm.complete(
                [LLMMessage(role="system", content=system),
                 LLMMessage(role="user", content=user)]
            )
            data = _parse_json_loosely(response.text)
            if data:
                index_doc["purpose"] = str(data.get("purpose", ""))[:600]
                for folder, text in (data.get("folders") or {}).items():
                    if folder in index_doc["folder_summaries"] and isinstance(text, str):
                        index_doc["folder_summaries"][folder]["responsibility"] = text[:300]
                await ctx.emit(EventType.LOG, "Repository summary enriched by LLM")
        except Exception as exc:  # enrichment is optional — never fail indexing
            log.warning("enrichment_failed", error=str(exc)[:200])
            await ctx.emit(EventType.LOG, f"LLM summary enrichment skipped: {exc}")

    await store.save_repository_index(index_doc)
    ctx.index = index_doc
    await set_phase_progress(ctx.run_id, Phase.INDEXING, 0.65)

    # 7. baseline environment + test run (recorded for later comparison)
    try:
        result = await run_tests_impl(ctx, [], attempt=0)
        await ctx.emit(
            EventType.LOG,
            f"Baseline tests: {result['passed']} passed, "
            f"{result['failed']} failed, {result['errors']} errors",
        )
    except ToolError as exc:
        await ctx.emit(EventType.LOG, f"Baseline test run skipped: {exc}")

    # 8. checkpoint — indexing never repeats after this
    await store.save_checkpoint(
        Checkpoint(run_id=ctx.run_id, phase=Phase.INDEXING, git_sha=baseline,
                   payload={"files": len(files), "python_files": len(py_paths)})
    )
    await ctx.emit(EventType.CHECKPOINT_CREATED, "Indexing checkpoint saved")
    await set_phase_progress(ctx.run_id, Phase.INDEXING, 1.0)
    await ctx.emit(EventType.PHASE_COMPLETED, "Indexing completed", {"phase": "INDEXING"})
