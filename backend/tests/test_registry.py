from pydantic import BaseModel, Field

from app.tools.registry import Tool, ToolRegistry


class EchoArgs(BaseModel):
    text: str = Field(min_length=1)


async def echo(ctx, args: EchoArgs):
    return {"echo": args.text}


async def boom(ctx, args: EchoArgs):
    raise RuntimeError("kaboom")


def _registry():
    registry = ToolRegistry()
    registry.register(Tool(name="echo", description="echo", input_model=EchoArgs, handler=echo))
    registry.register(
        Tool(name="mutate", description="m", input_model=EchoArgs, handler=echo, mutating=True)
    )
    registry.register(Tool(name="boom", description="b", input_model=EchoArgs, handler=boom))
    return registry


async def test_execute_validates_and_runs(repo_ctx):
    registry = _registry()
    result = await registry.execute(repo_ctx, "echo", {"text": "hi"}, allow_mutations=False)
    assert result.ok and result.data == {"echo": "hi"}


async def test_invalid_args_return_error_not_crash(repo_ctx):
    registry = _registry()
    result = await registry.execute(repo_ctx, "echo", {"wrong": 1}, allow_mutations=False)
    assert not result.ok and "Invalid arguments" in result.error


async def test_unknown_tool(repo_ctx):
    result = await _registry().execute(repo_ctx, "nope", {}, allow_mutations=True)
    assert not result.ok and "Unknown tool" in result.error


async def test_mutating_tool_blocked_in_readonly_phase(repo_ctx):
    registry = _registry()
    result = await registry.execute(repo_ctx, "mutate", {"text": "x"}, allow_mutations=False)
    assert not result.ok and "read-only" in result.error
    result = await registry.execute(repo_ctx, "mutate", {"text": "x"}, allow_mutations=True)
    assert result.ok


async def test_handler_crash_is_contained(repo_ctx):
    result = await _registry().execute(repo_ctx, "boom", {"text": "x"}, allow_mutations=True)
    assert not result.ok and "kaboom" in result.error


def test_specs_exclude_mutating_when_requested():
    registry = _registry()
    names_all = {s["name"] for s in registry.specs(include_mutating=True)}
    names_ro = {s["name"] for s in registry.specs(include_mutating=False)}
    assert "mutate" in names_all and "mutate" not in names_ro
