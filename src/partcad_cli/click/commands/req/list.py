#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req list OBJECT` -- what an object is required to be, printed as YAML (or JSON).

    pc req list bracket
    pc req list bracket --kind physics --kind has
    pc req list bracket --verify --json

What is printed is the object's `requirements:` section as PartCAD reads it --
an alias's being its source's, which `from:` then names -- in the shape it is
written in, so it can be read back: `pc req add <kind> --stdin` takes any part
of it. `--verify` adds `checks:`, each requirement with whether the model meets
it, as `pc req test` checks it. Daemon work (`requirements.check`).
"""

import json

import rich_click as click
import yaml

from ... import object_kind
from ...requirement_args import object_options, object_params
from ...service import run

# The kinds of requirement, as '--kind' names them, and the key of the section each is under.
KINDS = {
    "feature": "features",
    "port": "ports",
    "interface": "interfaces",
    "physics": "physics",
    "match": "match",
    # The yes-or-no requirements, each a key of the section itself.
    "has": "has_",
}


class _Dumper(yaml.SafeDumper):
    """YAML as a requirement is written by hand: a vector on one line ('[0, 0, -1]'), everything else in blocks."""


def _represent_list(dumper, data):
    flow = all(not isinstance(item, (dict, list)) for item in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _represent_list)


def _only(section, kinds):
    """The parts of 'section' the kinds asked for name, in the order it holds them."""
    if not kinds or not isinstance(section, dict):
        return section
    keys = [KINDS[kind] for kind in kinds]
    return {
        key: item for key, item in section.items() if key in keys or ("has_" in keys and str(key).startswith("has_"))
    }


def listing(result: dict, kinds=(), verify: bool = False) -> dict:
    """What 'pc req list' prints, out of what 'requirements.check' answered."""
    document = {"object": result.get("object"), "kind": result.get("kind")}
    declared = result.get("declared")
    if result.get("source") and declared != result.get("section"):
        # Read off what it points at: an alias's requirements are its source's.
        document["from"] = result["source"]
    document["requirements"] = _only(declared, kinds) or {}
    if verify:
        sections = set()
        for kind in kinds:
            sections.add("has" if kind == "has" else KINDS[kind])
        document["checks"] = [
            {key: check.get(key) for key in ("section", "name", "requirement", "passed", "detail")}
            for check in result.get("requirements") or []
            if not sections or check.get("section") in sections
        ]
    return document


@click.command(
    help=(
        "List what OBJECT is required to be: its 'requirements:' section as PartCAD reads it, as YAML (the "
        "default) or JSON. " + object_kind.LOOKED_UP
    )
)
@object_options
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    type=click.Choice(list(KINDS)),
    help="Only requirements of this kind (may be repeated)",
)
@click.option("--yaml", "output", flag_value="yaml", default=True, help="Print YAML (the default)")
@click.option("--json", "output", flag_value="json", help="Print JSON")
@click.option(
    "--verify",
    is_flag=True,
    help="Also check the model against each requirement, as 'pc req test' does, and print the verdicts",
)
@click.argument("object", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, kinds, output, verify, object):
    request = {**object_params(package, assembly, scene, sketch, object), "verify": verify}
    result = run(cli_ctx, "requirements.check", request, needs_context=True)
    if result is None:
        # The package did not load; the daemon has already said so.
        raise click.ClickException("Nothing was listed")
    document = listing(result, kinds, verify)
    if output == "json":
        click.echo(json.dumps(document, indent=2))
    else:
        click.echo(yaml.dump(document, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=4096), nl=False)
