#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc mcp` -- serve the Model Context Protocol on stdio, for an AI agent.

An MCP client (Claude Code, Cursor, VS Code, Claude Desktop, ...) starts this as
a subprocess and drives PartCAD through it: the server is a client of this
workspace's daemon, like every other `pc` command, and the work is the daemon's.
See `partcad_client.mcp_server` for what it serves and why it is shaped the way
it is.

stdout is the protocol, so nothing else may be written there: the root command
turns ANSI rendering off for this one (see `command.py`), and the SDK's stdio
transport points the process's own file descriptor 1 at stderr while it serves,
so even a stray `print` cannot corrupt the stream.
"""

import os

import rich_click as click


@click.command(help="Serve the Model Context Protocol on stdio, so that an AI agent can drive PartCAD")
@click.option(
    "--allow-path",
    "allow_paths",
    multiple=True,
    type=click.Path(file_okay=False),
    help="A directory outside the workspace whose files the agent may also name (repeatable)",
)
@click.option(
    "--allow-any-path",
    is_flag=True,
    help="Let the agent name any file on this machine, not only those in the workspace",
)
@click.pass_obj
def cli(cli_ctx, allow_paths, allow_any_path) -> None:
    # Imported here: the SDK and pydantic cost a noticeable fraction of a second,
    # and `pc --help` imports every command module to print its short help.
    from partcad_client import mcp_server

    workspace = getattr(cli_ctx, "path", None) or os.getcwd()
    mcp_server.serve(workspace, allow_paths=allow_paths, allow_any_path=allow_any_path)
