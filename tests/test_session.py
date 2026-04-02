from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from claudecode.session import SessionState
from claudecode.tools import default_tools


def make_response(*, content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def make_tool_call(tool_id: str, name: str, arguments: dict[str, object]):
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    return SimpleNamespace(id=tool_id, type="function", function=function)


class FakeCompletions:
    def __init__(self, parent):
        self.parent = parent

    def create(self, *, model, messages, tools):
        self.parent.calls.append({"model": model, "messages": messages, "tools": tools})
        if not self.parent.responses:
            raise AssertionError("No fake responses left.")
        return self.parent.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=FakeCompletions(self))


def make_session(tmp_path, client, confirm_callback=lambda _prompt: True):
    return SessionState(
        client=client,
        model="test-model",
        workspace_root=tmp_path,
        console=Console(file=StringIO(), force_terminal=False),
        tools=default_tools(),
        confirm_callback=confirm_callback,
    )


def test_agent_loop_executes_tool_then_returns_final_text(tmp_path):
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    client = FakeClient(
        [
            make_response(tool_calls=[make_tool_call("call_1", "list_files", {"path": "."})]),
            make_response(content="I listed the workspace."),
        ]
    )
    session = make_session(tmp_path, client)

    reply = session.run_turn("What is in this folder?")

    assert reply == "I listed the workspace."
    assert [message["role"] for message in session.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert "Listing for '.'" in session.messages[3]["content"]
    assert len(client.calls) == 2


def test_agent_loop_handles_multiple_tool_rounds_in_order(tmp_path):
    (tmp_path / "README.md").write_text("line one\nline two\n", encoding="utf-8")
    client = FakeClient(
        [
            make_response(tool_calls=[make_tool_call("call_1", "list_files", {"path": "."})]),
            make_response(tool_calls=[make_tool_call("call_2", "read_file", {"path": "README.md"})]),
            make_response(content="Done."),
        ]
    )
    session = make_session(tmp_path, client)

    reply = session.run_turn("Inspect the project.")

    assert reply == "Done."
    assert session.messages[3]["role"] == "tool"
    assert session.messages[5]["role"] == "tool"
    assert "README.md" in session.messages[5]["content"]


def test_mutating_tool_is_denied_without_confirmation(tmp_path):
    session = make_session(
        tmp_path,
        client=FakeClient([]),
        confirm_callback=lambda _prompt: False,
    )

    result = session.execute_tool_call(
        "write_file",
        json.dumps({"path": "blocked.txt", "content": "nope"}),
    )

    assert result.success is False
    assert "DENIED" in result.output
    assert not (tmp_path / "blocked.txt").exists()
