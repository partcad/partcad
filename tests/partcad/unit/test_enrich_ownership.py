#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""An 'enrich' is an alias to a parameterized instance of what it enriches.

Which settles where the objects it involves live. The instance is the source
package's object with other parameter values, so it belongs to the source
package, under the '<name>;<param>=<value>' name PartCAD gives any
parameterized instance - and only if that package does not hold it already. The
enrich itself is a reference carrying its own name, in the package that
declares it, where the assemblies of that package refer to it as a local part.

What used to happen is that the enrich built the instance itself and registered
it in the source package under the *enriching* object's name - which defaults
to the source object's own name - so enriching an object replaced it.
'examples/feature_enrich' does exactly that to
'examples/produce_sketch_cadquery', which is why rendering the examples in one
process produced a sketch with the enricher's dimensions in a package that
declares its own.

It also decides what an enrich points at from its own declaration rather than
from the object it is asked to fill in, which is what makes a chain of enriches
and aliases resolve the same way in any order.

None of this needs a CAD kernel: it is about which package holds which object,
and it is all decided before anything is built. The tests register a part and a
sketch type that construct nothing, so they run in milliseconds and stay honest
about what they are testing.
"""

import asyncio
import threading
import time
from typing import ClassVar

import pytest
import yaml

import partcad as pc
from partcad import assembly_factory, factory, part_factory, sketch_factory
from partcad.exception import ObjectNameTakenError


class NullPartFactory(part_factory.PartFactory):
    """A part type that registers a part and builds nothing."""

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)
        self._create(config)

    async def instantiate(self, part):
        return None


class CountingPartFactory(part_factory.PartFactory):
    """A part type that records every build and hands back a distinguishable one.

    A BREP envelope is what a factory returns; this one carries a payload that
    says which build produced it, so that two objects holding the same geometry
    and two objects holding copies of it can be told apart.
    """

    builds: ClassVar[list] = []

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)
        self._create(config)

    async def instantiate(self, part):
        CountingPartFactory.builds.append(f"{self.project.name}:{self.name}")
        return {"brep": ("geometry #%d" % len(CountingPartFactory.builds)).encode()}


class NullAssemblyFactory(assembly_factory.AssemblyFactory):
    """An assembly type that registers an assembly and assembles nothing."""

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)
        self._create(config)

    def instantiate(self, assembly):
        return None


class NullSketchFactory(sketch_factory.SketchFactory):
    """The same, for sketches."""

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)
        self._create(config)

    async def instantiate(self, sketch):
        return None


@pytest.fixture(autouse=True)
def null_types():
    """Make 'test-null' a part type and a sketch type for the duration of a test."""
    saved = {kind: factory.all[kind].get("test-null") for kind in ("part", "sketch", "assembly")}
    saved_counting = factory.all["part"].get("test-count")
    factory.register("part", "test-null", NullPartFactory)
    factory.register("sketch", "test-null", NullSketchFactory)
    factory.register("assembly", "test-null", NullAssemblyFactory)
    factory.register("part", "test-count", CountingPartFactory)
    CountingPartFactory.builds = []
    try:
        yield
    finally:
        for kind, previous in saved.items():
            if previous is None:
                del factory.all[kind]["test-null"]
            else:
                factory.register(kind, "test-null", previous)
        if saved_counting is None:
            del factory.all["part"]["test-count"]
        else:
            factory.register("part", "test-count", saved_counting)


def write_package(root, path, config):
    """Declare a package at 'path' under 'root'. Subdirectories are found on their own."""
    directory = root / path if path else root
    directory.mkdir(parents=True, exist_ok=True)
    # Declaration order is preserved: which object a package creates first is
    # what decides who keeps a name two declarations claim.
    (directory / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    return directory


def build(shape):
    """Prepare 'shape' and run the factory behind it, as 'get_wrapped()' does.

    Both halves matter: an enrich resolves what it points at while it is
    prepared, and hands back the geometry while it is instantiated.
    """
    asyncio.run(shape.prepare_async())
    asyncio.run(shape.instantiate(shape))


def width_of(shape):
    return shape.config["parameters"]["width"]["default"]


def assemble(assembly):
    """The same for an assembly, whose factory assembles synchronously."""
    asyncio.run(assembly.prepare_async())
    assembly.instantiate(assembly)


@pytest.fixture
def two_packages(tmp_path):
    """A package whose part is enriched by another, both under the same name.

    The shape of 'examples/feature_enrich' against
    'examples/produce_sketch_cadquery': the enrich names no 'source', so the
    source object's name defaults to the enriching object's - and the two
    packages then have a part called 'widget' each.
    """
    write_package(tmp_path, "", {"name": "//test"})
    write_package(
        tmp_path,
        "source",
        {"parts": {"widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(
        tmp_path,
        "enricher",
        {"parts": {"widget": {"type": "enrich", "package": "../source", "with": {"width": 5.0}}}},
    )
    return tmp_path


def test_enriching_a_part_leaves_the_source_package_s_own_part_alone(two_packages):
    ctx = pc.Context(str(two_packages))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    build(enricher.get_part("widget"))

    assert width_of(source.parts["widget"]) == 3.0
    assert source.get_part_config("widget")["parameters"]["width"]["default"] == 3.0


def test_the_instance_goes_to_the_source_package_under_a_name_of_its_own(two_packages):
    """The instance is the source part with other parameters, and says so."""
    ctx = pc.Context(str(two_packages))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    build(enricher.get_part("widget"))

    assert sorted(source.parts) == ["widget", "widget;width=5.0"]
    instance = source.parts["widget;width=5.0"]
    assert width_of(instance) == 5.0
    # Named after the source part, so the file that part is read from is still
    # the file this instance is read from.
    assert instance.config["orig_name"] == "widget"


def test_the_enrich_object_stays_in_the_package_that_declares_it(two_packages):
    """And stays the object that package holds under that name, before and after."""
    ctx = pc.Context(str(two_packages))
    enricher = ctx.get_project("//test/enricher")

    enrich = enricher.get_part("widget")
    build(enrich)

    assert enricher.parts["widget"] is enrich
    assert enrich.project_name == "//test/enricher"
    assert width_of(enrich) == 5.0
    # And says which instance it is a reference to.
    assert enrich.config["source"] == "//test/source:widget;width=5.0"


def test_an_enrich_under_a_name_of_its_own_does_not_add_that_name_to_the_source(tmp_path):
    """The enriching name never reaches the source package, matching or not.

    A source named explicitly is the case that was merely untidy rather than
    destructive: the source package ended up carrying an object its
    'partcad.yaml' never declared, under a name belonging to another package.
    """
    write_package(tmp_path, "", {"name": "//test"})
    write_package(
        tmp_path,
        "source",
        {"parts": {"widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(
        tmp_path,
        "enricher",
        {
            "parts": {
                "widget_xl": {
                    "type": "enrich",
                    "package": "../source",
                    "source": "widget",
                    "with": {"width": 9.0},
                }
            }
        },
    )

    ctx = pc.Context(str(tmp_path))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    build(enricher.get_part("widget_xl"))

    assert sorted(source.parts) == ["widget", "widget;width=9.0"]
    assert sorted(enricher.parts) == ["widget_xl"]
    assert width_of(enricher.parts["widget_xl"]) == 9.0


def test_an_enrich_that_changes_nothing_gets_the_source_part_itself(tmp_path):
    """'feature_enrich:dxf_01' is this: an enrich that overrides nothing.

    It was the silent half of the same defect - the object it put in the source
    package was identical to the one it replaced, so nothing looked wrong.
    """
    write_package(tmp_path, "", {"name": "//test"})
    write_package(
        tmp_path,
        "source",
        {"parts": {"widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(tmp_path, "enricher", {"parts": {"widget": {"type": "enrich", "package": "../source"}}})

    ctx = pc.Context(str(tmp_path))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    enrich = enricher.get_part("widget")
    original = source.parts["widget"]
    build(enrich)

    assert sorted(source.parts) == ["widget"]
    assert source.parts["widget"] is original
    assert width_of(enrich) == 3.0


def test_two_enriches_asking_for_the_same_parameters_share_one_instance(tmp_path):
    write_package(tmp_path, "", {"name": "//test"})
    write_package(
        tmp_path,
        "source",
        {"parts": {"widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(
        tmp_path,
        "enricher",
        {
            "parts": {
                "wide": {"type": "enrich", "package": "../source", "source": "widget", "with": {"width": 5.0}},
                "also_wide": {"type": "enrich", "package": "../source", "source": "widget", "with": {"width": 5.0}},
            }
        },
    )

    ctx = pc.Context(str(tmp_path))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    build(enricher.get_part("wide"))
    build(enricher.get_part("also_wide"))

    assert sorted(source.parts) == ["widget", "widget;width=5.0"]


def test_an_enrich_keeps_its_own_properties_and_the_instance_gets_none_of_them(tmp_path):
    """Which is what makes sharing the instance sound.

    Two enriches of the same instance differ in what they say about the object
    they produce - where it sits, what it is called, what it is for - and none
    of that can live on the instance they have in common.
    """
    write_package(tmp_path, "", {"name": "//test"})
    write_package(
        tmp_path,
        "source",
        {"parts": {"widget": {"type": "test-null", "desc": "the original", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(
        tmp_path,
        "enricher",
        {
            "parts": {
                "widget": {
                    "type": "enrich",
                    "package": "../source",
                    "with": {"width": 5.0},
                    "desc": "the enriched one",
                    "offset": [[0, 0, 0], [0, 0, 1], 90],
                }
            }
        },
    )

    ctx = pc.Context(str(tmp_path))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    enrich = enricher.get_part("widget")
    build(enrich)

    assert enrich.config["desc"] == "the enriched one"
    assert "offset" in enrich.config
    instance = source.parts["widget;width=5.0"]
    assert instance.config["desc"] == "the original"
    assert "offset" not in instance.config


def test_an_enrich_reports_what_it_resolved_to_without_being_built(two_packages):
    """A shape that comes out of the cache is never instantiated.

    'Shape.get_wrapped()' returns a cached shape before it ever reaches the
    factory, so what an enrich reports cannot be settled there: it would answer
    one way on a cold cache and another on a warm one.
    """
    ctx = pc.Context(str(two_packages))
    enricher = ctx.get_project("//test/enricher")

    enrich = enricher.get_part("widget")
    asyncio.run(enrich.prepare_async())

    assert width_of(enrich) == 5.0
    assert enrich.config["source"] == "//test/source:widget;width=5.0"


def test_the_same_enrich_can_be_instantiated_twice(two_packages):
    """The second time resolves to the instance the first time created.

    A shape is instantiated again whenever what it was built from is no longer
    what is wanted. The enrich carries the parameters it resolved to, so asking
    it again asks for the same instance rather than for the source part.
    """
    ctx = pc.Context(str(two_packages))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    enrich = enricher.get_part("widget")
    build(enrich)
    build(enrich)

    assert sorted(source.parts) == ["widget", "widget;width=5.0"]
    assert width_of(enrich) == 5.0
    assert width_of(source.parts["widget"]) == 3.0


def test_enriching_a_sketch_leaves_the_source_package_alone(tmp_path):
    """The sketch half of the same defect - the one 'pc render -r' tripped over."""
    write_package(tmp_path, "", {"name": "//test"})
    write_package(
        tmp_path,
        "source",
        {"sketches": {"sketch": {"type": "test-null", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(
        tmp_path,
        "enricher",
        {"sketches": {"sketch": {"type": "enrich", "package": "../source", "with": {"width": 4.0}}}},
    )

    ctx = pc.Context(str(tmp_path))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    enrich = enricher.get_sketch("sketch")
    build(enrich)

    assert width_of(source.sketches["sketch"]) == 3.0
    assert sorted(source.sketches) == ["sketch", "sketch;width=4.0"]
    assert enricher.sketches["sketch"] is enrich
    assert width_of(enrich) == 4.0


def test_enriching_an_assembly_leaves_the_source_package_alone(tmp_path):
    """An assembly takes parameters too, so it can be enriched like anything else.

    Its ASSY file is a template and the values reach it as 'param_<name>', so
    an assembly with other parameter values is another instance of the same
    assembly - which is what an enrich of it asks for.
    """
    write_package(tmp_path, "", {"name": "//test"})
    write_package(
        tmp_path,
        "source",
        {"assemblies": {"desk": {"type": "test-null", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(
        tmp_path,
        "enricher",
        {"assemblies": {"desk": {"type": "enrich", "package": "../source", "with": {"width": 5.0}}}},
    )

    ctx = pc.Context(str(tmp_path))
    source = ctx.get_project("//test/source")
    enricher = ctx.get_project("//test/enricher")

    enrich = enricher.get_assembly("desk")
    assemble(enrich)

    assert width_of(source.assemblies["desk"]) == 3.0
    assert sorted(source.assemblies) == ["desk", "desk;width=5.0"]
    assert enricher.assemblies["desk"] is enrich
    assert width_of(enrich) == 5.0
    assert enrich.config["source"] == "//test/source:desk;width=5.0"


def test_an_enrich_of_an_enrich_resolves_to_the_instance_at_the_bottom(tmp_path):
    """Each enrich in the chain adds its instance to the package it enriches.

    The one that could go wrong here is the relative 'package:' of the enrich
    in the middle: it belongs to the package that wrote it, so the instance it
    asks for has to be asked for from there.
    """
    write_package(tmp_path, "", {"name": "//test"})
    # 'c' is 'b's own sub-package, so 'b's path to it means nothing from 'a'.
    write_package(
        tmp_path,
        "b/c",
        {"parts": {"widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}}}},
    )
    write_package(
        tmp_path,
        "b",
        {"parts": {"widget": {"type": "enrich", "package": "c", "with": {"width": 5.0}}}},
    )
    write_package(
        tmp_path,
        "a",
        {"parts": {"widget": {"type": "enrich", "package": "../b"}}},
    )

    ctx = pc.Context(str(tmp_path))
    a = ctx.get_project("//test/a")
    c = ctx.get_project("//test/b/c")

    build(a.get_part("widget"))

    assert width_of(a.parts["widget"]) == 5.0
    assert width_of(c.parts["widget"]) == 3.0
    assert sorted(c.parts) == ["widget", "widget;width=5.0"]


# One instance is one object, and one object is built once.


def test_everything_pointing_at_one_instance_gets_the_one_geometry(tmp_path):
    """Two enriches, an alias to one of them, and an alias straight to the instance.

    Each of them is its own object with its own name, and each used to build the
    geometry over again: a reference ran the source's factory against itself,
    which left the source unbuilt and its cache entry - the only one there is,
    since a reference has none of its own - untouched.
    """
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {"type": "test-count", "parameters": {"width": {"default": 3.0}}},
                "wide_a": {"type": "enrich", "source": "widget", "with": {"width": 7.0}},
                "wide_b": {"type": "enrich", "source": "widget", "with": {"width": 7.0}},
                "referred": {"type": "alias", "source": ":wide_a"},
                "direct": {"type": "alias", "source": ":widget;width=7.0"},
            },
        },
    )
    ctx = pc.Context(str(tmp_path))
    project = ctx.get_project("//test")

    wrapped = {
        name: asyncio.run(project.get_part(name).get_wrapped(ctx))
        for name in ("wide_a", "wide_b", "referred", "direct")
    }

    assert CountingPartFactory.builds == ["//test:widget;width=7.0"]
    # One geometry, held by one object, and every reference carries that very
    # payload rather than a copy of it.
    payloads = {id(shape["brep"]) for shape in wrapped.values()}
    assert len(payloads) == 1
    assert payloads == {id(project.parts["widget;width=7.0"]._wrapped["brep"])}
    # Each of them is still itself, and says so.
    assert sorted(shape["name"] for shape in wrapped.values()) == [
        "//test:direct",
        "//test:referred",
        "//test:wide_a",
        "//test:wide_b",
    ]


def test_a_reference_is_keyed_on_what_it_points_at(tmp_path):
    """One entry in the cache, not one per reference to it.

    A reference that adds nothing shares the source's key outright, so the
    geometry is stored once however many aliases and enriches point at it - and
    the object that owns that entry is the one that fills it. A reference that
    moves what it points at is different geometry and keys differently, from
    the source's key plus what it adds.
    """
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {"type": "test-count", "parameters": {"width": {"default": 3.0}}},
                "wide": {"type": "enrich", "source": "widget", "with": {"width": 7.0}},
                "wide_too": {"type": "enrich", "source": "widget", "with": {"width": 7.0}},
                "moved": {
                    "type": "enrich",
                    "source": "widget",
                    "with": {"width": 7.0},
                    "offset": [[1, 0, 0], [0, 0, 1], 0],
                },
                "referred": {"type": "alias", "source": ":widget"},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//test")

    def key_of(name):
        return asyncio.run(project.get_part(name).get_cache_key_async())

    instance = key_of("widget;width=7.0")
    assert instance is not None
    assert key_of("wide") == instance
    assert key_of("wide_too") == instance
    assert key_of("referred") == key_of("widget")
    # Its own entry, because what it hands back is not what the instance does.
    assert key_of("moved") not in (None, instance)

    # And who fills which entry.
    assert project.parts["widget"].owns_cache_entry is True
    assert project.parts["wide"].owns_cache_entry is False
    assert project.parts["referred"].owns_cache_entry is False
    assert project.parts["moved"].owns_cache_entry is True


def test_an_enrich_does_not_apply_the_instance_s_placement_a_second_time(tmp_path):
    """The instance places itself now, so what it points at must not inherit it."""
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {
                    "type": "test-null",
                    "parameters": {"width": {"default": 3.0}},
                    "offset": [[0, 0, 0], [0, 0, 1], 90],
                },
                "wide": {"type": "enrich", "source": "widget", "with": {"width": 7.0}},
                "moved": {"type": "enrich", "source": "widget", "offset": [[1, 0, 0], [0, 0, 1], 0]},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//test")

    wide = project.get_part("wide")
    moved = project.get_part("moved")
    build(wide)
    build(moved)

    assert "offset" not in wide.config
    # Its own placement is still its own, and applies on top of the instance's.
    assert moved.config["offset"] == [[1, 0, 0], [0, 0, 1], 0]


# A reference that is handed parameters passes them to what it references, so
# aliases and enriches compose in any order.


def test_an_alias_to_an_enrich_is_the_enriched_part(tmp_path):
    """It used to be the un-enriched one.

    The enrich read its 'with' off the object it was handed, and through an
    alias that object is the alias, which declares none.
    """
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}},
                "enriched": {"type": "enrich", "source": "widget", "with": {"width": 7.0}},
                "referred": {"type": "alias", "source": ":enriched"},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//test")

    referred = project.get_part("referred")
    build(referred)

    # An alias reports its own configuration, so what it resolves to is read
    # the way anything reads through a reference.
    assert referred.get_final_config()["parameters"]["width"]["default"] == 7.0
    assert width_of(project.parts["widget"]) == 3.0
    assert "widget;width=7.0" in project.parts


def test_an_enrich_of_an_alias_parametrizes_what_the_alias_points_at(tmp_path):
    """The alias has no parameters of its own to apply them to, so it passes them on."""
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}},
                "referred": {"type": "alias", "source": ":widget"},
                "enriched": {"type": "enrich", "source": "referred", "with": {"width": 7.0}},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//test")

    enriched = project.get_part("enriched")
    build(enriched)

    assert width_of(enriched) == 7.0
    assert "widget;width=7.0" in project.parts


def test_an_enrich_of_an_enrich_overrides_it(tmp_path):
    """Parameters keep travelling down the chain, the outer ones winning."""
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}},
                "wider": {"type": "enrich", "source": "widget", "with": {"width": 7.0}},
                "widest": {"type": "enrich", "source": ":wider", "with": {"width": 9.0}},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//test")

    widest = project.get_part("widest")
    build(widest)

    assert width_of(widest) == 9.0
    # Straight to the instance at the bottom of the chain, and the object that
    # chain is made of is left as it was.
    assert "widget;width=9.0" in project.parts
    assert width_of(project.parts["widget"]) == 3.0


# Whatever installs an object into a package, the package is what says whether
# the name is free.


@pytest.fixture
def one_part(tmp_path):
    write_package(
        tmp_path,
        "",
        {"name": "//test", "parts": {"widget": {"type": "test-null"}}},
    )
    return pc.Context(str(tmp_path)).get_project("//test")


def test_a_package_refuses_to_have_an_object_displaced(one_part):
    widget = one_part.parts["widget"]

    with pytest.raises(ObjectNameTakenError):
        one_part.register_object("part", "widget", object())

    assert one_part.parts["widget"] is widget


def test_registering_the_same_object_again_is_not_a_collision(one_part):
    widget = one_part.parts["widget"]

    one_part.register_object("part", "widget", widget)

    assert one_part.parts["widget"] is widget


def test_a_part_an_assembly_materializes_is_handed_back_the_second_time(one_part):
    """A URDF's links and a STEP assembly's components are not declarations.

    Nothing in 'partcad.yaml' says they exist - the assembly's own source file
    does - so they are registered as it is built, and an assembly is built more
    than once: asking for one of its parts by name builds it, and so does
    rendering it. The later pass finds what the first one registered, which is
    the same part again and not a second claim on the name.
    """
    config = {"type": "test-null", "name": "robot/forearm", "orig_name": "robot/forearm"}

    first = one_part.materialize_part_by_config(config)
    second = one_part.materialize_part_by_config(config)

    assert first is not None
    assert second is first
    assert one_part.get_broken_object_reason("part", "robot/forearm") is None


def test_a_user_s_parameter_override_says_which_instance_an_enrich_wants(tmp_path):
    """'pc.user_config.parameter_config' set after the package has been loaded.

    Which is when it is normally set: the CLI reads it off the command line, and
    a program using PartCAD as a library sets it against a context it already
    has. An override on an enrich says which instance of the source it wants -
    not merely what that instance reports - so the reference has to be pointed
    at the other instance, and the stored declaration has to say so too, since
    'pc convert' reads the resolved name off it.
    """
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {"type": "test-null", "parameters": {"width": {"default": 3.0}}},
                "wide": {"type": "enrich", "source": ":widget", "with": {"width": 5.0}},
            },
        },
    )
    ctx = pc.Context(str(tmp_path))
    pc.user_config.parameter_config["//test:wide"] = {"width": 9.0}
    try:
        wide = ctx.get_part("//test:wide")
        asyncio.run(wide.prepare_async())
    finally:
        del pc.user_config.parameter_config["//test:wide"]

    project = ctx.get_project("//test")
    assert "widget;width=9.0" in project.parts
    assert wide.config["source"] == "//test:widget;width=9.0"
    assert project.part_configs["wide"]["source_resolved"] == "//test:widget;width=9.0"
    assert width_of(wide) == 9.0


def test_an_enrich_does_not_publish_the_aliases_of_what_it_points_at(tmp_path):
    """'aliases:' on the source is the source package's name for the source.

    A package does not gain a part called 'box' because one of its enriches
    happens to point at something that has one - which is what
    'examples/produce_part_cadquery_primitive' saw as an 'Aliases: box' row
    appearing under every enriched entry of its README.
    """
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "widget": {
                    "type": "test-null",
                    "parameters": {"width": {"default": 3.0}},
                    "aliases": ["box"],
                },
                "wide": {"type": "enrich", "source": ":widget", "with": {"width": 5.0}},
            },
        },
    )
    ctx = pc.Context(str(tmp_path))
    project = ctx.get_project("//test")
    wide = project.parts["wide"]
    build(wide)

    # The source keeps its own, and so does the alias the package made for it.
    assert project.part_configs["widget"]["aliases"] == ["box"]
    assert "box" in project.parts
    assert "aliases" not in wide.config


def test_two_threads_assembling_one_assembly_assemble_it_once(tmp_path):
    """An assembly is assembled once, however many threads ask for it.

    'Project._materialize_derived_part' assembles one to get at the parts it
    produces while another thread may be rendering it, and a factory appends to
    'children' rather than replacing them - so both finding it empty puts the
    whole tree in there twice. That is what 'examples/produce_assembly_urdf'
    saw as a robot.svg carrying every line of itself twice.
    """
    inside = threading.Event()

    class SlowAssemblyFactory(assembly_factory.AssemblyFactory):
        def __init__(self, ctx, source_project, target_project, config):
            super().__init__(ctx, source_project, target_project, config)
            self._create(config)

        def instantiate(self, assembly):
            inside.set()
            time.sleep(0.3)
            # As the URDF and ASSY factories do: appended, not assigned.
            assembly.children.append(object())

    factory.register("assembly", "test-slow", SlowAssemblyFactory)
    write_package(tmp_path, "", {"name": "//test", "assemblies": {"rig": {"type": "test-slow"}}})
    ctx = pc.Context(str(tmp_path))
    rig = ctx.get_project("//test").assemblies["rig"]

    def assemble_it(wait):
        if wait:
            inside.wait(5)
        asyncio.run(rig.do_instantiate())

    try:
        threads = [threading.Thread(target=assemble_it, args=(wait,)) for wait in (False, True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        del factory.all["assembly"]["test-slow"]

    assert len(rig.children) == 1


def test_two_tasks_assembling_one_assembly_assemble_it_once(tmp_path):
    """The same, for two tasks of one loop rather than two threads.

    The thread lock does not separate them: an RLock is re-entrant per
    *thread*, and the tasks of a loop share one, so every one of them passes
    it. Only the task lock inside it keeps the second out.
    """
    started = asyncio.Event()

    class SlowAssemblyFactory(assembly_factory.AssemblyFactory):
        def __init__(self, ctx, source_project, target_project, config):
            super().__init__(ctx, source_project, target_project, config)
            self._create(config)

        def instantiate(self, assembly):
            # On a worker thread, which is what gives the other task on the
            # loop its chance to run.
            time.sleep(0.3)
            assembly.children.append(object())

    factory.register("assembly", "test-slow-task", SlowAssemblyFactory)
    write_package(tmp_path, "", {"name": "//test", "assemblies": {"rig": {"type": "test-slow-task"}}})
    ctx = pc.Context(str(tmp_path))
    rig = ctx.get_project("//test").assemblies["rig"]

    async def first():
        started.set()
        await rig.do_instantiate()

    async def second():
        await started.wait()
        await rig.do_instantiate()

    try:
        asyncio.run(asyncio.wait_for(_gather(first(), second()), timeout=20))
    finally:
        del factory.all["assembly"]["test-slow-task"]

    assert len(rig.children) == 1


async def _gather(*coroutines):
    return await asyncio.gather(*coroutines)


def test_an_assembly_can_be_assembled_again_under_a_second_loop(tmp_path):
    """The task lock is keyed on the loop, so a second 'asyncio.run()' can take it.

    A worker thread runs one loop per instantiation, and an 'asyncio.Lock' binds
    to the loop the first time somebody waits on it - after which awaiting it
    under another loop raises. So a lock cached against the assembly alone would
    serve the first loop and refuse the second, which is an assembly asked for
    twice on one worker thread.
    """

    class SlowAssemblyFactory(assembly_factory.AssemblyFactory):
        def __init__(self, ctx, source_project, target_project, config):
            super().__init__(ctx, source_project, target_project, config)
            self._create(config)

        def instantiate(self, assembly):
            time.sleep(0.3)
            assembly.children.append(object())

    factory.register("assembly", "test-slow-loop", SlowAssemblyFactory)
    write_package(tmp_path, "", {"name": "//test", "assemblies": {"rig": {"type": "test-slow-loop"}}})
    ctx = pc.Context(str(tmp_path))
    rig = ctx.get_project("//test").assemblies["rig"]

    def assemble_contended():
        # Contended on purpose: an uncontended 'asyncio.Lock' never looks the
        # loop up, so only a second task waiting on it binds it to this loop.
        started = asyncio.Event()

        async def first():
            started.set()
            await rig.do_instantiate()

        async def second():
            await started.wait()
            await rig.do_instantiate()

        asyncio.run(asyncio.wait_for(_gather(first(), second()), timeout=20))

    try:
        assemble_contended()
        assert len(rig.children) == 1
        # Asked for again, on this same thread, under a loop of its own.
        rig.children = []
        assemble_contended()
    finally:
        del factory.all["assembly"]["test-slow-loop"]

    assert len(rig.children) == 1


def test_two_threads_materializing_one_part_get_one_part(one_part):
    """The same, when the two passes overlap rather than follow one another.

    'Assembly.do_instantiate' decides whether to assemble by reading 'children'
    without a lock, so the thread rendering a URDF assembly and the thread
    resolving one of its links by name can both be walking the same links. The
    second one must find the part the first is registering, not create a part
    under a name that is being taken.

    Deterministic in both directions: the second thread is released while the
    first is inside the factory, so without the lock it passes the presence
    test and lands on 'ObjectNameTakenError'.
    """
    inside = threading.Event()

    class SlowPartFactory(part_factory.PartFactory):
        def __init__(self, ctx, source_project, target_project, config):
            super().__init__(ctx, source_project, target_project, config)
            inside.set()
            time.sleep(0.3)
            self._create(config)

        async def instantiate(self, part):
            return None

    factory.register("part", "test-slow", SlowPartFactory)
    config = {"type": "test-slow", "name": "robot/wrist/visual/2", "orig_name": "robot/wrist/visual/2"}
    parts, failures = [], []

    def materialize(wait):
        if wait:
            inside.wait(5)
        try:
            parts.append(one_part.materialize_part_by_config(dict(config)))
        except Exception as e:  # pylint: disable=broad-except
            failures.append(e)

    try:
        threads = [threading.Thread(target=materialize, args=(wait,)) for wait in (False, True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        del factory.all["part"]["test-slow"]

    assert failures == []
    assert len(parts) == 2
    assert parts[0] is not None
    assert parts[1] is parts[0]


def test_materializing_a_part_does_not_deadlock_against_a_lookup(tmp_path):
    """Materializing a derived part takes one lock, so it cannot invert an order.

    'get_object' holds the package lock while it takes the part's own lock.
    Anything that held the part lock while registering - 'register_object' takes
    the package lock - would be the opposite order on the same two locks, and
    two threads resolving parts of one package at once would hang. So the
    collision is caught rather than prevented, and this holds the two paths
    against each other to say so.
    """
    inside = threading.Event()

    class SlowPartFactory(part_factory.PartFactory):
        def __init__(self, ctx, source_project, target_project, config):
            super().__init__(ctx, source_project, target_project, config)
            inside.set()
            time.sleep(0.3)
            self._create(config)

        async def instantiate(self, part):
            return None

    factory.register("part", "test-slow", SlowPartFactory)
    write_package(
        tmp_path,
        "",
        {"name": "//test", "parts": {"widget": {"type": "test-null"}}},
    )
    project = pc.Context(str(tmp_path)).get_project("//test")
    config = {"type": "test-slow", "name": "robot/forearm", "orig_name": "robot/forearm"}
    done, failures = [], []

    def materialize():
        try:
            done.append(project.materialize_part_by_config(dict(config)))
        except Exception as e:  # pylint: disable=broad-except
            failures.append(e)

    def look_up():
        # The same name, which is what makes the two orders meet: while the
        # other thread is inside the factory, 'get_object' takes the package
        # lock and then this part's lock, and holds the package lock until it
        # has it. The package does not declare the name, so this hands back
        # None - reaching the lock is the whole of what it is here to do.
        inside.wait(5)
        try:
            done.append(project.get_part("robot/forearm", quiet=True))
        except Exception as e:  # pylint: disable=broad-except
            failures.append(e)

    try:
        # Daemons, so that a regression fails this assertion rather than hanging
        # the whole run at interpreter exit waiting for two blocked threads.
        threads = [
            threading.Thread(target=materialize, daemon=True),
            threading.Thread(target=look_up, daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            # Generous, but finite: a deadlock here is the defect under test.
            thread.join(20)
        assert not any(thread.is_alive() for thread in threads), "materializing a part deadlocked against a lookup"
    finally:
        del factory.all["part"]["test-slow"]

    assert failures == []
    # The materializing thread got its part; the lookup may hand back either
    # that part or None, depending on which side of the registration it landed.
    assert done[0] is not None or done[1] is not None


def test_two_threads_asking_for_one_instance_do_not_deadlock(tmp_path):
    """Asking for an object releases the package lock before taking the object's.

    An instance is created on demand - it is what an enrich resolves to, and
    nothing declares it - and creating it registers it, which takes the package
    lock ('register_object'). A thread that held the package lock while waiting
    for the instance's own lock would be holding the half the creating thread
    still needs, and the two would wait on each other. Two threads asking one
    package for the same instance is all it takes, which is two enriches with
    the same 'with:' resolving at once.
    """
    inside = threading.Event()

    class SlowPartFactory(part_factory.PartFactory):
        def __init__(self, ctx, source_project, target_project, config):
            super().__init__(ctx, source_project, target_project, config)
            if ";" in config["name"]:
                inside.set()
                # Wide enough for the other thread to reach the instance's lock
                # while this one is still short of registering.
                time.sleep(0.3)
            self._create(config)

        async def instantiate(self, part):
            return None

    factory.register("part", "test-slow", SlowPartFactory)
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {"widget": {"type": "test-slow", "parameters": {"width": {"type": "float", "default": 3.0}}}},
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//test")
    found, failures = [], []

    def ask(wait_first):
        try:
            if wait_first:
                inside.wait(5)
            found.append(project.get_part("widget;width=5.0"))
        except Exception as e:  # pylint: disable=broad-except
            failures.append(e)

    try:
        # Daemons, so that a regression fails this assertion rather than hanging
        # the run at interpreter exit on two blocked threads.
        threads = [
            threading.Thread(target=ask, args=(False,), daemon=True),
            threading.Thread(target=ask, args=(True,), daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        assert not any(thread.is_alive() for thread in threads), "two lookups of one instance deadlocked"
    finally:
        del factory.all["part"]["test-slow"]

    assert failures == []
    # One instance, handed to both: the second look under the instance's own
    # lock is what keeps the loser from building a second one.
    assert len(found) == 2
    assert found[0] is not None
    assert found[0] is found[1]


def test_an_alias_that_collides_costs_the_alias_and_nothing_else(tmp_path):
    """An 'aliases:' entry naming a part the package also declares in its own right.

    Two declarations, one name: the second one used to win silently, which
    meant 'box' was whichever of them the package happened to load last.
    """
    write_package(
        tmp_path,
        "",
        {
            "name": "//test",
            "parts": {
                "cube": {"type": "test-null", "aliases": ["box"]},
                "box": {"type": "test-null"},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//test")

    # 'cube' is declared first, so its alias takes the name and keeps it.
    assert sorted(project.parts) == ["box", "cube"]
    assert project.parts["box"].config["type"] == "alias"
    assert "already has a part named 'box'" in project.get_broken_object_reason("part", "box")
    # The part whose 'aliases' claimed the name is unaffected by the clash.
    assert project.get_broken_object_reason("part", "cube") is None
