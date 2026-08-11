"""Read-only analysis tools: tiered context + deterministic dependency lookups."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.indexing.ast_analyzer import PythonAnalyzer
from app.indexing.summarizer import render_folder_summary, render_repo_summary
from app.tools.registry import Tool, ToolContext, ToolError, ToolRegistry


class EmptyArgs(BaseModel):
    pass


class FolderArgs(BaseModel):
    folder: str = Field(description="Folder path, e.g. 'app/routes'")


class PathArgs(BaseModel):
    path: str = Field(description="Repository-relative file path")


async def get_repository_summary(ctx: ToolContext, args: EmptyArgs):
    if not ctx.index:
        raise ToolError("Repository index not available yet")
    return render_repo_summary(ctx.index)


async def get_repository_tree(ctx: ToolContext, args: EmptyArgs):
    if not ctx.index:
        raise ToolError("Repository index not available yet")
    return ctx.index.get("tree", "")


async def get_folder_summary(ctx: ToolContext, args: FolderArgs):
    if not ctx.index:
        raise ToolError("Repository index not available yet")
    return render_folder_summary(ctx.index, args.folder.strip("/").replace("\\", "/"))


async def get_file_dependencies(ctx: ToolContext, args: PathArgs):
    doc = await ctx.store.get_dependency(ctx.run_id, args.path)
    if doc is None:
        raise ToolError(f"No dependency record for {args.path} (was it indexed?)")
    return {"file": args.path, "dependencies": doc.get("dependencies", [])}


async def get_reverse_dependencies(ctx: ToolContext, args: PathArgs):
    doc = await ctx.store.get_dependency(ctx.run_id, args.path)
    if doc is None:
        raise ToolError(f"No dependency record for {args.path} (was it indexed?)")
    return {
        "file": args.path,
        "reverse_dependencies": doc.get("reverse_dependencies", []),
        "note": "These files import the given file — changing its interface affects them.",
    }


async def get_file_symbols(ctx: ToolContext, args: PathArgs):
    """Live AST parse of the CURRENT file state (not the index-time snapshot)."""
    if not args.path.endswith(".py"):
        raise ToolError("get_file_symbols only supports Python files")
    py_files = [f for f in ctx.index.get("files", []) if f.endswith(".py")]
    if args.path not in py_files:
        py_files.append(args.path)
    analyzer = PythonAnalyzer(ctx.repo_dir, py_files)
    info = analyzer.analyze_file(args.path)
    if info.get("error"):
        raise ToolError(f"Could not analyze {args.path}: {info['error']}")
    return {
        "path": args.path,
        "functions": info["functions"],
        "classes": info["classes"],
        "routes": info["routes"],
        "imports": [i["module"] for i in info["imports"]],
        "local_dependencies": info["local_dependencies"],
        "external_libs": info["external_libs"],
    }


def register_analysis_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="get_repository_summary",
        description="Level-1 context: compact overview of the whole repository "
                    "(language, folders, technologies, tree).",
        input_model=EmptyArgs, handler=get_repository_summary,
    ))
    registry.register(Tool(
        name="get_repository_tree",
        description="ASCII tree of all repository files.",
        input_model=EmptyArgs, handler=get_repository_tree,
    ))
    registry.register(Tool(
        name="get_folder_summary",
        description="Level-2 context: files, classes, functions and routes of one folder.",
        input_model=FolderArgs, handler=get_folder_summary,
    ))
    registry.register(Tool(
        name="get_file_dependencies",
        description="Local files this file imports (deterministic, AST-based).",
        input_model=PathArgs, handler=get_file_dependencies,
    ))
    registry.register(Tool(
        name="get_reverse_dependencies",
        description="Local files that import this file (impact analysis).",
        input_model=PathArgs, handler=get_reverse_dependencies,
    ))
    registry.register(Tool(
        name="get_file_symbols",
        description="Functions, classes, routes and imports of a Python file, "
                    "parsed live from its current content.",
        input_model=PathArgs, handler=get_file_symbols,
    ))
