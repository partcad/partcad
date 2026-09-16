#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What a STEP file says about how precisely it has to be made.

'tolerance_inspect' reads ISO 10303-21 as text, without a CAD kernel, for the
two things in it that state a manufacturing tolerance: the bounds of a
plus/minus tolerance on a dimension, and the magnitude of a geometric tolerance.
What it must not read is the 'UNCERTAINTY_MEASURE_WITH_UNIT' every STEP file
carries, which is the precision the geometry was written to and not a tolerance
anybody is being held to.

A file that states several tolerances that are not the same has no single
tolerance, and that is reported as NaN rather than by picking one of them.
"""

import math

import pytest

from partcad import tolerance_inspect

MILLIMETRE = "#10=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));"


def _write(tmp_path, body, name="body.step"):
    path = tmp_path / name
    path.write_text(
        "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n" + MILLIMETRE + "\n" + body + "\nENDSEC;\nEND-ISO-10303-21;\n"
    )
    return str(path)


def _flatness(ident, value, unit=10):
    return "#%d=FLATNESS_TOLERANCE('','',#%d,#900);\n#%d=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(%s),#%d);" % (
        ident,
        ident + 1,
        ident + 1,
        value,
        unit,
    )


def test_a_file_with_no_tolerance_in_it_states_none(tmp_path):
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));")

    assert tolerance_inspect.of_step_file(path) is None


def test_the_geometric_uncertainty_is_not_a_tolerance(tmp_path):
    """Every STEP file carries one, and it is not what anybody is held to.

    Reading it would give every file ever exported a manufacturing tolerance of
    a ten-millionth of a millimetre - a number no shop can work to and nobody
    asked for.
    """
    path = _write(
        tmp_path,
        "#12=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#10,"
        "'distance_accuracy_value','confusion accuracy');",
    )

    assert tolerance_inspect.of_step_file(path) is None


def test_a_geometric_tolerance_written_as_its_own_entity(tmp_path):
    path = _write(tmp_path, _flatness(200, "0.05"))

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_a_geometric_tolerance_inside_a_complex_instance(tmp_path):
    """How AP242 writes a position tolerance with a datum and a modifier.

    The subtype is one entity of the instance and carries no attributes of its
    own, so the magnitude has to be found on the 'GEOMETRIC_TOLERANCE' beside
    it - which is why the reader matches the shape of an argument list rather
    than a list of entity names.
    """
    path = _write(
        tmp_path,
        "#300=(GEOMETRIC_TOLERANCE('pos','',#301,#302)"
        "GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE((#303))"
        "MODIFIED_GEOMETRIC_TOLERANCE(.MAXIMUM_MATERIAL_CONDITION.)"
        "POSITION_TOLERANCE());\n"
        "#301=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.25),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.25)


def test_a_symmetric_plus_minus_tolerance(tmp_path):
    path = _write(
        tmp_path,
        "#100=PLUS_MINUS_TOLERANCE(#101,#150);\n"
        "#101=TOLERANCE_VALUE(#102,#103);\n"
        "#102=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(-0.1),#10);\n"
        "#103=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.1),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.1)


def test_an_asymmetric_plus_minus_tolerance_is_its_largest_deviation(tmp_path):
    """A shop working to 0.2 satisfies a bound of 0 to +0.2; one working to
    0.1 - the half-width - does not."""
    path = _write(
        tmp_path,
        "#101=TOLERANCE_VALUE(#102,#103);\n"
        "#102=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.),#10);\n"
        "#103=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.2),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.2)


def test_tolerances_that_agree_are_one_tolerance(tmp_path):
    """Two spellings of one value, which is what a text format makes of it."""
    path = _write(tmp_path, _flatness(200, "0.05") + "\n" + _flatness(210, "5.E-02"))

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_tolerances_that_disagree_are_not_one_tolerance(tmp_path):
    path = _write(tmp_path, _flatness(200, "0.05") + "\n" + _flatness(210, "0.2"))

    assert math.isnan(tolerance_inspect.of_step_file(path))


def test_a_file_written_in_inches(tmp_path):
    """Read as inches it is 0.127 mm; read as millimetres it is 0.005, and a
    part is then quoted to twenty-five times the precision it asked for."""
    path = _write(
        tmp_path,
        "#20=(CONVERSION_BASED_UNIT('INCH',#21)LENGTH_UNIT()NAMED_UNIT(#22));\n"
        "#21=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#10);\n" + _flatness(200, "0.005", unit=20),
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.127)


def test_a_file_written_in_metres(tmp_path):
    path = _write(
        tmp_path,
        "#30=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT($,.METRE.));\n" + _flatness(200, "1.E-04", unit=30),
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.1)


def test_a_unit_defined_in_terms_of_itself_is_not_resolved(tmp_path):
    """Nothing legitimate writes that; a truncated or hand-edited file can."""
    path = _write(
        tmp_path,
        "#20=(CONVERSION_BASED_UNIT('LOOP',#21)LENGTH_UNIT()NAMED_UNIT(#22));\n"
        "#21=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#20);\n" + _flatness(200, "0.005", unit=20),
    )

    assert tolerance_inspect.of_step_file(path) is None


def test_a_semicolon_inside_a_string_does_not_end_the_record(tmp_path):
    """A tolerance carries a name and a description, both free text."""
    path = _write(
        tmp_path,
        "#200=FLATNESS_TOLERANCE('flat;ness','see note 3; datum A',#201,#900);\n"
        "#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_a_doubled_quote_inside_a_string(tmp_path):
    path = _write(
        tmp_path,
        "#200=FLATNESS_TOLERANCE('it''s flat','',#201,#900);\n"
        "#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 64, 4096])
def test_the_answer_does_not_depend_on_where_the_reads_fall(tmp_path, monkeypatch, chunk):
    """The file arrives a block at a time and a record straddles the join.

    The name below holds a doubled quote and, after it, a semicolon: a block
    that ends between the two halves of that quote cannot yet tell whether the
    string is over, and a block that guessed wrong would cut the record at a
    semicolon that is really part of its text.
    """
    monkeypatch.setattr(tolerance_inspect, "CHUNK", chunk)
    path = _write(
        tmp_path,
        "#200=FLATNESS_TOLERANCE('the bracket''s datum; face A','',#201,#900);\n"
        "#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);\n" + _flatness(210, "0.05"),
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_a_description_written_as_omitted_rather_than_empty(tmp_path):
    """AP242 makes the description optional, and '$' is how a file says so.

    Rejecting the record would lose the tolerance it states, silently.
    """
    path = _write(
        tmp_path,
        "#200=FLATNESS_TOLERANCE('flat',$,#201,#900);\n#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_an_omitted_name_as_well(tmp_path):
    path = _write(
        tmp_path,
        "#200=FLATNESS_TOLERANCE($,$,#201,#900);\n#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_an_entity_that_is_not_a_geometric_tolerance_is_still_told_apart(tmp_path):
    """What '$' buys must not cost the discrimination it was bought with.

    'PLUS_MINUS_TOLERANCE' takes two references and 'MODIFIED_GEOMETRIC_
    TOLERANCE' one enumeration; neither states a magnitude of its own, and
    neither may be read as though it did.
    """
    path = _write(
        tmp_path,
        "#100=PLUS_MINUS_TOLERANCE(#101,#150);\n"
        "#105=MODIFIED_GEOMETRIC_TOLERANCE(.MAXIMUM_MATERIAL_CONDITION.);\n"
        "#106=POSITION_TOLERANCE();",
    )

    assert tolerance_inspect.of_step_file(path) is None


def test_a_comment_holding_a_semicolon_does_not_end_a_record(tmp_path):
    """Part 21 allows '/* ... */' wherever a separator is allowed."""
    path = _write(
        tmp_path,
        "#200=FLATNESS_TOLERANCE(/* note 3; datum A */'','',#201,#900);\n"
        "#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_a_tolerance_written_inside_a_comment_is_not_a_tolerance(tmp_path):
    """It is text about the file, not a statement the file makes."""
    path = _write(
        tmp_path,
        "/* was #200=FLATNESS_TOLERANCE('','',#201,#900); with\n"
        "#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.5),#10); until rev C */\n" + _flatness(210, "0.05"),
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_a_comment_delimiter_inside_a_string_opens_no_comment(tmp_path):
    path = _write(
        tmp_path,
        "#200=FLATNESS_TOLERANCE('a /* b','c */ d',#201,#900);\n"
        "#201=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.05),#10);",
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


@pytest.mark.parametrize("chunk", [1, 3, 9, 64])
def test_a_comment_split_across_reads(tmp_path, monkeypatch, chunk):
    monkeypatch.setattr(tolerance_inspect, "CHUNK", chunk)
    path = _write(
        tmp_path,
        "/* a comment long enough to straddle a read; with a semicolon in it */\n" + _flatness(200, "0.05"),
    )

    assert tolerance_inspect.of_step_file(path) == pytest.approx(0.05)


def test_a_file_that_is_not_there_states_nothing(tmp_path):
    """A 'kicad' part's STEP file does not exist until the part is built, and a
    part fetched from a URL not until it is downloaded. Neither is a tolerance,
    and neither is this reader's problem to report."""
    assert tolerance_inspect.of_file("step", str(tmp_path / "absent.step")) is None


def test_a_format_nothing_here_reads_states_nothing(tmp_path):
    path = _write(tmp_path, _flatness(200, "0.05"), name="body.stl")

    assert tolerance_inspect.of_file("stl", path) is None
    assert tolerance_inspect.of_file(None, path) is None


def test_reducing_no_values_is_not_an_answer():
    assert tolerance_inspect.reduce([]) is None


def test_reducing_values_that_agree_within_a_rounding():
    assert tolerance_inspect.reduce([0.1, 0.1 + 1e-17]) == pytest.approx(0.1)


def test_reducing_values_that_do_not_agree():
    assert math.isnan(tolerance_inspect.reduce([0.1, 0.2]))
