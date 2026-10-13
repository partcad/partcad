#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The version every wrapper and plugin reports, and the keys it reaches.

A script states 'CACHE_VERSION = <int>' and everything it produces is keyed on
it: the shapes a wrapper or a repository plugin builds, the verdicts a test's
wrapper reaches, the analyses, routes and simulations an implementation
writes. These hold the reading of the number, its reaching each kind of key,
and every script and factory PartCAD ships to saying it.
"""

import ast
import asyncio
import os
import re

import pytest
import yaml

import partcad as pc
from partcad import code_version, shape_factory, wrapper
from partcad.cache_hash import CacheHash
from partcad.part_factory_wrapper import PartFactoryWrapper
from partcad.project_external_repository import ProjectExternalRepository
from partcad.test.test import Test

_SRC = os.path.dirname(os.path.abspath(pc.__file__))


# --------------------------------------------------------------------------- #
# Reading it                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, version",
    [
        ("CACHE_VERSION = 3\n", 3),
        ("import os\n\nCACHE_VERSION: int = 4\n", 4),
        ("x = 1\n", 0),
        # A typo, not a version.
        ("CACHE_VERSION = True\n", 0),
        ("CACHE_VERSION = 1 + 1\n", 0),
        # Only the module's own: a local of the same name says nothing.
        ("def f():\n    CACHE_VERSION = 7\n", 0),
        ("this is not python(\n", 0),
    ],
)
def test_a_python_script_states_it_at_the_top_level(tmp_path, text, version):
    script = tmp_path / "script.py"
    script.write_text(text)
    assert code_version.declared(str(script)) == version


def test_a_script_is_parsed_and_never_run(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("raise SystemExit('never')\n\nCACHE_VERSION = 2\n")
    assert code_version.declared(str(script)) == 2


@pytest.mark.parametrize(
    "text, version",
    [
        ("export const CACHE_VERSION = 5;\n", 5),
        ("import x from './x.mjs';\nconst CACHE_VERSION = 6 // a comment\n", 6),
        ("const OTHER = 1;\n", 0),
    ],
)
def test_a_javascript_script_states_it_as_a_top_level_constant(tmp_path, text, version):
    script = tmp_path / "script.mjs"
    script.write_text(text)
    assert code_version.declared(str(script)) == version


def test_a_script_that_is_not_there_states_nothing(tmp_path):
    assert code_version.declared(str(tmp_path / "missing.py")) == 0
    assert code_version.declared(None) == 0


def test_an_edited_script_is_read_again(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("CACHE_VERSION = 1\n")
    assert code_version.declared(str(script)) == 1
    script.write_text("CACHE_VERSION = 2\n# longer, so the size moves as well as the time\n")
    assert code_version.declared(str(script)) == 2


def test_the_key_leaves_out_what_states_nothing():
    assert code_version.key([("b.py", 2), ("a.py", 1), ("c.py", 0)]) == "a.py@1;b.py@2"
    # Nothing stated is no key at all, so a key it is added to stays as it was.
    assert code_version.key([("a.py", 0)]) is None
    assert code_version.key([]) is None


# --------------------------------------------------------------------------- #
# Everything PartCAD ships states it                                          #
# --------------------------------------------------------------------------- #


def _sources():
    for root, _dirs, files in os.walk(_SRC):
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _wrappers_called(path):
    """The literal names 'wrapper.get()' is called with in the module at 'path'."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "wrapper"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
    return names


def _all_wrappers_called():
    called = set()
    for path in _sources():
        called |= _wrappers_called(path)
    return called


def test_every_wrapper_partcad_runs_states_a_version():
    called = _all_wrappers_called()
    assert "step.py" in called and "part_type.py" in called  # the scan sees them
    for name in sorted(called):
        assert code_version.wrapper(name) >= 1, "%s states no CACHE_VERSION" % wrapper.get(name)


def test_every_implementation_partcad_ships_states_a_version():
    builtin = os.path.join(_SRC, "builtin")
    scripts = []
    for root, _dirs, files in os.walk(builtin):
        if "partcad.yaml" not in files:
            continue
        with open(os.path.join(root, "partcad.yaml"), encoding="utf-8") as f:
            text = f.read()
        for path in re.findall(r"^\s+path:\s*(\S+\.(?:py|mjs))\s*$", text, re.MULTILINE):
            scripts.append(os.path.join(root, path))
    assert len(scripts) >= 10  # every export, render, import and route type
    for script in scripts:
        assert code_version.declared(script) >= 1, "%s states no CACHE_VERSION" % script


def _factory_classes(module):
    return [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, shape_factory.ShapeFactory)
        and value.__module__ == module.__name__
    ]


def test_every_factory_names_the_wrappers_it_runs():
    """A wrapper a factory runs and does not name is one whose version no key carries."""
    import importlib

    checked = 0
    for path in sorted(_sources()):
        name = os.path.basename(path)[: -len(".py")]
        if not re.match(r"^(part|sketch|assembly)_factory_", name):
            continue
        called = _wrappers_called(path)
        if not called:
            continue
        module = importlib.import_module("partcad." + name)
        named = set()
        for cls in _factory_classes(module):
            named |= set(cls.WRAPPERS)
        assert called <= named, "%s runs %s but names %s" % (name, sorted(called), sorted(named))
        checked += 1
    assert checked >= 15


def test_every_test_names_the_wrappers_it_runs():
    """The verdict cache is keyed on them; see 'Test.WRAPPERS'."""
    import importlib

    reaches = {
        "get_solidity_async": "solidity.py",
        "get_interference_async": "interference.py",
        "manufacturability_analysis": "manufacturability.py",
    }
    test_dir = os.path.join(_SRC, "test")
    checked = 0
    for name in sorted(os.listdir(test_dir)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(test_dir, name), encoding="utf-8") as f:
            text = f.read()
        needed = {wrapper_name for call, wrapper_name in reaches.items() if call in text}
        if not needed:
            continue
        module = importlib.import_module("partcad.test." + name[: -len(".py")])
        classes = [
            value
            for value in vars(module).values()
            if isinstance(value, type) and issubclass(value, Test) and value.__module__ == module.__name__
        ]
        assert classes, name
        for cls in classes:
            assert needed <= set(cls.WRAPPERS), "%s.%s runs %s" % (name, cls.__name__, sorted(needed))
            checked += 1
    assert checked >= 8


# --------------------------------------------------------------------------- #
# A shape's key                                                               #
# --------------------------------------------------------------------------- #


class _Project:
    name = "//pkg"


def _factory(cls=shape_factory.ShapeFactory, wrappers=(), config=None, project=None):
    factory = cls.__new__(cls)
    factory.WRAPPERS = tuple(wrappers)
    factory.config = config if config is not None else {}
    factory.project = project or _Project()
    return factory


def test_a_shape_is_keyed_on_the_wrappers_its_factory_runs(monkeypatch):
    versions = {"step.py": 1, "transform.py": 1}
    monkeypatch.setattr(code_version, "wrapper", lambda name: versions[name])

    assert _factory(wrappers=["step.py"]).code_versions() == "step.py@1"
    # Moved or scaled on the way out: the wrapper that does that, too.
    assert _factory(wrappers=["step.py"], config={"offset": [1, 0, 0]}).code_versions() == "step.py@1;transform.py@1"
    # A factory that runs nothing keys as it always did.
    assert _factory().code_versions() is None

    versions["step.py"] = 2
    assert _factory(wrappers=["step.py"]).code_versions() == "step.py@2"


def test_an_object_a_plugin_serves_is_keyed_on_the_plugin_s_version(monkeypatch):
    monkeypatch.setattr(code_version, "wrapper", lambda name: 1)

    class Served(_Project):
        plugin_ref = "//pub/universe/lego:ldraw_repo"
        plugin_cache_version = 16

    assert _factory(wrappers=["part_type.py"], project=Served()).code_versions() == (
        "//pub/universe/lego:ldraw_repo@16;part_type.py@1"
    )


def test_the_versions_move_the_shape_s_hash(monkeypatch):
    class _Shape:
        def __init__(self):
            self.hash = CacheHash("//pkg:part", cache=True)

        def set_environment_cache_key(self, key):
            self.hash.add_string(key)

        def add_code_versions(self, versions):
            pc.shape.Shape.add_code_versions(self, versions)

    def hashed(version):
        monkeypatch.setattr(code_version, "wrapper", lambda name: version)
        shape = _Shape()
        _factory(wrappers=["step.py"]).apply_environment_cache_key(shape)
        return shape.hash.get()

    assert hashed(1) == hashed(1)
    assert hashed(1) != hashed(2)


def test_a_part_a_plugin_serves_is_keyed_on_the_plugin_s_version_end_to_end(tmp_path):
    ctx = pc.Context("examples")
    served = {
        "objects/part/box": {"type": "step", "path": "box.step"},
        "objects/part": {"box": {"type": "step", "path": "box.step"}},
    }
    (tmp_path / "box.step").write_text("ISO-10303-21; box")

    def key(version):
        repo = ProjectExternalRepository(
            ctx, "//ext", str(tmp_path), plugin_ref="//pkg:repo", cache_version=version, config_obj={}
        )

        class Fake:
            async def get_data(self, key):
                return served.get(key)

        repo._repository = Fake()
        part = repo.get_part("box", quiet=True)
        return asyncio.run(part.get_cache_key_async())

    assert key(16) == key(16)
    assert key(16) != key(17)


# --------------------------------------------------------------------------- #
# A partType's own script                                                     #
# --------------------------------------------------------------------------- #


def _part_type_factory(part_project, pt_project, ref="//types:thing"):
    factory = PartFactoryWrapper.__new__(PartFactoryWrapper)
    factory.part_type_ref = ref
    factory.part_type_package, factory.part_type_name = ref.split(":")
    factory.project = part_project

    class Ctx:
        def get_project(self, name):
            return pt_project if name == factory.part_type_package else None

    factory.ctx = Ctx()
    return factory


def test_a_local_part_type_reports_the_version_its_script_states(tmp_path):
    (tmp_path / "thing.py").write_text("CACHE_VERSION = 3\n")

    class Types:
        name = "//types"
        config_dir = str(tmp_path)

        def get_part_type_config(self, name):
            return {} if name == "thing" else None

    assert _part_type_factory(_Project(), Types())._part_type_versions() == "//types:thing@3"


def test_a_part_type_a_plugin_serves_reports_the_plugin_s_version():
    class Served:
        name = "//types"
        plugin_ref = "//types:repo"
        plugin_cache_version = 5

    assert _part_type_factory(_Project(), Served())._part_type_versions() == "//types:repo@5"
    # The part is served by the same plugin: its key has the version already.
    assert _part_type_factory(Served(), Served())._part_type_versions() is None


# --------------------------------------------------------------------------- #
# A test's verdict                                                            #
# --------------------------------------------------------------------------- #


class _Cache:
    def __init__(self):
        self.keys = []

    async def read_data_async(self, shape_hash, keys):
        self.keys.extend(keys)
        return {k: [] for k in keys}

    async def write_data_async(self, shape_hash, data):
        pass


class _Shape:
    hash = "geometry"
    is_manufacturable = True
    name = "part"
    project_name = "//pkg"

    def get_cacheable(self):
        return True


class _SolidTest(Test):
    WRAPPERS = ("solidity.py",)

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        return self.TEST_PASSED


def test_a_verdict_is_keyed_on_the_wrappers_the_test_runs(monkeypatch):
    def verdict_key(version):
        monkeypatch.setattr(code_version, "wrapper", lambda name: version)

        class Ctx:
            cache_tests = _Cache()

        ctx = Ctx()
        asyncio.run(_SolidTest("solidity").test_cached([], ctx, _Shape()))
        return ctx.cache_tests.keys[0]

    assert verdict_key(1).endswith(".code=solidity.py@1")
    assert verdict_key(1) != verdict_key(2)


def test_the_plugin_reader_is_the_shared_one(tmp_path):
    """A repository plugin's version is read the way every other script's is."""
    from partcad import project_factory_external

    script = tmp_path / "repo.py"
    script.write_text("CACHE_VERSION = 9\n")
    assert project_factory_external._read_declared_cache_version(str(script)) == 9
    assert project_factory_external.CACHE_VERSION_NAME == code_version.NAME


def test_builtin_partcad_yaml_paths_parse():
    # The implementation scan above reads 'path:' lines; make sure it reads
    # every one the YAML has, so a script added in another spelling is noticed.
    builtin = os.path.join(_SRC, "builtin")
    for root, _dirs, files in os.walk(builtin):
        if "partcad.yaml" not in files:
            continue
        with open(os.path.join(root, "partcad.yaml"), encoding="utf-8") as f:
            text = f.read()
        data = yaml.safe_load(text) or {}
        declared = set()
        for section in data.values():
            if isinstance(section, dict):
                for entry in section.values():
                    if isinstance(entry, dict) and str(entry.get("path", "")).endswith((".py", ".mjs")):
                        declared.add(entry["path"])
        scanned = set(re.findall(r"^\s+path:\s*(\S+\.(?:py|mjs))\s*$", text, re.MULTILINE))
        assert declared <= scanned, root
