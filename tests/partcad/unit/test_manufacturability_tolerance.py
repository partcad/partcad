#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A part that is going to be made has to say how precisely.

Where it says it from depends on its type, and 'Part.get_tolerance()' is what
knows which of the three places applies - a 'tolerance:' field, the file the part
is read from, or the 'tolerance' object-type parameter of the homogeneous types.
This is about what the manufacturability test does with the answer.

0.0 is a demand for perfect precision, which is what "nobody said" amounts to and
is not something a manufacturer can be asked for, so the test rejects it - for a
part in the package, and for a part an assembly in the package is procured from.
NaN is the opposite: a file that tolerances several features differently says how
precisely in more detail than one number holds, and that passes.

Only what is actually made is asked: a part that is bought comes as it comes.
"""

import asyncio
import math

import yaml

import partcad as pc
from partcad.test.manufacturability import ManufacturabilityTest


def _record_errors(monkeypatch):
    """Collect pc_logging.error() calls.

    The 'partcad' logger sets propagate=False, so the caplog fixture (which
    attaches to the root logger) sees nothing on the pytest version used in CI.
    """
    recorded = []
    monkeypatch.setattr(pc.logging, "error", lambda *args, **kwargs: recorded.append(" ".join(str(a) for a in args)))
    return recorded


# The extension each part type is read from, for the types these tests declare.
# The files are never opened by anything but the tolerance reader - nothing here
# instantiates a shape - but a file-backed factory checks that the path exists
# before it will create the part at all.
_EXTENSIONS = {"stl": ".stl", "step": ".step", "brep": ".brep"}


def _package(tmp_path, parts, assemblies=None, contents=None):
    config = {"name": "//test", "manufacturable": True, "parts": parts}
    if assemblies:
        config["assemblies"] = assemblies
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))
    for name, part in parts.items():
        extension = _EXTENSIONS.get(part.get("type"), ".stl")
        (tmp_path / (name + extension)).write_text((contents or {}).get(name, ""))
    return pc.Context(str(tmp_path))


def _step(*tolerances):
    """A STEP file stating a flatness tolerance of each of 'tolerances', in mm."""
    body = "".join(
        "#%d=FLATNESS_TOLERANCE('','',#%d,#900);\n#%d=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(%r),#10);\n"
        % (200 + 2 * i, 201 + 2 * i, 201 + 2 * i, value)
        for i, value in enumerate(tolerances)
    )
    return (
        "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
        "#10=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));\n" + body + "ENDSEC;\nEND-ISO-10303-21;\n"
    )


def _failure(part):
    return asyncio.run(ManufacturabilityTest().tolerance_failure(part))


def _made_part(**parameters):
    part = {"type": "stl", "manufacturing": {"method": "additive"}}
    if parameters:
        part["parameters"] = {k: {"type": "float", "default": v} for k, v in parameters.items()}
    return part


def test_a_part_with_no_tolerance_fails(tmp_path):
    ctx = _package(tmp_path, {"body": _made_part()})
    part = ctx.get_part("//:body")

    failure = _failure(part)

    assert failure is not None
    assert "tolerance" in failure


def test_a_part_with_a_tolerance_of_zero_fails_the_same_way(tmp_path):
    """Declaring the default explicitly is still nothing specified."""
    ctx = _package(tmp_path, {"body": _made_part(tolerance=0.0)})
    part = ctx.get_part("//:body")

    assert _failure(part) is not None


def test_a_part_with_a_tolerance_passes(tmp_path):
    ctx = _package(tmp_path, {"body": _made_part(tolerance=0.1)})
    part = ctx.get_part("//:body")

    assert _failure(part) is None


def test_a_type_that_cannot_carry_a_tolerance_says_so(tmp_path):
    """A BREP part has nowhere to state one, and the message says which type.

    Not the same failure as a part that could have said and did not: this one is
    a fact about the part's type, which is why it names it. 'brep' takes neither
    the object-type parameter (it is not one of the homogeneous types) nor the
    field (its format states no tolerance for a field to answer for).
    """
    ctx = _package(tmp_path, {"body": {"type": "brep", "manufacturing": {"method": "additive"}}})
    part = ctx.get_part("//:body")

    failure = _failure(part)

    assert failure is not None
    assert "brep" in failure
    assert "does not accept" in failure


def _step_part(**extra):
    part = {"type": "step", "manufacturing": {"method": "additive"}}
    part.update(extra)
    return part


def test_a_step_part_whose_file_says_nothing_fails(tmp_path):
    """The failure of a part that could have said and did not, not of its type."""
    ctx = _package(tmp_path, {"body": _step_part()}, contents={"body": _step()})
    part = ctx.get_part("//:body")

    failure = _failure(part)

    assert failure == "No manufacturing tolerance is specified"


def test_a_step_part_with_a_declared_tolerance_passes(tmp_path):
    """The field a poor STEP file leaves to the declaration to answer."""
    ctx = _package(tmp_path, {"body": _step_part(tolerance=0.1)}, contents={"body": _step()})
    part = ctx.get_part("//:body")

    assert _failure(part) is None
    assert asyncio.run(part.get_tolerance()) == 0.1


def test_a_step_file_that_states_one_tolerance_answers_for_the_part(tmp_path):
    ctx = _package(tmp_path, {"body": _step_part()}, contents={"body": _step(0.05, 0.05)})
    part = ctx.get_part("//:body")

    assert _failure(part) is None
    assert asyncio.run(part.get_tolerance()) == 0.05


def test_a_step_file_that_tolerates_feature_by_feature_passes(tmp_path):
    """NaN is an answer: the file says how precisely, per feature.

    There is no single number to report, and no honest way to invent one, so the
    test takes the file's word for it rather than demanding that the number be
    repeated in the declaration.
    """
    ctx = _package(tmp_path, {"body": _step_part()}, contents={"body": _step(0.05, 0.2)})
    part = ctx.get_part("//:body")

    assert math.isnan(asyncio.run(part.get_tolerance()))
    assert _failure(part) is None


def test_a_declared_tolerance_outranks_the_file(tmp_path):
    """It is written precisely because the file was not trusted to say."""
    ctx = _package(tmp_path, {"body": _step_part(tolerance=0.3)}, contents={"body": _step(0.05, 0.2)})
    part = ctx.get_part("//:body")

    assert asyncio.run(part.get_tolerance()) == 0.3
    assert _failure(part) is None


def test_the_manufacturability_check_reports_a_missing_tolerance_against_the_part(tmp_path, monkeypatch):
    """Reported through Test.failed(), like every other manufacturability failure."""
    recorded = _record_errors(monkeypatch)
    ctx = _package(tmp_path, {"body": _made_part()})
    part = ctx.get_part("//:body")

    check = ManufacturabilityTest()
    assert asyncio.run(check.test([check], ctx, part)) == ManufacturabilityTest.TEST_FAILED
    assert any("body" in message and "tolerance" in message for message in recorded), recorded


def test_a_purchased_part_is_not_asked_for_a_tolerance(tmp_path, monkeypatch):
    """It comes as it comes; the MCFTT parameters do not apply to it.

    It still fails - nothing in this package supplies it - but on the supplier
    question, which is what proves the tolerance check let it through.
    """
    recorded = _record_errors(monkeypatch)
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//test",
                "manufacturable": True,
                "parts": {"body": {"type": "stl", "vendor": "acme", "sku": "X-1"}},
            }
        )
    )
    (tmp_path / "body.stl").write_text("")
    ctx = pc.Context(str(tmp_path))
    part = ctx.get_part("//:body")

    check = ManufacturabilityTest()
    asyncio.run(check.test([check], ctx, part))

    assert not any("tolerance" in message for message in recorded), recorded


def _assembly_of(tmp_path, monkeypatch, part_config):
    """An assembly procured from one part, ready to be tested.

    'get_supply_bom()' is stubbed rather than computed: the real one calls
    'do_instantiate()', which builds the assembly and so needs a CAD kernel,
    while what is under test here is what 'test_assembly()' does with the bill
    of materials it is handed. That the bill is computed correctly is the
    subject of the assembly tests, not of this one.
    """
    (tmp_path / "top.assy").write_text("links:\n  - part: :body\n")
    ctx = _package(tmp_path, {"body": part_config}, assemblies={"top": {"type": "assy"}})
    assembly = ctx.get_assembly("//:top")

    async def supply_bom():
        return {f"{assembly.project_name}:body": 1}

    monkeypatch.setattr(assembly, "get_supply_bom", supply_bom)
    return ctx, assembly


def test_an_assembly_whose_part_has_no_tolerance_fails(tmp_path, monkeypatch):
    """The assembly path reaches the parts the assembly is procured from."""
    recorded = _record_errors(monkeypatch)
    ctx, assembly = _assembly_of(tmp_path, monkeypatch, _made_part())

    check = ManufacturabilityTest()
    assert asyncio.run(check.test([check], ctx, assembly)) == ManufacturabilityTest.TEST_FAILED

    # Once against the part that has no tolerance...
    assert any("body" in message and "tolerance" in message for message in recorded), recorded
    # ...and once against the assembly that is made of it.
    assert any("top" in message and "body" in message for message in recorded), recorded


def test_an_assembly_whose_part_has_a_tolerance_is_not_failed_for_it(tmp_path, monkeypatch):
    recorded = _record_errors(monkeypatch)
    ctx, assembly = _assembly_of(tmp_path, monkeypatch, _made_part(tolerance=0.1))

    check = ManufacturabilityTest()
    asyncio.run(check.test([check], ctx, assembly))

    assert not any("tolerance" in message for message in recorded), recorded
