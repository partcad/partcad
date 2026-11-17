#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What every `pc req` command takes, said once: the object, and how a value is given.

`pc req add <kind>` and `pc req remove <kind>` are a command per kind of
requirement, because each kind is written differently -- a port is a location,
a match a percentage per amount -- and each command then has the options of its
own kind and the help that goes with them. Their options may come anywhere
after the kind (`pc req add port --replace bracket top`): each kind is the
command that introduces them.

A value is given one of two ways, and both mean what the same text means in
`partcad.yaml`:

  * on the command line, one value per word, each read as YAML reads that text
    ('config_yaml.scalar'): `5` is the number, `null` is no value, and `'>0'` --
    quoted for the shell, which would otherwise redirect -- is the comparison.
    No YAML quoting is needed there: a word is one value whatever it starts with.
  * with `--stdin`, as the YAML (or, with `--json`, the JSON) of what the
    requirement's place in the section holds -- the same text that would be
    written there by hand, with YAML's quoting: a comparison that starts with
    `>`, `|` or `!` is written in quotes, `'>0'`.
"""

import json
import sys

import rich_click as click
import yaml

from partcad_utils import config_yaml

from . import object_kind

# What the help of a command that reads a value from standard input says about it.
STDIN_HELP = (
    "Read the requirement from standard input instead of from the options: the YAML of what its place in the "
    "'requirements:' section holds, as it would be written there by hand (so quoted where YAML needs it: '>0', "
    "'!0'), or JSON with '--json'"
)


def object_options(command):
    """-P, and the flags saying what kind of object OBJECT is."""
    for option in reversed(
        (
            click.option(
                "--package", "-P", type=str, default="", show_envvar=True, help="Package to find the object in"
            ),
            click.option("--assembly", "-a", is_flag=True, help=object_kind.flag_help("an assembly")),
            click.option("--scene", "-S", is_flag=True, help=object_kind.flag_help("a scene")),
            click.option("--sketch", "-s", is_flag=True, help=object_kind.flag_help("a sketch")),
        )
    ):
        command = option(command)
    return command


def object_params(package, assembly, scene, sketch, object) -> dict:
    """The request's object, and its kind when a flag said it."""
    said = [kind for kind, flag in (("assembly", assembly), ("scene", scene), ("sketch", sketch)) if flag]
    if len(said) > 1:
        raise click.UsageError("OBJECT is one kind of object: %s" % ", ".join("--" + kind for kind in said))
    params = {"package": package, "object": object}
    if said:
        params["kind"] = said[0]
    return params


def stdin_options(command):
    """--stdin, and --json saying that what it reads is JSON."""
    command = click.option("--json", "as_json", is_flag=True, help="With '--stdin': read JSON rather than YAML")(
        command
    )
    return click.option("--stdin", "from_stdin", is_flag=True, help=STDIN_HELP)(command)


def read_stdin(as_json: bool):
    """The value standard input holds: YAML (as PartCAD reads 'partcad.yaml'), or JSON."""
    text = sys.stdin.read()
    try:
        value = json.loads(text) if as_json else config_yaml.load(text)
    except (ValueError, yaml.YAMLError) as e:
        raise click.BadParameter(
            "standard input is not %s: %s" % ("JSON" if as_json else "YAML", e), param_hint="--stdin"
        )
    if not as_json:
        # '>5' unquoted is read, not refused: as an empty block of text, which
        # would then be written as the empty string -- for an interface, the
        # unnamed instance. Said as 'pc lint' says it, and nothing is sent.
        for line, column, header in config_yaml.empty_block_scalars(text):
            raise click.BadParameter(
                "line %d, column %d: %s" % (line + 1, column + 1, config_yaml.misread_block(header)),
                param_hint="--stdin",
            )
    return value


def value(text):
    """One value typed on the command line, read as the same text in 'partcad.yaml' would be."""
    return config_yaml.scalar(text) if text is not None else None


def vector(words):
    """Three values typed as three words, each read as 'value' reads it; None when none were given."""
    return [value(word) for word in words] if words else None


def location_options(command):
    """--position, --direction and --angle: where a port or an interface instance has to be."""
    for option in reversed(
        (
            click.option(
                "--position",
                nargs=3,
                type=str,
                default=None,
                metavar="X Y Z",
                help="Where its origin has to be, in mm in the object's own frame: one value per axis, each a number "
                "or a comparison ('>=5'), 'null' for none",
            ),
            click.option(
                "--direction",
                nargs=3,
                type=str,
                default=None,
                metavar="X Y Z",
                help="The way it has to face: the direction its Z axis points, NOT the axis its own location is "
                "rotated about ('0 0 -1' is facing down). One value per axis, as for --position",
            ),
            click.option(
                "--angle",
                type=str,
                default=None,
                help="How far it is turned about that direction, in degrees: a number or a comparison",
            ),
        )
    ):
        command = option(command)
    return command


def location(position, direction, angle):
    """The location requirement the options say, or None when they say nothing."""
    result = {}
    if position:
        result["position"] = vector(position)
    if direction:
        result["direction"] = vector(direction)
    if angle is not None:
        result["angle"] = value(angle)
    return result or None


def replace_option(command):
    """--replace: what 'pc req add' needs to change a requirement that is there already."""
    return click.option(
        "--replace",
        is_flag=True,
        help="Replace the requirement if OBJECT has it already; without this, one that is there is refused",
    )(command)


def refuse_both(from_stdin: bool, given: dict) -> None:
    """Refuse '--stdin' together with options that also say what the requirement is: one of the two says it."""
    named = [name for name, option in given.items() if option not in (None, (), False)]
    if from_stdin and named:
        raise click.UsageError("'--stdin' says what the requirement is, and so would %s: use one" % ", ".join(named))


def add(cli_ctx, request: dict, requirement: str, name: str, value, replace: bool = False, instances=()):
    """Write the requirement: daemon work ('requirements.add'), since the warm context has to read it again."""
    from .service import run

    params = {**request, "requirement": requirement, "name": name, "value": value, "replace": replace}
    if instances:
        params["instances"] = list(instances)
    run(cli_ctx, "requirements.add", params, needs_context=True)


def remove(cli_ctx, request: dict, requirement: str, name: str, **extra):
    """Take the requirement out: daemon work ('requirements.remove')."""
    from .service import run

    params = {**request, "requirement": requirement, "name": name}
    params.update({key: item for key, item in extra.items() if item})
    run(cli_ctx, "requirements.remove", params, needs_context=True)
