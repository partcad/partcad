#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json

import rich_click as click

from partcad_client import location as pc_location
from partcad_utils import user_locale
from partcad_utils.user_config import UserConfig, save_options


@click.command(help="Ask this computer's location service where it is")
@click.option("--save", is_flag=True, help="Write what it says into your configuration, as 'location'")
@click.option(
    "--timeout",
    type=float,
    default=pc_location.DEFAULT_TIMEOUT,
    show_default=True,
    help="How long to wait for an answer, in seconds",
)
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@click.pass_context
def cli(click_ctx, save: bool, timeout: float, as_json: bool) -> None:
    """Windows' location service, Core Location on macOS, GeoClue on Linux.

    The system asks the user for its own permission the first time, in its own
    way; `pc system locale settings` opens the page where that is changed later.
    What is printed and saved is rounded to two decimals - about a kilometre -
    which is enough to tell which shop is nearest, and all PartCAD uses it for.

    Running it is asking, so it asks whether or not 'locationAccess' is on:
    that option is what lets the IDE ask on its own, when it starts.
    """
    located = pc_location.locate(timeout)
    answer = located.to_dict()
    if located.found:
        rounded = user_locale.rounded_location({"latitude": located.latitude, "longitude": located.longitude})
        answer["location"] = rounded
        if save:
            # Not written when it has not moved: writing the file restarts the
            # daemon that read it, the IDE asks again every day, and no two
            # answers of a location service are the same (see 'moved').
            if not user_locale.moved(UserConfig().location, rounded, located.accuracy):
                answer["unchanged"] = True
            else:
                answer["saved"] = save_options({"location": rounded}, {"location": None})

    if as_json:
        click.echo(json.dumps(answer))
    elif located.found:
        click.echo("%s, %s" % (answer["location"]["latitude"], answer["location"]["longitude"]))
        if "saved" in answer:
            click.echo("Saved to %s" % answer["saved"])
    else:
        click.echo(located.message(), err=True)
    if not located.found:
        click_ctx.exit(1)
