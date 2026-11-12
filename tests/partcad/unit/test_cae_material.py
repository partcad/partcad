#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an analysis is told about what a part is made of, and what it meshes (see 'partcad.cae_material')."""

import asyncio

import pytest
import yaml

import partcad as pc
from partcad import cae_material, shape_envelope
from partcad.material import analysis_of

PLA = {
    "density": 1240,
    "youngsModulus": 3.5e9,
    "poissonsRatio": 0.36,
    "yieldStrength": 5.0e7,
    "thermalConductivity": 0.13,
}

WATER = {"density": 999.1, "viscosity": 0.001138, "thermalConductivity": 0.589}

PACKAGE = {
    "name": "//test",
    "materials": {"pla": dict(PLA), "plain": {"density": 1000}, "water": dict(WATER)},
    "parts": {
        "design": {
            "type": "basic",
            "cuboid": [20, 10, 5],
            "parameters": {"material": {"type": "string", "default": ":pla"}},
            "implements": {"pad": [[0, 0, 5], [0, 0, 1], 0]},
        },
        "printed": {"manufacturing": {"method": "additive", "source": "design", "fff": {"infill": "20%"}}},
        "printed-own-ports": {
            "manufacturing": {"method": "additive", "source": "design"},
            "ports": {"elsewhere": [[1, 2, 3], [0, 0, 1], 0]},
        },
        "molded": {"manufacturing": {"method": "forming", "source": "design"}},
        "shrunk": {"manufacturing": {"method": "forming", "source": "design", "mold": {"shrinkage": "2%"}}},
    },
    "interfaces": {"pad": {"ports": {"pad": None}}},
}


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    return pc.Context(str(tmp_path))


def _request(**implementation_defaults):
    """A request as '_output_request' builds it: the implementation's parameters, steel by default."""
    request = {"wrapped": None, "youngs_modulus": 2.1e11, "poissons_ratio": 0.3, "yield_strength": 2.5e8}
    request.update(implementation_defaults)
    return request


def test_a_material_states_what_an_analysis_takes(ctx):
    material = ctx.get_material("//test:pla")
    assert material.youngs_modulus == pytest.approx(3.5e9)
    assert material.poissons_ratio == pytest.approx(0.36)
    assert material.yield_strength == pytest.approx(5.0e7)
    assert analysis_of(material) == {
        "youngs_modulus": 3.5e9,
        "poissons_ratio": 0.36,
        "yield_strength": 5.0e7,
        "density": 1240.0,
        "conductivity": 0.13,
    }
    assert material.material_info()["Yield strength"] == "5e+07 Pa"
    assert material.material_info()["Thermal conductivity"] == "0.13 W/(m*K)"
    assert not material.is_fluid
    assert ctx.get_material("//test:water").is_fluid


def test_the_material_fills_what_the_implementation_defaults(ctx):
    request = _request(density=7850)
    filled = cae_material.fill(request, ctx.get_material("//test:pla"), stated=(), fraction=None)
    assert request["youngs_modulus"] == pytest.approx(3.5e9)
    assert request["yield_strength"] == pytest.approx(5.0e7)
    assert request["density"] == pytest.approx(1240)
    assert set(filled) == {"youngs_modulus", "poissons_ratio", "yield_strength", "density"}


def test_what_the_package_or_the_part_states_wins_over_the_material(ctx):
    request = _request(yield_strength=1.0e6)
    cae_material.fill(request, ctx.get_material("//test:pla"), stated=("yield_strength",), fraction=None)
    assert request["yield_strength"] == pytest.approx(1.0e6)
    assert request["youngs_modulus"] == pytest.approx(3.5e9)


def test_a_parameter_the_implementation_does_not_take_is_not_handed_to_it(ctx):
    """A key it ignores would only change the cache key."""
    request = {"wrapped": None, "youngs_modulus": 2.1e11}
    cae_material.fill(request, ctx.get_material("//test:pla"), stated=(), fraction=None)
    assert set(request) == {"wrapped", "youngs_modulus"}


def test_a_material_that_says_nothing_leaves_the_defaults(ctx):
    request = _request()
    assert cae_material.fill(request, ctx.get_material("//test:plain"), stated=(), fraction=None) == {}
    assert request["youngs_modulus"] == pytest.approx(2.1e11)


def test_a_print_is_its_material_at_the_density_it_is_printed_at(ctx):
    request = _request(density=7850)
    cae_material.fill(request, ctx.get_material("//test:pla"), stated=(), fraction=0.4)
    assert request["youngs_modulus"] == pytest.approx(3.5e9 * 0.4)
    assert request["yield_strength"] == pytest.approx(5.0e7 * 0.4)
    assert request["density"] == pytest.approx(1240 * 0.4)
    # A ratio of strains is not thinner for being printed sparsely.
    assert request["poissons_ratio"] == pytest.approx(0.36)


def test_a_thermal_analysis_takes_the_materials_conductivity(ctx):
    """Every thermal implementation in the index calls it 'conductivity'."""
    request = {"wrapped": None, "conductivity": 50.0, "ambient_temperature": 20.0}
    filled = cae_material.fill(request, ctx.get_material("//test:pla"), stated=(), fraction=None, analysis="thermal")
    assert filled == {"conductivity": pytest.approx(0.13)}
    assert request["ambient_temperature"] == 20.0


def test_a_prints_conductivity_is_thinned_like_its_stiffness(ctx):
    request = {"wrapped": None, "conductivity": 50.0}
    cae_material.fill(request, ctx.get_material("//test:pla"), stated=(), fraction=0.25, analysis="thermal")
    assert request["conductivity"] == pytest.approx(0.13 * 0.25)


def _cfd_request():
    """A CFD implementation's parameters: air at 20 C."""
    return {"wrapped": None, "density": 1.204, "viscosity": 1.82e-5, "iterations": 50}


def test_a_part_made_of_a_fluid_hands_a_cfd_analysis_its_fluid(ctx):
    request = _cfd_request()
    filled = cae_material.fill(request, ctx.get_material("//test:water"), stated=(), fraction=None, analysis="cfd")
    assert request["density"] == pytest.approx(999.1)
    assert request["viscosity"] == pytest.approx(0.001138)
    assert set(filled) == {"density", "viscosity"}


def test_a_solid_says_nothing_to_a_cfd_analysis(ctx):
    """A duct's PLA is not the density of the air a CFD analysis meshes it as."""
    request = _cfd_request()
    assert cae_material.fill(request, ctx.get_material("//test:pla"), stated=(), fraction=None, analysis="cfd") == {}
    assert request["density"] == pytest.approx(1.204)


def test_a_print_does_not_thin_the_fluid_a_cfd_analysis_is_of(ctx):
    request = _cfd_request()
    cae_material.fill(request, ctx.get_material("//test:water"), stated=(), fraction=0.2, analysis="cfd")
    assert request["density"] == pytest.approx(999.1)


def test_a_fluid_says_nothing_to_a_stress_analysis(ctx):
    request = _request(density=7850)
    assert cae_material.fill(request, ctx.get_material("//test:water"), stated=(), fraction=None, analysis="fea") == {}
    assert request["density"] == 7850


def test_a_print_of_nothing_named_is_the_implementations_default_thinned(ctx):
    request = _request()
    cae_material.fill(request, None, stated=("youngs_modulus",), fraction=0.5)
    assert request["youngs_modulus"] == pytest.approx(2.1e11)
    assert request["yield_strength"] == pytest.approx(2.5e8 * 0.5)


#
# What is meshed
#


def _envelope(volume):
    return {
        shape_envelope.KEY_BREP: b"",
        shape_envelope.KEY_METADATA: {shape_envelope.METADATA_MEASUREMENTS: {shape_envelope.METADATA_VOLUME: volume}},
    }


def _volumes(monkeypatch, volumes):
    async def wrapped(self, ctx):
        return _envelope(volumes[self.name])

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)


def test_a_print_is_meshed_as_its_design_at_what_it_deposits(ctx, monkeypatch):
    _volumes(monkeypatch, {"printed": 400.0, "design": 1000.0})
    subject = asyncio.run(cae_material.subject_async(ctx, ctx.get_part("//test:printed")))
    assert subject.shape.name == "design"
    assert subject.fraction == pytest.approx(0.4)
    assert "40%" in subject.note


def test_a_part_with_a_geometry_of_its_own_is_meshed_as_itself(ctx, monkeypatch):
    _volumes(monkeypatch, {"design": 1000.0, "molded": 1000.0})
    design = ctx.get_part("//test:design")
    assert asyncio.run(cae_material.subject_async(ctx, design)) == (design, None, None)
    # A molding is a solid already: the cavity, as the mold gives it back.
    molded = ctx.get_part("//test:molded")
    assert asyncio.run(cae_material.subject_async(ctx, molded)).shape is molded


#
# Where it connects
#


def test_a_print_connects_where_its_design_does(ctx):
    from partcad import shape_ports

    def names(name):
        records = asyncio.run(shape_ports.ports_async(ctx.get_part("//test:" + name), ctx))
        return sorted(record.name for record in records)

    assert names("printed") == ["pad"]
    assert names("molded") == ["pad"]
    # Its own say wins, and a mold that shrinks it moves its ports off the design's.
    assert names("printed-own-ports") == ["elsewhere"]
    assert names("shrunk") == []


#
# What a simulation collides with (see 'partcad.visual')
#


def _named(name, brep, volume):
    return {
        "name": name,
        shape_envelope.KEY_BREP: brep,
        shape_envelope.KEY_PROPERTIES: {"material": ":pla"},
        shape_envelope.KEY_METADATA: {shape_envelope.METADATA_MEASUREMENTS: {shape_envelope.METADATA_VOLUME: volume}},
    }


def test_a_simulation_collides_with_a_prints_design_and_weighs_the_print(ctx, monkeypatch):
    from partcad import visual

    design = _named("//test:design", b"DESIGN", 1000.0)

    async def wrapped(self, ctx):
        return design

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    printed = _named("//test:printed", b"DEPOSIT", 400.0)
    plain = _named("//test:design", b"DESIGN", 1000.0)
    tree = {"name": "//test:assy", shape_envelope.KEY_ASSEMBLY: [printed, plain]}

    scene = asyncio.run(visual.substitute_async(ctx, None, tree, outsides=True)).tree
    collided, untouched = scene[shape_envelope.KEY_ASSEMBLY]
    # The design's geometry...
    assert collided[shape_envelope.KEY_BREP] == b"DESIGN"
    # ...under the print's name, weighed by the print's measurements.
    assert collided["name"] == "//test:printed"
    assert collided[shape_envelope.KEY_METADATA] == printed[shape_envelope.KEY_METADATA]
    assert visual.NODE_KEY not in collided
    # A part that is not a print is left as it is.
    assert untouched is plain


def test_a_picture_still_draws_a_print_as_its_design_with_the_designs_measurements(ctx, monkeypatch):
    from partcad import visual

    design = _named("//test:design", b"DESIGN", 1000.0)

    async def wrapped(self, ctx):
        return design

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    tree = {"name": "//test:assy", shape_envelope.KEY_ASSEMBLY: [_named("//test:printed", b"DEPOSIT", 400.0)]}
    drawn = asyncio.run(visual.substitute_async(ctx, None, tree)).tree[shape_envelope.KEY_ASSEMBLY][0]
    assert drawn[shape_envelope.KEY_BREP] == b"DESIGN"
    # Asked for with the material the print was lent, as a visual is asked for with the part's own values.
    assert drawn[visual.NODE_KEY].startswith("//test:design")
