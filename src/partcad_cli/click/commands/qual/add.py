#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc qual add` -- declare a qualification test of an object, in its package's `partcad.yaml`.

Writes `<object>.qual.<subtype>.<name>`:

    pc qual add --other --path //pub/qual/lockwire:lockwire --set lockfile=rover.lockwire.yaml rover budgets
    pc qual add --simulation --path sim-mujoco:mujoco --set validation='after["bodies"]["b"]["pos"][2] > 0' b stands
    pc qual add --topology --set minArea=1.0 bracket tolerance-surfaces       # a built-in check's parameters

A check a plugin supplies needs `--path`, the plugin, and is resolved before
anything is written; a built-in check takes no `--path`, and what is written is
its parameters. Every `--set KEY=VALUE` is one more key of the entry, its value
read as the same text is read in `partcad.yaml` (`--set minArea=1.0` is a
number, `--set general=false` a boolean, `--set limit='>5'` the text: see
'config_yaml.scalar'). An entry of that name that is there already is refused
unless `--replace`. Daemon work (`qual.add`), because it writes a declaration
the warm context then has to read again, as `pc add` does.
"""

import rich_click as click

from partcad_utils import config_yaml

from ... import object_kind
from ...service import run


def _value(text: str):
    """A '--set' value, as the same text in 'partcad.yaml' reads: numbers, booleans and lists as themselves."""
    return config_yaml.scalar(text)


@click.command(
    help=(
        "Declare a qualification test of OBJECT under NAME: a check a plugin supplies ('--path'), a simulation "
        "('--simulation --path'), or the parameters of a built-in check. " + object_kind.LOOKED_UP
    ),
)
@click.option("--basic", "subtype", flag_value="basic", help="A basic test")
@click.option("--topology", "subtype", flag_value="topology", help="A topology test")
@click.option("--simulation", "--sim", "subtype", flag_value="sim", help="A simulation")
@click.option("--other", "subtype", flag_value="other", default=True, help="A test of another tool's (the default)")
@click.option(
    "--path",
    type=str,
    default=None,
    metavar="PACKAGE:NAME",
    help="The plugin that runs it: a 'qual:' entry of that package, or a 'simulation:' one for a simulation",
)
@click.option(
    "--set",
    "settings",
    multiple=True,
    metavar="KEY=VALUE",
    help="A key of the entry and its value, read as YAML: a parameter, or a simulation's 'scene', 'validation'...",
)
@click.option("--desc", type=str, default=None, help="What the test is for, in words")
@click.option(
    "--replace",
    is_flag=True,
    help="Replace the test if OBJECT declares one of that NAME already; without this, one that is there is refused",
)
@click.option("--package", "-P", type=str, default="", show_envvar=True, help="Package to find the object in")
@click.option("--assembly", "-a", is_flag=True, help=object_kind.flag_help("an assembly"))
@click.option("--scene", "-S", is_flag=True, help=object_kind.flag_help("a scene"))
@click.option("--sketch", "-s", is_flag=True, help=object_kind.flag_help("a sketch"))
@click.argument("object", type=str)
@click.argument("name", type=str)
@click.pass_obj
def cli(cli_ctx, subtype, path, settings, desc, replace, package, assembly, scene, sketch, object, name):
    entry = {}
    if desc:
        entry["desc"] = desc
    for setting in settings:
        key, sep, value = setting.partition("=")
        if not sep or not key:
            raise click.BadParameter("'%s' is not KEY=VALUE" % setting, param_hint="--set")
        entry[key.strip()] = _value(value)
    run(
        cli_ctx,
        "qual.add",
        {
            "package": package,
            "object": object,
            "assembly": assembly,
            "scene": scene,
            "sketch": sketch,
            "subtype": subtype or "other",
            "name": name,
            "path": path,
            "entry": entry,
            "replace": replace,
        },
        needs_context=True,
    )
