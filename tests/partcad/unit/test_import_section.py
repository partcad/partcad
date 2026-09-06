#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the 'import:' section: object types a package supplies.

What is under test here is the *mechanism*, not any one format. The three
readers PartCAD ships have suites of their own ('test_assembly_urdf.py',
'test_mjcf.py', 'test_world.py') and they exercise the same path from the other
end; these are about a package declaring a reader PartCAD has never heard of and
having it work.
"""

import asyncio
import os
import textwrap

import pytest
import yaml

import partcad as pc
from partcad import output

from ..conftest import builtin_import_declaration

# A reader that parses nothing. It is handed a file and reports one part read
# from a STL that really exists, which is all the core needs to build a tree -
# the point being that no XML and no format knowledge is involved in the
# machinery around it.
TRIVIAL_READER = """
def process(path, request):
    return {
        "success": True,
        "root": {
            "type": "assembly",
            "name": "root",
            "links": [
                {
                    "type": "part",
                    "name": "only",
                    "part_file": request["mesh"],
                    "part_type": "stl",
                }
            ],
        },
        "info": {"Greeting": request["greeting"]},
        "warnings": ["nothing was actually read"],
        "dropped": {"everything": 1},
    }
"""

CUBE = os.path.abspath(os.path.join("examples", "produce_part_stl", "cube.stl"))


def write_package(root, *, kinds, section, extra_type_fields="", object_fields=""):
    """A package declaring its own reader, and one object that uses it."""
    (root / "reader.py").write_text(TRIVIAL_READER, encoding="utf-8")
    (root / "thing.demo").write_text("nothing here is parsed\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(
        textwrap.dedent("""
            name: //p
            import:
              demo:
                path: reader.py
                extension: demo
                kinds: %(kinds)s
                noun: doodad
                greeting: hello
                mesh: %(mesh)s
                dropped:
                  everything: "the entire file"
            %(extra)s
            %(section)s:
              thing:
                type: demo
                path: thing.demo
            %(object_fields)s
            """)
        % {
            "kinds": kinds,
            "mesh": CUBE.replace("\\", "/"),
            "section": section,
            "extra": extra_type_fields,
            "object_fields": object_fields,
        },
        encoding="utf-8",
    )
    return pc.Context(str(root))


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def test_a_package_can_declare_an_object_type_of_its_own(package):
    """The whole point: a format PartCAD has never heard of, read by a package."""
    ctx = write_package(package, kinds="[assembly]", section="assemblies")
    assembly = ctx.get_assembly("//:thing")
    assert assembly is not None
    # Building is what runs the reader; holding the object does not.
    asyncio.run(assembly.do_instantiate())

    assert len(assembly.children) == 1
    # The part the reader named is registered under '<object>/<node>', the way
    # every imported object's parts are.
    assert ctx.get_part("//:thing/only") is not None


def test_the_same_reader_produces_a_scene_when_that_is_what_was_declared(package):
    """One reader, two kinds - the section is what says which."""
    ctx = write_package(package, kinds="[assembly, scene]", section="scenes")
    scene = ctx.get_scene("//:thing")
    assert scene is not None
    asyncio.run(scene.do_instantiate())

    assert len(scene.children) == 1


def test_a_reader_that_only_reads_assemblies_refuses_to_be_a_scene(package):
    """'kinds:' is a claim the core holds the declaration to."""
    ctx = write_package(package, kinds="[assembly]", section="scenes")

    assert ctx.get_project("//").get_scene("thing", quiet=True) is None


def test_an_undeclared_type_is_still_an_unknown_type(package):
    """Nothing declares 'nonesuch', so the object is a bad declaration."""
    root = package
    (root / "partcad.yaml").write_text(
        "name: //p\nassemblies:\n  thing:\n    type: nonesuch\n    path: thing.demo\n",
        encoding="utf-8",
    )
    ctx = pc.Context(str(root))

    assert ctx.get_project("//").get_assembly("thing", quiet=True) is None


def test_the_declaration_words_what_the_reader_counted(package):
    """The reader counts, the declaration names, and 'pc info' shows the result."""
    ctx = write_package(package, kinds="[assembly]", section="assemblies")
    assembly = ctx.get_assembly("//:thing")
    info = assembly.info()

    assert info["Dropped"] == {"the entire file": 1}
    # And what the reader chose to say about the file itself, in its own words.
    assert info["Greeting"] == "hello"


def test_a_parameter_of_the_declaration_reaches_the_reader(package):
    """Everything that is not an implementation key is the reader's to read."""
    ctx = write_package(package, kinds="[assembly]", section="assemblies")
    impl = output.import_declaration(ctx, ctx.get_project("//"), "demo")

    assert impl.parameters["greeting"] == "hello"
    # ...and the keys that configure the machinery are not handed over.
    for reserved in ("path", "extension", "kinds", "noun", "dropped"):
        assert reserved not in impl.parameters


def test_an_object_retunes_a_readers_parameter_for_itself(package):
    """A package tunes a reader per object, the way it tunes an exporter."""
    ctx = write_package(
        package,
        kinds="[assembly]",
        section="assemblies",
        object_fields="    greeting: goodbye",
    )
    assembly = ctx.get_assembly("//:thing")

    assert assembly.info()["Greeting"] == "goodbye"


def test_every_builtin_reader_declares_what_it_produces(package):
    """A declaration that forgot 'kinds:' would silently accept both sections."""
    for format_name in ("urdf", "mjcf", "world"):
        declaration = builtin_import_declaration(format_name)
        assert declaration["kinds"], format_name
        assert set(declaration["kinds"]) <= {"assembly", "scene"}, format_name
        assert declaration["path"], format_name
        assert declaration["noun"], format_name


def test_the_builtin_readers_ship_beside_their_declaration():
    """A 'path' naming a file that is not in the wheel is a broken package."""
    root = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]]
    with open(os.path.join(root, "partcad.yaml"), encoding="utf-8") as f:
        section = yaml.safe_load(f)["import"]

    for format_name, declaration in section.items():
        assert os.path.isfile(os.path.join(root, declaration["path"])), format_name


def test_a_dependency_under_import_fails_loudly(package):
    """The section changed hands, so the old meaning has to be told, not guessed.

    'import:' was the name of 'dependencies:'. Migrating it in silence is what
    stopped being possible: a reader declaration copied into 'dependencies'
    would be fetched as a package, and the failure would surface nowhere near
    the file that caused it.
    """
    (package / "partcad.yaml").write_text(
        "name: //p\n" "import:\n" "  robots:\n" "    type: git\n" "    url: https://github.com/openvmp/robots.git\n",
        encoding="utf-8",
    )

    with pytest.raises(pc.exception.ObsoleteImportSectionError) as caught:
        pc.Context(str(package))

    # The message has to name the offending entry and say what to do.
    assert "robots" in str(caught.value)
    assert "dependencies:" in str(caught.value)


def test_a_half_written_dependency_is_recognised_too(package):
    """'url:' alone is a dependency: 'type:' may simply not be typed yet."""
    (package / "partcad.yaml").write_text(
        "name: //p\nimport:\n  robots:\n    url: https://github.com/openvmp/robots.git\n",
        encoding="utf-8",
    )

    with pytest.raises(pc.exception.ObsoleteImportSectionError):
        pc.Context(str(package))


def test_a_reader_declaration_is_not_mistaken_for_a_dependency(package):
    """The check has to be silent for every package using the section as it is now."""
    ctx = write_package(package, kinds="[assembly]", section="assemblies")

    assert ctx.get_assembly("//:thing") is not None


def test_the_builtin_package_declares_readers_and_not_dependencies():
    """PartCAD's own 'import:' has to pass the check it imposes on everyone else."""
    from partcad.project_config import Configuration

    root = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]]
    with open(os.path.join(root, "partcad.yaml"), encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert Configuration._obsolete_import_entries(config["import"]) == []
