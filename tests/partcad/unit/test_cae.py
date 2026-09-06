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
        cae.config_of(FakeShape({}), "thermal")


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
    assert unmatched == [("rail", "no instance named lefft")]


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
    assert unmatched == [("rail", "no instance named right")]


def test_the_same_holds_for_a_load_named_per_instance():
    """`load:` carries a force per instance, and a missing one is a missing force."""
    config = AnalysisConfig("fea", {"load": {"rail": {"left": "1 N", "right": "2 N"}}})
    assigned, unmatched = cae.assign_ports(config, [_port("//pkg:rail", "left", "a")])
    assert [record["port"] for record in assigned] == ["a"]
    assert unmatched == [("rail", "no instance named right")]


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
