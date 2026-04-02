from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .types import ToolContext, ToolResult, ToolSpec


class ToolExecutionError(RuntimeError):
    """Raised when a tool cannot complete safely."""


def display_path(path: Path, workspace_root: Path) -> str:
    relative = path.relative_to(workspace_root)
    return "." if str(relative) == "." else str(relative)


def resolve_workspace_path(
    workspace_root: Path,
    raw_path: str,
    *,
    allow_missing: bool = False,
) -> Path:
    workspace_root = workspace_root.resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate

    candidate = candidate.resolve(strict=False)

    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise ToolExecutionError(
            f"Path '{raw_path}' is outside the workspace root '{workspace_root}'."
        ) from exc

    if not allow_missing and not candidate.exists():
        raise ToolExecutionError(f"Path does not exist: {display_path(candidate, workspace_root)}")

    return candidate


def format_numbered_lines(lines: list[str], start_line: int) -> str:
    width = len(str(start_line + len(lines)))
    return "\n".join(
        f"{line_number:>{width}} | {line}"
        for line_number, line in enumerate(lines, start=start_line)
    )


def list_files_tool(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    target = resolve_workspace_path(ctx.workspace_root, str(args.get("path", ".")))

    if target.is_file():
        stat = target.stat()
        rel = display_path(target, ctx.workspace_root)
        return ToolResult(f"{rel} is a file ({stat.st_size} bytes).")

    entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    rel = display_path(target, ctx.workspace_root)
    if not entries:
        return ToolResult(f"Directory '{rel}' is empty.")

    lines = [f"Listing for '{rel}':"]
    for entry in entries:
        kind = "dir " if entry.is_dir() else "file"
        lines.append(f"- [{kind}] {display_path(entry, ctx.workspace_root)}")
    return ToolResult("\n".join(lines))


def read_file_tool(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    raw_path = args.get("path")
    if not raw_path:
        raise ToolExecutionError("'path' is required.")

    target = resolve_workspace_path(ctx.workspace_root, str(raw_path))
    if not target.is_file():
        raise ToolExecutionError(f"Path is not a file: {display_path(target, ctx.workspace_root)}")

    start_line = int(args.get("start_line") or 1)
    end_line = args.get("end_line")
    end_line = int(end_line) if end_line is not None else None

    if start_line < 1:
        raise ToolExecutionError("'start_line' must be at least 1.")
    if end_line is not None and end_line < start_line:
        raise ToolExecutionError("'end_line' must be greater than or equal to 'start_line'.")

    content = target.read_text(encoding="utf-8")
    lines = content.splitlines()

    start_index = start_line - 1
    selected = lines[start_index:end_line]
    rel = display_path(target, ctx.workspace_root)

    if not selected:
        return ToolResult(f"Contents of '{rel}' for lines {start_line}-{end_line or start_line}: (no content)")

    last_line = start_line + len(selected) - 1
    body = format_numbered_lines(selected, start_line)
    return ToolResult(f"Contents of '{rel}' (lines {start_line}-{last_line}):\n{body}")


def write_file_tool(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    raw_path = args.get("path")
    if not raw_path:
        raise ToolExecutionError("'path' is required.")

    target = resolve_workspace_path(ctx.workspace_root, str(raw_path), allow_missing=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    content = str(args.get("content", ""))
    target.write_text(content, encoding="utf-8")
    rel = display_path(target, ctx.workspace_root)
    return ToolResult(f"Wrote {len(content)} characters to '{rel}'.")


def replace_in_file_tool(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    raw_path = args.get("path")
    if not raw_path:
        raise ToolExecutionError("'path' is required.")

    old_text = str(args.get("old_text", ""))
    new_text = str(args.get("new_text", ""))
    count = int(args.get("count", 1))

    if not old_text:
        raise ToolExecutionError("'old_text' must not be empty.")
    if count < 1:
        raise ToolExecutionError("'count' must be at least 1.")

    target = resolve_workspace_path(ctx.workspace_root, str(raw_path))
    if not target.is_file():
        raise ToolExecutionError(f"Path is not a file: {display_path(target, ctx.workspace_root)}")

    content = target.read_text(encoding="utf-8")
    matches = content.count(old_text)
    if matches == 0:
        raise ToolExecutionError("The target text was not found in the file.")

    replacements = min(matches, count)
    updated = content.replace(old_text, new_text, count)
    target.write_text(updated, encoding="utf-8")
    rel = display_path(target, ctx.workspace_root)
    return ToolResult(f"Replaced {replacements} occurrence(s) in '{rel}'.")


def run_shell_tool(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    command = str(args.get("command", "")).strip()
    if not command:
        raise ToolExecutionError("'command' must not be empty.")

    timeout_sec = int(args.get("timeout_sec", 60))
    if timeout_sec < 1 or timeout_sec > 600:
        raise ToolExecutionError("'timeout_sec' must be between 1 and 600.")

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=ctx.workspace_root,
            executable=ctx.shell,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        lines = [f"Command timed out after {timeout_sec} second(s): {command}"]
        if stdout:
            lines.append(f"STDOUT:\n{stdout}")
        if stderr:
            lines.append(f"STDERR:\n{stderr}")
        return ToolResult("\n".join(lines), success=False)

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    lines = [
        f"Command: {command}",
        f"Exit code: {completed.returncode}",
    ]
    if stdout:
        lines.append(f"STDOUT:\n{stdout}")
    if stderr:
        lines.append(f"STDERR:\n{stderr}")
    if not stdout and not stderr:
        lines.append("(no output)")

    return ToolResult("\n".join(lines), success=completed.returncode == 0)


def default_tools() -> dict[str, ToolSpec]:
    return {
        "list_files": ToolSpec(
            name="list_files",
            description="List files and directories under a workspace path.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory or file path relative to the workspace root.",
                        "default": ".",
                    }
                },
                "additionalProperties": False,
            },
            read_only=True,
            run=list_files_tool,
        ),
        "read_file": ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file, optionally with line bounds.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace root.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based starting line number.",
                        "minimum": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-based ending line number.",
                        "minimum": 1,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            read_only=True,
            run=read_file_tool,
        ),
        "write_file": ToolSpec(
            name="write_file",
            description="Write full UTF-8 file contents. Creates parent directories if needed.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            read_only=False,
            run=write_file_tool,
        ),
        "replace_in_file": ToolSpec(
            name="replace_in_file",
            description="Replace a target string in an existing UTF-8 text file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace root.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Text to replace.",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Maximum number of replacements.",
                        "default": 1,
                        "minimum": 1,
                    },
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
            read_only=False,
            run=replace_in_file_tool,
        ),
        "run_shell": ToolSpec(
            name="run_shell",
            description="Run a non-interactive shell command in the workspace root.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                    "timeout_sec": {
                        "type": "integer",
                        "description": "Timeout in seconds.",
                        "default": 60,
                        "minimum": 1,
                        "maximum": 600,
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            read_only=False,
            run=run_shell_tool,
        ),
    }
