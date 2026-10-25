#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the CAE boundary conditions: units, the keys of each analysis, findings.

Everything here is the part of `pc cae <analysis>` that runs before any
solver does, and it is the part that is easy to get quietly wrong: a load written
"5" and a load written "5 kg" have to be the same force, "2 lb" has to be pounds
and not two of something ending in "b", and a `fix:` naming an interface the part
does not implement has to be reported rather than silently doing nothing.

No sandbox and no CAD library: `partcad.cae` reads configuration and converts
numbers, which is precisely why it can be tested like this.
"""

import json

import pytest

from partcad import cae
from partcad.cae import EVERY_INSTANCE, GRAVITY, AnalysisConfig, CaeConfigError


class FakeShape:
    """The little of a shape that `cae.config_of()` reads."""

    def __init__(self, config):
        """Stand in for a shape carrying `config` as its declaration."""
        self.config = config

    def get_final_config(self):
        """What an alias or an enrich would have resolved to; here, itself."""
        return self.config


# ---- units -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value,newtons",
    [
        # A bare number is a mass in kilograms, which is the documented default.
        (5, 5 * GRAVITY),
        (5.5, 5.5 * GRAVITY),
        ("7", 7 * GRAVITY),
        # Mass units, with and without a space, plural and singular, any case.
        ("5kg", 5 * GRAVITY),
        ("5 kg", 5 * GRAVITY),
        ("5 KG", 5 * GRAVITY),
        ("5 kgs", 5 * GRAVITY),
        ("500g", 0.5 * GRAVITY),
        ("500 mg", 0.0005 * GRAVITY),
        ("1 ton", 1000 * GRAVITY),
        ("1 tonne", 1000 * GRAVITY),
        ("2 lb", 2 * 0.45359237 * GRAVITY),
        ("2 lbs", 2 * 0.45359237 * GRAVITY),
        ("2 pounds", 2 * 0.45359237 * GRAVITY),
        # Force units are stored as they stand: no gravity anywhere.
        ("30 N", 30.0),
        ("30n", 30.0),
        ("30 newtons", 30.0),
        ("0.5 kN", 500.0),
        ("3 mN", 0.003),
        # The task's own spelling of newtons.
        ("2 nm", 2.0),
        # A sign and an exponent are numbers like any other.
        ("-4 N", -4.0),
        ("1e3 g", 1.0 * GRAVITY),
    ],
)
def test_parse_force(value, newtons):
    """Every spelling of a load, and the newtons it has to come out as."""
    assert cae.parse_force(value) == pytest.approx(newtons)


@pytest.mark.parametrize("value", ["", "   ", "abc", "5 furlongs", "moons", "kg", True, None, [1], {"a": 1}])
def test_parse_force_refuses_nonsense(value):
    """A value that is not a force is refused with a sentence, never guessed at.

    'moons' is the interesting one: it ends in an 'n', and a parser that stopped
    at the first unit name it matched would read it as some number of newtons.
    """
    with pytest.raises(CaeConfigError):
        cae.parse_force(value)


def test_parse_force_error_names_the_field():
    """The message says which declaration is wrong, not just that one is."""
    with pytest.raises(CaeConfigError, match=r"'load: hook:'"):
        cae.parse_force("heavy", "'load: hook:'")


# ---- fix: ------------------------------------------------------------------


def test_fix_as_a_list_of_interfaces():
    """The short form: these interfaces, every instance of each."""
    config = AnalysisConfig("fea", {"fix": ["m3-screw", "//other:rail"]})
    assert config.fixtures == {"m3-screw": [EVERY_INSTANCE], "//other:rail": [EVERY_INSTANCE]}
    assert config.loads == {}


def test_fix_as_a_map_of_instances():
    """The long form, in all three ways one entry can name its instances."""
    config = AnalysisConfig("fea", {"fix": {"m3-screw": ["left", "right"], "rail": None, "pin": "one"}})
    assert config.fixtures == {
        "m3-screw": ["left", "right"],
        # An interface named with nothing under it is the whole of it.
        "rail": [EVERY_INSTANCE],
        "pin": ["one"],
    }


def test_fix_refuses_what_is_not_a_name():
    """An interface and an instance are names; anything else is a mistake."""
    with pytest.raises(CaeConfigError):
        AnalysisConfig("fea", {"fix": [{"m3-screw": 1}]})
    with pytest.raises(CaeConfigError):
        AnalysisConfig("fea", {"fix": {"m3-screw": [5]}})


# ---- outlet: ---------------------------------------------------------------


def test_outlet_takes_the_three_shapes_fix_takes():
    """It names interfaces and, where it matters, which instances of them."""
    assert AnalysisConfig("cfd", {"load": {"in": "1 N"}, "outlet": "out"}).outlets == {"out": [EVERY_INSTANCE]}
    assert AnalysisConfig("cfd", {"load": {"in": "1 N"}, "outlet": ["a", "b"]}).outlets == {
        "a": [EVERY_INSTANCE],
        "b": [EVERY_INSTANCE],
    }
    assert AnalysisConfig("cfd", {"load": {"in": "1 N"}, "outlet": {"out": ["left"]}}).outlets == {"out": ["left"]}


def test_outlet_refuses_what_is_not_a_name():
    with pytest.raises(CaeConfigError):
        AnalysisConfig("cfd", {"load": {"in": "1 N"}, "outlet": [{"out": 1}]})
    with pytest.raises(CaeConfigError):
        AnalysisConfig("cfd", {"load": {"in": "1 N"}, "outlet": 5})


def test_only_a_flow_has_an_outlet():
    """A stress analysis has nothing to let out, so the word is not accepted.

    Taking it silently would let a part write something that reads as a
    boundary condition and is not one -- and `fea:` would then be quietly
    ignoring half of what it was told.
    """
    with pytest.raises(CaeConfigError, match="outlet"):
        AnalysisConfig("fea", {"fix": ["root"], "outlet": ["tip"]})


def test_an_outlet_is_carried_to_the_implementation_only_when_there_is_one():
    """An implementation that never heard of outlets sees what it always saw."""
    assert "outlet" not in AnalysisConfig("cfd", {"fix": ["wall"], "load": {"in": "1 N"}}).to_data()
    data = AnalysisConfig("cfd", {"fix": ["wall"], "load": {"in": "1 N"}, "outlet": ["out"]}).to_data()
    assert data["outlet"] == {"out": [EVERY_INSTANCE]}


def test_an_outlet_lands_on_its_port():
    """The record an implementation reads the outlet off."""
    config = AnalysisConfig("cfd", {"fix": ["wall"], "load": {"in": "1 N"}, "outlet": ["out"]})
    records = [_port("//p:wall"), _port("//p:in"), _port("//p:out")]
    assigned, unmatched = cae.assign_ports(config, records)
    assert unmatched == []
    assert [entry["interface"] for entry in assigned if entry.get("outlet")] == ["//p:out"]
    # And the ones it does not name are told so, rather than left undecided.
    assert [entry.get("outlet") for entry in assigned] == [False, False, True]


def test_an_outlet_that_matched_nothing_is_reported():
    """A boundary condition doing nothing is worth saying out loud."""
    config = AnalysisConfig("cfd", {"fix": ["wall"], "load": {"in": "1 N"}, "outlet": ["out"]})
    _assigned, unmatched = cae.assign_ports(config, [_port("//p:wall"), _port("//p:in")])
    assert [name for name, _reason in unmatched] == ["out"]


# ---- load: -----------------------------------------------------------------


def test_load_flat_and_nested():
    """One value for the whole interface, or one per named instance."""
    config = AnalysisConfig(
        "fea",
        {"load": {"hook": "5 kg", "rail": {"left": "30 N", "right": 2}}},
    )
    assert config.loads["hook"] == {EVERY_INSTANCE: pytest.approx(5 * GRAVITY)}
    assert config.loads["rail"]["left"] == pytest.approx(30.0)
    assert config.loads["rail"]["right"] == pytest.approx(2 * GRAVITY)


def test_load_refuses_a_list():
    """A list would say what is loaded without saying with what."""
    with pytest.raises(CaeConfigError):
        AnalysisConfig("fea", {"load": ["hook"]})


def test_load_refuses_an_empty_instance_map():
    """`hook: {}` is an interface named and then nothing said about it."""
    with pytest.raises(CaeConfigError, match="names no instance"):
        AnalysisConfig("fea", {"load": {"hook": {}}})


# ---- the section as a whole -------------------------------------------------


@pytest.mark.parametrize(
    "section,message",
    [
        (None, "is empty"),
        ("m3-screw", "is not a section"),
        ({}, "declares neither"),
        ({"fix": None, "load": None}, "declares neither"),
        ({"hold": ["m3-screw"]}, "does not take"),
    ],
)
def test_malformed_sections_say_what_is_wrong(section, message):
    """Every refusal is a sentence: it is what the IDE's FEA tab prints."""
    with pytest.raises(CaeConfigError, match=message):
        AnalysisConfig("fea", section)


def test_config_of_reads_the_named_section():
    """A part may declare both, and each analysis reads only its own."""
    shape = FakeShape({"fea": {"fix": ["a"]}, "cfd": {"load": {"b": "1 N"}}})
    assert cae.config_of(shape, "fea").fixtures == {"a": [EVERY_INSTANCE]}
    assert cae.config_of(shape, "cfd").loads == {"b": {EVERY_INSTANCE: 1.0}}


def test_config_of_is_none_when_nothing_is_declared():
    """The ordinary case, and not an error: most parts are never analysed."""
    assert cae.config_of(FakeShape({"type": "step"}), "fea") is None


def test_config_of_refuses_an_analysis_partcad_does_not_run():
    """Asking about an analysis that does not exist is a caller's bug."""
    with pytest.raises(CaeConfigError):
        cae.config_of(FakeShape({}), "acoustics")


def test_to_data_is_json_and_names_the_analysis():
    """It crosses a sandbox boundary as JSON, so it has to survive the trip."""
    config = AnalysisConfig("cfd", {"fix": ["wall"], "load": {"inlet": "2 N"}})
    data = config.to_data()
    assert json.loads(json.dumps(data)) == {
        "analysis": "cfd",
        "fix": {"wall": [EVERY_INSTANCE]},
        "load": {"inlet": {EVERY_INSTANCE: 2.0}},
    }


# ---- attaching the conditions to ports --------------------------------------


def _port(interface, instance="", port="p"):
    """One record shaped as `render_overlay.collect_async()` produces them."""
    return {
        "port": port,
        "interface": interface,
        "interface_label": (interface or "").rsplit(":", 1)[-1],
        "instance": instance,
        "owner": "",
        "location": [[0, 0, 0], [0, 0, 1], 0],
    }


def test_assign_ports_matches_short_and_qualified_names():
    """A part names an interface as it names one anywhere else: short or full."""
    config = AnalysisConfig("fea", {"fix": ["m3-screw"], "load": {"//pkg:hook": "1 N"}})
    records = [_port("//pkg:m3-screw", port="a"), _port("//pkg:hook", port="b")]
    assigned, unmatched = cae.assign_ports(config, records)

    assert unmatched == []
    by_port = {record["port"]: record for record in assigned}
    assert by_port["a"]["fix"] is True and by_port["a"]["load"] == 0.0
    assert by_port["b"]["fix"] is False and by_port["b"]["load"] == pytest.approx(1.0)


def test_assign_ports_does_not_match_another_package_when_qualified():
    """A qualified declaration names one interface, not every one so called."""
    config = AnalysisConfig("fea", {"fix": ["//pkg:m3-screw"]})
    assigned, unmatched = cae.assign_ports(config, [_port("//other:m3-screw")])
    assert assigned == []
    assert unmatched == [("//pkg:m3-screw", "this object does not implement it")]


def test_assign_ports_selects_named_instances():
    """A condition on one instance leaves the interface's others alone."""
    config = AnalysisConfig("fea", {"fix": {"rail": ["left"]}})
    records = [_port("//pkg:rail", "left", "a"), _port("//pkg:rail", "right", "b")]
    assigned, _ = cae.assign_ports(config, records)
    assert [record["port"] for record in assigned] == ["a"]


def test_a_load_on_an_interface_applies_to_every_instance():
    """An interface-wide load is each instance's, not one shared between them.

    The conservative reading, and the one a user checking a bracket wants: a
    divided load would silently pass a part that a doubled one fails.
    """
    config = AnalysisConfig("fea", {"load": {"rail": "5 kg"}})
    records = [_port("//pkg:rail", "left", "a"), _port("//pkg:rail", "right", "b")]
    assigned, _ = cae.assign_ports(config, records)
    assert [record["load"] for record in assigned] == [
        pytest.approx(5 * GRAVITY),
        pytest.approx(5 * GRAVITY),
    ]


def test_a_named_instance_overrides_the_interface_wide_load():
    """The specific value wins where both are declared."""
    config = AnalysisConfig("fea", {"load": {"rail": {"left": "1 N", EVERY_INSTANCE: "9 N"}}})
    records = [_port("//pkg:rail", "left", "a"), _port("//pkg:rail", "right", "b")]
    assigned, _ = cae.assign_ports(config, records)
    loads = {record["port"]: record["load"] for record in assigned}
    assert loads == {"a": pytest.approx(1.0), "b": pytest.approx(9.0)}


def test_assign_ports_reports_what_nothing_matched():
    """A condition on an interface the part does not implement does nothing."""
    config = AnalysisConfig("fea", {"fix": ["absent"], "load": {"also-absent": "1 N"}})
    assigned, unmatched = cae.assign_ports(config, [_port("//pkg:rail")])
    assert assigned == []
    assert sorted(unmatched) == [
        ("absent", "this object does not implement it"),
        ("also-absent", "this object does not implement it"),
    ]


def test_a_misspelt_instance_is_not_reported_as_a_missing_interface():
    """The two are different mistakes and read very differently.

    Saying "this object does not implement m3-screw" about an object that
    implements it, because the *instance* was misspelt, sends the reader to look
    at `implements:` for something that is already there.
    """
    config = AnalysisConfig("fea", {"fix": {"rail": ["lefft"]}})
    assigned, unmatched = cae.assign_ports(config, [_port("//pkg:rail", "left")])
    assert assigned == []
    assert unmatched == [("rail", "no instance or port named lefft")]


def test_an_empty_fix_instance_list_is_refused():
    """`rail:` with nothing under it is every instance; `rail: []` is none.

    The second is naming the instances and then naming none, which is what
    `load: {}` is already refused for.
    """
    with pytest.raises(CaeConfigError, match="names no instance"):
        AnalysisConfig("fea", {"fix": {"rail": []}})


def test_assign_ports_leaves_out_the_ports_nothing_names():
    """The implementation is told where to hold and pull, not what else exists."""
    config = AnalysisConfig("fea", {"fix": ["rail"]})
    assigned, _ = cae.assign_ports(config, [_port("//pkg:rail", port="a"), _port("//pkg:other", port="b")])
    assert [record["port"] for record in assigned] == ["a"]


# ---- findings ---------------------------------------------------------------


def test_normalize_findings_accepts_every_shape_an_implementation_may_use():
    """A reader should not have to know which shape the solver chose."""
    assert cae.normalize_findings(None) == []
    assert cae.normalize_findings([]) == []
    assert cae.normalize_findings(["too thin"]) == [{"message": "too thin"}]
    assert cae.normalize_findings({"message": "one"}) == [{"message": "one"}]
    # A finding that named its text something else still prints as a finding.
    assert cae.normalize_findings([{"text": "bent", "severity": "error"}]) == [
        {"text": "bent", "severity": "error", "message": "bent"}
    ]


def test_findings_report_orders_the_worst_first():
    """What breaks the part is what a reader needs to see at the top."""
    report = cae.findings_report(
        "//pkg:bracket",
        "fea",
        cae.normalize_findings(
            [
                {"message": "a note", "severity": "info"},
                {"message": "it breaks", "severity": "error", "where": "hole 2"},
            ]
        ),
    )
    assert report.index("it breaks") < report.index("a note")
    assert "hole 2" in report
    assert "Total: 2 finding(s)" in report


def test_findings_report_says_so_when_there_is_nothing():
    """A pass is an answer and is printed as one, not as an empty list."""
    assert "found nothing" in cae.findings_report("//pkg:bracket", "fea", [])


# --------------------------------------------------------------------------- #
# The shapes a declaration can take, and the ones it cannot                   #
# --------------------------------------------------------------------------- #


def test_one_interface_name_holds_all_of_it():
    """`fix: m3-screw` is the degenerate case of the list, and means the same."""
    config = AnalysisConfig("fea", {"fix": "m3-screw"})
    assert config.fixtures == {"m3-screw": [EVERY_INSTANCE]}


def test_fix_that_is_neither_a_list_nor_a_map_is_refused():
    """A number under `fix:` names no interface, and saying so beats guessing."""
    with pytest.raises(CaeConfigError, match="neither a list of interfaces nor a map"):
        AnalysisConfig("fea", {"fix": 7})


def test_an_instance_that_is_neither_a_name_nor_a_list_is_refused():
    """`fix: {m3-screw: 3}` names an instance called what, exactly?"""
    with pytest.raises(CaeConfigError, match="neither an interface instance nor a list"):
        AnalysisConfig("fea", {"fix": {"m3-screw": 3}})


def test_the_repr_says_what_was_parsed():
    """The loads read back as the newtons they became, not as what was written."""
    text = repr(AnalysisConfig("fea", {"fix": ["m3-screw"], "load": {"hook": "1 kg"}}))
    assert "fea" in text and "m3-screw" in text
    assert str(GRAVITY) in text


# --------------------------------------------------------------------------- #
# Findings an implementation did not shape the way PartCAD expects            #
# --------------------------------------------------------------------------- #


def test_findings_that_are_not_a_list_become_one():
    """A solver that answered with a sentence still gets its sentence printed."""
    assert cae.normalize_findings("it breaks") == [{"message": "it breaks"}]


def test_a_single_finding_need_not_be_wrapped_in_a_list():
    """One dict is one finding, which is the shape a script most easily returns."""
    assert cae.normalize_findings({"message": "it breaks"}) == [{"message": "it breaks"}]


def test_a_finding_with_no_recognisable_text_still_prints_as_something():
    """Better the whole record than a row of blanks with the detail hidden."""
    (finding,) = cae.normalize_findings([{"severity": "error", "stress": 1.0}])
    assert "stress" in finding["message"]
    assert finding["severity"] == "error"


def test_a_port_that_belongs_to_no_interface_is_passed_over():
    """A bare coordinate frame is not something a condition can name."""
    config = AnalysisConfig("fea", {"fix": ["m3-screw"]})
    assigned, unmatched = cae.assign_ports(config, [_port(None)])
    assert assigned == []
    assert unmatched == [("m3-screw", "this object does not implement it")]


def test_a_load_named_for_one_instance_leaves_the_others_unloaded():
    """The other instances are not "loaded with nothing"; they are left out."""
    config = AnalysisConfig("fea", {"load": {"rail": {"left": "1 N"}}})
    records = [_port("//pkg:rail", "left", "a"), _port("//pkg:rail", "right", "b")]
    assigned, unmatched = cae.assign_ports(config, records)
    assert [record["port"] for record in assigned] == ["a"]
    assert unmatched == []


def test_an_instance_that_does_not_exist_is_reported_even_when_a_sibling_matched():
    """Two bolts named, one on the object: the other is not quietly dropped.

    A declaration is satisfied per *instance*, not per interface. Counting it as
    matched because a sibling matched is how a solver ends up holding one bolt of
    two and answering with a number that looks perfectly reasonable.
    """
    config = AnalysisConfig("fea", {"fix": {"rail": ["left", "right"]}})
    assigned, unmatched = cae.assign_ports(config, [_port("//pkg:rail", "left", "a")])
    assert [record["port"] for record in assigned] == ["a"]
    assert unmatched == [("rail", "no instance or port named right")]


def test_the_same_holds_for_a_load_named_per_instance():
    """`load:` carries a force per instance, and a missing one is a missing force."""
    config = AnalysisConfig("fea", {"load": {"rail": {"left": "1 N", "right": "2 N"}}})
    assigned, unmatched = cae.assign_ports(config, [_port("//pkg:rail", "left", "a")])
    assert [record["port"] for record in assigned] == ["a"]
    assert unmatched == [("rail", "no instance or port named right")]


def test_every_instance_is_satisfied_by_any_one_of_them():
    """`fix: [rail]` asks for all of them, so one port matching is a match."""
    config = AnalysisConfig("fea", {"fix": ["rail"]})
    assigned, unmatched = cae.assign_ports(config, [_port("//pkg:rail", "left", "a")])
    assert [record["port"] for record in assigned] == ["a"]
    assert unmatched == []


def test_an_instance_load_and_an_interface_wide_one_are_both_accounted_for():
    """The instance's own value wins, and the interface-wide one still counts.

    Both are declarations a user wrote, so a warning about either has to depend
    on whether that one landed somewhere -- not on the other having landed.
    """
    config = AnalysisConfig("fea", {"load": {"rail": {EVERY_INSTANCE: "1 N", "left": "2 N"}}})
    records = [_port("//pkg:rail", "left", "a"), _port("//pkg:rail", "right", "b")]
    assigned, unmatched = cae.assign_ports(config, records)
    by_port = {record["port"]: record for record in assigned}
    assert by_port["a"]["load"] == pytest.approx(2.0)
    assert by_port["b"]["load"] == pytest.approx(1.0)
    assert unmatched == []


# ---- dynamic: and thermal: ---------------------------------------------------


@pytest.mark.parametrize(
    "value,celsius",
    [
        # A bare number is Celsius: "held at 40" means forty degrees.
        (40, 40.0),
        ("40", 40.0),
        ("40 C", 40.0),
        ("40c", 40.0),
        ("40 °C", 40.0),
        ("40 degC", 40.0),
        ("313.15 K", 40.0),
        ("313.15 kelvin", 40.0),
        ("104 F", 40.0),
        ("-40 F", -40.0),
        ("-273.15 C", -273.15),
    ],
)
def test_parse_temperature(value, celsius):
    """Every spelling of one temperature lands on the same number of degrees Celsius."""
    assert cae.parse_temperature(value) == pytest.approx(celsius)


@pytest.mark.parametrize("value", ["-300 C", "-1 K", True, "warm", "40 R", None, ""])
def test_parse_temperature_refuses_nonsense(value):
    """Below absolute zero is a kelvin written as Celsius, not a cryostat."""
    with pytest.raises(CaeConfigError):
        cae.parse_temperature(value)


@pytest.mark.parametrize(
    "value,watts",
    [(5, 5.0), ("5 W", 5.0), ("5w", 5.0), ("250 mW", 0.25), ("1.5 kW", 1500.0), ("-2 W", -2.0), ("3 watts", 3.0)],
)
def test_parse_power(value, watts):
    """A heat input is a power, and a negative one is heat taken out."""
    assert cae.parse_power(value) == pytest.approx(watts)


@pytest.mark.parametrize("value,coefficient", [(10, 10.0), ("10", 10.0), ("10 W/m2K", 10.0), ("25 W/(m^2*K)", 25.0)])
def test_parse_film_coefficient(value, coefficient):
    """The one unit a film coefficient has, written any of the usual ways."""
    assert cae.parse_film_coefficient(value) == pytest.approx(coefficient)


def test_a_negative_film_coefficient_is_refused():
    """A surface that heats up by being cooled is a typo."""
    with pytest.raises(CaeConfigError, match="negative"):
        cae.parse_film_coefficient(-5)


def test_dynamic_reads_fix_alone():
    """A natural frequency is a property of the part and how it is held."""
    config = AnalysisConfig("dynamic", {"fix": ["root"]})
    assert config.fixtures == {"root": [EVERY_INSTANCE]}
    assert config.to_data() == {"analysis": "dynamic", "fix": {"root": [EVERY_INSTANCE]}}
    with pytest.raises(CaeConfigError, match="does not take load"):
        AnalysisConfig("dynamic", {"fix": ["root"], "load": {"tip": "1 N"}})
    with pytest.raises(CaeConfigError, match="declares none of 'fix:'"):
        AnalysisConfig("dynamic", {"desc": "nothing held"})


def test_thermal_reads_its_three_keys_in_their_units():
    """Temperatures in Celsius, heat in watts, film coefficients as written."""
    config = AnalysisConfig(
        "thermal",
        {
            "temperature": {"root": "293.15 K"},
            "heat": {"pad": {"left": "500 mW", "right": 2}},
            "convection": {"fins": 12},
        },
    )
    data = config.to_data()
    assert data["analysis"] == "thermal"
    assert data["temperature"] == {"root": {EVERY_INSTANCE: pytest.approx(20.0)}}
    assert data["heat"] == {"pad": {"left": pytest.approx(0.5), "right": pytest.approx(2.0)}}
    assert data["convection"] == {"fins": {EVERY_INSTANCE: 12.0}}
    assert json.loads(json.dumps(data)) == data


def test_thermal_takes_nothing_a_structural_analysis_takes():
    """`fix:` on a heat problem would read as a condition and not be one."""
    with pytest.raises(CaeConfigError, match="does not take fix"):
        AnalysisConfig("thermal", {"fix": ["root"], "heat": {"tip": "1 W"}})
    with pytest.raises(CaeConfigError, match="declares none of 'temperature:', 'heat:', 'convection:'"):
        AnalysisConfig("thermal", {})


def test_thermal_conditions_land_on_their_ports_with_every_key_present():
    """A newer analysis tells the implementation every key it reads, set or not."""
    config = AnalysisConfig("thermal", {"temperature": {"root": 20}, "heat": {"tip": "1 W"}})
    assigned, unmatched = cae.assign_ports(config, [_port("//p:root"), _port("//p:tip"), _port("//p:other")])
    assert unmatched == []
    assert [(entry["interface"], entry["temperature"], entry["heat"], entry["convection"]) for entry in assigned] == [
        ("//p:root", 20.0, None, None),
        ("//p:tip", None, 1.0, None),
    ]


def test_dynamic_fixtures_land_without_a_load_default():
    """There is no load in a modal analysis, so its records do not pretend there is."""
    config = AnalysisConfig("dynamic", {"fix": ["root"]})
    assigned, _unmatched = cae.assign_ports(config, [_port("//p:root")])
    assert assigned[0]["fix"] is True
    assert "load" not in assigned[0]


def test_every_analysis_has_a_label_and_roles():
    """What `pc cae`, the IDE and the schema enumerate has to agree."""
    assert set(cae.ANALYSES) == set(cae.ROLES) == set(cae.LABELS)


# ---- a load with a direction, and a gravity --------------------------------
#
# What a simulation measures acting on a part has a direction, and the part may
# be upside down or swinging: a stress analysis of it needs both said, in the
# part's own frame. A magnitude and an implementation's own gravity remain what
# every section that says neither is answered with.


def test_a_load_may_be_a_vector_in_the_parts_frame():
    """Three forces, each in any unit a load takes -- a bare number is still kilograms."""
    config = AnalysisConfig(
        "fea",
        {"fix": ["hub"], "load": {"tooth": {"21": ["0 N", "-146 N", "12N"]}, "hook": [0, 0, -5]}},
    )
    assert config.loads["tooth"]["21"] == pytest.approx([0.0, -146.0, 12.0])
    assert config.loads["hook"][EVERY_INSTANCE] == pytest.approx([0.0, 0.0, -5 * GRAVITY])
    assert config.directed


@pytest.mark.parametrize(
    "value,message",
    [
        ([1, 2], "list of 2"),
        ([0, 0, 0, 1], "list of 4"),
        (["0 N", "0 N", "0 N"], "nought in every direction"),
        (["1 N", "west", "0 N"], "the y of 'fea: load: tooth:' is not a force or a mass: 'west'"),
    ],
)
def test_a_vector_load_that_is_not_three_forces_is_refused(value, message):
    with pytest.raises(CaeConfigError, match=message):
        AnalysisConfig("fea", {"fix": ["hub"], "load": {"tooth": value}})


def test_a_vector_lands_as_its_magnitude_and_its_direction():
    """'load' stays the newtons every implementation reads; 'force' is the vector beside it."""
    config = AnalysisConfig("fea", {"fix": ["hub"], "load": {"tooth": {"21": ["3 N", "0 N", "-4 N"]}, "hook": "2 N"}})
    assigned, unmatched = cae.assign_ports(
        config,
        [
            {"interface": "tooth", "instance": "21", "port": "21-tooth"},
            {"interface": "tooth", "instance": "22", "port": "22-tooth"},
            {"interface": "hook", "instance": "", "port": "eye"},
            {"interface": "hub", "instance": "", "port": "bore"},
        ],
    )
    assert unmatched == []
    by_port = {record["port"]: record for record in assigned}
    assert sorted(by_port) == ["21-tooth", "bore", "eye"]
    assert by_port["21-tooth"]["load"] == pytest.approx(5.0)
    assert by_port["21-tooth"]["force"] == pytest.approx([3.0, 0.0, -4.0])
    # A magnitude is handed as it always was, with no direction to read.
    assert by_port["eye"]["load"] == pytest.approx(2.0)
    assert "force" not in by_port["eye"]


def test_the_request_carries_magnitudes_where_it_always_did_and_directions_beside_them():
    config = AnalysisConfig("fea", {"fix": ["hub"], "load": {"tooth": {"21": ["3 N", "0 N", "-4 N"]}, "hook": "2 N"}})
    data = json.loads(json.dumps(config.to_data()))
    assert data["load"] == {"tooth": {"21": pytest.approx(5.0)}, "hook": {EVERY_INSTANCE: pytest.approx(2.0)}}
    assert data["force"] == {"tooth": {"21": [3.0, 0.0, -4.0]}}
    assert "gravity" not in data
    # A section of magnitudes alone is the request it always was.
    plain = AnalysisConfig("fea", {"fix": ["hub"], "load": {"hook": "2 N"}}).to_data()
    assert "force" not in plain


def test_gravity_is_an_acceleration_in_the_parts_frame():
    config = AnalysisConfig("fea", {"fix": ["hub"], "gravity": [0, "-9.81 m/s^2", "1.5m/s2"]})
    assert config.gravity == pytest.approx([0.0, -9.81, 1.5])
    assert config.to_data()["gravity"] == pytest.approx([0.0, -9.81, 1.5])
    # Weightless is a thing worth saying, and is said.
    assert AnalysisConfig("fea", {"fix": ["hub"], "gravity": [0, 0, 0]}).gravity == [0.0, 0.0, 0.0]
    assert AnalysisConfig("fea", {"fix": ["hub"]}).gravity is None


@pytest.mark.parametrize("value", [9.81, [0, -9.81], [0, 0, "9.81 N"], "down"])
def test_gravity_that_is_not_three_accelerations_is_refused(value):
    with pytest.raises(CaeConfigError, match="'fea: gravity:'"):
        AnalysisConfig("fea", {"fix": ["hub"], "gravity": value})


def test_only_a_stress_analysis_takes_a_gravity():
    with pytest.raises(CaeConfigError, match="'dynamic:' does not take gravity"):
        AnalysisConfig("dynamic", {"fix": ["hub"], "gravity": [0, 0, -9.81]})
    with pytest.raises(CaeConfigError, match="it takes 'fix:', 'load:', 'gravity:', and 'desc:', 'feature:'"):
        AnalysisConfig("fea", {"fix": ["hub"], "weight": 1})


def test_what_an_implementation_has_to_read_to_answer_a_section():
    assert AnalysisConfig("fea", {"fix": ["hub"], "load": {"hook": "2 N"}}).reads() == set()
    assert AnalysisConfig("fea", {"fix": ["hub"], "load": {"hook": [0, 0, "-2 N"]}}).reads() == {"force"}
    assert AnalysisConfig("fea", {"fix": ["hub"], "gravity": [0, 0, -9.81]}).reads() == {"gravity"}


def test_an_implementation_that_does_not_read_a_direction_is_refused_rather_than_asked():
    config = AnalysisConfig("fea", {"fix": ["hub"], "load": {"hook": [0, 0, "-2 N"]}, "gravity": [0, 0, -1]})
    assert cae.unread_by(config, {"force", "gravity"}, "//x:fea") is None
    said = cae.unread_by(config, {"gravity"}, "//x:fea")
    assert "a load with a direction" in said and "//x:fea does not read it" in said
    assert "every load pulled straight down" in said and "state the loads as magnitudes" in said
    said = cae.unread_by(config, set(), "//x:fea")
    assert "lists nothing" in said and "reads 'force' and 'gravity'" in said
    # A section that states neither is answered by anything that answers it.
    assert cae.unread_by(AnalysisConfig("fea", {"fix": ["hub"]}), set(), "//x:fea") is None


def test_a_parameterized_interface_is_named_as_it_is_implemented():
    """A gear's teeth: '<package>:gear-tooth;module=1.25', instance '21', matched exactly."""
    name = "//pub/gears:gear-tooth;module=1.25"
    config = AnalysisConfig("fea", {"fix": ["hub"], "load": {name: {"21": ["0 N", "-1 N", "0 N"]}}})
    assigned, unmatched = cae.assign_ports(
        config, [{"interface": name, "instance": "21"}, {"interface": "hub", "instance": ""}]
    )
    assert unmatched == [] and assigned[0]["force"] == pytest.approx([0.0, -1.0, 0.0])


def test_a_name_under_an_interface_may_be_one_of_its_ports():
    """One tooth of a gear: its teeth are the ports of one unnamed instance of one interface."""
    gear = "//pub/gears:gear-28t;module=1.25"
    config = AnalysisConfig(
        "fea",
        {
            "fix": {"pattern": ["outer"]},
            "load": {gear: {"13-tooth": ["0 N", "-1 N", "0 N"], EVERY_INSTANCE: "1 N"}, "hook": {"eye-left": "2 N"}},
        },
    )
    records = [
        {"interface": gear, "instance": "", "port": "12-tooth"},
        {"interface": gear, "instance": "", "port": "13-tooth"},
        {"interface": "pattern", "instance": "outer", "port": "outer-TL"},
        {"interface": "pattern", "instance": "outer", "port": "outer-BR"},
        {"interface": "pattern", "instance": "inner", "port": "inner-TL"},
        {"interface": "hook", "instance": "", "port": "eye-left"},
        {"interface": "hook", "instance": "", "port": "eye-right"},
    ]
    assigned, unmatched = cae.assign_ports(config, records)
    assert unmatched == []
    by_port = {record["port"]: record for record in assigned}
    # The tooth named has its own force; every other port of the instance, the interface-wide one.
    assert by_port["13-tooth"]["force"] == pytest.approx([0.0, -1.0, 0.0])
    assert by_port["12-tooth"]["load"] == pytest.approx(1.0) and "force" not in by_port["12-tooth"]
    # Every port of the instance a set names; none of the other instance's.
    assert by_port["outer-TL"]["fix"] and by_port["outer-BR"]["fix"] and "inner-TL" not in by_port
    assert by_port["eye-left"]["load"] == pytest.approx(2.0) and "eye-right" not in by_port


def test_a_port_named_that_is_not_there_is_reported_as_neither():
    config = AnalysisConfig("fea", {"fix": ["hub"], "load": {"gear": {"31-tooth": "1 N"}}})
    _assigned, unmatched = cae.assign_ports(
        config, [{"interface": "gear", "instance": "", "port": "1-tooth"}, {"interface": "hub", "instance": ""}]
    )
    assert unmatched == [("gear", "no instance or port named 31-tooth")]


# --------------------------------------------------------------------------- #
# Named scenarios                                                             #
# --------------------------------------------------------------------------- #
#
# An analysis section is a map of scenarios, each under a name of its own, as
# 'simulate:' is a map of simulations. The form a section had before -- the
# conditions themselves -- is still read, as one scenario named 'default'.


def test_a_section_is_a_map_of_named_scenarios():
    scenarios = cae.declared("fea", {"loaded": {"fix": ["hub"], "load": {"hook": "1 N"}}, "free": {"fix": ["hub"]}})
    assert [scenario.name for scenario in scenarios] == ["loaded", "free"]
    assert not any(scenario.legacy for scenario in scenarios)
    assert scenarios[0].conditions().loads == {"hook": {EVERY_INSTANCE: 1.0}}
    assert scenarios[1].conditions().fixtures == {"hub": [EVERY_INSTANCE]}


def test_the_unnamed_form_is_one_scenario_named_default():
    """What every section was before scenarios, read as it always was."""
    (scenario,) = cae.declared("fea", {"fix": ["hub"], "load": {"hook": "1 N"}})
    assert scenario.legacy
    assert scenario.name == cae.LEGACY_SCENARIO
    assert scenario.conditions().fixtures == {"hub": [EVERY_INSTANCE]}
    # Its sentences read as they always did: no scenario name in them.
    assert scenario.label == "fea"
    assert scenario.title == "FEA"


def test_the_unnamed_form_is_told_apart_by_its_keys_alone():
    """'desc:' or 'implementation:' alone is the unnamed form too, and then names no condition."""
    (scenario,) = cae.declared("dynamic", {"implementation": "elmer:dynamic"})
    assert scenario.legacy
    with pytest.raises(CaeConfigError, match="'dynamic:' declares none of 'fix:'"):
        scenario.conditions()


def test_another_analysis_s_condition_is_the_unnamed_form_refused_as_such():
    """'outlet:' under 'fea:' is CFD's key in the wrong place, not a scenario called 'outlet'."""
    (scenario,) = cae.declared("fea", {"fix": ["hub"], "outlet": ["tip"]})
    assert scenario.legacy
    with pytest.raises(CaeConfigError, match="'fea:' does not take outlet"):
        scenario.conditions()


def test_a_condition_beside_a_named_scenario_is_refused():
    """A scenario's conditions one level too high, or a name one level too low."""
    with pytest.raises(CaeConfigError, match="mixes boundary conditions .'fix:'. with scenarios .loaded."):
        cae.declared("fea", {"fix": ["hub"], "loaded": {"load": {"hook": "1 N"}}})


@pytest.mark.parametrize("section", [None, {}, [{"fix": ["hub"]}], "loaded"])
def test_a_section_that_is_not_a_map_of_scenarios_is_refused(section):
    with pytest.raises(CaeConfigError, match="'fea:'"):
        cae.declared("fea", section)


@pytest.mark.parametrize("names", [("arm/held", "arm_held"), ("Loaded", "loaded")])
def test_two_scenarios_that_would_write_one_model_are_refused(names):
    """Each would overwrite the other's model, and be handed back the other's answer."""
    first, second = names
    with pytest.raises(CaeConfigError, match="names the scenarios '%s' and '%s'" % (first, second)):
        cae.declared("fea", {first: {"fix": ["x"]}, second: {"fix": ["x"]}})


def test_a_scenario_name_is_spelt_as_every_other_name_is():
    with pytest.raises(CaeConfigError, match="names a scenario 'a b'"):
        cae.declared("fea", {"a b": {"fix": ["hub"]}})


def test_a_malformed_scenario_names_itself_and_leaves_the_others_readable():
    """Listing never fails on one scenario; its own run is what reports it."""
    good, bad = cae.declared("fea", {"loaded": {"fix": ["hub"]}, "broken": {"load": {"hook": "5 bananas"}}})
    assert good.conditions().fixtures
    with pytest.raises(CaeConfigError, match="'fea: broken: load: hook:'") as raised:
        bad.conditions()
    assert "bananas" in str(raised.value)
    with pytest.raises(CaeConfigError, match="'fea: empty:' is empty"):
        cae.declared("fea", {"empty": None})[0].conditions()
    with pytest.raises(CaeConfigError, match="'cfd: walls:' declares neither 'fix:' nor 'load:'"):
        cae.declared("cfd", {"walls": {"desc": "nothing yet"}})[0].conditions()


def test_what_a_scenario_says_about_itself():
    """'desc:', 'feature:', 'implementation:' and 'params:', read without failing."""
    (scenario,) = cae.declared(
        "fea",
        {
            "loaded": {
                "desc": "A full shelf",
                "feature": "carries-a-shelf",
                "implementation": " calculix:fea ",
                "params": {"mesh_size": 0.01},
                "fix": ["hub"],
            }
        },
    )
    assert scenario.desc == "A full shelf"
    assert scenario.features == ["carries-a-shelf"]
    assert scenario.implementation == "calculix:fea"
    assert scenario.params == {"mesh_size": 0.01}
    assert scenario.to_dict() == {
        "name": "loaded",
        "desc": "A full shelf",
        "implementation": "calculix:fea",
        "features": ["carries-a-shelf"],
        "legacy": False,
    }
    config = scenario.conditions()
    assert config.name == "loaded"
    assert config.params == {"mesh_size": 0.01}
    assert config.features == ["carries-a-shelf"]
    assert config.implementation == "calculix:fea"


def test_a_scenario_may_demonstrate_several_features():
    (scenario,) = cae.declared("thermal", {"in-use": {"feature": ["cool", "", 7, "quiet"], "heat": {"chip": "1 W"}}})
    assert scenario.features == ["cool", "quiet"]


def test_params_have_to_be_a_map():
    (scenario,) = cae.declared("fea", {"loaded": {"fix": ["hub"], "params": [1, 2]}})
    with pytest.raises(CaeConfigError, match="'fea: loaded: params:' is not a map"):
        scenario.conditions()


def test_of_shape_reads_every_scenario_in_order():
    shape = FakeShape({"fea": {"b": {"fix": ["x"]}, "a": {"fix": ["y"]}}})
    assert [scenario.name for scenario in cae.of_shape(shape, "fea")] == ["b", "a"]
    assert cae.of_shape(shape, "cfd") == []


def test_the_unnamed_form_is_said_to_be_deprecated_once(caplog):
    shape = FakeShape({"fea": {"fix": ["x"]}})
    shape.project_name, shape.name = "//deprecation", "once"
    with caplog.at_level("WARNING"):
        cae.of_shape(shape, "fea")
        cae.of_shape(shape, "fea")
    assert caplog.text.count("deprecated") == 1
    assert "//deprecation:once" in caplog.text


def test_choose_takes_the_named_scenario_or_the_only_one():
    scenarios = cae.declared("fea", {"a": {"fix": ["x"]}, "b": {"fix": ["y"]}})
    assert cae.choose(scenarios, "b", "//p:q", "fea").name == "b"
    assert cae.choose(scenarios[:1], None, "//p:q", "fea").name == "a"
    with pytest.raises(CaeConfigError, match="declares 2 FEA scenarios .a, b.: name the one to run"):
        cae.choose(scenarios, None, "//p:q", "fea")
    with pytest.raises(CaeConfigError, match="declares no FEA scenario 'c'. It declares: a, b"):
        cae.choose(scenarios, "c", "//p:q", "fea")


def test_config_of_reads_one_scenario():
    shape = FakeShape({"fea": {"a": {"fix": ["x"]}, "b": {"load": {"y": "2 N"}}}})
    assert cae.config_of(shape, "fea", "b").loads == {"y": {EVERY_INSTANCE: 2.0}}
    with pytest.raises(CaeConfigError, match="name the one to run"):
        cae.config_of(shape, "fea")


def test_each_scenario_writes_a_model_of_its_own():
    """'bracket.fea.loaded.glb'; the unnamed form keeps 'bracket.fea.glb'."""
    (named,) = cae.declared("fea", {"loaded": {"fix": ["x"]}})
    (legacy,) = cae.declared("fea", {"fix": ["x"]})
    (slashed,) = cae.declared("fea", {"arm/held": {"fix": ["x"]}})
    assert cae.model_suffix("fea", named) == ".fea.loaded"
    assert cae.model_suffix("fea", legacy) == ".fea"
    assert cae.model_suffix("fea", None) == ".fea"
    assert cae.model_suffix("cfd", slashed) == ".cfd.arm_held"


def test_the_reports_name_the_scenario():
    assert cae.findings_report("//p:q", "fea", [], scenario="loaded") == "//p:q: FEA 'loaded' found nothing to report"
    assert cae.findings_report("//p:q", "fea", []) == "//p:q: FEA found nothing to report"
    report = cae.findings_report("//p:q", "fea", [{"message": "too much"}], scenario="loaded")
    assert report.startswith("//p:q: FEA 'loaded' findings:")
    assert cae.dysfunction_report("//p:q", "fea", "//x:fea", Exception("no ccx"), scenario="loaded").startswith(
        "//p:q: FEA 'loaded' could not be run by //x:fea"
    )


# --------------------------------------------------------------------------- #
# The schema                                                                  #
# --------------------------------------------------------------------------- #


def _valid(section, analysis="fea"):
    import jsonschema

    from partcad.lint.all import get_partcad_schema

    config = {"parts": {"bracket": {"type": "step", analysis: section}}}
    try:
        jsonschema.validate(instance=config, schema=get_partcad_schema())
    except jsonschema.exceptions.ValidationError:
        return False
    return True


def test_the_schema_takes_named_scenarios():
    assert _valid(
        {
            "loaded": {
                "desc": "A full shelf",
                "feature": ["carries-a-shelf"],
                "params": {"mesh_size": 0.01},
                "implementation": "//pub/feature/cae/calculix:fea",
                "fix": ["m3-screw"],
                "load": {"hook": "5 kg"},
                "gravity": [0, 0, -9.81],
            },
            "dropped": {"fix": ["m3-screw"]},
        }
    )
    assert _valid({"bolted-down": {"fix": ["m3-screw"]}}, "dynamic")
    assert _valid({"in-use": {"heat": {"chip": "5 W"}}}, "thermal")
    assert _valid({"poiseuille": {"load": {"inlet": "5 mN"}, "outlet": ["out"]}}, "cfd")


def test_the_schema_still_takes_the_unnamed_form():
    assert _valid({"fix": ["m3-screw"], "load": {"hook": "5 kg"}})
    assert _valid({"implementation": "elmer:thermal", "temperature": {"root": 20}}, "thermal")


def test_the_schema_refuses_what_the_reader_refuses():
    # A scenario named after a key, which is what tells the two forms apart.
    assert not _valid({"load": {"fix": ["m3-screw"]}})
    # A condition beside a named scenario.
    assert not _valid({"fix": ["m3-screw"], "loaded": {"load": {"hook": 1}}})
    # A key the analysis does not read, in a scenario.
    assert not _valid({"loaded": {"fix": ["m3-screw"], "outlet": ["out"]}})
    # A name that is not one.
    assert not _valid({"a b": {"fix": ["m3-screw"]}})
    assert not _valid({})
