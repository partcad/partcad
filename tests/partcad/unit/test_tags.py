#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What a context is tagged with, and what 'unless' does with those tags.

A package - or one object of a package - may declare the conditions it does not
work under. It is then skipped where one holds, rather than loaded and left to
fail at use. A condition is a clause: one tag, or several that must hold
together; any clause excluding is enough.

The case that prompted this is the KiCad example. KiCad's official container
images are 'linux/amd64' only, so the sandbox PartCAD runs 'kicad-cli' in cannot
be pulled on an Arm host - but only when that container is what is going to be
used, which is a fact about the configuration and not about the machine. Hence
'[[arm, useDocker, useDockerKicad]]', and hence tags for both.
"""

import asyncio
import platform

import pytest
import yaml

import partcad as pc
from partcad import tags as pc_tags
from partcad_utils.user_config import UserConfig

CUBE = "import cadquery as cq\nshape = cq.Workplane('front').box(1, 1, 1)\nshow_object(shape)\n"


def write_package(path, config, with_cube=True):
    path.mkdir(parents=True, exist_ok=True)
    (path / "partcad.yaml").write_text(yaml.safe_dump(config))
    if with_cube:
        (path / "cube.py").write_text(CUBE)
    return path


@pytest.fixture
def here():
    """A tag this host really has, so that 'unless' on it excludes for real."""
    return sorted(pc_tags.host_tags())[0]


@pytest.fixture
def also_here():
    """A second one, for the clauses that need two tags that both hold.

    From the host rather than from the configuration: every host has an
    architecture and an operating system, whereas which way 'useDocker' is set
    is a property of whoever is running the tests.
    """
    return sorted(pc_tags.host_tags())[1]


# The tags a host reports about itself


def test_the_host_is_tagged_with_its_own_architecture():
    assert platform.machine().lower() in pc_tags.host_tags()


def test_the_two_spellings_of_an_architecture_are_both_tags():
    """'amd64' and 'x86_64' name the same thing; which one a host reports is
    the operating system's choice, and no package should have to know it."""
    tags = pc_tags.host_tags()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        assert {"x86_64", "amd64"} <= tags
    elif machine in ("aarch64", "arm64"):
        # Plus the family, so that 'unless: [arm]' covers 64-bit Arm too.
        assert {"arm64", "aarch64", "arm"} <= tags


def test_the_host_is_tagged_with_its_operating_system():
    tags = pc_tags.host_tags()
    expected = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}[platform.system()]
    assert expected in tags


def test_the_host_is_tagged_with_its_operating_system_version():
    """One tag of the form '<os>-<version>' - 'ubuntu-24.04', 'macos-26'.

    On Linux that is the distribution rather than the kernel, read from
    '/etc/os-release'. A container without one contributes none, which is why
    this asserts the shape of what is there rather than that something is.
    """
    versioned = [tag for tag in pc_tags.host_tags() if "-" in tag and not tag.startswith("-")]
    for tag in versioned:
        name, _, version = tag.partition("-")
        assert name and version
        assert name in pc_tags.host_tags(), "'%s' should imply the tag '%s'" % (tag, name)


def test_a_context_carries_the_host_tags():
    ctx = pc.Context()
    assert pc_tags.host_tags() <= ctx.tags


def test_the_user_configuration_adds_tags():
    class FakeUserConfig:
        tags = "no-kicad, build-machine"

    tags = pc_tags.context_tags(FakeUserConfig())
    assert {"no-kicad", "build-machine"} <= tags
    assert pc_tags.host_tags() <= tags


def test_tags_are_matched_regardless_of_spelling():
    """Kept as written - 'pc system status' shows these back - but matched
    case-insensitively, so neither side has to know how the other typed it."""

    class FakeUserConfig:
        tags = ["  No-KiCad  "]

    tags = pc_tags.context_tags(FakeUserConfig())
    assert "No-KiCad" in tags
    assert pc_tags.excluded_by({"unless": "no-kicad"}, tags, "x") == "no-kicad"


# The tags a configuration contributes


def test_a_boolean_option_is_a_tag_in_one_of_its_two_spellings():
    class FakeUserConfig:
        use_docker = True
        use_docker_python_declared = False
        use_docker_kicad_declared = True

    assert pc_tags.config_tags(FakeUserConfig()) == {"useDocker", "!useDockerPython", "useDockerKicad"}


def test_an_option_this_build_does_not_have_contributes_nothing():
    """Neither 'useDocker' nor '!useDocker' is true of a PartCAD with no such
    option, and claiming either would exclude on a question never asked."""

    class FakeUserConfig:
        pass

    assert pc_tags.config_tags(FakeUserConfig()) == set()


def test_a_real_configuration_contributes_its_docker_tags():
    ctx = pc.Context()
    for option, _attribute in pc_tags.CONFIG_TAGS:
        assert (option in ctx.tags) != ("!" + option in ctx.tags), option


def test_the_master_switch_is_reported_apart_from_what_it_governs():
    """'useDocker' off with 'useDockerKicad' on is a real state, and the pair of
    tags has to be able to say so - it is the state the KiCad example's first
    clause used to be written for."""
    from partcad_utils.user_config import UserConfig

    config = UserConfig()
    config.use_docker = False
    config.use_docker_kicad_declared = True
    config.use_docker_python_declared = False

    tags = pc_tags.config_tags(config)
    assert "!useDocker" in tags
    assert "useDockerKicad" in tags


# Clauses: any one excludes (OR), all the tags in one must hold (AND)


def test_a_clause_excludes_only_when_all_of_its_tags_hold(tmp_path, here, also_here):
    write_package(
        tmp_path,
        {
            "name": "//test",
            "parts": {
                "gone": {"type": "cadquery", "path": "cube.py", "unless": [[here, also_here]]},
                "kept": {"type": "cadquery", "path": "cube.py", "unless": [[here, "no-such-tag"]]},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.object_names("part") == ["kept"]
    assert project.get_skipped_object_clause("part", "gone") == "%s and %s" % (here, also_here)


def test_any_one_clause_is_enough(tmp_path, here):
    write_package(
        tmp_path,
        {
            "name": "//test",
            "parts": {
                "gone": {
                    "type": "cadquery",
                    "path": "cube.py",
                    "unless": [["no-such-tag", "nor-this"], [here]],
                }
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.object_names("part") == []
    assert project.get_skipped_object_clause("part", "gone") == here


def test_clauses_and_bare_tags_mix_in_one_list(tmp_path, here):
    assert pc_tags.parse_unless([["arm", "useDocker"], "macos"], "x") == [["arm", "useDocker"], ["macos"]]
    assert pc_tags.parse_unless("arm64", "x") == [["arm64"]]
    assert pc_tags.parse_unless(["arm64", "windows"], "x") == [["arm64"], ["windows"]]


def test_an_empty_clause_is_refused():
    """It holds vacuously, so it would exclude everywhere. Nobody writes that."""
    with pytest.raises(ValueError):
        pc_tags.parse_unless([[]], "x")


def test_a_clause_of_something_other_than_tags_is_refused():
    with pytest.raises(ValueError):
        pc_tags.parse_unless([{"arm": True}], "x")
    with pytest.raises(ValueError):
        pc_tags.parse_unless([[17]], "x")


# 'unless' on an object


def test_an_object_excluded_by_a_tag_is_not_declared(tmp_path, here):
    write_package(
        tmp_path,
        {
            "name": "//test",
            "parts": {
                "kept": {"type": "cadquery", "path": "cube.py"},
                "gone": {"type": "cadquery", "path": "cube.py", "unless": [here]},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.object_names("part") == ["kept"]
    assert "gone" not in project.parts
    # Skipped, not broken: nothing failed and there is nothing to fix.
    assert project.broken_objects["part"] == {}
    assert project.get_skipped_object_clause("part", "gone") == here


def test_an_object_excluded_by_a_tag_resolves_to_nothing(tmp_path, here):
    write_package(
        tmp_path,
        {"name": "//test", "parts": {"gone": {"type": "cadquery", "path": "cube.py", "unless": here}}},
    )
    ctx = pc.Context(str(tmp_path))

    assert ctx.get_part("//:gone") is None


def test_a_single_tag_need_not_be_written_as_a_list(tmp_path, here):
    write_package(
        tmp_path,
        {"name": "//test", "parts": {"gone": {"type": "cadquery", "path": "cube.py", "unless": here}}},
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.object_names("part") == []


def test_an_object_is_kept_where_no_tag_of_its_own_holds(tmp_path):
    write_package(
        tmp_path,
        {
            "name": "//test",
            "parts": {"kept": {"type": "cadquery", "path": "cube.py", "unless": ["no-such-tag", "另一个"]}},
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.object_names("part") == ["kept"]
    assert project.get_skipped_object_clause("part", "kept") is None


def test_objects_of_every_kind_can_be_excluded(tmp_path, here):
    write_package(
        tmp_path,
        {
            "name": "//test",
            "sketches": {"s": {"type": "basic", "circle": 5, "unless": here}},
            "parts": {"p": {"type": "cadquery", "path": "cube.py", "unless": here}},
            "assemblies": {"a": {"type": "assy", "path": "a.assy", "unless": here}},
            "interfaces": {"i": {"abstract": True, "unless": here}},
            "providers": {"v": {"type": "store", "unless": here}},
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    for kind in ("sketch", "part", "assembly", "interface", "provider"):
        assert project.object_names(kind) == [], kind


def test_a_misshapen_unless_is_reported_against_the_object(tmp_path):
    """A typo must not pass for "excludes nothing" - that is an exclusion that
    silently does not happen. The object is dropped and the reason recorded."""
    write_package(
        tmp_path,
        {
            "name": "//test",
            "parts": {
                "bad": {"type": "cadquery", "path": "cube.py", "unless": 17},
                "good": {"type": "cadquery", "path": "cube.py"},
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.object_names("part") == ["good"]
    assert "unless" in project.get_broken_object_reason("part", "bad")


def test_a_parametrized_name_whose_base_is_excluded_says_so(tmp_path, here, caplog):
    """'gone;width=5' has to read the way 'gone' does.

    The parametrized path looks the base up in the filtered declarations, where
    an excluded object is absent - which used to come back as an ERROR saying
    the base was not found, sending the user hunting for a typo they do not
    have.
    """
    write_package(
        tmp_path,
        {
            "name": "//test",
            "parts": {
                "gone": {
                    "type": "cadquery",
                    "path": "cube.py",
                    "unless": here,
                    "parameters": {"width": {"type": "float", "default": 1.0}},
                }
            },
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    with caplog.at_level("INFO", logger="partcad"):
        assert project.get_part("gone;width=5") is None
    assert "excluded by 'unless'" in caplog.text
    assert "not found" not in caplog.text


def test_a_genuinely_missing_base_is_still_an_error(tmp_path, caplog):
    """The distinction above must not swallow the case it was carved out of."""
    write_package(tmp_path, {"name": "//test", "parts": {"kept": {"type": "cadquery", "path": "cube.py"}}})
    project = pc.Context(str(tmp_path)).get_project("//")

    with caplog.at_level("INFO", logger="partcad"):
        assert project.get_part("nosuch;width=5") is None
    assert "not found" in caplog.text


def test_rendering_a_package_does_not_trip_over_its_excluded_objects(tmp_path, here):
    """An excluded object is not a shape to render.

    'render_async' enumerates a package's shapes from its configuration, which
    still lists everything - nothing rewrites the file. An excluded one resolves
    to None, and a None among the shapes fails the whole package's render with
    'EmptyShapesError'.
    """
    write_package(
        tmp_path,
        {
            "name": "//test",
            "parts": {
                "kept": {"type": "cadquery", "path": "cube.py"},
                "gone": {"type": "cadquery", "path": "cube.py", "unless": here},
            },
            "render": {"svg": None},
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    shapes = project._enumerate_shapes(None, None, None, None)
    assert None not in shapes
    assert [shape.name for shape in shapes] == ["kept"]


# 'unless' on a package


def test_a_package_excluded_by_a_tag_declares_nothing(tmp_path, here):
    write_package(
        tmp_path,
        {"name": "//test", "unless": [here], "parts": {"gone": {"type": "cadquery", "path": "cube.py"}}},
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.skipped
    assert project.skipped_by == here
    assert project.object_names("part") == []
    assert project.parts == {}


def test_rendering_a_skipped_package_is_a_no_op(tmp_path, here):
    """Not an 'EmptyShapesError'. Its declarations are all still in
    'config_obj', so enumerating them would resolve every one to None."""
    write_package(
        tmp_path,
        {
            "name": "//test",
            "unless": here,
            "parts": {"gone": {"type": "cadquery", "path": "cube.py"}},
            "render": {"svg": None},
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")
    assert project.skipped

    asyncio.run(project.render_async(output_dir=str(tmp_path)))
    assert not list(tmp_path.glob("*.svg"))


def test_a_skipped_package_is_not_listed(tmp_path, here):
    write_package(tmp_path, {"name": "//test"})
    write_package(tmp_path / "kept", {"desc": "kept"})
    write_package(tmp_path / "gone", {"desc": "gone", "unless": [here]})
    ctx = pc.Context(str(tmp_path))

    listed = [package["name"] for package in ctx.get_all_packages(has_stuff=False)]
    assert "//test/kept" in listed
    assert "//test/gone" not in listed


def test_nothing_under_a_skipped_package_is_reachable(tmp_path, here):
    """Skipping a package skips what it brings in. A child reached through it
    would otherwise load as if its parent had never opted out."""
    write_package(tmp_path, {"name": "//test"})
    write_package(tmp_path / "gone", {"desc": "gone", "unless": [here]})
    write_package(tmp_path / "gone" / "below", {"parts": {"p": {"type": "cadquery", "path": "cube.py"}}})
    ctx = pc.Context(str(tmp_path))

    assert ctx.get_project("//test/gone").skipped
    assert ctx.get_project("//test/gone/below") is None
    assert ctx.get_project("//test/gone").get_child_project_names() == []
    listed = [package["name"] for package in ctx.get_all_packages(has_stuff=False)]
    assert not any(name.startswith("//test/gone") for name in listed)


def test_a_package_is_kept_where_no_tag_of_its_own_holds(tmp_path):
    write_package(
        tmp_path,
        {
            "name": "//test",
            "unless": ["no-such-tag"],
            "parts": {"kept": {"type": "cadquery", "path": "cube.py"}},
        },
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert not project.skipped
    assert project.object_names("part") == ["kept"]


def test_a_misshapen_unless_does_not_take_the_package_out_of_the_tree(tmp_path):
    """Reported and then ignored: losing a package - and everything under it -
    over a typo is a far worse outcome than loading one that meant to opt out."""
    write_package(
        tmp_path,
        {"name": "//test", "unless": {"arm64": True}, "parts": {"kept": {"type": "cadquery", "path": "cube.py"}}},
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert not project.skipped
    assert project.object_names("part") == ["kept"]


# A plugin-backed package, whose configuration arrives over the wire


def _external_package(ctx, data):
    """A plugin-backed package standing on a fake repository (see
    'test_project_external_repository' for the same fixture in full)."""
    from partcad.project_external_repository import ProjectExternalRepository

    class FakeRepository:
        async def get_data(self, key):
            return data.get(key)

    package = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", config_obj={})
    package._repository = FakeRepository()
    return package


def test_a_plugin_backed_package_can_exclude_itself(tmp_path, here):
    """Its configuration is not a file the constructor could read: 'meta'
    arrives from the repository, so the exclusion is decided when it does."""
    import asyncio

    write_package(tmp_path, {"name": "//test"}, with_cube=False)
    ctx = pc.Context(str(tmp_path))
    package = _external_package(ctx, {"meta": {"desc": "over the wire", "unless": [here]}})

    assert not package.skipped  # nothing has been fetched yet
    asyncio.run(package.ensure_enumerated_async())

    assert package.skipped
    assert package.skipped_by == here


def test_a_plugin_backed_package_can_exclude_one_object(tmp_path, here):
    write_package(tmp_path, {"name": "//test"}, with_cube=False)
    ctx = pc.Context(str(tmp_path))
    package = _external_package(
        ctx,
        {"objects/part": {"kept": {"type": "step"}, "gone": {"type": "step", "unless": here}}},
    )

    assert package.object_names("part") == ["kept"]
    assert package.object_config("part", "gone") is None


# The KiCad example, which is what all of this is for


KICAD_CLAUSE = ["arm", "useDocker", "useDockerKicad"]


def test_the_kicad_example_is_declared_the_way_it_is_skipped():
    with open("examples/produce_part_kicad/partcad.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert pc_tags.parse_unless(config.get("unless"), "kicad example") == [KICAD_CLAUSE]


def kicad_container_config(**overrides):
    """A configuration with the two Docker switches pinned, not inherited.

    The tags a context carries come from the user configuration it resolves, so
    a developer whose own '~/.partcad/config.yaml' turns either switch off would
    otherwise fail these tests over a machine setting rather than over the code.
    """
    config = UserConfig()
    config.use_docker = overrides.get("use_docker", True)
    config.use_docker_kicad_declared = overrides.get("use_docker_kicad_declared", True)
    config.use_docker_python_declared = False
    config.tags = ""
    return config


def test_the_kicad_example_is_skipped_on_an_arm_host_using_the_container(monkeypatch):
    """The whole point, exercised on every host rather than only on Arm ones.

    'platform.machine()' is the one thing that decides the architecture, so
    standing in for it is enough to put a context on the far side of the
    condition CI hits: an Arm machine with the KiCad container in use.
    """
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    ctx = pc.Context("examples", user_config=kicad_container_config())
    assert {"arm64", "aarch64", "arm"} <= ctx.tags
    assert {"useDocker", "useDockerKicad"} <= ctx.tags

    project = ctx.get_project("//produce_part_kicad")
    assert project.skipped
    assert project.skipped_by == "arm and useDocker and useDockerKicad"
    assert project.object_names("part") == []
    assert ctx.get_part("//produce_part_kicad:Arduino_Nano") is None
    listed = [package["name"] for package in ctx.get_packages(has_stuff=False)]
    assert "//produce_part_kicad" not in listed


@pytest.mark.parametrize("off", ["use_docker", "use_docker_kicad_declared"])
def test_an_arm_host_running_kicad_natively_keeps_the_example(monkeypatch, off):
    """Turning the container off - either switch - takes the exclusion away.

    KiCad does ship Arm builds, so somebody who has 'kicad-cli' installed
    natively can build this on Arm. The clause is about the container, and this
    is the case a bare 'unless: [arm]' would have got wrong.
    """
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    ctx = pc.Context("examples", user_config=kicad_container_config(**{off: False}))

    project = ctx.get_project("//produce_part_kicad")
    assert not project.skipped
    assert "Arduino_Nano" in project.object_names("part")


def test_the_kicad_example_is_skipped_exactly_where_it_says():
    """Against whatever this machine actually resolves to, ambient configuration
    included - which is why it branches rather than asserting one outcome."""
    ctx = pc.init("examples")
    project = ctx.get_project("//produce_part_kicad")
    excluded = all(tag in ctx.tags for tag in KICAD_CLAUSE)

    if excluded:
        assert project.skipped
        assert project.object_names("part") == []
    else:
        assert not project.skipped
        assert "Arduino_Nano" in project.object_names("part")
