"""Typer CLI for the Letta/vibe prototype.

Commands:
    vibe          — start the human feedback server
    ableton-mcp   — start the MCP bridge Letta uses to run LOM code in Live
    self-improve  — let the Claude Agent SDK edit this prototype, then restart its services
"""

from __future__ import annotations

import os

import typer
from rich.console import Console

app = typer.Typer(name="letta-vibe", help="Prototype: Letta-backed feedback loop around Ableton Live.")
console = Console()


@app.command()
def ableton_mcp(
    bridge_port: int = typer.Option(9010, "--bridge-port", help="Port for the MCP bridge HTTP server."),
    mcp_host: str = typer.Option("127.0.0.1", "--mcp-host", help="Ableton TCP host."),
    mcp_port: int = typer.Option(16619, "--mcp-port", help="Ableton TCP port."),
) -> None:
    """Start the Ableton MCP bridge server (Streamable HTTP for Letta).

    Exposes execute / api / search_api as a native MCP server so Letta can
    connect via StreamableHTTPServerConfig at http://host.docker.internal:<port>/mcp.
    """
    os.environ["ABLETON_MCP_BRIDGE_PORT"] = str(bridge_port)
    os.environ["ABLETON_MCP_HOST"] = mcp_host
    os.environ["ABLETON_TCP_PORT"] = str(mcp_port)

    from letta_vibe.mcp_server import serve

    console.print(f"[bold]Ableton MCP bridge → http://0.0.0.0:{bridge_port}/mcp[/bold]")
    console.print(f"[dim]Letta server_url: http://host.docker.internal:{bridge_port}/mcp[/dim]")
    serve()


@app.command()
def vibe(
    port: int = typer.Option(8080, "--port", help="Local vibe server port."),
    bind: str = typer.Option("127.0.0.1", "--bind", help="Interface to listen on. Loopback by default."),
    tunnel: bool = typer.Option(False, "--tunnel/--no-tunnel", help="Open ngrok tunnel (requires VIBE_TOKEN)."),
    mcp_host: str = typer.Option("127.0.0.1", "--mcp-host", help="Ableton MCP server host."),
    mcp_port: int = typer.Option(16619, "--mcp-port", help="Ableton MCP server port."),
) -> None:
    """Start the Letta-backed human feedback server."""
    from hands.live.transport import LiveClient
    from letta_vibe.vibe.server import VibeServer

    output_dir = os.environ.get("VIBE_OUTPUT_DIR", "/tmp/vibe")
    transport = LiveClient(host=mcp_host, port=mcp_port)
    server = VibeServer(transport=transport, output_dir=output_dir)

    if tunnel:
        # A tunnel makes the server public; the code-changing endpoints must be gated.
        if not os.environ.get("VIBE_TOKEN"):
            console.print("[red]--tunnel needs VIBE_TOKEN set (it gates /self-improve and /restart).[/red]")
            raise typer.Exit(1)
        os.environ["VIBE_TUNNEL"] = "1"  # every endpoint now needs the token
        from letta_vibe.vibe.tunnel import open_tunnel
        url = open_tunnel(port)
        console.print(f"[green]Tunnel open: {url}[/green]")

    console.print(f"[bold]Vibe server listening on http://{bind}:{port}[/bold]")
    console.print(f"[dim]Output dir: {output_dir}[/dim]")
    console.print("POST /bounce — trigger a bounce")
    console.print("POST /feedback — submit feedback")
    console.print("GET  /session — session info")
    server.serve(port=port, host=bind)


@app.command("self-improve")
def self_improve(
    description: str = typer.Argument(..., help="Short label for the improvement."),
    prompt: str = typer.Option(..., "--prompt", "-p", help="Full instructions for Claude Code."),
    restart: list[str] = typer.Option([], "--service", "-s", help="Service(s) to restart (repeat for multiple). Omit to auto-detect from changed files."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the prompt without running the agent."),
) -> None:
    """Apply a self-improvement to this prototype using the Claude Agent SDK.

    Claude Code will make the requested code edits, then the affected services
    are restarted automatically.

    Example:
        letta-vibe self-improve "add /health endpoint" \\
          --prompt "Add a GET /health endpoint to src/letta_vibe/vibe/server.py
                    that returns {status: ok, session_id: ...}. Follow the
                    existing _send_json pattern."
    """
    import asyncio

    if dry_run:
        console.print(f"[bold]Description:[/bold] {description}")
        console.print(f"[bold]Prompt:[/bold]\n{prompt}")
        if restart:
            console.print(f"[bold]Restart:[/bold] {', '.join(restart)}")
        else:
            console.print("[dim]Restart: auto-detect from changed files[/dim]")
        return

    try:
        from letta_vibe.self_modify import apply_improvement
    except ImportError as exc:
        console.print(f"[red]claude-agent-sdk not installed: {exc}[/red]")
        console.print("[dim]Install with: uv pip install -e '.[self-improve]'[/dim]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]Self-improve:[/bold cyan] {description}")
    console.print("[dim]Running Claude Agent SDK session…[/dim]")

    result = asyncio.run(
        apply_improvement(
            description=description,
            prompt=prompt,
            restart=restart if restart else None,
        )
    )

    if result.get("changed_files"):
        console.print(f"\n[green]Changed files ({len(result['changed_files'])}):[/green]")
        for f in result["changed_files"]:
            console.print(f"  {f}")
    else:
        console.print("[yellow]No file changes detected.[/yellow]")

    if result.get("restarted_services"):
        console.print(f"\n[green]Restarted:[/green] {', '.join(result['restarted_services'])}")
    if result.get("setup_tools_run"):
        console.print("[green]Re-registered Letta tools (make setup-tools).[/green]")

    if result.get("agent_result"):
        console.print(f"\n[dim]Agent summary:[/dim] {result['agent_result'][:300]}")


def main() -> None:
    app()
