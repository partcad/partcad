#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The environment a shape is produced in, as part of its cache key.

A shape produced by a sandboxed interpreter belongs to the interpreter and the
dependency versions that produced it. None of that is in the shape's own
configuration, so without this a package that moves to another interpreter or
another CAD library is served what the previous one built.

This covers every kind of shape, not only parts: a sketch is rendered the same
way, and so is a part read from a CAD file - the importer that turns a STEP file
into a BREP is itself a script in a sandbox.
"""

import pytest

import partcad as pc
from partcad import sandbox_versions
from partcad.runtime_javascript import JavaScriptRuntime
from partcad.runtime_python import PythonRuntime
from partcad.user_config import UserConfig
from partcad_utils import telemetry


@pytest.fixture
def config():
    user_config = UserConfig()
    user_config.javascript_sandbox = "none"
    user_config.python_sandbox = "none"
    return user_config


#
# The key itself
#


def test_the_key_names_the_interpreter_and_its_dependencies():
    key = sandbox_versions.environment_cache_key("python", "3.11", ["b==2", "a==1"])

    assert key.startswith("python==3.11;")
    assert "a==1" in key
    assert "b==2" in key


def test_the_key_is_the_set_not_the_order():
    """What an environment holds decides the key, not how it was asked for."""
    assert sandbox_versions.environment_cache_key("python", "3.11", ["a==1", "b==2"]) == (
        sandbox_versions.environment_cache_key("python", "3.11", ["b==2", "a==1"])
    )


def test_the_key_ignores_duplicates_and_blanks():
    assert sandbox_versions.environment_cache_key("nodejs", "22", ["a@1", "a@1", "", "  ", None]) == (
        sandbox_versions.environment_cache_key("nodejs", "22", ["a@1"])
    )


# --------------------------------------------------------------------------- #
# The image, where the sandbox was built in one                                #
# --------------------------------------------------------------------------- #


def test_two_images_are_two_environments():
    """An image is named precisely for what pip cannot install.

    Same interpreter, same wheels, different native stack underneath -- a
    different OpenCASCADE, a different solver. A shape built in one is not the
    shape the other builds, so keying them alike hands back the wrong model
    when a package changes its 'dockerImage'.
    """
    one = sandbox_versions.environment_cache_key("python", "3.11", ["a==1"], image="ghcr.io/x/a:1")
    two = sandbox_versions.environment_cache_key("python", "3.11", ["a==1"], image="ghcr.io/x/b:1")

    assert one != two
    assert "ghcr.io/x/a:1" in one


def test_no_image_keys_exactly_as_it_always_did():
    """Every cached shape on every machine was built without one.

    A key that changed shape for everybody would invalidate all of them, to
    record something that is not true of any of them -- so the image is
    appended only when there is one.
    """
    assert sandbox_versions.environment_cache_key("python", "3.11", ["a==1"]) == "python==3.11;a==1"
    assert sandbox_versions.environment_cache_key("python", "3.11", ["a==1"], image=None) == "python==3.11;a==1"
    assert sandbox_versions.environment_cache_key("python", "3.11", ["a==1"], image="") == "python==3.11;a==1"


def test_an_image_is_not_mistaken_for_a_requirement():
    """It is appended under its own name, not folded into the sorted set."""
    key = sandbox_versions.environment_cache_key("python", "3.11", ["a==1"], image="ghcr.io/x/a:1")
    assert key == "python==3.11;a==1;image=ghcr.io/x/a:1"


@pytest.mark.parametrize(
    "left, right",
    [
        # A different interpreter version
        (("python", "3.11", ["a==1"]), ("python", "3.12", ["a==1"])),
        # A different dependency version
        (("python", "3.11", ["a==1"]), ("python", "3.11", ["a==2"])),
        # One more dependency
        (("python", "3.11", ["a==1"]), ("python", "3.11", ["a==1", "b==2"])),
        # The same versions, another language
        (("python", "3.11", ["a==1"]), ("nodejs", "3.11", ["a==1"])),
    ],
)
def test_different_environments_key_differently(left, right):
    assert sandbox_versions.environment_cache_key(*left) != sandbox_versions.environment_cache_key(*right)


#
# What the factories put in it
#


def _part(tmp_path, config, partcad_yaml, filename, source="# empty\n"):
    (tmp_path / "partcad.yaml").write_text(partcad_yaml)
    (tmp_path / filename).write_text(source)
    return pc.Context(str(tmp_path), user_config=config).get_part("thing")


def test_a_python_part_keys_on_the_interpreter_and_the_cad_stack(tmp_path, config):
    part = _part(tmp_path, config, "parts:\n  thing:\n    type: build123d\n", "thing.py")

    assert part.environment_cache_key.startswith("python==")
    # The CAD stack is preinstalled into every sandbox and held to these
    # versions, so all of it is what produced the shape.
    for requirement in sandbox_versions.PINNED_REQUIREMENTS:
        assert requirement in part.environment_cache_key


def _package(tmp_path, name):
    """A directory of its own for one of two packages a test compares."""
    directory = tmp_path / name
    directory.mkdir()
    return directory


def _stamped(monkeypatch, image):
    """Every Python runtime the context hands back claims to run in 'image'.

    Stamped onto whatever runtime the context returns rather than by asking for
    a container one: what is under test is that the key does *not* read it, and
    starting a real container sandbox needs a daemon this suite does not assume.
    """
    real = pc.Context.get_python_runtime

    def stamped(self, *args, **kwargs):
        runtime = real(self, *args, **kwargs)
        runtime.image = image
        return runtime

    monkeypatch.setattr(pc.Context, "get_python_runtime", stamped)


@pytest.mark.parametrize(
    "image",
    [
        # PartCAD's own base image, as the 'docker' and 'remote' sandboxes run a
        # package that declares none: the release and the architecture are in
        # the tag, so keying on it would move every key on every release.
        "ghcr.io/partcad/partcad-container-python:0.8.166-py3.11-amd64",
        "ghcr.io/partcad/partcad-container-python:0.8.167-py3.11-arm64",
    ],
)
def test_the_sandbox_a_part_happened_to_run_in_is_not_in_its_key(tmp_path, config, monkeypatch, image):
    """Sandboxes are equivalent, so switching between them must find the same entries."""
    yaml = "parts:\n  thing:\n    type: build123d\n"
    on_conda = _part(_package(tmp_path, "a"), config, yaml, "thing.py")
    _stamped(monkeypatch, image)
    in_a_container = _part(_package(tmp_path, "b"), config, yaml, "thing.py")

    assert in_a_container.environment_cache_key == on_conda.environment_cache_key
    assert "image=" not in in_a_container.environment_cache_key


def test_a_python_part_keys_on_the_image_its_package_declares(tmp_path, config, monkeypatch):
    """A declaration, so the same string whichever sandbox ran it.

    A machine with no container runtime installs the requirements instead of
    pulling the image, and a 'docker' sandbox that could not pull it falls back
    to PartCAD's own; neither changes what the package said it needs.
    """
    yaml = "dockerImage: ghcr.io/x/a:1\nparts:\n  thing:\n    type: build123d\n"
    declared = _part(_package(tmp_path, "a"), config, yaml, "thing.py")
    _stamped(monkeypatch, "ghcr.io/partcad/partcad-container-python:0.8.166-py3.11-amd64")
    fell_back = _part(_package(tmp_path, "b"), config, yaml, "thing.py")

    assert declared.environment_cache_key.endswith(";image=ghcr.io/x/a:1")
    assert fell_back.environment_cache_key == declared.environment_cache_key


def test_a_part_naming_its_own_image_keys_on_it(tmp_path, config):
    part = _part(
        tmp_path,
        config,
        "parts:\n  thing:\n    type: build123d\n    dockerImage: ghcr.io/x/b:1\n",
        "thing.py",
    )
    assert part.environment_cache_key.endswith(";image=ghcr.io/x/b:1")


def test_a_sandbox_with_no_image_says_nothing_about_one(tmp_path, config):
    """Which is every sandbox that is not container-backed."""
    part = _part(tmp_path, config, "parts:\n  thing:\n    type: build123d\n", "thing.py")
    assert "image=" not in part.environment_cache_key


def test_a_python_part_keys_on_what_its_package_asks_for(tmp_path, config):
    part = _part(
        tmp_path,
        config,
        'pythonRequirements:\n  - "seaborn==0.13.2"\n\nparts:\n  thing:\n    type: build123d\n',
        "thing.py",
    )

    assert "seaborn==0.13.2" in part.environment_cache_key


def test_a_python_part_keys_on_what_it_asks_for_itself(tmp_path, config):
    part = _part(
        tmp_path,
        config,
        'parts:\n  thing:\n    type: build123d\n    pythonRequirements:\n      - "seaborn==0.13.2"\n',
        "thing.py",
    )

    assert "seaborn==0.13.2" in part.environment_cache_key


def test_a_python_part_keys_on_what_will_be_installed(tmp_path, config):
    """A requirement PartCAD overrides must not key as though it was honored.

    Asking for another CadQuery does not get you one - reconcile_requirement()
    holds the sandbox to the pinned stack - so the key has to say what the
    sandbox will actually hold.
    """
    part = _part(
        tmp_path,
        config,
        'parts:\n  thing:\n    type: cadquery\n    pythonRequirements:\n      - "cadquery==2.7.0"\n',
        "thing.py",
    )

    assert "cadquery==2.7.0" not in part.environment_cache_key
    assert sandbox_versions.CADQUERY in part.environment_cache_key


def test_a_javascript_part_keys_on_node_and_its_dependencies(tmp_path, config):
    part = _part(tmp_path, config, "parts:\n  thing:\n    type: chili3d\n", "thing.chili")

    assert part.environment_cache_key.startswith("nodejs==")
    assert sandbox_versions.CHILI3D in part.environment_cache_key
    assert sandbox_versions.HAPPY_DOM in part.environment_cache_key


def test_a_javascript_part_keys_on_the_node_it_asked_for_not_the_host_s(tmp_path, config, monkeypatch):
    """The 'none' sandbox runs whatever Node.js the host has; the key is the declaration.

    Otherwise one shape keys one way on a machine with Node.js 20 and another on
    one with 22 or on the conda sandbox, and every entry is private to a host.
    """
    monkeypatch.setattr("partcad.runtime_javascript_none.host_node_version", lambda _path: "17")
    part = _part(
        tmp_path,
        config,
        'javascriptVersion: "22.11"\nparts:\n  thing:\n    type: chili3d\n',
        "thing.chili",
    )

    assert part.environment_cache_key.startswith("nodejs==22;")


def test_a_javascript_part_keys_on_the_chili3d_it_chose(tmp_path, config):
    part = _part(
        tmp_path,
        config,
        'parts:\n  thing:\n    type: chili3d\n    chili3dVersion: "1.0.0"\n',
        "thing.chili",
    )

    assert "chili3d@1.0.0" in part.environment_cache_key
    assert sandbox_versions.CHILI3D not in part.environment_cache_key


def test_a_javascript_part_keys_on_what_it_asks_for_itself(tmp_path, config):
    part = _part(
        tmp_path,
        config,
        'parts:\n  thing:\n    type: chili3d\n    javascriptRequirements:\n      - "seedrandom@3.0.5"\n',
        "thing.chili",
    )

    assert "seedrandom@3.0.5" in part.environment_cache_key


@pytest.mark.parametrize(
    "part_type, extension",
    [("step", "step"), ("brep", "brep"), ("stl", "stl"), ("3mf", "3mf"), ("obj", "obj"), ("scad", "scad")],
)
def test_a_part_read_from_a_file_keys_on_its_importer(tmp_path, config, part_type, extension):
    """Reading a CAD file is itself a script in a sandbox, so it has one too.

    The interpreter is fixed per format rather than resolved from the package,
    which is what ShapeFactory.PYTHON_SANDBOX_VERSION expresses.
    """
    part = _part(
        tmp_path,
        config,
        "parts:\n  thing:\n    type: %s\n" % part_type,
        "thing." + extension,
    )

    assert part.environment_cache_key.startswith("python==")
    assert sandbox_versions.CADQUERY_OCP in part.environment_cache_key


def _sketch(tmp_path, config, partcad_yaml, filename, source="# empty\n"):
    (tmp_path / "partcad.yaml").write_text(partcad_yaml)
    (tmp_path / filename).write_text(source)
    return pc.Context(str(tmp_path), user_config=config).get_sketch("thing")


@pytest.mark.parametrize(
    "sketch_type, extension",
    [("cadquery", "py"), ("build123d", "py"), ("dxf", "dxf"), ("svg", "svg")],
)
def test_a_sketch_keys_on_its_environment(tmp_path, config, sketch_type, extension):
    """The whole point of rescoping this to Shape: sketches render too."""
    sketch = _sketch(
        tmp_path,
        config,
        "sketches:\n  thing:\n    type: %s\n" % sketch_type,
        "thing." + extension,
    )

    assert sketch.environment_cache_key.startswith("python==")
    assert sandbox_versions.CADQUERY_OCP in sketch.environment_cache_key


def test_a_sketch_keys_on_what_its_package_asks_for(tmp_path, config):
    sketch = _sketch(
        tmp_path,
        config,
        'pythonRequirements:\n  - "seaborn==0.13.2"\n\nsketches:\n  thing:\n    type: build123d\n',
        "thing.py",
    )

    assert "seaborn==0.13.2" in sketch.environment_cache_key


def test_a_basic_sketch_keys_on_its_environment(tmp_path, config):
    """Even the one built from parameters alone - it is built in a sandbox."""
    (tmp_path / "partcad.yaml").write_text(
        "sketches:\n  thing:\n    type: basic\n    circle: 5\n",
    )
    ctx = pc.Context(str(tmp_path), user_config=config)

    assert ctx.get_sketch("thing").environment_cache_key.startswith("python==")


def test_an_assembly_has_no_environment_of_its_own(tmp_path, config):
    """It is composed from shapes that each carry their own."""
    (tmp_path / "partcad.yaml").write_text(
        "assemblies:\n  thing:\n    type: assy\n",
    )
    (tmp_path / "thing.assy").write_text("links:\n")
    ctx = pc.Context(str(tmp_path), user_config=config)

    assert ctx.get_assembly("thing").environment_cache_key is None


#
# What it does to the hash
#


def _hash_for(tmp_path, config, name, partcad_yaml, filename):
    package = tmp_path / name
    package.mkdir()
    return _part(package, config, partcad_yaml, filename).hash.get()


def test_the_environment_moves_the_hash(tmp_path, config):
    template = 'chili3dVersion: "%s"\n\nparts:\n  thing:\n    type: chili3d\n'

    first = _hash_for(tmp_path, config, "first", template % "1.0.0", "thing.chili")
    second = _hash_for(tmp_path, config, "second", template % "1.0.1", "thing.chili")

    assert first != second


def test_an_unchanged_environment_keeps_the_hash(tmp_path, config):
    template = 'chili3dVersion: "1.0.0"\n\nparts:\n  thing:\n    type: chili3d\n'

    first = _hash_for(tmp_path, config, "first", template, "thing.chili")
    second = _hash_for(tmp_path, config, "second", template, "thing.chili")

    assert first == second


#
# How the helpers behind it have to be declared
#


def test_the_requirement_helpers_are_not_class_attributes():
    """They have to be module-level functions, not static methods.

    Both runtimes are decorated with '@telemetry.instrument()', which rewrites
    every callable in the class body - and a 'staticmethod' object is callable,
    so it comes back out as a plain function and turns into a bound method the
    moment it is reached through an instance. The result is a TypeError about
    argument counts from a call that reads as correct.
    """
    for cls in (PythonRuntime, JavaScriptRuntime):
        assert not hasattr(cls, "package_requirements"), cls.__name__
        assert not hasattr(cls, "shape_requirements"), cls.__name__


def test_instrument_unwraps_a_static_method():
    """The behavior the rule above exists for, pinned so it stays visible."""

    @telemetry.instrument()
    class Example:
        @staticmethod
        def helper(value):
            return value

    # The staticmethod is gone from the class body, so the attribute binds like
    # any other function and an instance call passes 'self' as its first
    # argument. What that then raises varies with the argument types, which is
    # part of why the symptom is confusing; that it no longer descriptor-binds
    # correctly is the fact worth pinning.
    assert not isinstance(Example.__dict__["helper"], staticmethod)
