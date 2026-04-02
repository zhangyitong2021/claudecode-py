from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from claudecode.tools import ToolExecutionError, default_tools, resolve_workspace_path
from claudecode.types import ToolContext


def make_context(tmp_path):
    return ToolContext(
        workspace_root=tmp_path,
        confirm=lambda _prompt: True,
        console=Console(file=StringIO(), force_terminal=False),
    )


def test_resolve_workspace_path_rejects_escape(tmp_path):
    with pytest.raises(ToolExecutionError):
        resolve_workspace_path(tmp_path, "../outside.txt", allow_missing=True)


def test_read_file_supports_line_ranges(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    ctx = make_context(tmp_path)

    result = default_tools()["read_file"].run(
        {"path": "notes.txt", "start_line": 2, "end_line": 3},
        ctx,
    )

    assert "lines 2-3" in result.output
    assert "2 | beta" in result.output
    assert "3 | gamma" in result.output


def test_write_file_creates_missing_parents(tmp_path):
    ctx = make_context(tmp_path)
    result = default_tools()["write_file"].run(
        {"path": "nested/example.txt", "content": "hello"},
        ctx,
    )

    assert "nested/example.txt" in result.output
    assert (tmp_path / "nested" / "example.txt").read_text(encoding="utf-8") == "hello"


def test_run_shell_reports_timeout(tmp_path):
    ctx = make_context(tmp_path)
    result = default_tools()["run_shell"].run(
        {"command": "python3 -c 'import time; time.sleep(2)'", "timeout_sec": 1},
        ctx,
    )

    assert result.success is False
    assert "timed out" in result.output
