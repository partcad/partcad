#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'material' objects a package catalogues.

A material is what a part is made of, not a part: it has no geometry, nothing
constructs it, and it exists so that the 'material' parameter of a part points
at something PartCAD can ask questions of instead of at a string only a
manufacturing provider could interpret.

The fixture package ('data/material') declares one of each shape the feature
has: a full declaration, one whose 'tags' is a single scalar, the short form,
and one that states no density - which is the case a mass calculation has to
refuse rather than guess at.
"""

import pytest

import partcad as pc
from partcad import material as pc_material
from partcad.project import OBJECT_KINDS, OBJECT_KIND_SECTIONS
from partcad.shape import Shape

DATA = "tests/partcad/unit/data/material"


@pytest.fixture
def ctx():
    return pc.Context(DATA)


@pytest.fixture
def root(ctx):
    return ctx.get_project(ctx.get_current_project_path())


#
# The object kind
#


def test_material_is_an_object_kind():
    assert "material" in OBJECT_KINDS
    assert OBJECT_KIND_SECTIONS["material"] == "materials"


def test_materials_are_enumerated_without_being_instantiated(root):
    assert sorted(root.object_names("material")) == ["abs", "mystery", "nylon", "pla"]
    assert root.object_count("material") == 4


def test_every_declared_material_is_instantiated_with_the_package(root):
    # 'init_materials' runs with the package, so they are all there before
    # anybody asks: a part that names one must not pay for a second pass.
    assert sorted(root.materials) == ["abs", "mystery", "nylon", "pla"]


def test_a_material_is_not_a_shape(root):
    # Deliberately not a Shape: there is nothing to tessellate, render, export
    # or measure about a substance.
    assert not isinstance(root.get_material("pla"), Shape)


#
# What a declaration says
#


def test_the_full_declaration_is_read(root):
    pla = root.get_material("pla")
    assert pla.name == "pla"
    assert pla.formal == "PLA"
    assert pla.full == "Polylactic Acid"
    assert pla.url == "https://en.wikipedia.org/wiki/Polylactic_acid"
    assert "thermoplastic" in pla.desc
    assert pla.tags == ["low-cost", "biodegradable"]


def test_the_description_has_no_trailing_newline(root):
    # A folded YAML scalar ends with one, and it reaches a generated README as
    # a line break inside a table cell.
    assert not root.get_material("pla").desc.endswith("\n")


def test_a_single_tag_may_be_written_as_a_scalar(root):
    assert root.get_material("abs").tags == ["heat-resistant"]


def test_the_short_form_is_the_full_name(root):
    nylon = root.get_material("nylon")
    assert nylon.full == "Nylon"
    # Not invented from the object's own name: the package never stated one.
    assert nylon.formal is None


def test_no_tags_is_an_empty_list_not_none(root):
    assert root.get_material("mystery").tags == []


#
# Density, and the mass that comes out of it
#


def test_density_is_in_the_units_partcad_measures_in(root):
    pla = root.get_material("pla")
    assert pla.density == pytest.approx(0.00132)
    # Datasheets quote g/cm^3, which is 1000x larger.
    assert pla.density_g_cm3 == pytest.approx(1.32)


def test_mass_is_volume_times_density(root):
    assert root.get_material("pla").mass(1000.0) == pytest.approx(1.32)


def test_a_material_with_no_density_reports_no_mass(root):
    # None rather than 0.0 or a guess: nothing downstream could tell an
    # invented mass apart from a stated one.
    mystery = root.get_material("mystery")
    assert mystery.density is None
    assert mystery.density_g_cm3 is None
    assert mystery.mass(1000.0) is None


#
# Getting one
#


def test_the_same_object_comes_back_every_time(root):
    assert root.get_material("pla") is root.get_material("pla")


def test_an_undeclared_material_is_none(root):
    assert root.get_material("unobtainium", quiet=True) is None


def test_the_context_resolves_a_material_reference(ctx):
    assert ctx.get_material(":pla").formal == "PLA"


def test_lookup_returns_the_package_and_the_material(ctx):
    project, mat = pc_material.lookup(ctx, "//:pla")
    assert project is not None
    assert mat.formal == "PLA"


def test_lookup_of_an_undeclared_material_names_the_package_it_looked_in(ctx):
    # The package resolved, the material did not: the caller can tell the two
    # apart, which is what makes the error message worth printing.
    project, mat = pc_material.lookup(ctx, "//:unobtainium", quiet=True)
    assert project is not None
    assert mat is None


def test_lookup_of_a_missing_package_returns_neither(ctx):
    project, mat = pc_material.lookup(ctx, "//nonesuch:pla", quiet=True)
    assert project is None
    assert mat is None


#
# What 'pc info' prints
#


def test_info_reports_both_density_units(root):
    info = root.get_material("pla").info()
    assert info["Formal"] == "PLA"
    assert "g/mm^3" in info["Density"]
    assert "g/cm^3" in info["Density"]


def test_info_omits_what_was_not_declared(root):
    info = root.get_material("mystery").info()
    assert "Density" not in info
    assert "Tags" not in info
    assert "Formal" not in info


def test_matches_finds_a_material_by_name_and_by_content(root):
    pla = root.get_material("pla")
    assert pla.matches("pla")
    assert pla.matches("Polylactic")
    assert not pla.matches("titanium")
    assert not pla.matches("")
