#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Interfaces and ports parametrized the way parts and sketches are.

The subject is one package, 'data/parametric_interfaces', which declares the
metric fastener family once instead of once per size: what used to take a
Jinja2 loop over every size, depth and width a package might ever be asked for
is a handful of declarations with values in their 'parameters:' - the same
section a part declares its parameters in, and the same section an interface
has always declared its freedom of movement in.
"""

from unittest import mock

import pytest

import partcad as pc
from partcad import expr

PACKAGE = "tests/partcad/unit/data/parametric_interfaces/partcad.yaml"


class _FakeWithPorts:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def get_interfaces(self):
        return self._interfaces


class _FakeShape:
    """The bare minimum of a part that 'find_mating_interfaces' looks at."""

    def __init__(self, interfaces):
        self.name = "fake"
        self.with_ports = _FakeWithPorts(interfaces)


def _fake_shape(interfaces):
    return _FakeShape(interfaces)


@pytest.fixture
def ctx():
    # A context of its own rather than 'pc.init()', which hands back the
    # process-wide one when the path matches: these tests read what resolving
    # an interface put into the context, and a context another test has already
    # walked would answer for that test instead.
    return pc.Context(PACKAGE)


# --- the expression syntax itself -------------------------------------------


def test_expression_whole_string_keeps_the_type():
    """A coordinate written as an expression is a number, not the text of one."""
    assert expr.substitute("%size%", {"size": 4.0}) == 4.0
    assert expr.substitute("%size / 2%", {"size": 5.0}) == 2.5
    assert expr.substitute("%-pitch / 2%", {"pitch": 31.0}) == -15.5


def test_expression_inside_a_string_is_formatted_into_it():
    assert expr.substitute("%depth%mm deep", {"depth": 4.0}) == "4mm deep"
    assert expr.substitute("m;size=%size%", {"size": 2.5}) == "m;size=2.5"
    assert expr.substitute("%a% by %b%", {"a": 1.0, "b": 2}) == "1 by 2"


def test_expression_may_use_arithmetic_and_math():
    values = {"size": 9.0}
    assert expr.substitute("%sqrt(size)%", values) == 3.0
    assert expr.substitute("%max(size, 10)%", values) == 10
    assert expr.substitute("%round(size / 2)%", values) == 4


@pytest.mark.parametrize(
    "expression",
    [
        "%open('/etc/passwd')%",  # no builtins
        "%().__class__%",  # and no way to walk to them
        "%size.__class__%",
        "%[x for x in (1, 2)]%",
        "%(lambda: 1)()%",
    ],
)
def test_an_expression_is_arithmetic_and_nothing_else(expression):
    """A declaration is read whenever a package is loaded, long before anything is built."""
    with pytest.raises(expr.ExpressionError):
        expr.substitute(expression, {"size": 4.0})


@pytest.mark.parametrize(
    "expression",
    [
        "%9**9**9%",  # seconds of CPU and gigabytes, in eight characters
        "%2**64%",  # so the operator goes, not a size limit on it
        "%1 << 1000000000%",
        "%'x' * 1000000000%",  # repeating a sequence is the other way to allocate
        "%['x'] * 1000000000%",
        "%label * 1000000000%",  # including through a parameter that holds text
        # ... and through anything that merely *might* be text. A call is the
        # case that matters: reading an unrecognised form as a number is what
        # let this one through the first time.
        "%str(1) * 1000000000%",
        "%max('a', 'b') * 1000000000%",
    ],
)
def test_an_expression_cannot_cost_more_than_it_looks(expression):
    """A package is loaded in this process, before anything is sandboxed.

    So a declaration fetched from a git URL must not be able to hang the PartCAD
    that imported it, which '%9**9**9%' otherwise does.
    """
    with pytest.raises(expr.ExpressionError):
        expr.substitute(expression, {"size": 4.0, "label": "M4-0.7"})


def test_arithmetic_a_coordinate_actually_needs_still_works():
    """The bound above is on what the operators can cost, not on the arithmetic."""
    values = {"size": 4.0, "width": 30.0}
    assert expr.substitute("%size * 2%", values) == 8.0
    assert expr.substitute("%-width / 2 + size%", values) == -11.0
    assert expr.substitute("%max(size - 2, 0)%", values) == 2.0
    # 'pow()' is what is left of exponentiation, and it cannot blow up: it is
    # 'math.pow', which answers in floats and overflows rather than allocating.
    assert expr.substitute("%pow(size, 2)%", values) == 16.0
    with pytest.raises(expr.ExpressionError):
        expr.substitute("%pow(9, 999999999)%", values)


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("%size * 2%", 8.0),
        ("%-size * 2%", -8.0),
        ("%2 * (size + 1)%", 10.0),
        ("%round(size) * 3%", 12),
        ("%abs(-size) * 2%", 8.0),
        ("%(size if size > 2 else 1) * 4%", 16.0),
        # A method whose answer is a number, which is how the historical form
        # reads a size out of a thread designation.
        ("%label:value.index('-') * 2%", 4),
    ],
)
def test_multiplication_of_things_that_are_numbers_is_allowed(expression, expected):
    """ "Provably a number" has to admit the arithmetic a coordinate is made of."""
    assert expr.substitute(expression, {"size": 4.0, "label": "M4-0.7"}) == expected


def test_an_expression_may_be_a_conditional():
    """What is allowed is allowed: comparisons and a conditional are arithmetic."""
    assert expr.substitute("%size if size > 3 else 3%", {"size": 4.0}) == 4.0
    assert expr.substitute("%size if size > 3 else 3%", {"size": 2.0}) == 3


def test_expression_historical_spelling_still_resolves():
    """'%name:expression%', which interface names have used since 2024."""
    assert expr.substitute("%size:value * 2%", {"size": 3.0}) == 6.0


def test_expression_resolves_what_the_published_packages_actually_write():
    """The one historical expression in the wild, from '//pub/std/metric/cqwarehouse'.

    It names the interface of an M4 screw by slicing the thread designation:
    "M4-0.7" is an 'm4-screw'. Indexing and a string's own methods are therefore
    not an extension for its own sake - they are what the form was already used
    for, back when it was an unrestricted 'eval'.
    """
    values = {"size": "M4-0.7"}
    assert expr.substitute("m%size:value[1:value.index('-')]%-screw", values) == "m4-screw"
    assert expr.substitute("%size:value.split('-')[0]%", values) == "M4"
    assert expr.substitute("%size:int(value[1:value.index('-')])%", values) == 4


@pytest.mark.parametrize(
    "expression",
    [
        "%size:value.__class__.__mro__%",  # the reason the list is a list
        "%'{0.__class__}'.format(size)%",  # 'format' traverses attributes at run time
        "%size:value.encode('utf8')%",  # and these answer with something else
        "%size:value.translate({})%",
    ],
)
def test_an_attribute_off_the_list_is_refused(expression):
    """Allowing attribute access is only safe because of which attributes."""
    with pytest.raises(expr.ExpressionError):
        expr.substitute(expression, {"size": "M4-0.7"})


def test_expression_is_not_jinja2():
    """Jinja2's delimiters are left alone: 'partcad.yaml' was rendered already."""
    assert expr.substitute("{{ size }}", {"size": 3.0}) == "{{ size }}"


def test_resolve_walks_keys_and_lists():
    resolved = expr.resolve(
        {"m;size=%size%": [["%-size%", 0, 0], [0, 0, 1], 0]},
        {"size": 4.0},
    )
    assert resolved == {"m;size=4": [[-4.0, 0, 0], [0, 0, 1], 0]}


def test_resolve_reports_a_broken_expression_and_leaves_it():
    """A package that misspells one expression loses that value, not the package."""
    reported = []
    with mock.patch.object(pc.logging, "error", lambda *args: reported.append(args)):
        assert expr.resolve("%nope + 1%", {"size": 4.0}, "//test:iface") == "%nope + 1%"
    assert len(reported) == 1
    assert "%nope + 1%" in str(reported[0])
    assert "//test:iface" in str(reported[0])


# --- referencing a parametrized interface -----------------------------------


def test_interface_is_built_with_the_values_the_reference_names(ctx):
    thru = ctx.get_interface(":m-thru;size=4,depth=2")
    assert thru is not None
    assert thru.desc == "2mm thick through hole of 4mm diameter"
    assert thru.info()["values"] == {"size": 4.0, "depth": 2.0}


def test_interface_defaults_apply_when_nothing_is_named(ctx):
    thru = ctx.get_interface(":m-thru")
    assert thru.desc == "3mm thick through hole of 3mm diameter"


def test_the_same_values_are_the_same_interface(ctx):
    """Whatever order they are written in, and however the numbers are spelled.

    An interface's name is what a mating is registered under, so two objects
    for one set of values would be two halves of a connection that never find
    each other.
    """
    a = ctx.get_interface(":m-thru;size=4,depth=2")
    b = ctx.get_interface(":m-thru;depth=2,size=4")
    c = ctx.get_interface(":m-thru;depth=2.0,size=4.00")
    assert a is b is c
    assert a.full_name == "//:m-thru;depth=2,size=4"


def test_parameter_values_may_also_be_passed_separately(ctx):
    """What 'pc info -i -p size=4' does."""
    named = ctx.get_interface(":m-thru;size=4,depth=2")
    passed = ctx.get_interface(":m-thru", params={"size": "4", "depth": "2"})
    assert named is passed


def test_an_unparametrized_interface_still_works(ctx):
    plain = ctx.get_interface(":plain")
    assert plain is not None
    assert list(plain.get_ports().keys()) == ["plain"]


def test_a_parameter_the_interface_does_not_declare_is_reported(ctx):
    assert ctx.get_interface(":m-thru;nope=1") is None


def test_an_interface_with_no_values_cannot_be_parametrized(ctx):
    assert ctx.get_interface(":plain;size=4") is None


def test_one_section_holds_both_kinds_of_parameter(ctx):
    """'parameters:' is a part's and an interface's at once, told apart by content."""
    m = ctx.get_interface(":m;size=4")
    m.test()
    # The values it is built from, read as a part's parameters are...
    assert m.info()["values"] == {"size": 4.0}
    # ... beside the freedom of movement the section has always declared.
    assert sorted(m.params) == ["moveZ", "turnZ"]
    assert m.params["turnZ"].type == "turn"
    assert m.params["turnZ"].max == 360


def test_every_way_a_part_declares_a_parameter_works_on_an_interface(ctx):
    """'the exact same way as for parts' - types, enum, desc and the short form."""
    demo = ctx.get_interface(":vocabulary")
    demo.test()
    assert demo.info()["values"] == {
        "size": 3,
        "pitch": 0.5,
        "finish": "plain",
        "threaded": True,
        "count": 4,
    }
    assert demo.desc == "plain M3 x 0.5, 4 off, threaded=true"
    # An expression over them places the port...
    assert demo.get_ports()["p"].location.as_packed()[0] == [0.0, 0.0, 1.5]
    # ... and the freedom of movement declared beside them is untouched.
    assert (demo.params["moveZ"].min, demo.params["moveZ"].max) == (0, 10)

    other = ctx.get_interface(":vocabulary;size=8,pitch=1.25,finish=zinc,threaded=false,count=2")
    other.test()
    assert other.info()["values"] == {
        "size": 8,
        "pitch": 1.25,
        "finish": "zinc",
        "threaded": False,
        "count": 2,
    }
    assert other.desc == "zinc M8 x 1.25, 2 off, threaded=false"
    assert other.get_ports()["p"].location.as_packed()[0] == [0.0, 0.0, 10.0]


def test_an_integer_parameter_refuses_a_fraction(ctx):
    """The same rule a part's integer parameter follows."""
    assert ctx.get_interface(":vocabulary;size=3.5") is None


def test_a_shape_declares_no_freedom_of_movement_of_its_own(ctx):
    """A part's 'parameters:' is all values; what it may do comes from what it implements."""
    plate = ctx.get_part(":plate")
    assert plate.with_ports.declared_movement_params(plate.config) == {}
    assert "thickness" in plate.with_ports.expression_values()


# --- what the values reach ---------------------------------------------------


def test_a_port_passes_its_parameter_values_to_its_sketch(ctx):
    """One sketch serves the family, instead of one sketch per size."""
    port = ctx.get_interface(":m-thru;size=4,depth=2").get_ports()["thru-opening-m"]
    assert port.sketch.name == "m;size=4"
    assert port.sketch.info()["outline"] == {"circle": 2.0}

    # A value equal to the default still names an instance of its own, exactly
    # as 'cube;width=10' does where 10 is what 'cube' defaults to.
    port3 = ctx.get_interface(":m-thru;size=3,depth=2").get_ports()["thru-opening-m"]
    assert port3.sketch.name == "m;size=3"
    assert port3.sketch.info()["outline"] == {"circle": 1.5}


def test_port_coordinates_may_be_expressions(ctx):
    pattern = ctx.get_interface(":m-square-pattern;size=4,pitch=20,depth=2")
    corners = {name: port.location.as_packed()[0] for name, port in pattern.get_ports().items()}
    assert corners == {
        "TL-thru-opening-m": [-10.0, 10.0, 0.0],
        "TR-thru-opening-m": [10.0, 10.0, 0.0],
        "BL-thru-opening-m": [-10.0, -10.0, 0.0],
        "BR-thru-opening-m": [10.0, -10.0, 0.0],
    }


def test_an_inherited_interface_may_be_named_by_an_expression(ctx):
    pattern = ctx.get_interface(":m-square-pattern;size=4,pitch=20,depth=2")
    assert sorted(pattern.get_parents().keys()) == ["//:m-thru;depth=2,size=4"]


def test_freedom_of_movement_may_be_an_expression(ctx):
    """'parameters:' still means the freedom of movement, and reads the values."""
    screw = ctx.get_interface(":m-screw;size=4,length=10")
    assert screw.params["moveZ"].max == 8.0
    assert ctx.get_interface(":m-screw;size=4,length=6").params["moveZ"].max == 4.0


def test_an_interface_narrows_the_freedom_it_inherits(ctx):
    """The screw's own 'moveZ' is how far this screw goes in, not 'm's silence."""
    screw = ctx.get_interface(":m-screw;size=4,length=10")
    screw.test()  # the inherited parameters arrive when the interface is instantiated
    assert screw.params["moveZ"].max == 8.0
    # And what it does not redeclare it still gets: 'm' allows the full turn.
    assert screw.params["turnZ"].max == 360


def test_parameters_may_be_the_bare_list_they_have_always_been(ctx):
    """'parameters: [moveX, moveY, turnZ]' - names, no bounds, move freely.

    It predates the two-kind section, and the reader that tells the two kinds
    apart now sees this configuration before the one that expanded the list did.
    """
    iface = ctx.get_interface(":m-list-form")
    assert iface is not None, "the list short form failed to load"
    iface.test()
    assert sorted(iface.params) == ["moveX", "moveY", "turnZ"]


def test_a_freedom_that_runs_backwards_is_reported_and_read_as_none(ctx):
    """A computed bound can invert: 'length - 2' for a 1mm screw is -1.

    The published '//pub/std/metric/m' does exactly that, and a solver handed
    0..-1 has no value to choose from.
    """
    reported = []
    with mock.patch.object(pc.logging, "warning", lambda *args: reported.append(args)):
        screw = ctx.get_interface(":m-screw;size=4,length=1")
        screw.test()
    assert screw.params["moveZ"].min == 0
    assert screw.params["moveZ"].max == 0
    assert screw.params["moveZ"].default == 0
    assert any("backwards" in str(args) for args in reported)


def test_anything_else_of_an_interface_may_be_an_expression(ctx):
    assert ctx.get_interface(":m;size=5").get_thread_step() == 1.0


def test_mates_are_registered_between_the_parametrized_instances(ctx):
    thru = ctx.get_interface(":m-thru;size=4,depth=2")
    thru.test()  # 'mates:' is read when the interface is instantiated, which is lazy
    assert list(ctx.mates.get(thru.full_name, {}).keys()) == ["//:m-screw;size=4"]
    # And the other way round, which is what makes the screw find the hole.
    screw = ctx.get_interface(":m-screw;size=4")
    assert thru.full_name in ctx.mates.get(screw.full_name, {})


# --- an inherited port drawn with a different boundary ------------------------


def test_an_inherited_instance_may_restate_its_boundary(ctx):
    """The same opening drawn differently: a slotted hole is a through hole.

    It inherits one, so it mates as one and keeps its port where the plain hole
    would have been; what tells them apart is the outline and the freedom of
    movement.
    """
    slotted = ctx.get_interface(":m-thru-slotted;size=4,width=30")
    slotted.test()

    ((name, port),) = slotted.get_ports().items()
    assert name == "slotted-30-thru-opening-m"
    assert port.sketch.name == "m-slot;size=4,width=30"

    # It is a through hole, all the way up.
    assert "//:m-thru;depth=1,size=4" in slotted.compatible_with
    assert "//:m-opening;size=4" in slotted.compatible_with

    # And the slot is what it may move along.
    assert (slotted.params["moveX"].min, slotted.params["moveX"].max) == (0, 26.0)


def test_an_inherited_port_keeps_its_boundary_where_nothing_restates_it(ctx):
    thru = ctx.get_interface(":m-thru;size=4,depth=1")
    thru.test()
    (port,) = thru.get_ports().values()
    assert port.sketch.name == "m;size=4"


# --- an interface that is another one under a different name -----------------


def test_an_alias_has_the_target_s_ports_under_the_same_names(ctx):
    """What a package published before its family became parametric keeps working."""
    alias = ctx.get_interface(":m3-thru-3")
    target = ctx.get_interface(":m-thru;size=3,depth=3")
    alias.test()
    target.test()
    assert sorted(alias.get_ports()) == sorted(target.get_ports()) == ["thru-opening-m"]
    assert alias.desc == target.desc


def test_an_alias_may_state_a_description_of_its_own(ctx):
    alias = ctx.get_interface(":m4-screw-6")
    assert alias.desc == "6mm long M4 screw, under the name this package has always used"


def test_an_alias_may_be_written_as_a_bare_string(ctx):
    """The short form a sketch and a part already have."""
    alias = ctx.get_interface(":m5-thru-2")
    alias.test()
    assert alias.alias == "m-thru;size=5,depth=2"
    assert alias.desc == "2mm thick through hole of 5mm diameter"
    assert sorted(alias.get_ports()) == ["thru-opening-m"]


def test_parametrizing_an_alias_is_reported_rather_than_crashing(ctx):
    """An alias has no parameters of its own - the values are in what it names."""
    assert ctx.get_interface(":m5-thru-2;size=9") is None


def test_an_alias_is_a_drop_in_for_what_it_names(ctx):
    alias = ctx.get_interface(":m3-thru-3")
    alias.test()
    assert alias.compatible_with == {
        "//:m-thru;depth=3,size=3",
        "//:m-opening;size=3",
        "//:m;size=3",
    }


def test_compatibility_reaches_all_the_way_up(ctx):
    """Not only the first parent: what that one is a drop-in for counts too."""
    thru = ctx.get_interface(":m-thru;size=3,depth=3")
    thru.test()
    assert "//:m;size=3" in thru.compatible_with


def test_an_alias_mates_with_what_its_target_mates_with(ctx):
    alias = ctx.get_interface(":m3-thru-3")
    alias.test()
    ctx.get_interface(":m-screw;size=3").test()
    source, target = ctx.find_mating_interfaces(
        _fake_shape({"//:m-screw;size=3": {"": {}}}),
        _fake_shape({alias.full_name: {"": {}}}),
    )
    assert source == {"//:m-screw;size=3"}
    assert target == {"//:m3-thru-3"}


# --- a shape's own ports and the interfaces it implements --------------------


def test_a_part_implements_an_interface_parametrized_by_its_own_parameters(ctx):
    plate = ctx.get_part(":plate")
    assert "//:m-thru;depth=3,size=3" in plate.with_ports.get_interfaces()

    thicker = ctx.get_part(":plate;thickness=5")
    assert "//:m-thru;depth=5,size=3" in thicker.with_ports.get_interfaces()


def test_a_part_gets_the_ports_of_the_interface_it_implements(ctx):
    plate = ctx.get_part(":plate")
    assert sorted(plate.with_ports.get_ports().keys()) == [
        "BL-thru-opening-m",
        "BR-thru-opening-m",
        "TL-thru-opening-m",
        "TR-thru-opening-m",
    ]
