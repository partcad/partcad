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
    for format_name in ("urdf",):
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


def write_plugin_and_user(root, plugin_dir):
    """A package that declares a reader, and a separate one that uses it.

    Which is the arrangement the section exists for -- '//builtin/import' is not
    the only package that may declare a reader -- and the one nothing could
    exercise while every reader shipped in the wheel.
    """
    plugin_dir.mkdir()
    (plugin_dir / "reader.py").write_text(TRIVIAL_READER, encoding="utf-8")
    (plugin_dir / "partcad.yaml").write_text(
        textwrap.dedent("""
            name: //the-plugin
            import:
              demo:
                path: reader.py
                extension: demo
                kinds: [assembly]
                noun: doodad
                greeting: hello
                mesh: %(mesh)s
                dropped:
                  everything: "the entire file"
            """) % {"mesh": CUBE.replace("\\", "/")},
        encoding="utf-8",
    )
    (root / "thing.demo").write_text("nothing here is parsed\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(
        textwrap.dedent("""
            dependencies:
              reads-demo:
                type: local
                path: %(plugin)s
            assemblies:
              thing:
                type: reads-demo:demo
                path: thing.demo
            """) % {"plugin": str(plugin_dir).replace("\\", "/")},
        encoding="utf-8",
    )
    return pc.Context(str(root))


def test_a_reader_in_another_package_is_named_through_it(package, tmp_path):
    """'type: reads-demo:demo' -- the spelling a plugin's own README gives."""
    ctx = write_plugin_and_user(package, tmp_path / "plugin")
    assembly = ctx.get_project("//").get_assembly("thing")

    assert assembly is not None
    asyncio.run(assembly.do_instantiate())
    assert [child.name for child in assembly.children] == ["only"]


def test_a_reader_in_another_package_resolves_while_the_package_loads(package, tmp_path, caplog):
    """Which is when it has to, and is where it used to fail.

    A package's objects are created as part of loading it, so an object whose
    'type:' names another package resolves that package right then - before the
    package doing the asking has finished loading and been registered under its
    own name. Looking it up from the root therefore answered None for a
    dependency that was declared perfectly well, and the object was recorded as
    broken on the way in and worked on the second attempt.

    So this asserts on the loading itself rather than on the result: no error,
    and the object is there the first time it is asked for.
    """
    with caplog.at_level("ERROR"):
        ctx = write_plugin_and_user(package, tmp_path / "plugin")
        project = ctx.get_project("//")

    assert project.get_assembly("thing") is not None
    assert [record.message for record in caplog.records] == []


def test_a_package_that_does_not_declare_the_reader_it_was_named_for(package, tmp_path):
    """A path is an answer to "whose reader", so a wrong one is about the package."""
    ctx = write_plugin_and_user(package, tmp_path / "plugin")
    project = ctx.get_project("//")
    project.assembly_configs["thing"]["type"] = "reads-demo:nosuch"
    project.assemblies.pop("thing", None)

    assert project.get_assembly("thing") is None


def test_a_dependency_under_import_is_reported_and_not_migrated(package):
    """The section changed hands, so the old meaning has to be told, not guessed.

    'import:' was the name of 'dependencies:'. Migrating it in silence is what
    stopped being possible: a reader declaration copied into 'dependencies'
    would be fetched as a package, and the failure would surface nowhere near
    the file that caused it.

    In the *root* package - the one the user is standing in, and the one they
    can fix - that is an error and the package is broken, which is how every
    other unreadable 'partcad.yaml' is handled. An imported one is somebody
    else's; see the test below.
    """
    (package / "partcad.yaml").write_text(
        "name: //p\n" "import:\n" "  robots:\n" "    type: git\n" "    url: https://github.com/openvmp/robots.git\n",
        encoding="utf-8",
    )

    ctx = pc.Context(str(package))
    project = ctx.get_project("//")

    assert project.broken
    # Not migrated: that is the whole point.
    assert not project.config_obj.get("dependencies")
    assert "import" not in project.config_obj


def test_a_legacy_dependency_in_somebody_elses_package_is_a_warning(package):
    """One legacy package in an index must not fail every command walking past it.

    The public index carries such a package today, several levels below
    anything a user wrote. Marking it broken would be reported by
    'Context.import_project()' as an error of its own, so a 'pc list' that
    merely enumerates the index would exit non-zero over a section the user
    cannot reach, let alone rename.

    So it warns, and the package goes on providing everything else it declares.
    What is lost is what the section named, and nothing besides.
    """
    legacy = package / "legacy"
    legacy.mkdir()
    (legacy / "partcad.yaml").write_text(
        "name: //legacy\n"
        "dependencies: {}\n"
        "import:\n"
        "  robots:\n"
        "    type: git\n"
        "    url: https://example.invalid/r.git\n"
        "parts:\n"
        "  cube:\n"
        "    type: stl\n"
        "    path: %s\n" % CUBE.replace("\\", "/"),
        encoding="utf-8",
    )
    (package / "partcad.yaml").write_text(
        "name: //root\ndependencies:\n  legacy:\n    type: local\n    path: ./legacy\n",
        encoding="utf-8",
    )
    ctx = pc.Context(str(package))

    imported = ctx.get_project("//root/legacy")
    assert imported is not None
    assert not imported.broken
    # Not migrated, and the entry it named is simply gone.
    assert not imported.config_obj.get("dependencies")
    assert "import" not in imported.config_obj
    # ...while the rest of the package is untouched.
    assert ctx.get_part("//root/legacy:cube") is not None


def test_a_reader_beside_a_legacy_dependency_survives_it(package):
    """A package part-way through the rename keeps the half it got right.

    The check is per entry, so the deletion is too. A mapping holding both a
    legacy dependency and a working reader used to lose the reader along with
    the dependency, and every object using it then failed as an unknown type --
    a message pointing nowhere near the section that caused it.
    """
    (package / "reader.py").write_text(TRIVIAL_READER, encoding="utf-8")
    (package / "thing.demo").write_text("nothing here is parsed\n", encoding="utf-8")
    (package / "partcad.yaml").write_text(
        textwrap.dedent("""
            name: //p
            import:
              robots:
                type: git
                url: https://example.invalid/r.git
              demo:
                path: reader.py
                extension: demo
                kinds: [assembly]
                noun: doodad
                greeting: hello
                mesh: %(mesh)s
            assemblies:
              thing:
                type: demo
                path: thing.demo
            """) % {"mesh": CUBE.replace("\\", "/")},
        encoding="utf-8",
    )

    ctx = pc.Context(str(package))
    project = ctx.get_project("//")

    # The dependency-shaped entry is gone...
    assert "robots" not in project.config_obj["import"]
    assert not project.config_obj.get("dependencies")
    # ...and the reader beside it is not.
    assert "demo" in project.config_obj["import"]
    assert output.import_declaration(ctx, project, "demo").parameters["greeting"] == "hello"


def test_a_half_written_dependency_is_recognised_too(package):
    """'url:' alone is a dependency: 'type:' may simply not be typed yet."""
    (package / "partcad.yaml").write_text(
        "name: //p\nimport:\n  robots:\n    url: https://github.com/openvmp/robots.git\n",
        encoding="utf-8",
    )

    assert pc.Context(str(package)).get_project("//").broken


def test_a_legacy_package_does_not_strand_the_loading_marker(package):
    """What made this cascade: a package that fails to load must not poison the name.

    An exception escaping a project factory used to leave the name marked as
    being loaded for the life of the context, so every later import of it
    reported a recursion that was not happening -- naming the innocent package
    rather than the one that failed.
    """
    legacy = package / "legacy"
    legacy.mkdir()
    (legacy / "partcad.yaml").write_text(
        "name: //legacy\nimport:\n  robots:\n    type: git\n    url: https://example.invalid/r.git\n",
        encoding="utf-8",
    )
    (package / "partcad.yaml").write_text(
        "name: //root\ndependencies:\n  legacy:\n    type: local\n    path: ./legacy\n",
        encoding="utf-8",
    )
    ctx = pc.Context(str(package))

    ctx.get_project("//root/legacy")

    assert not ctx._projects_being_loaded, ctx._projects_being_loaded


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


def test_loading_a_dependency_does_not_rewrite_what_the_package_declared(tmp_path):
    """A README must not depend on whether a dependency happened to be loaded.

    'import_project()' is told where to load a package by the 'name' of the
    configuration it is handed, and that used to be written into the parent's
    own 'dependencies' entry. 'Project.get_readme()' titles a sub-package's
    section from that same 'name', so the rendered README named a dependency by
    its alias before it was loaded and by its full package path afterwards --
    two different files from one tree, decided by whether the dependency could
    be fetched. That is what broke 'Examples (PartCAD)' on #637: the checked-in
    README was rendered offline, where a git dependency never loads.
    """
    child = tmp_path / "child"
    child.mkdir()
    (child / "partcad.yaml").write_text("name: //declared\n", encoding="utf-8")
    (tmp_path / "partcad.yaml").write_text(
        "name: //root\ndependencies:\n  kid:\n    type: local\n    path: ./child\n",
        encoding="utf-8",
    )

    ctx = pc.Context(str(tmp_path))
    declared = ctx.get_project("//root").config_obj["dependencies"]["kid"]
    assert "name" not in declared, declared

    # Load it, which is what used to rewrite the entry above.
    assert ctx.get_project("//root/kid") is not None

    assert "name" not in declared, declared
    assert declared["path"] == "./child"


def test_a_git_sub_package_is_titled_by_the_alias(tmp_path):
    """The branch that rendered differently, pinned on the file it writes.

    Only the 'git' branch of the sub-package section reads 'name' -- the 'local'
    one always uses the alias -- so this is where a rewritten 'dependencies'
    entry showed up, as a heading that read '//pub/examples/.../sim-mujoco'
    instead of 'sim-mujoco'. A dependency that declares no 'name:' is titled by
    the alias, which is the name the package gave the thing it imported.

    What keeps the entry from being rewritten in the first place is the test
    above; this one says what the rewriting looked like to a reader.
    """
    (tmp_path / "partcad.yaml").write_text(
        "name: //root\n"
        "dependencies:\n"
        "  sim-mujoco:\n"
        "    type: git\n"
        "    url: https://github.com/partcad/partcad-sim-mujoco.git\n",
        encoding="utf-8",
    )
    project = pc.Context(str(tmp_path)).get_project("//root")
    out = tmp_path / "out"
    out.mkdir()

    # Named '..._async' but synchronous; it is the one that writes the file.
    project.render_readme_async({}, str(out))
    headings = [
        line for line in (out / "README.md").read_text(encoding="utf-8").splitlines() if line.startswith("### ")
    ]

    assert headings == ["### [sim-mujoco](https://github.com/partcad/partcad-sim-mujoco.git)"], headings
