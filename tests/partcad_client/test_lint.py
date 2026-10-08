#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the client-side file check (`partcad_client.lint`).

What is pinned here is the *client* half: which files get checked at all, where
their content comes from (the disk, or a buffer an editor has not saved), and
the shape the answer comes back in. The checking itself belongs to
``partcad_utils.assy_lint`` and is covered by that package's tests.
"""

import pytest

from partcad_client import lint


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_a_clean_assy_file_reports_nothing(tmp_path):
    report = lint.check_file(write(tmp_path, "logo.assy", "links:\n  - part: cube\n"))
    assert report.checked is True
    assert report.diagnostics == []
    assert report.failed is False


def test_a_broken_assy_file_is_reported_with_positions(tmp_path):
    path = write(tmp_path, "logo.assy", "links:\n  - part: cube\n    location: [0, 0, 0]\n")
    report = lint.check_file(path)
    assert report.failed is True
    assert all(d.line == 2 for d in report.diagnostics)


def test_the_supplied_buffer_wins_over_the_file_on_disk(tmp_path):
    # The point of the whole arrangement: an editor checks what is on screen,
    # which is why this never became a request to a daemon that can only see
    # what was saved.
    path = write(tmp_path, "logo.assy", "links:\n  - part: cube\n")
    assert lint.check_file(path).diagnostics == []
    edited = lint.check_file(path, "links:\n  - part: cube\n    locaton: 1\n")
    assert [d.message for d in edited.diagnostics] == ["unexpected property 'locaton'"]


def test_a_file_type_with_no_checks_is_not_reported_as_clean(tmp_path):
    report = lint.check_file(write(tmp_path, "notes.txt", "not an assembly"))
    assert report.checked is False
    assert report.diagnostics == []
    assert report.failed is False


def test_a_package_configuration_is_checked_too(tmp_path):
    """The file the package fails to load *because* of is the client's to check.

    Sending it to a daemon would mean asking a daemon that cannot load the
    package about the file that is stopping it.
    """
    path = write(tmp_path, "partcad.yaml", "desc: a package\nparts:\n  cube:\n    type: cadquery\n")
    report = lint.check_file(path)
    assert report.checked is True
    assert report.diagnostics == []

    edited = lint.check_file(path, "desc: a package\nprts:\n  cube:\n    type: cadquery\n")
    assert [d.message for d in edited.diagnostics] == ["unexpected property 'prts'"]
    assert (edited.diagnostics[0].line, edited.diagnostics[0].column) == (1, 0)


def test_a_configuration_has_no_flavor(tmp_path):
    """Nothing points at a package configuration, so no flavor is worked out for one.

    The packages above it are still read -- for what they mark manufacturable,
    which its parts inherit (see `test_a_configuration_inherits_what_a_package_above_marks`)
    -- but the question of what declares it is not asked.
    """
    report = lint.check_file(write(tmp_path, "partcad.yaml", "desc: a package\n"))
    assert report.flavor is None
    assert report.to_dict()["flavor"] is None


def test_a_scene_flavor_named_for_a_configuration_is_ignored(tmp_path):
    """`--schema scene` aimed at the wrong file gets the configuration schema.

    A scene-flavored configuration schema would forbid a `how` no package
    configuration has, which is a schema nothing should ever be checked against.
    """
    path = write(tmp_path, "partcad.yaml", "desc: a package\nscenes:\n  bench:\n    type: assy\n")
    report = lint.check_file(path, flavor="scene")
    assert report.flavor is None
    assert report.diagnostics == []


def test_a_templated_configuration_is_not_mistaken_for_broken_yaml(tmp_path):
    """`partcad.yaml` is a Jinja2 template too -- it even has `includePaths`."""
    path = write(
        tmp_path,
        "partcad.yaml",
        "parts:\n{% for size in [10, 20] %}\n  cube_{{ size }}:\n    type: cadquery\n    path: cube.py\n{% endfor %}\n",
    )
    assert lint.check_file(path).diagnostics == []


def test_what_pc_init_writes_is_clean(tmp_path):
    """A new package must not be three errors the moment its file is opened.

    An empty section parses as null, which is how the loader reads it as well;
    `pc init` writes three of them and `pc add part` fills one in.
    """
    path = write(tmp_path, "partcad.yaml", "dependencies:\nsketches:\nparts:\nassemblies:\n")
    assert lint.check_file(path).diagnostics == []


def test_a_missing_file_raises(tmp_path):
    # A caller that named a file it cannot open wants to hear about it, rather
    # than get an empty (and therefore reassuring) report back.
    with pytest.raises(OSError):
        lint.check_file(str(tmp_path / "gone.assy"))


def test_a_missing_file_is_fine_when_the_content_is_supplied(tmp_path):
    # An editor can check a buffer for a file that was never saved.
    report = lint.check_file(str(tmp_path / "untitled.assy"), "links:\n  - part: cube\n")
    assert report.checked is True
    assert report.diagnostics == []


def test_paths_come_back_exactly_as_they_went_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "logo.assy", "links:\n  - part: cube\n")
    assert [report.path for report in lint.check_files(["logo.assy"])] == ["logo.assy"]


def test_check_files_reports_every_path(tmp_path):
    paths = [
        write(tmp_path, "a.assy", "links:\n  - part: cube\n"),
        write(tmp_path, "b.assy", "links:\n  - part: cube\n    locaton: 1\n"),
    ]
    reports = lint.check_files(paths)
    assert [report.path for report in reports] == paths
    assert [len(report.diagnostics) for report in reports] == [0, 1]


def test_supplied_content_needs_exactly_one_file(tmp_path):
    with pytest.raises(ValueError):
        lint.check_files(["a.assy", "b.assy"], "links:\n")


def test_report_serializes_for_a_json_consumer(tmp_path):
    path = write(tmp_path, "logo.assy", "links:\n  - part: cube\n    locaton: 1\n")
    payload = lint.check_file(path).to_dict()
    assert payload["path"] == path
    assert payload["checked"] is True
    finding = payload["diagnostics"][0]
    assert finding["severity"] == "warning"
    assert (finding["line"], finding["column"]) == (2, 4)
    assert finding["source"] == "partcad"


# ---- what a file is rendered with, and held to ------------------------------
#
# Worked out from the 'partcad.yaml' files around it by 'partcad_utils.lint_context'
# -- the same answer the daemon gets, which is why the client asks it there.


def package(tmp_path, config, assy=None, name="pkg"):
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / "partcad.yaml").write_text(config)
    if assy is not None:
        (root / "thing.assy").write_text(assy)
    return root


LOOPED = "links:\n{% for n in range(param_count) %}\n  - part: leg\n    name: leg-{{ n }}\n{% endfor %}\n"


def test_a_declared_file_is_rendered_with_its_parameters(tmp_path):
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n    parameters:\n      count: 2\n", LOOPED)
    assert lint.check_file(str(root / "thing.assy")).diagnostics == []
    # A value the parameter cannot take is the declaration's to answer for.
    broken = package(
        tmp_path,
        "assemblies:\n  thing:\n    type: assy\n    parameters:\n      count:\n        type: string\n"
        "        default: two\n",
        LOOPED,
        name="broken",
    )
    [diagnostic] = lint.check_file(str(broken / "thing.assy")).diagnostics
    assert diagnostic.code == "jinja2"
    assert "'thing'" in diagnostic.message


def test_a_file_nothing_declares_is_checked_masked(tmp_path):
    # Its parameters are unknown, so it cannot be rendered -- and is not
    # reported as broken for that.
    (tmp_path / "loose.assy").write_text(LOOPED)
    assert lint.check_file(str(tmp_path / "loose.assy")).diagnostics == []


def test_a_declaration_a_templated_configuration_makes_is_found(tmp_path):
    config = "assemblies:\n{% for size in ['thing'] %}\n  {{ size }}:\n    type: assy\n{% endfor %}\n"
    root = package(tmp_path, config, "links:\n  - part: a\n    name: {{ name }}\n")
    report = lint.check_file(str(root / "thing.assy"))
    assert report.diagnostics == []


PLACED = "links:\n  - part: frame\n  - part: motor\n    location: [[0, 0, 5], [0, 0, 1], 0]\n"


@pytest.mark.parametrize(
    "config, above, held",
    [
        ("assemblies:\n  thing:\n    type: assy\n    manufacturable: true\n", None, True),
        ("manufacturable: true\nassemblies:\n  thing:\n    type: assy\n", None, True),
        ("assemblies:\n  thing:\n    type: assy\n", "manufacturable: true\n", True),
        ("manufacturable: false\nassemblies:\n  thing:\n    type: assy\n", "manufacturable: true\n", False),
        ("assemblies:\n  thing:\n    type: assy\n", None, False),
        # A scene is not a product to be made unless it says so itself.
        ("manufacturable: true\nscenes:\n  thing:\n    type: assy\n", None, False),
        ("scenes:\n  thing:\n    type: assy\n    manufacturable: true\n", None, True),
    ],
)
def test_an_assembly_marked_manufacturable_connects_what_it_places(tmp_path, config, above, held):
    if above is not None:
        (tmp_path / "partcad.yaml").write_text(above)
    root = package(tmp_path, config, PLACED)
    codes = [d.code for d in lint.check_file(str(root / "thing.assy")).diagnostics]
    assert codes == (["manufacturable"] if held else [])


def test_a_configuration_inherits_what_a_package_above_marks(tmp_path):
    (tmp_path / "partcad.yaml").write_text("manufacturable: true\n")
    root = package(tmp_path, "parts:\n  bolt:\n    type: step\n")
    [diagnostic] = lint.check_file(str(root / "partcad.yaml")).diagnostics
    assert diagnostic.code == "manufacturable"
    # Its own word wins over the one above.
    (root / "partcad.yaml").write_text("manufacturable: false\nparts:\n  bolt:\n    type: step\n")
    assert lint.check_file(str(root / "partcad.yaml")).diagnostics == []


def test_a_configuration_includes_from_what_the_package_above_gives_it(tmp_path):
    """A dependency's 'includePaths', relative to the dependency, as 'ProjectLocal' renders it with."""
    (tmp_path / "partcad.yaml").write_text(
        "dependencies:\n  child:\n    path: child\n    includePaths:\n      - ../common\n"
    )
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "parts.yaml").write_text("  bolt:\n    type: step\n")
    child = package(tmp_path, "parts:\n{% include 'parts.yaml' %}\n", name="child")
    assert lint.check_file(str(child / "partcad.yaml")).diagnostics == []
    # And what it includes is checked, the finding placed on the include.
    (tmp_path / "common" / "parts.yaml").write_text("  bolt:\n    type: nonsense\n")
    [diagnostic] = lint.check_file(str(child / "partcad.yaml")).diagnostics
    assert (diagnostic.code, diagnostic.line) == ("schema", 1)


def test_an_include_that_is_not_found_is_not_reported_as_broken(tmp_path):
    # Whatever would have put it there may be a package this cannot see.
    root = package(tmp_path, "parts:\n{% include 'parts.yaml' %}\n")
    assert lint.check_file(str(root / "partcad.yaml")).diagnostics == []


def test_a_package_above_that_cannot_be_read_does_not_stop_the_check(tmp_path):
    # Not YAML at all, and YAML the parser raises 'ValueError' on.
    (tmp_path / "partcad.yaml").write_text("desc: 2001-13-45\n")
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n", PLACED)
    assert lint.check_file(str(root / "thing.assy")).diagnostics == []
    assert lint.check_file(str(root / "partcad.yaml")).diagnostics == []


@pytest.mark.parametrize("connectivity", ["requireAnchored: false", "skip: true"])
def test_an_assembly_pc_test_does_not_hold_to_connectivity_is_not_held_to_it_here(tmp_path, connectivity):
    root = package(
        tmp_path,
        "manufacturable: true\nassemblies:\n  thing:\n    type: assy\n    connectivity:\n      %s\n" % connectivity,
        PLACED,
    )
    assert lint.check_file(str(root / "thing.assy")).diagnostics == []


# ---- what the editor's 'partcad.lint' settings add ----------------------------


SIZED = "links:\n{% for n in range(param_count) %}\n  - part: leg\n{% if n > 2 %}\n    locaton: 1\n{% endif %}\n{% endfor %}\n"


@pytest.mark.parametrize("object_name", ["thing", ":thing", "//anything:thing"])
def test_an_override_renders_the_file_with_its_value(tmp_path, object_name):
    """'--extra-param' and '~/.partcad/config.yaml' replace a default, as PartCAD renders with."""
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n    parameters:\n      count: 2\n", SIZED)
    path = str(root / "thing.assy")
    assert lint.check_file(path).diagnostics == []
    # Text, as it comes from the command line, read as the declared int.
    found = lint.check_file(path, parameter_overrides={object_name: {"count": "4"}}).diagnostics
    assert [d.message for d in found] == ["unexpected property 'locaton'"]


def test_an_override_for_another_object_or_parameter_changes_nothing(tmp_path):
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n    parameters:\n      count: 2\n", SIZED)
    overrides = {"other": {"count": "4"}, "thing": {"undeclared": "4"}}
    assert lint.check_file(str(root / "thing.assy"), parameter_overrides=overrides).diagnostics == []


def test_an_include_path_is_where_an_include_is_also_looked_for(tmp_path):
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n", "links:\n{% include 'legs.yaml' %}\n")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "legs.yaml").write_text("  - part: leg\n    locaton: 1\n")
    path = str(root / "thing.assy")
    # Not found, it is checked as if its values were unknown; found, as it renders.
    assert lint.check_file(path).diagnostics == []
    found = lint.check_file(path, include_paths=[str(shared)]).diagnostics
    assert [(d.message, d.line) for d in found] == [("unexpected property 'locaton'", 1)]
