#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req test` -- `pc qual test --basic --filter requirements`, under the name of what it tests.

    pc req test bracket
    pc req test -P ... -r          # every object from here down that requires anything

The `requirements` check is one of `pc qual test`'s basic tests; this runs it
and nothing else, with every other option of `pc qual test` -- the package, the
recursion, the parameters, the exclusions -- taken from that command rather than
declared again, so the two cannot come to take different options. What it
leaves out is what it fixes (the subtypes and the filter), and what only a run
of the simulations takes.
"""

import rich_click as click

from ..qual import test as qual_test

# What 'pc qual test' takes that this does not: what it says itself, what only
# '--simulation' takes, and '--interface' (an interface requires nothing).
FIXED = {"basic", "topology", "simulation", "other", "filter", "as_json", "plugin", "before_path", "after_path"}
FIXED |= {"video_path", "interface"}

# The test 'pc qual test --filter' selects: the requirements check's name.
FILTER = "requirements"


def _callback(**kwargs):
    context = click.get_current_context()
    return context.invoke(
        qual_test.cli,
        **kwargs,
        basic=True,
        topology=False,
        simulation=False,
        other=False,
        filter=FILTER,
        interface=False,
        as_json=False,
        plugin=None,
        before_path=None,
        after_path=None,
        video_path=None,
    )


cli = click.RichCommand(
    name="test",
    # Not 'pass_obj': what 'pc qual test' is handed, it is handed by 'invoke'.
    callback=_callback,
    params=[param for param in qual_test.cli.params if param.name not in FIXED],
    help=(
        "Test the model against its requirements: 'pc qual test --basic --filter requirements', which runs the "
        "'requirements' check alone. Takes the options of 'pc qual test' that do not choose the tests."
    ),
)
