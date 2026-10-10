#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A ':' in a parameter value, from a declaration to the object it names.

'<package>:<object>;<param>=<value>' is split at the first ':', and only at a
':' before the parameters (see 'partcad_utils.utils.split_resource_path' and
'tests/partcad_utils/test_resource_path.py'). What used to happen to such a
name depended on who read it:
  * 'resolve_resource_path' split on every ':' and raised "too many values to
    unpack";
  * 'reference.split' and 'material.owner_package' split on the last one, and
    named an object after the tail of the value.

The first is how an enrich of a scene failed when it set the scene's medium to
a material ('//pub/std/materials:water'). None of this needs a CAD kernel: the
types registered here build nothing.
"""

import asyncio
import types

import pytest
import yaml

import partcad as pc
from partcad import assembly_factory, factory, material, part_factory, reference
from partcad.scene_factory import SceneFactoryMixin

WATER = "//pub/std/materials:water"


class NullPartFactory(part_factory.PartFactory):
    """A part type that registers a part and builds nothing."""

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)
        self._create(config)

    async def instantiate(self, part):
        return None


class NullSceneFactory(SceneFactoryMixin, assembly_factory.AssemblyFactory):
    """A scene type that registers a scene and assembles nothing."""

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)
        self._create(config)

    def instantiate(self, scene):
        return None


@pytest.fixture(autouse=True)
def null_types():
    saved = {kind: factory.all[kind].get("test-null") for kind in ("part", "scene")}
    factory.register("part", "test-null", NullPartFactory)
    factory.register("scene", "test-null", NullSceneFactory)
    try:
        yield
    finally:
        for kind, previous in saved.items():
            if previous is None:
                del factory.all[kind]["test-null"]
            else:
                factory.register(kind, "test-null", previous)


@pytest.fixture
def package(tmp_path):
    """A scene with a medium and a part with a URL, each enriched with a ':' in the value."""
    config = {
        "name": "//test",
        "parts": {
            "plate": {"type": "test-null", "parameters": {"url": {"type": "string", "default": "none"}}},
            "plate_online": {"type": "enrich", "source": "plate", "with": {"url": "https://example.com/a:b"}},
        },
        "scenes": {
            "room": {"type": "test-null", "parameters": {"medium": {"type": "string", "default": "air"}}},
            "pool": {"type": "enrich", "source": "room", "with": {"medium": WATER}},
            # The same instance, asked for by name rather than through 'with'.
            "pool_by_name": {"type": "alias", "source": "room;medium=" + WATER},
        },
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    return pc.Context(str(tmp_path)).get_project("//test")


def prepared(shape):
    asyncio.run(shape.prepare_async())
    return shape


def medium_of(scene):
    return scene.config["parameters"]["medium"]["default"]


#
# End to end
#


def test_an_enrich_of_a_scene_takes_a_material_reference_as_a_value(package):
    pool = package.get_scene("pool")
    assert pool is not None, "the enrich was not created"
    prepared(pool)

    assert pool.config["source"] == "//test:room;medium=" + WATER
    assert medium_of(pool) == WATER
    # The scene it enriches keeps its own value.
    assert medium_of(package.get_scene("room")) == "air"


def test_a_reference_can_name_that_instance_itself(package):
    """An alias written with the parameters in its 'source', where the value used to be cut off at its ':'."""
    alias = prepared(package.get_scene("pool_by_name"))
    assert alias.config["source_resolved"] == "//test:room;medium=" + WATER

    instance = package.get_scene("room;medium=" + WATER)
    assert instance is not None
    assert medium_of(instance) == WATER


def test_an_enrich_of_a_part_takes_a_url_as_a_value(package):
    plate = prepared(package.get_part("plate_online"))
    assert plate.config["source"] == "//test:plate;url=https://example.com/a:b"
    assert plate.config["parameters"]["url"]["default"] == "https://example.com/a:b"


#
# The readers that split from the right
#


@pytest.mark.parametrize(
    "source, package_name, object_name",
    [
        ("//pkg:obj", "//pkg", "obj"),
        ("//pkg:obj;a=x:y", "//pkg", "obj;a=x:y"),
        ("//pkg:room;medium=" + WATER, "//pkg", "room;medium=" + WATER),
        ("//pkg:file:inner", "//pkg", "file:inner"),
        ("obj", "", "obj"),
    ],
)
def test_a_qualified_reference_is_split_at_its_first_colon(source, package_name, object_name):
    assert reference.split(source) == (package_name, object_name)


@pytest.mark.parametrize(
    "shape_name, package_name",
    [
        ("//pkg:part", "//pkg"),
        ("//pkg:part;url=https://example.com/a:b", "//pkg"),
        ("//pkg:room;medium=" + WATER, "//pkg"),
        ("//pkg:file:inner", "//pkg"),
        ("//pkg", "//pkg"),
    ],
)
def test_a_shape_belongs_to_the_package_before_its_first_colon(shape_name, package_name):
    assert material.owner_package(shape_name) == package_name


#
# The daemon's reading of which packages a request is about
#


def test_a_request_for_an_unqualified_instance_reloads_the_current_package():
    from partcad_service_json_rpc.core import operations

    asked = []
    ctx = types.SimpleNamespace(resolve_package_path=lambda package: asked.append(package) or package)
    targets, _ = operations._config_check_targets(ctx, {"package": "//here", "object": "room;medium=" + WATER})
    assert targets == ["//here"]
    targets, _ = operations._config_check_targets(ctx, {"package": "//here", "object": "//other:room;medium=" + WATER})
    assert targets == ["//other"]
