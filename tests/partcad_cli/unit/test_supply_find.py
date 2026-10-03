#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc supply find` when it is not told which provider to ask.

That branch finds the suppliers itself, through 'Context.find_suppliers()'. It
used to pass the QoS to that method as an argument it does not take, and died
on a TypeError before finding anything; the QoS belongs on the cart, which is
where every supplier is asked about it. The answer is keyed by '<name>#<count>',
the same as the '--provider' branch, because the count is what a supplier is
asked whether it can supply.
"""

import json

from partcad.plugin_provider import Provider
from partcad_cli.click.command import cli

PART = "//pub/examples/partcad/provider_store:screw_m8_35mm#3"
PROVIDER = "//pub/examples/partcad/provider_store:myGarage"


def _find(click_runner, *args):
    return click_runner.invoke(
        cli,
        ["--no-ansi", "--path", "examples/provider_store", "supply", "find", "--json", *args, PART],
    )


def test_find_without_provider_lists_suppliers_by_spec(click_runner):
    result = _find(click_runner)
    assert result.exit_code == 0, result.output
    suppliers = json.loads(result.stdout.strip().splitlines()[-1])
    assert suppliers == {PART: [PROVIDER]}


def test_find_without_provider_asks_suppliers_about_the_qos(click_runner, monkeypatch):
    asked = []

    def is_qos_available(self, qos):
        asked.append(qos)
        return qos == "priority"

    monkeypatch.setattr(Provider, "is_qos_available", is_qos_available)

    result = _find(click_runner, "--qos", "priority")
    assert result.exit_code == 0, result.output
    assert asked and set(asked) == {"priority"}
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {PART: [PROVIDER]}
