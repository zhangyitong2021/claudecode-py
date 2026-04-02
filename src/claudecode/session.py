from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from .tools import ToolExecutionError, default_tools
from .types import ConfirmCallback, ToolContext, ToolResult, ToolSpec


def build_system_prompt(workspace_root: Path, tools: dict[str, ToolSpec]) -> str:
    tool_lines = "\n".join(
        f"- {tool.name} ({'read-only' if tool.read_only else 'requires approval'}): {tool.description}"
        for tool in tools.values()
    )
    return (
        "You are claudecode-py, a teaching-oriented local coding agent.\n"
        f"Workspace root: {workspace_root}\n"
        "Use tools when they help. Prefer listing files and reading files before making edits.\n"
        "All mutating tools require host approval and may be denied.\n"
        "Keep shell commands short and non-interactive.\n"
        "When editing files, make the smallest targeted change that solves the task.\n"
        "Available tools:\n"
        f"{tool_lines}"
    )


@dataclass(slots=True)
class SessionState:
    client: Any
    model: str
    workspace_root: Path
    console: Console
    tools: dict[str, ToolSpec] = field(default_factory=default_tools)
    confirm_callback: ConfirmCallback = field(default=lambda _prompt: False)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspace_root = self.workspace_root.resolve()
        if not self.messages:
            self.reset()

    def reset(self) -> None:
        self.messages = [
            {
                "role": "system",
                "content": build_system_prompt(self.workspace_root, self.tools),
            }
        ]

    def build_tool_context(self) -> ToolContext:
        return ToolContext(
            workspace_root=self.workspace_root,
            confirm=self.confirm_callback,
            console=self.console,
        )

    def run_turn(self, user_text: str) -> str:
        if not user_text.strip():
            return ""

        self.messages.append({"role": "user", "content": user_text})
        return self._run_agent_loop()

    def _run_agent_loop(self) -> str:
        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=[tool.to_openai_tool() for tool in self.tools.values()],
            )

            assistant_message = response.choices[0].message
            self.messages.append(self.serialize_assistant_message(assistant_message))

            tool_calls = getattr(assistant_message, "tool_calls", None) or []
            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    self.console.print(f"[bold yellow]tool[/bold yellow] {tool_name}")
                    result = self.execute_tool_call(tool_name, tool_call.function.arguments)
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result.output,
                        }
                    )
                continue

            return getattr(assistant_message, "content", "") or ""

    def execute_tool_call(self, tool_name: str, raw_arguments: str) -> ToolResult:
        tool = self.tools.get(tool_name)
        if tool is None:
            return ToolResult(f"ERROR: Unknown tool '{tool_name}'.", success=False)

        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return ToolResult(f"ERROR: Invalid tool arguments for '{tool_name}': {exc}", success=False)

        if not isinstance(arguments, dict):
            return ToolResult(
                f"ERROR: Tool arguments for '{tool_name}' must decode to a JSON object.",
                success=False,
            )

        if not tool.read_only:
            approved = self.confirm_callback(
                f"Allow {tool_name} with arguments {json.dumps(arguments, ensure_ascii=True)}?"
            )
            if not approved:
                return ToolResult(f"DENIED: User rejected tool '{tool_name}'.", success=False)

        try:
            return tool.run(arguments, self.build_tool_context())
        except ToolExecutionError as exc:
            return ToolResult(f"ERROR: {exc}", success=False)
        except Exception as exc:  # pragma: no cover - last resort guardrail
            return ToolResult(f"ERROR: Unexpected failure in '{tool_name}': {exc}", success=False)

    @staticmethod
    def serialize_assistant_message(message: Any) -> dict[str, Any]:
        tool_calls = getattr(message, "tool_calls", None) or []
        serialized_tool_calls = [
            {
                "id": tool_call.id,
                "type": getattr(tool_call, "type", "function"),
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in tool_calls
        ]

        payload: dict[str, Any] = {"role": "assistant", "content": getattr(message, "content", None)}
        if serialized_tool_calls:
            payload["tool_calls"] = serialized_tool_calls
        return payload
