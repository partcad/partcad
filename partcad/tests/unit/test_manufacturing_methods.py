#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import pytest

import partcad as pc
from partcad.assembly_config import AssemblyConfiguration
from partcad.assembly_config_manufacturing import (
    METHOD_ASSEMBLE_PARTCAD_ASSY,
    METHOD_ASSY,
    AssemblyConfigManufacturing,
)
from partcad.part_config_manufacturing import (
    METHOD_ADDITIVE,
    METHOD_FORMING,
    METHOD_NONE,
    METHOD_SUBTRACTIVE,
    PartConfigManufacturing,
)


class _FakeShape:
    def __init__(self, config):
        self.config = config

    def get_final_config(self):
        return self.config


def test_part_methods_are_the_ways_of_making_a_part():
    """A part is made, one way or another; none of those is an assembly's way"""
    for name, method in (
        ("additive", METHOD_ADDITIVE),
        ("subtractive", METHOD_SUBTRACTIVE),
        ("forming", METHOD_FORMING),
    ):
        assert PartConfigManufacturing({"manufacturing": {"method": name}}).method == method
    # "assy" is how an assembly is put together, and means nothing for a part.
    assert PartConfigManufacturing({"manufacturing": {"method": METHOD_ASSY}}).method == METHOD_NONE


def test_assembly_has_one_method_and_it_is_assy():
    """An assembly is put together rather than made, so it shares no method"""
    assert AssemblyConfigManufacturing({"manufacturing": {"method": METHOD_ASSY}}).method == (
        METHOD_ASSEMBLE_PARTCAD_ASSY
    )
    assert str(AssemblyConfigManufacturing({"manufacturing": {"method": METHOD_ASSY}})).endswith("method=assy)")
    for name in ("additive", "subtractive", "forming", "basic"):
        assert AssemblyConfigManufacturing({"manufacturing": {"method": name}}).method is None


def test_assy_assemblies_inherit_the_method():
    """The method comes with the type, so it never has to be spelled out"""
    config = AssemblyConfiguration.normalize("a", {"type": "assy"}, "//package:a")
    assert config["manufacturing"]["method"] == METHOD_ASSY
    assert AssemblyConfigManufacturing(config).method == METHOD_ASSEMBLE_PARTCAD_ASSY


def test_assy_assemblies_keep_what_they_declare():
    config = AssemblyConfiguration.normalize(
        "a", {"type": "assy", "manufacturing": {"method": METHOD_ASSY}}, "//package:a"
    )
    assert config["manufacturing"]["method"] == METHOD_ASSY


def test_only_assy_assemblies_inherit_the_method():
    """An alias stands for whatever it points at, so it inherits nothing here"""
    config = AssemblyConfiguration.normalize("a", {"type": "alias", "source": ":other"}, "//package:a")
    assert "manufacturing" not in config


@pytest.mark.parametrize(
    "spec",
    [
        "//feature_interface:connect-instructions",
        "//feature_interface:connect-mates",
        "//provider_manufacturer:assembly",
    ],
)
def test_example_assemblies_are_assembled_by_their_own_instructions(spec):
    ctx = pc.init("examples")
    assembly = ctx._get_assembly(spec)
    assert assembly is not None
    assert AssemblyConfiguration.get_manufacturing_data(assembly).method == METHOD_ASSEMBLE_PARTCAD_ASSY


def test_the_interface_example_buys_from_the_store_next_door():
    """It demonstrates interfaces, so it defines no provider of its own"""
    ctx = pc.init("examples")
    interfaces = ctx.get_project("//feature_interface")
    assert "providers" not in interfaces.config_obj

    suppliers = list(interfaces.get_suppliers().keys())
    assert suppliers == ["//pub/examples/partcad/provider_store:myGarage"]
    assert ctx.get_provider(suppliers[0]) is not None

    # And the store stocks what that example is assembled from.
    for name in ("bracket", "motor", "screw_m3_6mm", "screw_m4_6mm"):
        part = ctx.get_part("//provider_store:" + name)
        assert part is not None, name
        store_data = part.get_store_data()
        assert store_data.vendor and store_data.sku, name
