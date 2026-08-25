#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A part that is going to be made has to say how precisely.

'tolerance' is an object-type parameter of the homogeneous part types, and it
reads back as 0.0 when nothing declared one. 0.0 is a demand for perfect
precision, which is what "nobody said" amounts to and is not something a
manufacturer can be asked for, so the CAM test rejects it - for a part in the
package, and for a part an assembly in the package is procured from.

Only what is actually made is asked: a part that is bought comes as it comes.
"""

import asyncio

import yaml

import partcad as pc
from partcad.test.cam import CamTest


def _record_errors(monkeypatch):
    """Collect pc_logging.error() calls.

    The 'partcad' logger sets propagate=False, so the caplog fixture (which
    attaches to the root logger) sees nothing on the pytest version used in CI.
    """
    recorded = []
    monkeypatch.setattr(pc.logging, "error", lambda *args, **kwargs: recorded.append(" ".join(str(a) for a in args)))
    return recorded


def _package(tmp_path, parts, assemblies=None):
    config = {"name": "//test", "manufacturable": True, "parts": parts}
    if assemblies:
        config["assemblies"] = assemblies
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))
    for name in parts:
        (tmp_path / (name + ".stl")).write_text("")
    return pc.Context(str(tmp_path))


def _made_part(**parameters):
    part = {"type": "stl", "manufacturing": {"method": "additive"}}
    if parameters:
        part["parameters"] = {k: {"type": "float", "default": v} for k, v in parameters.items()}
    return part


def test_a_part_with_no_tolerance_fails(tmp_path):
    ctx = _package(tmp_path, {"body": _made_part()})
    part = ctx.get_part("//:body")

    failure = CamTest().tolerance_failure(part)

    assert failure is not None
    assert "tolerance" in failure


def test_a_part_with_a_tolerance_of_zero_fails_the_same_way(tmp_path):
    """Declaring the default explicitly is still nothing specified."""
    ctx = _package(tmp_path, {"body": _made_part(tolerance=0.0)})
    part = ctx.get_part("//:body")

    assert CamTest().tolerance_failure(part) is not None


def test_a_part_with_a_tolerance_passes(tmp_path):
    ctx = _package(tmp_path, {"body": _made_part(tolerance=0.1)})
    part = ctx.get_part("//:body")

    assert CamTest().tolerance_failure(part) is None


def test_a_type_that_cannot_carry_a_tolerance_says_so(tmp_path):
    """A STEP part has no tolerance to declare, and the message says which."""
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//test",
                "manufacturable": True,
                "parts": {"body": {"type": "step", "manufacturing": {"method": "additive"}}},
            }
        )
    )
    (tmp_path / "body.step").write_text("")
    part = pc.Context(str(tmp_path)).get_part("//:body")

    failure = CamTest().tolerance_failure(part)

    assert failure is not None
    assert "step" in failure


def test_the_cam_test_reports_a_missing_tolerance_against_the_part(tmp_path, monkeypatch):
    """Reported through Test.failed(), like every other CAM failure."""
    recorded = _record_errors(monkeypatch)
    ctx = _package(tmp_path, {"body": _made_part()})
    part = ctx.get_part("//:body")

    cam = CamTest()
    assert asyncio.run(cam.test([cam], ctx, part)) == CamTest.TEST_FAILED
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

    cam = CamTest()
    asyncio.run(cam.test([cam], ctx, part))

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

    cam = CamTest()
    assert asyncio.run(cam.test([cam], ctx, assembly)) == CamTest.TEST_FAILED

    # Once against the part that has no tolerance...
    assert any("body" in message and "tolerance" in message for message in recorded), recorded
    # ...and once against the assembly that is made of it.
    assert any("top" in message and "body" in message for message in recorded), recorded


def test_an_assembly_whose_part_has_a_tolerance_is_not_failed_for_it(tmp_path, monkeypatch):
    recorded = _record_errors(monkeypatch)
    ctx, assembly = _assembly_of(tmp_path, monkeypatch, _made_part(tolerance=0.1))

    cam = CamTest()
    asyncio.run(cam.test([cam], ctx, assembly))

    assert not any("tolerance" in message for message in recorded), recorded
