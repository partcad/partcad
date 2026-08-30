#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`--help` has to render for every command in the tree.

Commands are loaded lazily: `partcad_cli.click.loader.Loader.get_command`
imports `partcad_cli.click.commands.<path>` the first time click asks for it. So
a command module that cannot be imported is invisible until someone types the
command -- or types `--help` on its *group*, because rich-click renders a group's
command panel by asking for every subcommand in it.

`commands/search/all.py` shipped annotating its parameter with a `CliContext` it
never imported. Python evaluates that annotation at `def` time, so the module
raised `NameError` on import: `pc search all` was unusable and `pc search --help`
died with it. It reached the user as a raw traceback rather than a click error,
because `get_command` only converts `ModuleNotFoundError` and `SyntaxError`.

Nothing caught it. `features/pc.feature` renders `pc --help`, which loads the
top-level commands only, and the behave suite exercised every `pc search`
subcommand except `all`.

The walk below renders help for all of them -- 70-odd nodes, four levels deep --
in about a second, since help is what click produces without running anything.
It deliberately does not go through `CliRunner`: invoking the root callback
writes the parsed global options onto the process-wide `user_config` singleton
(see `clean_user_config` in `test_upgrade.py`), and this test has no business
leaving that behind. Building the context directly renders the same help.

This is the general form of `features/search/all.feature`, which covers the one
command that broke.
"""

import traceback

import pytest
import rich_click as click
from partcad_cli.click.command import cli as root, command_groups

# A few paths that have to be in the walk. Not an exhaustive list -- that would
# be a second copy of the command tree -- just enough that a walk which silently
# stops at the top level cannot pass: one nested command per group style, and
# the deepest path in the tree.
EXPECTED_PATHS = [
    "pc search all",
    "pc list parts",
    "pc supply quote",
    "pc system set telemetry env",
]


def _walk(cmd, ctx, path, visited, failures):
    """Render this node's help, then recurse into its subcommands."""
    label = " ".join(path)
    visited.append(label)

    try:
        ctx.get_help()
    except Exception:  # noqa: BLE001 - collecting every failure is the point
        failures.append((label, traceback.format_exc()))
        return

    if not isinstance(cmd, click.Group):
        return

    try:
        names = cmd.list_commands(ctx)
    except Exception:  # noqa: BLE001
        failures.append((f"{label} (list_commands)", traceback.format_exc()))
        return

    for name in names:
        try:
            sub = cmd.get_command(ctx, name)
        except Exception:  # noqa: BLE001
            # What a broken command module looks like from here.
            failures.append((f"{label} {name} (import)", traceback.format_exc()))
            continue
        if sub is None:
            failures.append((f"{label} {name}", "get_command() returned None"))
            continue
        # `context_class` is rich-click's RichContext; a plain click.Context
        # gives the group a formatter without the rich configuration on it.
        sub_ctx = sub.context_class(sub, info_name=name, parent=ctx)
        _walk(sub, sub_ctx, path + [name], visited, failures)


@pytest.fixture(scope="module")
def command_tree():
    """Walk the whole tree once; both tests below read the same result."""
    visited, failures = [], []
    ctx = root.context_class(root, info_name="pc")
    _walk(root, ctx, ["pc"], visited, failures)
    return visited, failures


def test_help_renders_for_every_command(command_tree):
    _, failures = command_tree
    assert not failures, "\n\n".join(f"--- {label}\n{detail}" for label, detail in failures)


@pytest.mark.parametrize("path", EXPECTED_PATHS)
def test_the_walk_reaches_the_nested_commands(command_tree, path):
    """A walk that never recursed would pass the test above without checking anything."""
    visited, _ = command_tree
    assert path in visited, f"{path!r} was not reached; the walk visited {len(visited)} commands"


def test_every_top_level_command_is_in_exactly_one_help_panel():
    """`pc --help` groups its commands into named panels; nothing may fall out.

    A command missing from `command_groups` is not dropped -- rich-click collects
    the leftovers into a trailing, unnamed "Commands" panel underneath the named
    ones, so it looks like a category of its own. `search` and `upgrade` sat
    there, which is easy to do and easy to miss: adding a command is one new file
    under `commands/`, and nothing asks the author to name its panel.
    """
    ctx = root.context_class(root, info_name="pc")
    actual = set(root.list_commands(ctx))

    listed = [name for group in command_groups for name in group["commands"]]

    duplicated = sorted({name for name in listed if listed.count(name) > 1})
    assert not duplicated, f"listed in more than one panel of command_groups: {', '.join(duplicated)}"

    stale = sorted(set(listed) - actual)
    assert not stale, f"named in command_groups but not a command: {', '.join(stale)}"

    ungrouped = sorted(actual - set(listed))
    assert not ungrouped, (
        "these commands are in no panel of command_groups, so `pc --help` puts them in a trailing "
        f"unnamed 'Commands' panel: {', '.join(ungrouped)}"
    )
