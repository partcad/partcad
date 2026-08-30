#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc open` -- open a file in a third-party application.

Entirely in the client process, and deliberately so. Opening a file in FreeCAD
is not work the daemon can do on anyone's behalf: a daemon can be remote, where
the window would appear on somebody else's screen (or on a machine with no
screen at all), and the path named on this command line means nothing on the
other side of the wire. It needs no package graph, no CAD runtime and no
context either -- the file is already on disk -- so there is no RPC method for
it and none should be added. Same reasoning as `pc lint --file` and
`pc upgrade`; see "Command boundary" in src/partcad_cli/AGENTS.md.

That is also why it takes a path rather than a `<package>:<part>` name:
resolving a name means loading the package graph, which is exactly the daemon
round trip this command does not make. The VS Code extension's "Open in..."
context menu passes the source file of the object the user clicked -- and no
more than that: which file KiCad is actually pointed at, given the STEP a
`kicad` part is, is a fact about KiCad and lives in the tool table.

The application is run from this machine when it is installed here, and
otherwise -- with `--use-docker` -- from a container PartCAD keeps for it. The
finding, the container and the X forwarding are `partcad_client.external`, so
the extension and the CLI cannot drift apart.
"""

import json

import rich_click as click


@click.command(help="Open a file in a third-party application, on this machine.")
@click.option(
    "--with",
    "tool",
    type=str,
    default="freecad",
    show_default=True,
    metavar="APPLICATION",
    help="Which application to open the file in: freecad, gazebo (a scene's world file) or kicad (a board).",
)
@click.option(
    "--use-docker",
    is_flag=True,
    help="If the application is not installed here, run it in a container PartCAD keeps for it.",
)
@click.option(
    "--docker-image",
    type=str,
    default=None,
    metavar="IMAGE",
    help="Create that container from this image instead of the application's default one.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print what happened as JSON, including the reason on failure.",
)
@click.argument("path", type=str, required=True)
@click.pass_context
def cli(click_ctx, tool: str, use_docker: bool, docker_image: str, as_json: bool, path: str) -> None:
    # Deferred: `pc --help` imports every command module to print its short
    # help, and there is no reason for that to touch the tool tables.
    from partcad_client import external

    try:
        result = external.open_file(
            path,
            tool=tool,
            use_docker=use_docker,
            image=docker_image,
            # Silent under --json: the caller parses stdout, and progress lines
            # would be in the way of the one thing it is there to read.
            log=None if as_json else click.echo,
        )
    except external.ExternalToolError as e:
        if as_json:
            # Machine-readable and self-contained, so a caller needs neither the
            # log stream nor the exit code to know what to show the user. The
            # message is the whole point of the failure -- it says which X
            # server to install, or how to let PartCAD use a container.
            click.echo(json.dumps({"ok": False, "tool": tool, "path": path, "error": str(e)}))
            click_ctx.exit(1)
        raise click.ClickException(str(e))

    if as_json:
        click.echo(json.dumps(result.to_dict()))
        return
    click.echo(result.detail)
