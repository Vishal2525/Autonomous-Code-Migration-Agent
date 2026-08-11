"""Assemble the standard tool registry used by the agent phases."""
from __future__ import annotations

from app.tools.analysis_tools import register_analysis_tools
from app.tools.command_tools import register_command_tools
from app.tools.file_tools import register_file_tools
from app.tools.git_tools import register_git_tools
from app.tools.registry import ToolRegistry
from app.tools.test_tools import register_test_tools


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_analysis_tools(registry)
    register_file_tools(registry)
    register_test_tools(registry)
    register_git_tools(registry)
    register_command_tools(registry)
    return registry
