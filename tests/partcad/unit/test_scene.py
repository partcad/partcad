#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the 'scene' kind of object.

A scene is built the way an assembly is, out of the very same files, and the
tests here are about the two things that make it a kind of its own: what a
package calls it, and the one rule that follows from what it means -- a scene
states an end state, so it has no assembly instructions.
"""

import asyncio
import os
import shutil

import pytest
import yaml

import partcad as pc
from partcad.assembly import Assembly
from partcad.scene import Scene

EXAMPLES = "examples"
SCENE_EXAMPLE_PACKAGE = "produce_scene_assy"
SCENE_EXAMPLE_PACKAGES = (SCENE_EXAMPLE_PACKAGE, "produce_assembly_assy", "produce_part_cadquery_primitive")


def sandbox(tmp_path, packages=SCENE_EXAMPLE_PACKAGES, name="workspace"):
    """A throwaway copy of some example packages, as a package root of its own."""
    root = tmp_path / name
    root.mkdir()
    shutil.copy(os.path.join(EXAMPLES, "partcad.yaml"), root)
    for package in packages:
        shutil.copytree(os.path.join(EXAMPLES, package), root / package)
    return root


@pytest.fixture
def project(tmp_path):
    return pc.Context(str(sandbox(tmp_path))).get_project("//" + SCENE_EXAMPLE_PACKAGE)


#
# The kind
#


def test_a_package_declares_scenes_beside_its_assemblies(project):
    assert sorted(project.scene_configs) == ["bench"]
    # And they are a namespace of their own: nothing here is an assembly.
    assert project.get_assembly_config("bench") is None


def test_a_scene_is_an_assembly_with_a_kind_of_its_own(project):
    """Everything that works on an assembly works on a scene, by construction."""
    scene = project.get_scene("bench")
    assert isinstance(scene, Scene)
    assert isinstance(scene, Assembly)
    assert scene.kind == "scene"
    assert scene.path.endswith("bench.assy")


def test_a_scene_is_not_manufacturable_unless_it_says_so(tmp_path, project):
    """A scene is not a product to be made, so 'pc test' does not ask.

    The default is set as the declaration is normalized rather than left to the
    package-wide answer, which is about the products a package publishes - so a
    scene that really is a deliverable gets the checks back by saying so.
    """
    assert project.get_scene("bench").is_manufacturable is False

    root = sandbox(tmp_path, name="declared")
    config_path = root / SCENE_EXAMPLE_PACKAGE / "partcad.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["scenes"]["bench"]["manufacturable"] = True
    config_path.write_text(yaml.safe_dump(config))

    declared = pc.Context(str(root)).get_project("//" + SCENE_EXAMPLE_PACKAGE)
    assert declared.get_scene("bench").is_manufacturable is True


def test_a_scene_declared_as_a_bare_string_is_an_alias(tmp_path):
    root = sandbox(tmp_path)
    config_path = root / SCENE_EXAMPLE_PACKAGE / "partcad.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["scenes"]["workbench"] = "bench"
    config_path.write_text(yaml.safe_dump(config))

    project = pc.Context(str(root)).get_project("//" + SCENE_EXAMPLE_PACKAGE)
    alias = project.get_scene("workbench")
    assert alias is not None
    assert alias.kind == "scene"
    assert alias.desc == "Alias to bench"


def test_a_scene_alias_resolves_to_a_scene_and_not_to_an_assembly(tmp_path):
    """The source of a scene alias is looked up among scenes.

    Both sections may declare the same name - they are separate namespaces - and
    an alias that reached for the assembly would quietly hand back the wrong
    object.
    """
    root = sandbox(tmp_path)
    config_path = root / SCENE_EXAMPLE_PACKAGE / "partcad.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["scenes"]["twin"] = {"type": "alias", "source": "bench"}
    config["assemblies"] = {"bench": {"type": "assy", "path": "bench.assy"}}
    config_path.write_text(yaml.safe_dump(config))

    project = pc.Context(str(root)).get_project("//" + SCENE_EXAMPLE_PACKAGE)
    assert project.get_scene("twin") is not None
    # The alias is a scene, and so is what it points at; the assembly of the
    # same name is a different object.
    assert project.get_scene("bench").kind == "scene"
    assert project.get_assembly("bench").kind == "assembly"


def test_the_context_resolves_a_scene_by_name(tmp_path):
    ctx = pc.Context(str(sandbox(tmp_path)))
    assert ctx.get_scene("//%s:bench" % SCENE_EXAMPLE_PACKAGE) is not None
    assert ctx.stats_scenes >= 1


#
# What a scene may not say
#


def test_a_scene_rejects_the_assembly_instructions_of_a_connection(tmp_path):
    """'how' is reported and dropped rather than acted upon.

    Per link, and the rest of the file is still read: the placement a 'connect'
    describes is perfectly good, and it is only the account of how the two
    objects were brought together that does not belong in a scene.
    """
    from partcad.scene_factory import SceneFactoryAssy

    project = pc.Context(str(sandbox(tmp_path))).get_project("//" + SCENE_EXAMPLE_PACKAGE)
    # The hook is what the ASSY reader asks per link; a factory is built here
    # rather than fished out of a scene, which holds it only in a closure.
    factory = SceneFactoryAssy.__new__(SceneFactoryAssy)
    factory.name = "bench"
    factory.project = project

    pc.logging.reset_errors()
    how = factory.connect_how({"part": "cube"}, {"name": "block", "how": {"stage": 1}}, "lid")
    assert how.is_default()
    assert pc.logging.had_errors

    pc.logging.reset_errors()
    how = factory.connect_how({"part": "cube"}, {"name": "block"}, "lid")
    assert how.is_default()
    assert not pc.logging.had_errors


def test_an_assembly_keeps_the_assembly_instructions(tmp_path):
    """The very same hook on the assembly factory reads 'how' as it always did."""
    from partcad.assembly_factory_assy import AssemblyFactoryAssy

    factory = AssemblyFactoryAssy.__new__(AssemblyFactoryAssy)
    factory.name = "widget"
    how = factory.connect_how({"part": "cube"}, {"name": "block", "how": {"stage": "1"}}, "lid")
    assert not how.is_default()


#
# The plumbing every kind shares
#


def test_scenes_are_enumerated_for_rendering(project):
    shapes = project._enumerate_shapes(None, None, [], None)
    assert sorted(shape.name for shape in shapes if shape.kind == "scene") == ["bench"]


def test_an_imported_scene_owns_the_parts_named_under_it(tmp_path):
    """An imported scene's shapes are parts of the package that nothing declares.

    'get_part' has to build the scene that produces one when it is handed such
    a name, which is what '_derived_part_owner' decides - and it has to say
    which *kind* of object owns it, because 'assemblies:' and 'scenes:' are
    separate namespaces.

    The format is one this package declares, because that is the only kind there
    is now: the engine scene formats belong to their plugins, and the rule under
    test is PartCAD's rather than any one format's.
    """
    root = tmp_path / "derived"
    root.mkdir()
    (root / "reader.py").write_text("def process(path, request):\n    return {}\n", encoding="utf-8")
    (root / "site.demo").write_text("nothing here is parsed\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(
        "name: //d\n"
        "import:\n"
        "  demo:\n"
        "    path: reader.py\n"
        "    extension: demo\n"
        "    kinds: [scene]\n"
        "    noun: model\n"
        "scenes:\n"
        "  warehouse:\n    type: demo\n    path: site.demo\n",
        encoding="utf-8",
    )
    project = pc.Context(str(root)).get_project("//")

    assert project._derived_part_owner("warehouse/pallet_a/link") == ("scene", "warehouse")
    # A name no scene of this package owns is not one of these.
    assert project._derived_part_owner("brackets/left") is None


def test_the_package_schema_accepts_the_scene_example():
    """The example package validates against the schema editors use."""
    from jsonschema import Draft7Validator

    from partcad.lint.all import get_partcad_schema

    schema = get_partcad_schema()
    config = yaml.safe_load(open(os.path.join(EXAMPLES, SCENE_EXAMPLE_PACKAGE, "partcad.yaml")))
    errors = sorted(Draft7Validator(schema).iter_errors(config), key=lambda e: list(e.path))
    assert not errors, "\n".join("%s: %s" % (list(e.path), e.message) for e in errors)


def test_an_engine_scene_format_is_not_a_file_type_this_wheel_knows(tmp_path):
    """'-t world' resolves to nothing, and that is the point of the split.

    SDFormat is written by 'partcad/partcad-sim-gazebo' and MJCF by
    'partcad/partcad-sim-mujoco', so the bare names are not built-in file types
    and 'pc export -t world' has nothing to resolve. The qualified spelling,
    'sim-gazebo:world', reaches the package that does implement it.

    'urdf' is the counterpart that stays: it describes a robot rather than any
    one engine's world, and it is still handed the tree rather than the geometry
    it decodes to.
    """
    from partcad import output

    ctx = pc.Context(str(sandbox(tmp_path)))
    formats = output.all_formats(ctx)
    assert "world" not in formats
    assert "mjcf" not in formats

    config = output.builtin_formats(ctx, output.EXPORT)["urdf"]
    implementation = output.Implementation(output.EXPORT, "urdf", config)
    assert implementation.extension("bin") == "urdf"
    # Handed the tree rather than the geometry it decodes to: the links, the
    # poses and the properties are all built from what it says.
    assert implementation.decode is False


def test_a_scene_asks_for_the_output_files_a_scene_excludes(project):
    """'exclude: [scenes]' on a file type keeps it away from scenes."""
    cfg = {"step": {"exclude": ["scenes"]}}
    assert project._should_render_format("step", cfg, None, "scene") is False
    # An assembly is not what the exclusion names, so it still gets the file.
    assert project._should_render_format("step", cfg, None, "assembly") is True
    assert project._should_render_format("step", {"step": {}}, None, "scene") is True


#
# Supply
#


class _FakeStoreData:
    vendor = None
    sku = None
    count_per_sku = None


class _FakeLeaf:
    """A line item the cart can resolve: what a bill of materials names."""

    def get_store_data(self):
        return _FakeStoreData()

    async def get_mcftt(self, _which):
        return None


class _FakeHolder(_FakeLeaf):
    """An object that claims to be sold whole, and knows what it holds."""

    def __init__(self, bom):
        self._bom = bom

    def is_declared_purchasable(self):
        return True

    async def get_supply_bom(self):
        return dict(self._bom)

    async def get_bom(self):
        return dict(self._bom)


class _FakeProject:
    """A package holding one object called 'thing' and the parts it is made of."""

    def __init__(self, assembly=None, scene=None):
        self._assembly = assembly
        self._scene = scene

    async def get_part_async(self, name, quiet=False):
        return self.get_part(name, quiet)

    def get_part(self, name, quiet=False):
        return None if name == "thing" else _FakeLeaf()

    def get_assembly(self, name, quiet=False):
        return self._assembly if name == "thing" else None

    def get_scene(self, name, quiet=False):
        return self._scene if name == "thing" else None


class _FakeContext:
    def __init__(self, project):
        self.current_project_path = "//pkg"
        self._project = project

    def get_project(self, name):
        return self._project


def _cart_names(project):
    from partcad.plugin_provider_data_cart import ProviderCart

    cart = ProviderCart()
    asyncio.run(cart.add_object(_FakeContext(project), "//pkg:thing"))
    return sorted(cart.parts)


def test_a_scene_is_never_ordered_whole_however_it_is_declared():
    """Nobody sells an arrangement, so a scene is expanded and never added as is.

    'Scene' inherits 'is_declared_purchasable()' from 'Assembly', which answers
    from 'vendor' and 'sku'. The schema gives a scene neither, but an enrich or
    an alias can carry anything, and the contract is absolute.
    """
    scene = _FakeHolder({"//pkg:bolt": 2})
    assert _cart_names(_FakeProject(scene=scene)) == ["//pkg:bolt"]


def test_an_assembly_sold_assembled_is_still_added_as_one_item():
    """The shortcut the scene skips is untouched for what it is there for."""
    assembly = _FakeHolder({"//pkg:bolt": 2})
    assert _cart_names(_FakeProject(assembly=assembly)) == ["//pkg:thing"]
