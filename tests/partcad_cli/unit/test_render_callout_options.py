#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The callout options of 'pc render', as they reach the daemon.

'--with-component-names' and '--with-component-prices' are sent as they are;
'--without-port-names' and '--without-interface-names' are sent only when given,
as a false, so that a run that uses none of them asks a daemon exactly what it
asked before they existed. What the daemon does with them is tested beside
'partcad.render_overlay' and the operations.
"""

import importlib

from click.testing import CliRunner

from partcad_cli.click.command import cli


def _render(monkeypatch, *args):
    calls = []

    def run(cli_ctx, method, params, needs_context=False):
        calls.append((method, params))

    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands.render"), "run", run)
    result = CliRunner().invoke(cli, ["--no-ansi", "render", *args, "logo"])
    assert result.exit_code == 0, result.output
    ((method, params),) = calls
    assert method == "render.objects"
    return params


def test_no_callout_option_sends_what_a_render_always_sent(monkeypatch):
    params = _render(monkeypatch)

    assert params["with_component_names"] is False
    assert params["with_component_prices"] is False
    assert "with_port_names" not in params
    assert "with_interface_names" not in params


def test_the_component_callouts_are_asked_for(monkeypatch):
    params = _render(monkeypatch, "--with-component-names", "--with-component-prices")

    assert params["with_component_names"] is True
    assert params["with_component_prices"] is True


def test_the_names_of_the_ports_and_interfaces_can_be_left_off(monkeypatch):
    params = _render(monkeypatch, "--with-all", "--without-port-names", "--without-interface-names")

    assert params["with_all"] is True
    assert params["with_port_names"] is False
    assert params["with_interface_names"] is False


def test_asking_for_the_names_is_asking_for_the_default(monkeypatch):
    params = _render(monkeypatch, "--with-ports", "--with-port-names", "--with-interface-names")

    assert "with_port_names" not in params
    assert "with_interface_names" not in params
