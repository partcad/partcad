#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the CAE boundary conditions: units, `fix:`/`load:`, findings.

Everything here is the part of `pc cae fea` / `pc cae cfd` that runs before any
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
        self.config = config

    def get_final_config(self):
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
    config = AnalysisConfig("fea", {"fix": ["m3-screw", "//other:rail"]})
    assert config.fixtures == {"m3-screw": [EVERY_INSTANCE], "//other:rail": [EVERY_INSTANCE]}
    assert config.loads == {}


def test_fix_as_a_map_of_instances():
    config = AnalysisConfig("fea", {"fix": {"m3-screw": ["left", "right"], "rail": None, "pin": "one"}})
    assert config.fixtures == {
        "m3-screw": ["left", "right"],
        # An interface named with nothing under it is the whole of it.
        "rail": [EVERY_INSTANCE],
        "pin": ["one"],
    }


def test_fix_refuses_what_is_not_a_name():
    with pytest.raises(CaeConfigError):
        AnalysisConfig("fea", {"fix": [{"m3-screw": 1}]})
    with pytest.raises(CaeConfigError):
        AnalysisConfig("fea", {"fix": {"m3-screw": [5]}})


# ---- load: -----------------------------------------------------------------


def test_load_flat_and_nested():
    config = AnalysisConfig(
        "fea",
        {"load": {"hook": "5 kg", "rail": {"left": "30 N", "right": 2}}},
    )
    assert config.loads["hook"] == {EVERY_INSTANCE: pytest.approx(5 * GRAVITY)}
    assert config.loads["rail"]["left"] == pytest.approx(30.0)
    assert config.loads["rail"]["right"] == pytest.approx(2 * GRAVITY)


def test_load_refuses_a_list():
    with pytest.raises(CaeConfigError):
        AnalysisConfig("fea", {"load": ["hook"]})


def test_load_refuses_an_empty_instance_map():
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
    shape = FakeShape({"fea": {"fix": ["a"]}, "cfd": {"load": {"b": "1 N"}}})
    assert cae.config_of(shape, "fea").fixtures == {"a": [EVERY_INSTANCE]}
    assert cae.config_of(shape, "cfd").loads == {"b": {EVERY_INSTANCE: 1.0}}


def test_config_of_is_none_when_nothing_is_declared():
    """The ordinary case, and not an error: most parts are never analysed."""
    assert cae.config_of(FakeShape({"type": "step"}), "fea") is None


def test_config_of_refuses_an_analysis_partcad_does_not_run():
    with pytest.raises(CaeConfigError):
        cae.config_of(FakeShape({}), "thermal")


def test_to_data_is_json_and_names_the_analysis():
    config = AnalysisConfig("cfd", {"fix": ["wall"], "load": {"inlet": "2 N"}})
    data = config.to_data()
    assert json.loads(json.dumps(data)) == {
        "analysis": "cfd",
        "fix": {"wall": [EVERY_INSTANCE]},
        "load": {"inlet": {EVERY_INSTANCE: 2.0}},
    }


# ---- attaching the conditions to ports --------------------------------------


def _port(interface, instance="", port="p"):
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
    assert unmatched == ["//pkg:m3-screw"]


def test_assign_ports_selects_named_instances():
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
    assert sorted(unmatched) == ["absent", "also-absent"]


def test_assign_ports_leaves_out_the_ports_nothing_names():
    """The implementation is told where to hold and pull, not what else exists."""
    config = AnalysisConfig("fea", {"fix": ["rail"]})
    assigned, _ = cae.assign_ports(config, [_port("//pkg:rail", port="a"), _port("//pkg:other", port="b")])
    assert [record["port"] for record in assigned] == ["a"]


# ---- findings ---------------------------------------------------------------


def test_normalize_findings_accepts_every_shape_an_implementation_may_use():
    assert cae.normalize_findings(None) == []
    assert cae.normalize_findings([]) == []
    assert cae.normalize_findings(["too thin"]) == [{"message": "too thin"}]
    assert cae.normalize_findings({"message": "one"}) == [{"message": "one"}]
    # A finding that named its text something else still prints as a finding.
    assert cae.normalize_findings([{"text": "bent", "severity": "error"}]) == [
        {"text": "bent", "severity": "error", "message": "bent"}
    ]


def test_findings_report_orders_the_worst_first():
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
    assert "found nothing" in cae.findings_report("//pkg:bracket", "fea", [])
