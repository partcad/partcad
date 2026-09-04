#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc open` -- open a file in a third-party application.

Opening the file happens here, in the client process, and deliberately so.
Opening a file in FreeCAD is not work the daemon can do on anyone's behalf: a
daemon can be remote, where the window would appear on somebody else's screen
(or on a machine with no screen at all), and the path named on this command line
means nothing on the other side of the wire. It needs no package graph and no
context either -- the file is already on disk -- so there is no RPC method for
opening a file, and none should be added. Same reasoning as `pc lint --file` and
`pc upgrade`; see "Command boundary" in src/partcad_cli/AGENTS.md.

That is also why it takes a path rather than a `<package>:<part>` name:
resolving a name means loading the package graph, which is exactly the daemon
round trip this command does not make. The VS Code extension's "Open in..."
context menu passes the source file of the object the user clicked -- and no
more than that: which file KiCad is actually pointed at, given the STEP a
`kicad` part is, is a fact about KiCad and lives in the tool table.

**One thing here does cross the wire, and it is not the opening.** Two of the
applications read one thing only: Blender reads meshes, and MuJoCo reads MJCF.
A part that is not already a mesh, or a scene that is not already an MJCF model,
has to be converted before it is handed over -- and both conversions drive a CAD
wrapper, whose runtime lives in the daemon's environment and may not exist on
this machine at all. So the conversion is `adhoc.convert`, the same method
`pc adhoc convert` sends, on the same absolute paths, with `kind` saying which
of the two it is; it carries no context (it is file-in, file-out) and it leaves
nothing on the daemon to go stale. The window still opens here, from this
process, on this machine's display.

The application is run from this machine when it is installed here, and
otherwise -- with `--use-docker` -- from a container PartCAD keeps for it. The
finding, the container, the X forwarding and the rule about which types are
meshes are `partcad_client.external` and `partcad_client.object_types`, so the
extension and the CLI cannot drift apart.
"""

import json
import os

import rich_click as click

from ..service import run


@click.command(help="Open a file in a third-party application, on this machine.")
@click.option(
    "--with",
    "tool",
    type=str,
    default="freecad",
    show_default=True,
    metavar="APPLICATION",
    help="Which application to open the file in: freecad, blender, gazebo (a scene's world file), "
    "mujoco (a scene, converted to MJCF if it is not one already) or kicad (a board).",
)
@click.option(
    "--type",
    "object_type",
    type=str,
    default=None,
    metavar="TYPE",
    help="The PartCAD type the object was declared with ('step', 'cadquery', 'world', ...). Only "
    "needed when the file name does not say -- a '.py' is three different script types -- and only "
    "for an application that reads meshes or one that reads a scene description, which is what "
    "decides whether the file has to be converted first.",
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
def cli(click_ctx, tool: str, object_type: str, use_docker: bool, docker_image: str, as_json: bool, path: str) -> None:
    # Deferred: `pc --help` imports every command module to print its short
    # help, and there is no reason for that to touch the tool tables.
    from partcad_client import external

    def transcode(source: str, source_type: str, target: str, target_type: str, kind: str = "part") -> None:
        """Make ``target`` out of ``source``, on the daemon: this is CAD work.

        The only round trip this command makes, and it is made only for an
        application that cannot read what the user asked to open. ``kind`` says
        which of the two conversions it is -- a part, for an application that
        reads meshes, or a scene, for one that reads only its own description of
        an arrangement -- and it defaults to the older of the two so that a
        caller written against the four-argument form still works. Paths are
        already absolute (`external` resolved them), which is what
        `adhoc.convert` expects.
        """
        run(
            click_ctx.obj,
            "adhoc.convert",
            {
                "kind": kind,
                "input_type": source_type,
                "output_type": target_type,
                "input_filename": source,
                "output_filename": target,
            },
            needs_context=False,
        )

    try:
        result = external.open_file(
            path,
            tool=tool,
            use_docker=use_docker,
            image=docker_image,
            object_type=object_type,
            transcode=transcode,
            # Silent under --json: the caller parses stdout, and progress lines
            # would be in the way of the one thing it is there to read. (A
            # conversion still logs through the shared renderer, which
            # `--no-ansi` sends to stderr -- which is why anything parsing this
            # output passes it, as the VS Code extension does.)
            log=None if as_json else click.echo,
        )
    except (external.ExternalToolError, click.ClickException) as e:
        # A failed conversion arrives as a ClickException from `run`, and it is
        # as much a reason the file could not be opened as a missing X server
        # is: it has to reach the caller the same way rather than as a bare
        # non-zero exit.
        message = e.format_message() if isinstance(e, click.ClickException) else str(e)
        if as_json:
            # Machine-readable and self-contained, so a caller needs neither the
            # log stream nor the exit code to know what to show the user. The
            # message is the whole point of the failure -- it says which X
            # server to install, or how to let PartCAD use a container.
            click.echo(json.dumps({"ok": False, "tool": tool, "path": path, "error": message}))
            click_ctx.exit(1)
        raise click.ClickException(message)

    if as_json:
        click.echo(json.dumps(result.to_dict()))
        return
    if result.source is not None:
        # What was actually handed over, when it is not what was asked for: the
        # board beside a KiCad part's STEP, or the mesh made out of a solid.
        click.echo("Opened %s (from %s)." % (os.path.basename(result.path), os.path.basename(result.source)))
    click.echo(result.detail)
