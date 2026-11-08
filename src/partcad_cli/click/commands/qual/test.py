#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc qual test` -- run the qualification tests of a part, an assembly, a scene, a sketch or a whole package.

Every built-in test of the subtypes asked for, of each object it has something
to ask of, and every test an object declares under `qual:` itself. `--basic`,
`--topology`, `--simulation` and `--other` select subtypes and may be combined;
none of them is all four. All of it is daemon work (`qual.run`).

`--simulation` on its own is the one run that reports more than verdicts: each
simulation the object declares, run as `qual.simulate` runs it, with `-f`
selecting simulations by name, `--json` printing everything the plugin
reported, `--plugin` running them with another plugin than the one each names,
and `--before`, `--after` and `--video` saving what one run started from, ended
in and recorded (see 'simulation_output'). A simulation whose `validation:` does
not hold exits non-zero, because a simulation nobody notices failing is not a
check.
"""

import json
import sys

import rich_click as click

from ... import fast_only, object_kind
from ...exclude import exclude_option, exclude_params
from ...parameters import param_option, param_params
from ...service import run
from ...simulation_output import save_state, save_video

# The options that only a run of the simulations alone takes.
SIMULATION_OPTIONS = ("--json", "--plugin", "--before", "--after", "--video")


@click.command(
    help=(
        "Run the qualification tests of a part, an assembly, a scene or a sketch -- all four subtypes unless "
        "'--basic', '--topology', '--simulation' or '--other' say which. With '--simulation' alone, every "
        "simulation the object declares is run and reported as it ran. "
        "OBJECT may be written '...:<name>' to mean every object of that name in this "
        "package and in every package below it. " + object_kind.LOOKED_UP
    ),
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="",
    show_envvar=True,
    help="Package to retrieve the object from ('<package>...' for that package and every package below it)",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    show_envvar=True,
    help="Recursively qualify all imported packages (older spelling of '<package>...')",
)
@fast_only.option(short=False)
@click.option("--basic", is_flag=True, help="Run the basic tests: findings in words")
@click.option("--topology", is_flag=True, help="Run the topology tests: findings that are places on the object")
@click.option(
    "--simulation",
    "--sim",
    "simulation",
    is_flag=True,
    help="Run the simulations the object declares under 'qual: sim:'",
)
@click.option("--other", is_flag=True, help="Run the tests other tools supply through plugins")
@click.option(
    "--filter",
    "-f",
    help="Only run the tests whose names start with this; with '--simulation' alone, the simulations",
    type=str,
    show_envvar=True,
    default=None,
)
@click.option("--sketch", "-s", is_flag=True, show_envvar=True, help=object_kind.flag_help("a sketch"))
@click.option("--interface", "-i", is_flag=True, show_envvar=True, help=object_kind.flag_help("an interface"))
@click.option("--assembly", "-a", is_flag=True, show_envvar=True, help=object_kind.flag_help("an assembly"))
@click.option("--scene", "-S", is_flag=True, show_envvar=True, help=object_kind.flag_help("a scene"))
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help=(
        "With '--simulation' alone: print the full result of every run as JSON, including what the plugin "
        "reported; and write '--before'/'--after' as JSON rather than YAML"
    ),
)
@click.option(
    "--plugin",
    type=str,
    default=None,
    show_envvar=True,
    metavar="PACKAGE:NAME",
    help=(
        "With '--simulation' alone: run with this simulation plugin instead of the one each simulation names "
        "in its 'path:', e.g. '//pub/feature/simulate/gazebo:gazebo'"
    ),
)
@click.option(
    "--before",
    "before_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="With '--simulation' alone: save the state the simulation started from to this file (YAML, or JSON)",
)
@click.option(
    "--after",
    "after_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="With '--simulation' alone: save the state the simulation ended in to this file (YAML, or JSON)",
)
@click.option(
    "--video",
    "video_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help=(
        "With '--simulation' alone: save the video of the run the simulation plugin recorded to this file "
        "(WebM). Its size is 'simulation.videoResolution' in the configuration "
        "(PC_SIMULATION_VIDEO_RESOLUTION), HD by default"
    ),
)
@exclude_option
@param_option
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(
    cli_ctx,
    package,
    recursive,
    fast_only,
    basic,
    topology,
    simulation,
    other,
    filter,
    sketch,
    interface,
    assembly,
    scene,
    as_json,
    plugin,
    before_path,
    after_path,
    video_path,
    exclude,
    params,
    object,
):
    subtypes = [
        subtype
        for subtype, chosen in (("basic", basic), ("topology", topology), ("sim", simulation), ("other", other))
        if chosen
    ]
    if subtypes == ["sim"]:
        if sketch or interface:
            raise click.UsageError("A sketch and an interface declare no simulations: '--simulation' takes -a or -S")
        if assembly and scene:
            raise click.UsageError("OBJECT is an assembly or a scene, not both")
        simulate(
            cli_ctx,
            {
                "package": package,
                "recursive": recursive,
                "fast_only": fast_only,
                "assembly": assembly,
                "scene": scene,
                "filter": filter,
                "object": object,
                "plugin": plugin,
                # The video's bytes back with the result, to be written here:
                # the daemon may be on another machine (see 'simulation_output').
                "inline": bool(video_path),
                **param_params(params),
                **exclude_params(exclude),
            },
            as_json,
            before_path,
            after_path,
            video_path,
        )
        return
    asked = [
        name for name, value in zip(SIMULATION_OPTIONS, (as_json, plugin, before_path, after_path, video_path)) if value
    ]
    if asked:
        raise click.UsageError("%s apply to '--simulation' on its own" % ", ".join(asked))
    run(
        cli_ctx,
        "qual.run",
        {
            "package": package,
            "recursive": recursive,
            "fast_only": fast_only,
            "filter": filter,
            "subtypes": subtypes,
            "sketch": sketch,
            "interface": interface,
            "assembly": assembly,
            "scene": scene,
            "object": object,
            **param_params(params),
            **exclude_params(exclude),
        },
        needs_context=True,
    )


def simulate(cli_ctx, request: dict, as_json: bool, before_path, after_path, video_path) -> None:
    """Every simulation the object declares, run and reported as it ran: `qual.simulate`."""
    result = run(cli_ctx, "qual.simulate", request, needs_context=True)

    if result is None:
        # The package did not load; the daemon has already said so.
        raise click.ClickException("Nothing was simulated")

    # The bytes asked for to save the video, taken out of the result before
    # anything prints it: they were asked for to be written, not read.
    recordings = [entry.pop("recording", None) for entry in result.get("simulations") or []]
    if video_path:
        for entry in result.get("simulations") or []:
            entry.pop("images", None)

    if as_json:
        # To stdout, so it can be piped into `jq` no matter where the logs go.
        sys.stdout.write(json.dumps(result, indent=4) + "\n")
        sys.stdout.flush()

    # Before the verdict decides the exit status: a run whose validation did
    # not hold is exactly the run whose state somebody wants to look at.
    for moment, path in (("before", before_path), ("after", after_path)):
        if path:
            save_state(result, moment, path, as_json)
    if video_path:
        save_video(result, recordings, video_path)

    if not result.get("ok", True):
        raise click.ClickException(
            "%d of %d simulation(s) did not pass" % (result.get("failed", 0), result.get("total", 0))
        )
