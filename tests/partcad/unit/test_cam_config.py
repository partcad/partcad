#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the `cam:` section: what an object says about being cut.

`partcad.cam` reads a configuration and converts its units, and that is all it
does -- it imports no CAD library and touches no geometry, which is what lets it
be tested without a sandbox. The three things checked here are the three a wrong
answer would be discovered on a machine rather than in a diff:

* every spelling a length, a feed and a speed may be written in ends up as the
  same number, in millimetres and millimetres per minute;
* an object's `cam:` section takes a **closed** set of keys, so that a typo is a
  sentence rather than a route cut to a default;
* what an object did *not* declare stays absent, so that a package's own layer
  still answers for it.
"""

import pytest

from partcad import cam

# --------------------------------------------------------------------------- #
# Units                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,millimetres",
    [
        (6, 6.0),
        (6.35, 6.35),
        ("6", 6.0),
        ("6mm", 6.0),
        ("6 mm", 6.0),
        ("6 MM", 6.0),
        ("0.5 cm", 5.0),
        ("0.01 m", 10.0),
        ("0.25 in", 6.35),
        ("0.25 inch", 6.35),
        ("0.25 inches", 6.35),
        ('0.25"', 6.35),
        ("125 thou", 3.175),
        ("1 ft", 304.8),
    ],
)
def test_a_length_is_millimetres_however_it_is_written(value, millimetres):
    """A bare number is millimetres, and a unit converts to them."""
    assert cam.parse_length(value) == pytest.approx(millimetres)


@pytest.mark.parametrize(
    "value,per_minute",
    [
        (1200, 1200.0),
        ("1200", 1200.0),
        ("1200 mm/min", 1200.0),
        ("1200mm/min", 1200.0),
        ("20 mm/s", 1200.0),
        ("60 in/min", 1524.0),
        ("1 m/min", 1000.0),
    ],
)
def test_a_feed_is_millimetres_per_minute_however_it_is_written(value, per_minute):
    """The length and the time may each be named, and a bare number is mm/min."""
    assert cam.parse_feed(value) == pytest.approx(per_minute)


@pytest.mark.parametrize("value", ["18000", 18000, "18000 rpm", "18000rpm", "18000 r/min"])
def test_a_spindle_speed_is_a_plain_number_of_revolutions(value):
    """'rpm' is accepted because it is how a spindle speed is written; it scales nothing."""
    assert cam.parse_number(value) == pytest.approx(18000.0)


@pytest.mark.parametrize("value", [0, -1, "0 mm", "-3 mm", True, None, "", "deep", [6]])
def test_a_length_that_is_not_a_positive_length_is_refused(value):
    """Zero is a cut that removes nothing, and a bool is not a number."""
    with pytest.raises(cam.CamConfigError):
        cam.parse_length(value, "'cam: depth:'")


def test_a_feed_with_a_time_nobody_uses_is_refused():
    """'per fortnight' parses as far as the '/' and no further."""
    with pytest.raises(cam.CamConfigError) as raised:
        cam.parse_feed("1200 mm/fortnight", "'cam: feed:'")
    assert "'cam: feed:'" in str(raised.value)


def test_a_unit_name_inside_a_word_is_not_a_unit():
    """'moons' ends in 's' and 'items' in 'm'; neither is a length."""
    with pytest.raises(cam.CamConfigError):
        cam.parse_length("12 items")


# --------------------------------------------------------------------------- #
# The object's own section                                                    #
# --------------------------------------------------------------------------- #


def test_the_job_arrives_as_numbers_whatever_it_was_written_as():
    """One section, every value converted, nothing else added."""
    config = cam.CamConfig(
        {
            "operation": "Profile",
            "diameter": "0.25 in",
            "depth": "18 mm",
            "feed": "60 in/min",
            "speed": "18000 rpm",
        }
    )
    assert config.operation == cam.PROFILE
    assert config.to_data() == {
        "operation": "profile",
        "diameter": pytest.approx(6.35),
        "depth": pytest.approx(18.0),
        "feed": pytest.approx(1524.0),
        "speed": pytest.approx(18000.0),
    }


def test_what_the_object_did_not_say_is_absent_rather_than_defaulted():
    """The layer underneath still answers for it.

    This is the whole reason `to_data()` carries only what was declared: a
    package that set a feed for all of its parts under `cam: gcode:` must keep
    answering for the part that named only a diameter. A default written in here
    would silently outrank it, because the object is the topmost layer.
    """
    data = cam.CamConfig({"diameter": 6}).to_data()
    assert data == {"diameter": 6.0}
    assert "feed" not in data
    assert "operation" not in data


def test_a_key_that_is_not_a_job_parameter_is_refused():
    """A closed set, so a typo cannot be read as a file-type declaration.

    An object declares its job under `manufacturing:` and a package declares
    who implements one under `cam:` (see the module docstring of `partcad.cam`).
    What keeps the job side unambiguous is this: it holds job parameters and
    nothing else, so `gcode:` among them is a mistake with a sentence rather
    than an implementation nobody asked for.
    """
    for section in (
        {"diameter": 6, "toool": 3},
        {"diameter": 6, "gcode": {"path": "x.py"}},
        {"diameter": 6, "output_dir": "."},
    ):
        with pytest.raises(cam.CamConfigError) as raised:
            cam.CamConfig(section)
        assert "does not take" in str(raised.value)


def test_an_empty_section_is_refused():
    """Opting in and then describing no route is a cut nobody chose.

    The file type's defaults could cover it, and that is exactly the reading to
    refuse -- there is no default cutter diameter, and there must not be.
    """
    for section in ({}, None, "profile", []):
        with pytest.raises(cam.CamConfigError):
            cam.CamConfig(section)


def test_an_operation_nobody_implements_is_refused():
    with pytest.raises(cam.CamConfigError) as raised:
        cam.CamConfig({"diameter": 6, "operation": "turning"})
    assert "profile" in str(raised.value)


def test_a_stepover_wider_than_the_cutter_is_refused():
    """It parses, it runs, and it leaves a ridge nobody sees until the machine."""
    with pytest.raises(cam.CamConfigError):
        cam.CamConfig({"diameter": 6, "stepover": 1.5})
    assert cam.CamConfig({"diameter": 6, "stepover": 1}).to_data()["stepover"] == pytest.approx(1.0)


def test_the_implementation_is_carried_but_is_not_a_parameter():
    """Who runs it is acted on before anything is handed over, so it does not travel."""
    config = cam.CamConfig({"diameter": 6, "implementation": " some/package:gcode ", "desc": "the lid"})
    assert config.implementation == "some/package:gcode"
    assert config.desc == "the lid"
    assert "implementation" not in config.to_data()
    assert "desc" not in config.to_data()


# --------------------------------------------------------------------------- #
# Which objects have one at all                                               #
# --------------------------------------------------------------------------- #


class _Shape:
    """The least of a shape that `config_of` reads: its final configuration."""

    def __init__(self, config):
        self.config = config

    def get_final_config(self):
        return self.config


def test_an_object_with_no_section_is_not_an_error():
    """Most objects are never cut, which is why this is None rather than a refusal.

    It is what lets `pc cam` over a package be silent about the objects it skips
    and loud about the one whose section is wrong.
    """
    assert cam.config_of(_Shape({"type": "step"})) is None
    assert cam.declared_config(_Shape({"type": "step"})) is None


def test_an_object_with_a_broken_section_is_visited_and_then_refused():
    """Deciding what to visit must not judge, and reading it must not fall back.

    Two questions of one broken section, and they need opposite answers.
    `declares_job` draws up the list `pc cam` will walk, so a `cnc:` with a typo
    in it has to be *on* that list -- an object nobody visits is an object nobody
    reports. `declared_config` is the read that precedes writing a file, and
    there it has to refuse: a section that could not be read leaves no machine
    behind, which is indistinguishable from the part that named none, and that
    one routes as CNC. So swallowing it hands a router program to a part whose
    `laser:` had a typo in it.
    """
    shape = _Shape({"manufacturing": {"method": "subtractive", "source": "blank", "cnc": {"toool": 6}}})
    assert cam.declares_job(shape) is True
    for read in (cam.declared_config, cam.config_of):
        with pytest.raises(cam.CamConfigError) as raised:
            read(shape)
        assert "does not take toool" in str(raised.value)


# --------------------------------------------------------------------------- #
# The merged request                                                          #
# --------------------------------------------------------------------------- #


def test_every_layer_is_converted_and_not_just_the_object():
    """A '2400 mm/min' written by the package is as much PartCAD's to understand.

    The package's and `//builtin/cam`'s layers reach the implementation through
    the ordinary output-option merge, which has never been near a parser -- so
    without this they arrive as the strings they were written as and are refused
    by the implementation, which is the right answer to the wrong question.
    """
    normalized = cam.normalize_job(
        {
            "wrapped": object(),
            "feed": "2400 mm/min",
            "safe_z": "0.5 in",
            "operation": "Pocket",
            "units": "mm",
            "something_a_plugin_invented": "6 mm",
        }
    )
    assert normalized["feed"] == pytest.approx(2400.0)
    assert normalized["safe_z"] == pytest.approx(12.7)
    assert normalized["operation"] == "pocket"
    # Untouched: PartCAD does not know what an implementation's own parameters
    # mean, so it does not convert them.
    assert normalized["units"] == "mm"
    assert normalized["something_a_plugin_invented"] == "6 mm"


def test_the_merged_job_is_not_required_to_name_a_diameter():
    """ "A route needs a cutter diameter" is the implementation's statement, not PartCAD's.

    `//builtin/cam` refuses a CNC request with no `diameter`, and says where to
    set it. Requiring it here would be PartCAD answering on behalf of an
    implementation it has never seen -- and the laser beside it cuts with a beam,
    which has a kerf and no diameter at all.
    """
    assert "diameter" not in cam.normalize_job({"feed": 1200})


def test_normalizing_is_idempotent():
    """The object's own values are already numbers by the time they get here."""
    once = cam.normalize_job({"diameter": "6 mm", "feed": "20 mm/s"})
    assert cam.normalize_job(once) == once


# --------------------------------------------------------------------------- #
# What a review of #649 turned up                                             #
# --------------------------------------------------------------------------- #


def test_the_stepover_bound_holds_at_every_layer():
    """A package's layer can write the same mistake an object's is refused for.

    `CamConfig` refuses a stepover above 1 because it leaves a ridge of uncut
    material between passes. Written one layer down -- under the package's own
    `cam: <file type>:` -- it reached the implementation unchecked and produced
    the very route that check exists to prevent, because `normalize_job` only
    parsed the number.
    """
    with pytest.raises(cam.CamConfigError) as raised:
        cam.normalize_job({"diameter": 6, "stepover": 1.5})
    assert "cannot exceed 1" in str(raised.value)
    # The bound, not the parse: 1 is the largest stepover that means anything.
    assert cam.normalize_job({"diameter": 6, "stepover": 1})["stepover"] == pytest.approx(1.0)


def test_direction_is_a_job_key_and_not_a_file_setting():
    """Which way round a contour is cut is a property of how the object is made.

    It decides which side of the tool the chip comes off and which of the two
    edges is the finished one, so it belongs with the tool and the depth rather
    than with `units:` and `precision:`, which describe the file.
    """
    assert "direction" in cam.KEYS
    config = cam.CamConfig({"diameter": 6, "direction": "Conventional"})
    assert config.direction == cam.CONVENTIONAL
    assert config.to_data()["direction"] == "conventional"
    # And at every layer, like the operation beside it.
    assert cam.normalize_job({"direction": "CLIMB"})["direction"] == cam.CLIMB


def test_a_direction_nobody_mills_in_is_refused_at_every_layer():
    for section in (
        lambda: cam.CamConfig({"diameter": 6, "direction": "sideways"}),
        lambda: cam.normalize_job({"direction": "sideways"}),
    ):
        with pytest.raises(cam.CamConfigError) as raised:
            section()
        assert "climb" in str(raised.value)


def test_what_describes_the_file_is_not_an_object_key():
    """`units:` and its siblings stay with the file type, and the refusal says so.

    An object's section is checked against a list, and a list can only hold what
    PartCAD knows the name of -- so the closed set covers the cut and not the
    parameters of an implementation PartCAD has never seen. A package sets those.
    """
    for key in ("units", "precision", "tolerance", "comments"):
        assert key not in cam.KEYS
        with pytest.raises(cam.CamConfigError):
            cam.CamConfig({"diameter": 6, key: "whatever"})
        # They still reach the implementation untouched from the layers that may
        # set them -- `normalize_job` converts what it knows and carries the rest.
        assert cam.normalize_job({key: "whatever"})[key] == "whatever"
