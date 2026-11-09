#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc qual test --simulation` writes beside its verdict: the states and the video of one run.

Done here rather than by the daemon: the daemon may be on another machine, where
a path would name a file nobody here could open. It sends the two states and,
asked, the video's bytes back with the result, and this process writes them --
the states as YAML, which reads, unless '--json' was asked for or the path ends
in '.json'.
"""

import json
import os

import rich_click as click

from partcad_utils import framing


def save_video(result: dict, recordings: list, path: str) -> None:
    """Write the video one simulation's plugin recorded to 'path', or say why not.

    One simulation's, for the reason 'save_state' saves one state.
    """
    simulations = result.get("simulations") or []
    if len(simulations) != 1:
        raise click.ClickException(
            "--video saves the video of one simulation, and %d ran: name the object, and the simulation with -f"
            % len(simulations)
        )
    (simulation,) = simulations
    (recording,) = recordings
    if not recording or not recording.get("content"):
        if simulation.get("error"):
            why = simulation["error"]
        elif simulation.get("video"):
            why = "it could not be read back"
        else:
            why = (
                "its plugin recorded none -- one that predates videos, or one that could not record it on this "
                "machine says why among its warnings -- or 'simulation.videoResolution' is 'none'"
            )
        raise click.ClickException(
            "%s: the simulation '%s' has no video to save: %s"
            % (simulation.get("object"), simulation.get("simulation"), why)
        )

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "wb") as f:
        # Its bytes, or base64 from a daemon that sends no attachments.
        f.write(framing.as_bytes(recording["content"]))
    # To stderr: with '--json', stdout is the result and nothing else.
    click.echo("Saved the video of the simulation '%s' to %s" % (simulation.get("simulation"), path), err=True)


def save_state(result: dict, moment: str, path: str, as_json: bool) -> None:
    """Write one simulation's 'before' or 'after' to 'path', or say why not.

    One simulation's: the file is that run's state, and a file holding several
    keyed by name would be a different shape depending on how many ran, which
    is not something a script reading it can rely on. So more than one is
    refused, and '-f' is how to name the one wanted.
    """
    simulations = result.get("simulations") or []
    if len(simulations) != 1:
        raise click.ClickException(
            "--%s saves the state of one simulation, and %d ran: name the object, and the "
            "simulation with -f" % (moment, len(simulations))
        )
    (simulation,) = simulations
    state = (simulation.get("result") or {}).get(moment)
    if state is None:
        raise click.ClickException(
            "%s: the simulation '%s' has no '%s' to save: %s"
            % (
                simulation.get("object"),
                simulation.get("simulation"),
                moment,
                simulation.get("error") or "its plugin reported none",
            )
        )

    if as_json or path.lower().endswith(".json"):
        text = json.dumps(state, indent=2) + "\n"
    else:
        import yaml

        # Flow style for the innermost lists, so that a position or a quaternion
        # is a line rather than a column.
        text = yaml.safe_dump(state, sort_keys=False, default_flow_style=None, allow_unicode=True)

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # To stderr: with '--json', stdout is the result and nothing else.
    click.echo(
        "Saved the state %s the simulation '%s' to %s" % (moment, simulation.get("simulation"), path),
        err=True,
    )
