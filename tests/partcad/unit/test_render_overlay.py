#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for what "pc render --with-ports/--with-interfaces" draws.

Where the ports are is worked out from the configuration alone - no geometry is
built and no sandbox is needed - so the answers are checked here directly,
against the example that has the most of them.
"""

import asyncio

import pytest

import partcad as pc
from partcad import output
from partcad.render_overlay import Overlay, collect_async, effective

EXAMPLES = "examples"
PACKAGE = "//pub/examples/partcad/feature_interface"


def _collect(name, kind="part", overlay=None):
    """The port records of one object of the example package."""
    ctx = pc.init(EXAMPLES)
    project = ctx.get_project(PACKAGE)
    shape = project.get_part(name) if kind == "part" else project.get_assembly(name)
    return asyncio.run(collect_async(shape, ctx, overlay or Overlay(ports=True)))


def _implementation(section, config):
    """A file type of the given section, configured as a package would."""
    return output.Implementation(section, "svg", config)


def test_overlay_of_reports_nothing_as_none():
    """The overwhelmingly common case is neither option, and it is one value."""
    assert Overlay.of() is None
    assert Overlay.of(ports=True).ports
    assert not Overlay.of(ports=True).interfaces
    assert Overlay.of(interfaces=True).interfaces
    everything = Overlay.of(all=True)
    assert everything.ports and everything.interfaces
    # On its own it asks for nothing: it says how deep the others reach.
    assert Overlay.of(internals=True) is None
    assert Overlay.of(ports=True, internals=True).internals


def test_only_a_render_file_type_carries_an_overlay():
    """A STEP file is not a picture to draw ports on."""
    assert effective(Overlay(ports=True), _implementation(output.EXPORT, {})) is None
    assert effective(Overlay(ports=True), _implementation(output.RENDER, {})).ports


def test_a_file_type_can_ask_for_the_overlay_itself():
    """Which is how a package keeps a drawing of its ports checked in."""
    declared = _implementation(output.RENDER, {"with_ports": True})
    assert effective(None, declared).ports
    assert not effective(None, declared).interfaces
    assert effective(None, _implementation(output.RENDER, {})) is None


def test_the_option_adds_to_what_the_file_type_declared():
    """Neither overrides the other: both are somebody asking for a drawing."""
    both = effective(Overlay(interfaces=True), _implementation(output.RENDER, {"with_ports": True}))
    assert both.ports and both.interfaces


def test_a_file_type_can_ask_to_see_inside_an_assembly():
    """Which is how the example keeps a drawing of a whole mount checked in."""
    declared = _implementation(output.RENDER, {"with_ports": True, "with_internals": True})
    assert effective(None, declared).internals
    assert not effective(None, _implementation(output.RENDER, {"with_ports": True})).internals


def test_a_part_reports_every_port_it_implements():
    """'implements:' has already placed them, so this is a lookup."""
    records = _collect("example-bracket")
    ports = [record["port"] for record in records]
    # Four bolt holes on each face of the bracket, plus the two slotted feet.
    assert len(ports) == 10
    assert "inner-TL-3mm-thru-opening-m3" in ports
    assert "L-30mm-slotted-3mm-thru-opening-m4" in ports


def test_a_port_carries_the_interface_a_connect_would_name():
    """A port is only useful on the picture if it says what selects it."""
    records = {record["port"]: record for record in _collect("example-bracket")}
    hole = records["outer-BR-3mm-thru-opening-m3"]
    assert hole["interface"] == PACKAGE + ":nema-17-motor-bracket-3"
    # What is written on the drawing, where the package prefix is noise.
    assert hole["interface_label"] == "nema-17-motor-bracket-3"
    assert hole["instance"] == "outer"
    assert hole["owner"] == ""


def test_a_port_with_no_boundary_sketch_asked_for_carries_none():
    """The sketches are only built when the interfaces are to be drawn."""
    assert all("sketch" not in record for record in _collect("example-bracket"))


def test_an_assembly_is_taken_at_its_word():
    """An assembly's ports are the ones it externalizes, and this one has none.

    What is inside it is its own business: the drawing stops at the boundary,
    the same one 'pc info' and a 'connect:' see.
    """
    assert _collect("connect-mates", kind="assembly") == []


def test_an_assembly_reports_the_ports_of_everything_in_it():
    """With '--with-internals', which is for looking inside one anyway."""
    records = _collect("connect-mates", kind="assembly", overlay=Overlay(ports=True, internals=True))
    ports = [record["port"] for record in records]
    assert "example-bracket:inner-TL-3mm-thru-opening-m3" in ports
    assert "example-motor:TL-4.5mm-hole-opening-m3" in ports
    assert "socket-head-m3-screw-6mm:6mm-long-screw-m3" in ports
    # The assembly the ASSY file's 'links:' becomes is no object of any package
    # and nobody names it in a 'connect:', so it is not in any of these names.
    assert not any("None" in port for port in ports)
    assert all(port.count(":") == 1 for port in ports)


def test_an_assembly_moves_a_childs_ports_where_it_put_the_child():
    """This is the whole point of the overlay on an assembly.

    Two ports that were connected end up at the same place, and one that was not
    does not - which is what makes a connection that went wrong visible as two
    frames that should have met and did not.
    """
    records = {
        record["port"]: record
        for record in _collect("connect-mates", kind="assembly", overlay=Overlay(ports=True, internals=True))
    }
    connected = records["example-bracket:outer-TR-3mm-thru-opening-m3"]["location"][0]
    mated = records["example-motor:TR-4.5mm-hole-opening-m3"]["location"][0]
    elsewhere = records["example-bracket:inner-TR-3mm-thru-opening-m3"]["location"][0]

    assert connected == pytest.approx(mated, abs=1e-6)
    assert elsewhere != pytest.approx(mated, abs=1e-6)
    # Not the port's own coordinates in the part: the assembly moved it there.
    assert records["example-motor:TR-4.5mm-hole-opening-m3"]["owner"] == "example-motor"


def test_the_interfaces_overlay_brings_the_port_boundaries_along():
    """The circle of a hole, the profile of a rail: what makes an interface
    visible rather than merely named."""
    from partcad import shape_envelope

    records = _collect("example-bracket", overlay=Overlay(interfaces=True))
    assert records
    for record in records:
        placed = record["sketch"]
        assert placed, record["port"]
        # Still an envelope, placed as plain data: the geometry is only built
        # when the render sandbox decodes it.
        for component in placed:
            assert shape_envelope.is_shape_envelope(component)
            assert component[shape_envelope.KEY_LOCATION] == record["location"]


def test_a_failed_collection_is_not_remembered(monkeypatch):
    """One file type's failure must not take the ports off the next one.

    The two collections differ only in whether the port boundaries came along,
    so the successful one is cached for both. A *failed* one must not be:
    building a boundary sketch can fail where locating the port cannot, and
    remembering that as "no ports" would empty a later file type that never
    asked for a boundary.
    """
    from partcad import render_overlay

    ctx = pc.init(EXAMPLES)
    shape = ctx.get_project(PACKAGE).get_part("example-bracket")

    async def collect(shape, ctx, overlay):
        """Fail only where a port boundary would have to be built."""
        if overlay.interfaces:
            raise RuntimeError("a port boundary could not be built")
        return [{"port": "only-when-asked-without-boundaries", "interface": None, "instance": None}]

    monkeypatch.setattr(render_overlay, "collect_async", collect)

    cache = {}
    assert asyncio.run(shape._overlay_ports_async(ctx, Overlay(interfaces=True), cache)) == []
    ports_only = asyncio.run(shape._overlay_ports_async(ctx, Overlay(ports=True), cache))
    assert [record["port"] for record in ports_only] == ["only-when-asked-without-boundaries"]


# ---- which ports, rather than whether any ---------------------------------
#
# The overlay PartCAD draws used to be three booleans, so a panel that lists a
# part's twelve ports had no way to ask for one of them. 'select' is that: the
# names the records come back under, which is what '--port' spells and what the
# IDE's 2D tab composes from the rows it is showing.


def test_a_selection_on_its_own_asks_for_nothing():
    # It says *which* ports, not that there are any to draw, so naming ports
    # without naming an overlay draws the picture it would have drawn anyway.
    assert Overlay.of(select=["a"]) is None
    assert Overlay.of(ports=True, select=["a"]) is not None


def test_an_overlay_draws_every_port_until_it_is_told_which():
    assert Overlay(ports=True).draws("anything")
    overlay = Overlay(ports=True, select=["a", "b"])
    assert overlay.draws("a") and overlay.draws("b")
    assert not overlay.draws("c")


def test_two_overlays_asking_for_the_same_thing_have_one_key():
    # What the per-call port cache is keyed on: a collection for one selection
    # must not answer for another.
    assert Overlay(ports=True, select=["a", "b"]).key() == Overlay(ports=True, select=["b", "a"]).key()
    assert Overlay(ports=True, select=["a"]).key() != Overlay(ports=True, select=["b"]).key()
    assert Overlay(ports=True).key() != Overlay(ports=True, select=["a"]).key()
    # The flag that says *whether* the frames are drawn is not part of it: a
    # collection made for one answers the other.
    assert Overlay(ports=True).key() == Overlay(interfaces=False, ports=False).key()


def test_a_selection_narrows_what_is_collected():
    every = {record["port"] for record in _collect("example-bracket")}
    assert len(every) > 1
    one = sorted(every)[0]

    records = _collect("example-bracket", overlay=Overlay(ports=True, select=[one]))
    assert [record["port"] for record in records] == [one]


def test_a_file_type_cannot_narrow_the_ports_itself():
    """Which ports is this run's answer; a file type asks for the overlay.

    A declaration is permanent and a selection is about the one picture somebody
    is looking at, so 'effective()' carries the command line's and reads nothing
    from the configuration.
    """
    impl = _implementation(output.RENDER, {"with_ports": True, "ports": ["declared"]})
    assert effective(None, impl).select is None
    assert effective(Overlay(ports=True, select=["asked"]), impl).select == frozenset({"asked"})


# ---- the callouts ------------------------------------------------------------
#
# What the IDE's 3D and 2D tabs call "Component names", "Component prices",
# "Port names" and "Interface names", and 'pc render --with-component-names',
# '--with-component-prices', '--without-port-names' and
# '--without-interface-names'.


def test_a_name_switched_off_is_kept_although_it_draws_nothing():
    """It has to reach a file type that draws its ports of its own accord."""
    assert Overlay.of() is None
    quiet = Overlay.of(port_names=False)
    assert quiet is not None and not quiet
    assert not quiet.port_names and quiet.interface_names
    assert not Overlay.of(interface_names=False).interface_names
    # A source of prices on its own asks for nothing either.
    assert Overlay.of(prices=lambda ctx, shape: {}) is None


def test_a_callout_on_the_components_is_something_to_draw():
    assert Overlay.of(component_names=True)
    assert Overlay.of(component_prices=True).components
    assert not Overlay(ports=True).components


def test_the_callouts_are_this_runs_answer():
    """A file type that draws its ports writes their names, unless the run says not to."""
    declared = _implementation(output.RENDER, {"with_ports": True, "with_interfaces": True})
    assert effective(None, declared).port_names
    assert effective(None, declared).interface_names
    assert not effective(None, declared).components

    asked = effective(Overlay.of(port_names=False, interface_names=False), declared)
    assert asked.ports and not asked.port_names and not asked.interface_names

    source = object()
    asked = effective(Overlay.of(component_names=True, component_prices=True, prices=source), declared)
    assert asked.component_names and asked.component_prices
    assert asked.prices is source

    # Names switched off and nothing drawn: nothing at all.
    assert effective(Overlay.of(port_names=False), _implementation(output.RENDER, {})) is None
    # And a picture of the components is one, with no ports declared or asked.
    assert effective(Overlay.of(component_names=True), _implementation(output.RENDER, {})).component_names
    # Never on a file that is not a picture.
    assert effective(Overlay.of(component_names=True), _implementation(output.EXPORT, {})) is None


def test_a_price_is_written_with_the_code_of_its_currency():
    from partcad.render_overlay import price_text

    assert price_text(1.5, "USD") == "1.50 USD"
    assert price_text(12, None) == "12.00"
    # Every character is one the picture's own font has: no currency symbols.
    assert price_text(0.125, "EUR") == "0.12 EUR"


class _Shape:
    project_name = "//pkg"
    name = "top"


def test_the_prices_come_from_the_source_the_overlay_carries():
    from partcad.render_overlay import component_prices_async

    asked = []

    async def prices(ctx, shape):
        asked.append(shape)
        return {
            "//pkg:bolt": {"price": 0.25, "currency": "USD"},
            "//pkg:nut": {"price": None, "currency": "USD"},
            "//pkg:plate": {"price": 3, "currency": None},
        }

    shape = _Shape()
    labels = asyncio.run(component_prices_async(shape, None, Overlay(component_prices=True, prices=prices)))

    assert asked == [shape]
    # A price of nothing is no price, rather than a price of nought.
    assert labels == {"//pkg:bolt": "0.25 USD", "//pkg:plate": "3.00"}


def test_no_prices_cost_nothing_but_the_prices():
    """No source, a source that fails, a source with nothing: an empty answer and a reason."""
    from partcad.render_overlay import component_prices_async

    assert asyncio.run(component_prices_async(_Shape(), None, Overlay(component_prices=True))) == {}

    async def failing(ctx, shape):
        raise RuntimeError("no network")

    assert asyncio.run(component_prices_async(_Shape(), None, Overlay(component_prices=True, prices=failing))) == {}

    async def none(ctx, shape):
        return {}

    assert asyncio.run(component_prices_async(_Shape(), None, Overlay(component_prices=True, prices=none))) == {}


def test_the_request_says_only_what_differs_from_a_request_without_callouts():
    """A picture that asks for no callouts is handed the request it always was, and keeps its cache."""
    from partcad import render_overlay
    from partcad.shape import Shape

    class _Impl:
        parameters = {}

    class _Fake:
        name = "top"
        kind = "assembly"
        config = {"type": "assy"}
        project_name = "//pkg"

        _output_request = Shape._output_request

    plain = asyncio.run(_Fake()._output_request(None, "wrapped", _Impl(), {}, overlay=Overlay(ports=True)))
    for key in (
        render_overlay.COMPONENT_NAMES_KEY,
        render_overlay.COMPONENT_PRICES_KEY,
        render_overlay.PORT_NAMES_KEY,
        render_overlay.INTERFACE_NAMES_KEY,
    ):
        assert key not in plain

    overlay = Overlay(ports=True, component_names=True, component_prices=True, port_names=False, interface_names=False)
    asked = asyncio.run(
        _Fake()._output_request(None, "wrapped", _Impl(), {}, overlay=overlay, prices={"//pkg:bolt": "0.25 USD"})
    )
    assert asked[render_overlay.COMPONENT_NAMES_KEY] is True
    assert asked[render_overlay.COMPONENT_PRICES_KEY] == {"//pkg:bolt": "0.25 USD"}
    assert asked[render_overlay.PORT_NAMES_KEY] is False
    assert asked[render_overlay.INTERFACE_NAMES_KEY] is False
