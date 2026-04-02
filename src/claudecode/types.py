from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rich.console import Console


ConfirmCallback = Callable[[str], bool]
ToolRunner = Callable[[dict[str, Any], "ToolContext"], "ToolResult"]


@dataclass(slots=True)
class ToolResult:
    output: str
    success: bool = True


@dataclass(slots=True)
class ToolContext:
    workspace_root: Path
    confirm: ConfirmCallback
    console: Console
    shell: str = field(default_factory=lambda: os.environ.get("SHELL", "/bin/zsh"))


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    run: ToolRunner

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
