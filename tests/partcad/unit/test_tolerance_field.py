#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The 'tolerance:' field, and the one reader of a part's tolerance.

A 'step' part rejects the 'tolerance' object-type *parameter*, and goes on
rejecting it, for the reason it always did: a STEP file may hold many solids,
each already stating what it is, so a single value declared beside the file is a
claim about a part the file describes better. That reasoning holds for what a
STEP file states -- and plenty of them state no tolerance at all, which leaves a
part read from one of those with nothing to say about how precisely it has to be
made, and 'pc test' rejecting it for saying nothing.

So the field: a way for the declaration to answer for a file that does not.
'Part.get_tolerance()' is the one thing that reads it, along with the file and
the parameter, because which of the three applies is a property of the part's
type and not something each caller should work out again.
"""

import asyncio
import math
import pathlib

import pytest
import yaml

import partcad as pc

# Types that take the field, and types that take neither it nor the parameter.
ACCEPTING_TYPES = ["step", "kicad"]
REJECTING_TYPES = ["stl", "cadquery", "build123d", "brep"]

_EXTENSIONS = {
    "stl": ".stl",
    "step": ".step",
    "brep": ".brep",
    "kicad": ".kicad_pcb",
    "cadquery": ".py",
    "build123d": ".py",
}

MILLIMETRE = "#10=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));"


def _step(*tolerances):
    """A STEP file stating a flatness tolerance of each of 'tolerances', in mm."""
    body = "".join(
        "#%d=FLATNESS_TOLERANCE('','',#%d,#900);\n#%d=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(%r),#10);\n"
        % (200 + 2 * i, 201 + 2 * i, 201 + 2 * i, value)
        for i, value in enumerate(tolerances)
    )
    return "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n" + MILLIMETRE + "\n" + body + "ENDSEC;\nEND-ISO-10303-21;\n"


def _write_package(tmp_path, parts, contents=None):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"name": "//test", "parts": parts}))
    for name, part in parts.items():
        for extension in set(_EXTENSIONS.values()):
            (tmp_path / (name + extension)).write_text((contents or {}).get(name, ""))
        path = part.get("path")
        if path:
            (tmp_path / path).write_text((contents or {}).get(name, ""))
    return pc.Context(str(tmp_path))


def _part(part_type, **extra):
    config = {"type": part_type}
    config.update(extra)
    return config


def _tolerance(part):
    return asyncio.run(part.get_tolerance())


@pytest.mark.parametrize("part_type", ACCEPTING_TYPES)
def test_accepted_by_the_types_whose_file_may_state_one(tmp_path, part_type):
    """'kicad' is a STEP file behind a footprint, and inherits this with it."""
    pc.logging.reset_errors()
    ctx = _write_package(tmp_path, {"body": _part(part_type, tolerance=0.1)})

    part = ctx.get_part("//:body")

    assert part is not None
    assert pc.logging.had_errors is False
    assert _tolerance(part) == 0.1


@pytest.mark.parametrize("part_type", REJECTING_TYPES)
def test_rejected_by_the_types_that_have_no_use_for_it(tmp_path, part_type):
    """Per object, like every other declaration a type cannot honour.

    Refused rather than ignored: a part whose author believed it was tolerated
    would otherwise go to a manufacturer without a tolerance. The homogeneous
    types have the parameter for this, which is what the message's 'field' says
    it is not.
    """
    pc.logging.reset_errors()
    ctx = _write_package(
        tmp_path,
        {"body": _part(part_type, tolerance=0.1), "sibling": _part("stl")},
    )
    project = ctx.get_project("//")

    assert "body" not in project.parts
    assert "sibling" in project.parts
    assert pc.logging.had_errors is True

    reason = project.get_broken_object_reason("part", "body")
    assert "body" in reason
    assert part_type in reason
    assert "tolerance" in reason
    assert "field" in reason


def test_the_field_is_not_the_parameter(tmp_path):
    """A 'step' part takes the field and still rejects the parameter.

    They answer different questions. The parameter is a request made of the type
    that produces the shape, and a STEP file's many solids are why that type
    cannot honour one; the field says nothing about how the shape is built, only
    how precisely the thing it describes has to be made.
    """
    pc.logging.reset_errors()
    ctx = _write_package(
        tmp_path,
        {"body": _part("step", parameters={"tolerance": {"type": "float", "default": 0.1}})},
    )
    project = ctx.get_project("//")

    assert "body" not in project.parts
    reason = project.get_broken_object_reason("part", "body")
    assert "parameter" in reason


def test_a_non_numeric_tolerance_is_reported_and_treated_as_absent(tmp_path):
    """The declaration is wrong, not the part - the same as for the parameter."""
    pc.logging.reset_errors()
    ctx = _write_package(tmp_path, {"body": _part("step", tolerance="quite tight")}, contents={"body": _step()})

    part = ctx.get_part("//:body")

    assert pc.logging.had_errors is True
    assert _tolerance(part) == 0.0


@pytest.mark.parametrize(
    "declared",
    [".nan", ".inf", "-.inf", "-5", "true", "yes", "false"],
    ids=["nan", "infinity", "negative-infinity", "negative", "true", "yes", "false"],
)
def test_a_declared_tolerance_that_is_not_a_length_is_refused(tmp_path, declared):
    """None of these is a tolerance anybody can be asked to hold.

    YAML spells every one of them and 'float()' takes every one, so without a
    check a part could declare its way past the manufacturability test: NaN is
    the answer that means "tolerated feature by feature", which 'pc test'
    accepts; an infinite or negative value is neither zero nor NaN and so reads
    as a real tolerance; and a boolean is an int in Python, so 'true' reads back
    as one millimetre. 'yes' is in here because YAML makes that the easiest of
    them to write by accident - it is 'True', not the word.

    Reported and treated as absent, like any other bad declaration.
    """
    pc.logging.reset_errors()
    (tmp_path / "partcad.yaml").write_text("parts:\n  body:\n    type: step\n    tolerance: %s\n" % declared)
    (tmp_path / "body.step").write_text(_step())

    part = pc.Context(str(tmp_path)).get_part("//:body")

    assert pc.logging.had_errors is True
    assert _tolerance(part) == 0.0


def test_a_boolean_is_refused_rather_than_read_as_one_millimetre(tmp_path):
    """The file's own answer must survive a declaration that is not one.

    'float(True)' is 1.0, which is finite, not negative, and so passes every
    other guard - and then outranks the file, silently, with a tolerance a
    millimetre wide that nobody wrote.
    """
    pc.logging.reset_errors()
    (tmp_path / "partcad.yaml").write_text("parts:\n  body:\n    type: step\n    tolerance: yes\n")
    (tmp_path / "body.step").write_text(_step(0.05))

    part = pc.Context(str(tmp_path)).get_part("//:body")

    assert pc.logging.had_errors is True
    # The file, not 1.0 and not 0.0.
    assert _tolerance(part) == 0.05


@pytest.mark.parametrize(
    "declared",
    [".nan", ".inf", "-.inf", "-5", "true", "yes"],
    ids=["nan", "infinity", "negative-infinity", "negative", "true", "yes"],
)
def test_the_tolerance_parameter_is_held_to_the_same_rule_as_the_field(tmp_path, declared):
    """The homogeneous types state this as a parameter, and it is still a length.

    The same four spellings reach 'get_object_type_parameter()', whose
    coercion turns 'True' into 1.0 and passes NaN, the infinities and negatives
    straight through. NaN is the one that has to be stopped rather than merely
    tidied: 'ManufacturabilityTest.tolerance_failure()' takes a NaN to mean "the
    file tolerances this feature by feature" and passes it, so a NaN a
    declaration produced would be reported as something no file ever said.
    """
    pc.logging.reset_errors()
    (tmp_path / "partcad.yaml").write_text(
        "parts:\n  body:\n    type: stl\n"
        "    parameters:\n      tolerance:\n        type: float\n        default: %s\n" % declared
    )
    (tmp_path / "body.stl").write_text("")

    part = pc.Context(str(tmp_path)).get_part("//:body")

    # Read first: unlike the field, which the factory validates as the part is
    # created, a parameter is checked when something asks for it.
    assert _tolerance(part) == 0.0
    assert pc.logging.had_errors is True


def test_a_tolerance_parameter_that_is_a_length_still_reads_back(tmp_path):
    """The rule refuses what is not a length, and nothing else."""
    pc.logging.reset_errors()
    (tmp_path / "partcad.yaml").write_text(
        "parts:\n  body:\n    type: stl\n"
        "    parameters:\n      tolerance:\n        type: float\n        default: 0.1\n"
    )
    (tmp_path / "body.stl").write_text("")

    part = pc.Context(str(tmp_path)).get_part("//:body")

    assert _tolerance(part) == 0.1
    assert pc.logging.had_errors is False


def test_only_a_file_can_produce_the_nan_the_manufacturability_check_accepts(tmp_path):
    """The invariant the two rules above exist to protect.

    NaN means "the file tolerances this part feature by feature". Nothing a
    declaration can write may mint one, on either path, or the
    manufacturability check would pass a part on the strength of a sentence no
    file said.
    """
    tolerated = _step(0.05, 0.2)
    ctx = _write_package(
        tmp_path,
        {"from_file": _part("step"), "from_field": _part("step", tolerance=0.1)},
        contents={"from_file": tolerated, "from_field": tolerated},
    )

    # The same file, tolerated feature by feature, under both parts.
    assert math.isnan(_tolerance(ctx.get_part("//:from_file")))
    # ...and the declared length is what the second one answers with, not a NaN.
    assert _tolerance(ctx.get_part("//:from_field")) == 0.1


def test_a_declared_tolerance_of_zero_is_still_a_declaration(tmp_path):
    """The check refuses what is not a length, not what is not useful.

    0.0 is what "nobody said" reads as, and the manufacturability check is what
    has an opinion about it; it is not this reader's to throw away.
    """
    pc.logging.reset_errors()
    ctx = _write_package(tmp_path, {"body": _part("step", tolerance=0.0)}, contents={"body": _step(0.05)})

    part = ctx.get_part("//:body")

    assert pc.logging.had_errors is False
    # Declared, so it outranks the 0.05 the file states.
    assert _tolerance(part) == 0.0


def test_a_step_part_that_says_nothing_anywhere_reads_back_as_nobody_said(tmp_path):
    """0.0, not None: this part could have said and did not."""
    ctx = _write_package(tmp_path, {"body": _part("step")}, contents={"body": _step()})

    assert _tolerance(ctx.get_part("//:body")) == 0.0


def test_a_step_file_is_read_when_nothing_is_declared(tmp_path):
    ctx = _write_package(tmp_path, {"body": _part("step")}, contents={"body": _step(0.05)})

    assert _tolerance(ctx.get_part("//:body")) == 0.05


def test_a_step_file_that_tolerates_feature_by_feature_reads_back_as_nan(tmp_path):
    ctx = _write_package(tmp_path, {"body": _part("step")}, contents={"body": _step(0.05, 0.2)})

    assert math.isnan(_tolerance(ctx.get_part("//:body")))


def test_the_declaration_outranks_the_file(tmp_path):
    ctx = _write_package(tmp_path, {"body": _part("step", tolerance=0.3)}, contents={"body": _step(0.05)})

    assert _tolerance(ctx.get_part("//:body")) == 0.3


def test_the_file_is_prepared_before_it_is_read(tmp_path):
    """A STEP file fetched from a URL is not on disk until it is downloaded.

    'Shape.prepare_async()' is where the factory hangs that download - it is
    "everything that has to happen before this shape's cache key means
    anything" - so reading the file before it has run would report that a file
    nobody had fetched yet states nothing, and have 'pc test' cache that answer
    against the hash of a file that was never there.
    """
    ctx = _write_package(tmp_path, {"body": _part("step")})
    part = ctx.get_part("//:body")
    source = pathlib.Path(part.path)
    source.unlink()

    async def download(_self):
        source.write_text(_step(0.05))

    part._prepare = download
    part._prepared = False

    assert _tolerance(part) == 0.05


def test_a_preparation_that_fails_leaves_the_file_stating_nothing(tmp_path):
    """Not this reader's to report: whatever needs the file next says so."""
    ctx = _write_package(tmp_path, {"body": _part("step")})
    part = ctx.get_part("//:body")
    pathlib.Path(part.path).unlink()

    async def unreachable(_self):
        raise RuntimeError("404")

    part._prepare = unreachable
    part._prepared = False

    assert _tolerance(part) == 0.0


def test_the_file_is_read_once(tmp_path, monkeypatch):
    """A STEP file large enough to be worth caring about is large enough not to
    want scanned twice, and it does not change under a loaded package."""
    from partcad import tolerance_inspect

    reads = []
    original = tolerance_inspect.of_step_file
    monkeypatch.setattr(
        tolerance_inspect,
        "of_step_file",
        lambda path: (reads.append(path), original(path))[1],
    )
    monkeypatch.setitem(tolerance_inspect._READERS, "step", tolerance_inspect.of_step_file)

    ctx = _write_package(tmp_path, {"body": _part("step")}, contents={"body": _step(0.05)})
    part = ctx.get_part("//:body")

    assert _tolerance(part) == 0.05
    assert _tolerance(part) == 0.05
    assert len(reads) == 1


def test_a_homogeneous_type_still_answers_from_its_parameter(tmp_path):
    """Nothing about the field changes what the types that have the parameter do."""
    ctx = _write_package(
        tmp_path,
        {
            "declared": _part("stl", path="a.stl", parameters={"tolerance": {"type": "float", "default": 0.25}}),
            "silent": _part("stl", path="b.stl"),
        },
    )

    assert _tolerance(ctx.get_part("//:declared")) == 0.25
    assert _tolerance(ctx.get_part("//:silent")) == 0.0


def test_a_type_with_no_way_to_say_reads_back_as_none(tmp_path):
    """Not 0.0: 'this part cannot say' and 'this part said nothing' differ, and
    the manufacturability test reports them differently."""
    ctx = _write_package(tmp_path, {"body": _part("brep")})

    assert _tolerance(ctx.get_part("//:body")) is None


def test_an_alias_carrying_the_field_is_ignored_rather_than_refused(tmp_path):
    """An alias is a second name for another object, and what that object is
    made to is the source's business. 'enrich.ENRICH_IGNORED_PROPERTIES' lists
    this field among the ones such a declaration ignores."""
    pc.logging.reset_errors()
    ctx = _write_package(
        tmp_path,
        {"body": _part("step"), "other": _part("alias", source=":body", tolerance=0.1)},
    )
    project = ctx.get_project("//")

    assert "other" in project.parts
    assert pc.logging.had_errors is False


def test_a_declared_tolerance_keys_the_cache(tmp_path):
    """A consequence of the cache key being a deny-list, and left that way.

    The field cannot change the geometry, so hashing it only ever costs a
    rebuild. Exempting it would mean naming 'tolerance' in
    'shape._NON_GEOMETRIC_CONFIG_KEYS', which is shared with sketches - where a
    'tolerance:' is how a drawing's edges are merged into wires, and so is very
    much what the shape is made of. Two sketches alike but for it would then
    share one cache entry, which is the mistake that list warns about.
    """
    ctx = _write_package(
        tmp_path,
        {
            "silent": _part("step", path="a.step"),
            "declared": _part("step", path="a.step", tolerance=0.1),
        },
    )
    project = ctx.get_project("//")
    keys = {name: project.parts[name].hash.get() for name in ["silent", "declared"]}

    assert None not in keys.values()
    assert keys["silent"] != keys["declared"]
