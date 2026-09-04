#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every file an object is declared by is a Jinja2 template, not only the ASSY one.

An ASSY file has always been rendered before it is parsed, which is what lets
one file describe a family of assemblies. A URDF, a Gazebo world and an MJCF
model are declared exactly the same way and had not been, so a package could
parameterize one kind of arrangement and not the other three. They share the
implementation now ('AssemblyFactoryFile'), and these are the properties that
sharing has to keep.

The rendered file goes into PartCAD's own state directory rather than beside the
original -- rendering is derived data, and instantiating an object must not put
files in the user's source tree -- so what the file *references* has to keep
resolving against the directory the package declared it in. That is the property
the readers are handed 'base_dir' for, and the one this is really about.
"""

import os

import pytest

import partcad as pc

MJCF = '<mujoco model="{{ name }}"><worldbody><body name="{{ param_body }}"/></worldbody></mujoco>'


@pytest.fixture
def package(tmp_path):
    """A package declaring one MJCF file, with and without parameters."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "plain.xml").write_text('<mujoco model="plain"><worldbody/></mujoco>', encoding="utf-8")
    (root / "template.xml").write_text(MJCF, encoding="utf-8")
    (root / "partcad.yaml").write_text(
        "name: //t\n"
        "scenes:\n"
        "  plain:\n    type: mjcf\n    path: plain.xml\n"
        "  templated:\n"
        "    type: mjcf\n"
        "    path: template.xml\n"
        "    parameters:\n"
        "      body:\n        type: string\n        default: brick\n",
        encoding="utf-8",
    )
    return pc.Context(str(root)).get_project("//")


def factory_of(project, name, params=None):
    return project.get_scene(name, params).mjcf_factory


def test_a_file_with_no_template_in_it_is_the_file_itself(package):
    """The usual case: a plain URDF stays the file the package points at."""
    factory = factory_of(package, "plain")
    assert factory.rendered_source() == factory.path


def test_a_template_is_rendered_with_the_parameter_values(package):
    factory = factory_of(package, "templated")

    path = factory.rendered_source()

    assert path != factory.path
    rendered = open(path, encoding="utf-8").read()
    assert 'name="brick"' in rendered
    # 'name' is the object's, exactly as it is in an ASSY file.
    assert 'model="templated"' in rendered


def test_two_instances_of_one_template_do_not_overwrite_each_other(package):
    first = factory_of(package, "templated", {"body": "brick"}).rendered_source()
    second = factory_of(package, "templated", {"body": "beam"}).rendered_source()

    assert first != second
    assert 'name="brick"' in open(first, encoding="utf-8").read()
    assert 'name="beam"' in open(second, encoding="utf-8").read()


def test_the_rendered_file_is_not_written_into_the_package(package):
    """Rendering is derived data; a `git status` after an inspect stays clean."""
    factory = factory_of(package, "templated")

    path = factory.rendered_source()

    assert not path.startswith(os.path.abspath(package.config_dir) + os.sep)


def test_a_template_that_will_not_render_names_the_file_it_is_in(package, tmp_path):
    factory = factory_of(package, "templated")
    open(factory.path, "w", encoding="utf-8").write("{% for %}")

    with pytest.raises(Exception, match="failed to render the template"):
        factory.rendered_source()


def test_the_reader_is_told_where_the_file_was_declared(package):
    """So a mesh named relative to the source still resolves after rendering."""
    import asyncio

    factory = factory_of(package, "templated")
    seen = {}

    async def capture(command, request):
        seen.update(pc.shape_envelope.deserialize(request))
        return 0, pc.shape_envelope.serialize({"success": True, "root": {"links": [], "parts": []}}), ""

    class Runtime:
        async def ensure_async(self, _requirement):
            return None

        async def run_async(self, command, request):
            return await capture(command, request)

    factory.ctx.get_python_runtime = lambda *args, **kwargs: Runtime()
    asyncio.run(factory._read_async())

    assert seen["base_dir"] == os.path.dirname(os.path.abspath(factory.path))
    assert seen["mjcf_file"] != os.path.abspath(factory.path)
