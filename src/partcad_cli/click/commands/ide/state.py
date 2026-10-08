#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ide state` -- what the PartCAD IDE on this machine is showing, as data.

Three views, as one document: the PartCAD Explorer (what is selected in it, by
full path and kind), the PartCAD Inspector (the selected object's properties, its
parameters and what each field holds now) and the PartCAD Viewer (the tab and
sub-tab on screen, the filter and the selections of every sub-tab, and a
screenshot of the one on screen). It is what an agent working beside a person
reads to know what that person is looking at, and what a bug report attaches.

Asked of the IDE over the socket it already listens on for 'show' (see
`partcad_ide_client.protocol.MSG_STATE`), so it needs no daemon, no package and
no workspace: the IDE is on this machine or nowhere, the same reason
`pc ide open` stays here. The screenshot is written by the IDE into its own
temporary directory -- /tmp on Linux -- and only its path comes back.
"""

import json
import sys

import rich_click as click

from partcad_ide_client import STATE_TIMEOUT, StateNotSupported, ViewerNotAvailable, state


@click.command(
    help="Print what the PartCAD IDE on this machine is showing: the Explorer's selection, the Inspector's "
    "properties and parameters, and the Viewer's tab, sub-tab, filters, selections and a screenshot."
)
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@click.option("--yaml", "as_yaml", is_flag=True, help="Print YAML (the default)")
@click.option(
    "--timeout",
    type=float,
    default=STATE_TIMEOUT,
    show_default=True,
    help="Seconds to wait for the IDE to answer",
)
def cli(as_json: bool, as_yaml: bool, timeout: float) -> None:
    if as_json and as_yaml:
        raise click.UsageError("--json and --yaml are two answers to one question; pass one of them.")
    try:
        answer = state(reply_timeout=timeout)
    except ViewerNotAvailable:
        raise click.ClickException(
            "No PartCAD IDE is running on this machine (nothing is listening on the PartCAD Viewer port). "
            "Open VS Code with the PartCAD extension, or the PartCAD IDE, and try again."
        )
    except StateNotSupported as e:
        raise click.ClickException(str(e))
    except (OSError, ValueError) as e:
        raise click.ClickException("The PartCAD IDE did not answer: %s" % e)

    if as_json:
        json.dump(answer, sys.stdout, indent=2, sort_keys=False)
        sys.stdout.write("\n")
        return
    import yaml

    yaml.safe_dump(answer, sys.stdout, sort_keys=False, allow_unicode=True, default_flow_style=False)
