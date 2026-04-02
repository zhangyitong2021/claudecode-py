from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from claudecode.cli import app


runner = CliRunner()


def test_chat_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(app, ["chat", "--cwd", str(tmp_path)])

    assert result.exit_code == 1
    assert "OPENAI_API_KEY" in result.output


def test_chat_rejects_missing_workspace(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    missing = Path("/tmp/claudecode-py-missing-workspace")

    result = runner.invoke(app, ["chat", "--cwd", str(missing)])

    assert result.exit_code == 1
    assert "Invalid workspace directory" in result.output
