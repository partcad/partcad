#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


@click.command(
    help=(
        "Compare a part or an assembly with another: CURRENT against REFERENCE. Reports how their volumes "
        "and masses differ, how precisely each is to be made, with --displacement how their displacements "
        "differ (the volume and every void sealed inside it), and -- with --surface-distance -- how far the "
        "surface of CURRENT is from the surface of REFERENCE, measured along the normals of REFERENCE at "
        "points that far apart (every vertex, then the edges, then the faces), against the tolerances of both "
        "added up. Differences are CURRENT less REFERENCE, percentages are of REFERENCE. Exits non-zero when "
        "something it is held to does not hold: the surface, when measured, and any --max-... limit given. "
        "Parameter values are written into a name: 'bolt;length=10'."
    ),
)
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve both objects from, unless a name says its own ('//<package>:<name>')",
    default=None,
    show_envvar=True,
)
@click.option(
    "--surface-distance",
    "surface_distance",
    type=click.FloatRange(min=0, min_open=True),
    metavar="MM",
    help=(
        "Also measure the surface distance, at points this many millimetres apart on REFERENCE. "
        "Every point is a sandbox intersection, so a smaller spacing is slower"
    ),
    default=None,
    show_envvar=True,
)
@click.option(
    "--displacement",
    "displacement",
    help=(
        "Also compare the displacements: what each would push aside if submerged, its volume and every void "
        "sealed inside it (not a hole right through it). Measured in a sandbox"
    ),
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "--max-volume-difference",
    "max_volume_difference",
    type=click.FloatRange(min=0),
    metavar="PERCENT",
    help="Fail unless the volume of CURRENT is within this many percent of the volume of REFERENCE",
    default=None,
    show_envvar=True,
)
@click.option(
    "--max-displacement-difference",
    "max_displacement_difference",
    type=click.FloatRange(min=0),
    metavar="PERCENT",
    help=(
        "Fail unless the displacement of CURRENT is within this many percent of the displacement of REFERENCE. "
        "Implies --displacement"
    ),
    default=None,
    show_envvar=True,
)
@click.option(
    "--max-mass-difference",
    "max_mass_difference",
    type=click.FloatRange(min=0),
    metavar="PERCENT",
    help="Fail unless the mass of CURRENT is within this many percent of the mass of REFERENCE",
    default=None,
    show_envvar=True,
)
@click.option(
    "--worst",
    "worst",
    type=click.IntRange(min=0),
    help="How many of the points furthest apart to list, with where they are",
    default=10,
    show_default=True,
    show_envvar=True,
)
@click.option(
    "--json",
    "as_json",
    help="Print the comparison as the JSON object it is, instead of as a report",
    is_flag=True,
    show_envvar=True,
)
@click.argument("reference", type=str, required=True)
@click.argument("current", type=str, required=True)
@click.pass_obj
def cli(
    cli_ctx,
    package,
    surface_distance,
    displacement,
    max_volume_difference,
    max_displacement_difference,
    max_mass_difference,
    worst,
    as_json,
    reference,
    current,
):
    """Read CURRENT against REFERENCE.

    A daemon command: the volumes and masses are the package graph's, and the
    displacement and the surface distance drive CAD wrappers. The report is printed by the daemon
    through PartCAD logging, so that what a user sees does not depend on which
    client asked; `--json` is the exception, since a machine-readable object has
    to reach stdout of *this* process to be piped anywhere. What stays here is
    the exit code, which makes the command a gate in a script.
    """
    result = run(
        cli_ctx,
        "compare.objects",
        {
            "package": package,
            "object": reference,
            "current": current,
            "surface_distance": surface_distance,
            "displacement": displacement,
            "max_volume_difference": max_volume_difference,
            "max_displacement_difference": max_displacement_difference,
            "max_mass_difference": max_mass_difference,
            "worst": worst,
            "json": as_json,
        },
        needs_context=True,
    )
    if as_json:
        import json

        click.echo(json.dumps(result, indent=2))

    # Printed first, then failed: a caller piping '--json' has as much use for
    # the numbers as for the verdict.
    if result is not None and result.get("passed") is False:
        raise click.ClickException("%s does not hold to %s" % (current, reference))
