from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from openai import OpenAI
from rich.console import Console
from rich.prompt import Confirm

from .session import SessionState
from .tools import default_tools


app = typer.Typer(
    add_completion=False,
    help="A teaching-oriented Claude Code style coding agent.",
    no_args_is_help=True,
)


@app.callback()
def root() -> None:
    """Root CLI entry point."""


def confirm_action(prompt: str) -> bool:
    return Confirm.ask(prompt, default=False)


def show_help(console: Console) -> None:
    console.print("Available commands:")
    console.print("  /help   Show this help message")
    console.print("  /tools  Show the built-in tools")
    console.print("  /reset  Clear the in-memory conversation")
    console.print("  /exit   Exit the REPL")


def show_tools(console: Console) -> None:
    console.print("Built-in tools:")
    for tool in default_tools().values():
        mode = "read-only" if tool.read_only else "requires approval"
        console.print(f"  - {tool.name} [{mode}]: {tool.description}")


def handle_slash_command(command: str, session: SessionState, console: Console) -> bool:
    normalized = command.strip()
    if normalized == "/help":
        show_help(console)
        return True
    if normalized == "/tools":
        show_tools(console)
        return True
    if normalized == "/reset":
        session.reset()
        console.print("[green]Session reset.[/green]")
        return True
    if normalized in {"/exit", "/quit"}:
        return False

    console.print(f"[red]Unknown command:[/red] {normalized}")
    show_help(console)
    return True


def run_repl(session: SessionState, console: Console) -> None:
    console.print("[bold cyan]claudecode-py[/bold cyan]")
    console.print(f"Workspace: {session.workspace_root}")
    console.print(f"Model: {session.model}")
    console.print("Type /help for commands.\n")

    while True:
        try:
            user_input = console.input("[bold blue]you>[/bold blue] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting.[/dim]")
            break

        if not user_input.strip():
            continue
        if user_input.startswith("/"):
            if not handle_slash_command(user_input, session, console):
                console.print("[dim]Bye.[/dim]")
                break
            continue

        try:
            console.print("[dim]Thinking...[/dim]")
            reply = session.run_turn(user_input)
        except KeyboardInterrupt:
            console.print("[red]Interrupted while waiting for the model.[/red]")
            continue
        except Exception as exc:
            console.print(f"[red]Request failed:[/red] {exc}")
            continue

        if reply.strip():
            console.print(f"[bold magenta]assistant>[/bold magenta] {reply}\n")
        else:
            console.print("[bold magenta]assistant>[/bold magenta] (no text response)\n")


@app.command()
def chat(
    cwd: Optional[Path] = typer.Option(None, help="Workspace directory for file and shell tools."),
    model: Optional[str] = typer.Option(None, help="Model name for the OpenAI-compatible backend."),
    base_url: Optional[str] = typer.Option(None, help="Base URL for an OpenAI-compatible API."),
) -> None:
    console = Console()
    workspace_root = (cwd or Path.cwd()).resolve()
    if not workspace_root.exists() or not workspace_root.is_dir():
        console.print(f"[red]Invalid workspace directory:[/red] {workspace_root}")
        raise typer.Exit(code=1)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        console.print("[red]Missing OPENAI_API_KEY.[/red] Set it before starting the CLI.")
        raise typer.Exit(code=1)

    resolved_model = model or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    resolved_base_url = base_url or os.getenv("OPENAI_BASE_URL")
    client = OpenAI(api_key=api_key, base_url=resolved_base_url)

    session = SessionState(
        client=client,
        model=resolved_model,
        workspace_root=workspace_root,
        console=console,
        tools=default_tools(),
        confirm_callback=confirm_action,
    )
    run_repl(session, console)


def main() -> None:
    app()
