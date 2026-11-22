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
@click.option(
    "--root",
    "root",
    type=str,
    default=None,
    help="The PartCAD root to serve, relative to the folder of the agent configuration naming it (.mcp.json, "
    ".codex/config.toml, ...), which is looked for from the current directory upwards: what 'pc init' writes there. "
    "By hand, name a directory with '-p' instead",
)
@click.option(
    "--from",
    "source",
    type=str,
    default=None,
    help="With --root: the agent configuration naming it, relative to its folder (.mcp.json, .codex/config.toml, "
    "...), which is then the only file looked in. 'pc init' writes it",
)
@click.pass_obj
def cli(cli_ctx, allow_paths, allow_any_path, root, source) -> None:
    # Imported here: the SDK and pydantic cost a noticeable fraction of a second,
    # and `pc --help` imports every command module to print its short help.
    from partcad_client import mcp_server

    workspace = getattr(cli_ctx, "path", None)
    if root is not None:
        # Where the entry `pc init` wrote is, rather than where the agent
        # started this: see `partcad_utils.agent_config` for why those differ.
        from partcad_utils import agent_config

        if workspace:
            raise click.UsageError("'-p' and '--root' both say what to serve; give one of them")
        workspace = agent_config.resolve_root(os.getcwd(), root, source)
        if workspace is None:
            raise click.UsageError(
                "'--root %s' is relative to the folder of the agent configuration naming it (.mcp.json, "
                ".codex/config.toml, ...), and there is none in '%s' or above: start the agent in the folder "
                "holding the configuration that starts this server, or name the directory with '-p'"
                % (root, os.getcwd())
            )
        if not os.path.isdir(workspace):
            raise click.UsageError("'--root %s' is '%s', which does not exist" % (root, workspace))
    elif source is not None:
        raise click.UsageError("'--from' says which configuration names '--root'; give it with '--root'")
    mcp_server.serve(workspace or os.getcwd(), allow_paths=allow_paths, allow_any_path=allow_any_path)
