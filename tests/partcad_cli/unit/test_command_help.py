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

from partcad_cli.click.command import cli as root
from partcad_cli.click.command import command_groups

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


def _commands(cmd, ctx, path, found):
    """Every command in the tree, as (label, command) pairs."""
    found.append((" ".join(path), cmd))
    if not isinstance(cmd, click.Group):
        return
    for name in cmd.list_commands(ctx):
        sub = cmd.get_command(ctx, name)
        if sub is None:
            continue
        sub_ctx = sub.context_class(sub, info_name=name, parent=ctx)
        _commands(sub, sub_ctx, path + [name], found)


def test_no_command_spells_one_option_two_ways():
    """Two options of one command may not share a flag, and Click will not refuse it.

    It resolves a repeated flag by letting the last one registered win, with a
    `UserWarning` raised at *parse* time -- which the suite runs with warnings
    off and which a user sees once, underneath the output they asked for. So the
    flag quietly changes meaning: `--filter` was given `-f` on `pc render` and
    `pc export`, where `-f` is `--fast-only`, and `pc render -f widget` became a
    filter of 'widget' with no object named rather than a fast-only render of
    'widget'.

    `fast_only.option(short=False)` exists for a command that owns `-f` for
    something else, which is how `pc test` and `pc sim` keep theirs. This
    asserts that nothing has to remember.
    """
    found = []
    ctx = root.context_class(root, info_name="pc")
    _commands(root, ctx, ["pc"], found)
    assert len(found) > 1, "the walk reached only the root"

    collisions = []
    for label, cmd in found:
        seen = {}
        for param in cmd.params:
            for flag in list(param.opts) + list(param.secondary_opts):
                seen.setdefault(flag, []).append(param.name)
        for flag, owners in sorted(seen.items()):
            if len(owners) > 1:
                collisions.append("%s: %s is %s" % (label, flag, " and ".join(owners)))
    assert not collisions, "one flag, two options:\n  " + "\n  ".join(collisions)


# --- The copy of this list that lives in the documentation --------------------
#
# `docs/source/installation.rst` pastes a `pc --help` transcript by hand, as
# orientation on the page someone reads before they have the command. It is the
# one place in the tree that restates the command list in prose, and it has gone
# stale twice: the August review found it missing `upgrade`, `daemon`, `open` and
# `bom`, and the review five weeks later found it missing `sim`, `filter`, `cae`
# and `cam`. Nothing connected it to the code it describes.
#
# Generating it at build time was considered and rejected: `sphinx-click` has to
# import the application, and `.readthedocs.yaml` installs `docs/requirements.txt`
# alone -- so the published documentation would start depending on PartCAD's whole
# install closure, and a broken runtime dependency would take the docs down with
# it. It also renders in its own style, which matches neither this plain
# transcript nor the box-drawn panels rich-click actually prints.
#
# So the transcript stays checked in, the way `examples/` keeps its rendered
# output checked in, and this is the gate: a command added to `command_groups`
# and not to the page fails here, with the panel and the name to add.

DOCS_HELP_PAGE = "docs/source/installation.rst"


def _transcript_panels():
    """The command names per panel, read out of the pasted transcript."""
    import pathlib
    import re

    path = pathlib.Path(__file__).resolve().parents[3] / DOCS_HELP_PAGE
    text = path.read_text(encoding="utf-8")

    start = text.index("  Host commands:")
    end = text.index("\nCommon options apply", start)
    panels, panel = {}, None
    for line in text[start:end].split("\n"):
        heading = re.fullmatch(r"  ([A-Z][a-z]+) commands:", line)
        if heading:
            panel = "%s commands" % heading.group(1)
            panels[panel] = []
            continue
        # '    name         description'. One space is enough: the description
        # column is as wide as the longest name, so `instructions` leaves a
        # single space where `render` leaves seven. A wrapped continuation line
        # is indented to that column, so it has no name in the first position
        # and cannot match.
        entry = re.fullmatch(r"    ([a-z][a-z-]*) +\S.*", line)
        if entry and panel:
            panels[panel].append(entry.group(1))
    return panels


def test_the_documented_help_transcript_lists_every_command():
    documented = _transcript_panels()
    assert documented, "found no command panels in %s" % DOCS_HELP_PAGE

    expected = {group["name"]: list(group["commands"]) for group in command_groups}

    assert set(documented) == set(expected), "panels differ: documented %s, code %s" % (
        sorted(documented),
        sorted(expected),
    )

    for panel, names in sorted(expected.items()):
        missing = [n for n in names if n not in documented[panel]]
        extra = [n for n in documented[panel] if n not in names]
        assert not missing, "%s is missing from '%s' in %s" % (", ".join(missing), panel, DOCS_HELP_PAGE)
        assert not extra, "%s is in '%s' in %s but not in command_groups" % (", ".join(extra), panel, DOCS_HELP_PAGE)
        assert documented[panel] == names, "'%s' in %s is in a different order than command_groups:\n  %s\n  %s" % (
            panel,
            DOCS_HELP_PAGE,
            documented[panel],
            names,
        )
