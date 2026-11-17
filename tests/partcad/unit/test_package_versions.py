#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A package at a revision: '[<path>/]<name>@<revision>' (see 'partcad.package_versions').

Against a real repository, written with pygit2 into a temporary directory, and a
real context of it: what a revision is loaded as, what it is another name of,
what a reference inside it reaches, which commits a package's history lists,
and what the Revisions tab and the Used By views are told about it.
"""

import asyncio
import os

import pygit2
import pytest
import yaml

import partcad as pc
from partcad import package_versions, requirements
from partcad import revision as pc_revision
from partcad import revisions, usage


def _commit(path, message, tag=None) -> str:
    repo = pygit2.Repository(str(path))
    index = repo.index
    index.add_all()
    index.write()
    tree = index.write_tree()
    signature = pygit2.Signature("Test", "test@example.com", 1_700_000_000, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    oid = repo.create_commit("HEAD", signature, signature, message, tree, parents)
    if tag is not None:
        repo.references.create("refs/tags/%s" % tag, oid)
    return str(oid)


def _write(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False))


def _cube(length):
    return {"type": "basic", "desc": "A cube", "cuboid": length}


@pytest.fixture
def repo(tmp_path):
    """A package with a history: 'first' (tagged v1), then 'second', then an edit not committed."""
    root = tmp_path / "repo"
    pygit2.init_repository(str(root))
    _write(root / "partcad.yaml", {"name": "//", "desc": "version one", "parts": {"cube": _cube(10)}})
    _write(root / "sub" / "partcad.yaml", {"parts": {"peg": {"type": "alias", "source": "//:cube"}}})
    first = _commit(root, "first", tag="v1")
    _write(root / "partcad.yaml", {"name": "//", "desc": "version two", "parts": {"cube": _cube(20)}})
    second = _commit(root, "second")
    # Uncommitted: what the working tree is now, and no revision is.
    _write(root / "partcad.yaml", {"name": "//", "desc": "version two", "parts": {"cube": _cube(30)}})
    return root, first, second


@pytest.fixture
def ctx(repo, tmp_path, monkeypatch):
    root, _, _ = repo
    context = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))
    return context


# ---- names -----------------------------------------------------------------


def test_a_name_with_no_revision_is_not_versioned():
    assert package_versions.split("//pub/std") is None
    assert not package_versions.is_versioned("//pub/std")
    assert package_versions.candidates("//pub/std") == []


def test_a_revision_is_everything_after_the_at():
    assert package_versions.split("//pub/std@v1.2") == ("//pub/std", "v1.2")
    assert package_versions.split("//@abc") == ("//", "abc")


def test_a_branch_with_a_slash_is_tried_before_a_package_inside_a_revision():
    assert package_versions.candidates("//a@feature/x/sub") == [
        ("//a", "feature/x/sub", ""),
        ("//a", "feature/x", "sub"),
        ("//a", "feature", "x/sub"),
    ]


def test_the_package_a_versioned_name_is_a_revision_of():
    assert package_versions.unversioned("//a@abc/sub") == "//a/sub"
    assert package_versions.unversioned("//a@abc") == "//a"
    assert package_versions.unversioned("//@abc/sub") == "//sub"
    assert package_versions.unversioned("//a") == "//a"


@pytest.mark.parametrize("revision", ["", "a:b", "a;b", "a b", "a@b"])
def test_what_cannot_be_a_revision_is_refused(revision):
    with pytest.raises(ValueError):
        package_versions.check_revision(revision)


@pytest.mark.parametrize(
    "package_name, pattern, expected",
    [
        # The revision's own package, and everything under it, is the revision's.
        ("//a@s", "//a:x", "//a@s:x"),
        ("//a@s/sub", "//a/other:y", "//a@s/other:y"),
        ("//@s/sub", "//:cube", "//@s:cube"),
        ("//@s", "//pub/std:bolt", "//@s/pub/std:bolt"),
        # Anything else is left as it is.
        ("//a@s", "//b:x", "//b:x"),
        ("//a@s", "//ab:x", "//ab:x"),
        ("//a@s", "//builtin/render:svg", "//builtin/render:svg"),
        ("//a@s", "//a@t:x", "//a@t:x"),
        ("//a@s", ":x", ":x"),
        ("//a", "//a:x", "//a:x"),
        # A parameter value is the user's text, whatever it holds.
        ("//a@s", "//a:x;m=//b:c", "//a@s:x;m=//b:c"),
    ],
)
def test_a_reference_written_inside_a_revision_stays_inside_it(package_name, pattern, expected):
    assert package_versions.rebase(package_name, pattern) == expected


# ---- loading a revision ----------------------------------------------------


def test_a_package_without_a_revision_is_the_working_tree_as_before(ctx):
    assert ctx.root.name == "//"
    assert ctx.get_part("//:cube").config["cuboid"] == 30


def test_a_revision_is_loaded_under_its_commit_and_answers_to_its_tag(ctx, repo):
    _, first, _ = repo

    project = ctx.get_project("//@v1")

    assert project is not None
    assert project.name == "//@%s" % first
    assert project.revision_sha == first
    assert project.revision_of == "//"
    assert project.config_obj["desc"] == "version one"
    # The tag is another name of it, not a second copy.
    assert ctx.project_aliases["//@v1"] == project.name
    assert ctx.get_project("//@%s" % first) is project
    assert ctx.get_project("//@%s" % first[:8]) is project
    assert "//@v1" not in ctx.projects


def test_an_object_of_a_revision_is_that_revision_s_and_the_working_tree_s_is_untouched(ctx, repo):
    _, first, second = repo

    assert ctx.get_part("//@v1:cube").config["cuboid"] == 10
    assert ctx.get_part("//@%s:cube" % second).config["cuboid"] == 20
    assert ctx.get_part("//:cube").config["cuboid"] == 30
    assert ctx.get_part("//@v1:cube").project_name == "//@%s" % first


def test_the_files_come_from_the_git_cache_never_from_the_working_tree(ctx, repo, tmp_path):
    root, first, _ = repo

    project = ctx.get_project("//@v1")

    assert os.path.realpath(project.config_dir).startswith(os.path.realpath(str(tmp_path / "state" / "git")))
    assert package_versions.exported_sha(project.config_dir) == first
    # Written out of the repository, not a repository of its own.
    assert package_versions.repository_of(project.config_dir) is None
    assert pc_revision.package_revision(project) == first
    assert os.path.realpath(str(root)) != os.path.realpath(project.config_dir)


def test_a_package_inside_a_revision_is_reached_from_the_revision(ctx, repo):
    _, first, _ = repo

    sub = ctx.get_project("//@v1/sub")

    assert sub is not None
    assert sub.name == "//@%s/sub" % first
    assert pc_revision.package_revision(sub) == first
    # A reference it makes to the root it was written beside is to the root at
    # the same revision.
    peg = ctx.get_part("//@v1/sub:peg")
    assert peg.config["source_resolved"] == "//@%s:cube" % first


def test_a_revision_nothing_names_is_not_a_package(ctx):
    assert ctx.get_project("//@no-such-tag") is None


def test_a_package_in_no_repository_has_no_revisions(tmp_path, monkeypatch):
    _write(tmp_path / "plain" / "partcad.yaml", {"name": "//", "parts": {"cube": _cube(10)}})
    context = pc.Context(str(tmp_path / "plain"), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))

    assert context.get_project("//@v1") is None
    assert revisions.history(context, context.root) == {
        "package": "//",
        "published": False,
        "head": None,
        "revisions": [],
    }


# ---- history and comparison ------------------------------------------------


def test_the_history_is_the_commits_that_changed_the_package_newest_first(ctx, repo):
    _, first, second = repo

    history = revisions.history(ctx, ctx.root)

    assert history["published"] is True
    assert history["head"] == second
    assert [entry["sha"] for entry in history["revisions"]] == [second, first]
    assert [entry["short"] for entry in history["revisions"]] == [second[:8], first[:8]]
    assert history["revisions"][0]["summary"] == "second"


def test_a_package_that_shares_a_repository_lists_only_its_own_commits(ctx, repo):
    _, first, _ = repo

    history = revisions.history(ctx, ctx.get_project("//sub"))

    assert [entry["sha"] for entry in history["revisions"]] == [first]


def test_a_revision_s_history_is_its_package_s(ctx, repo):
    _, first, second = repo

    history = revisions.history(ctx, ctx.get_project("//@v1"))

    assert history["package"] == "//"
    assert [entry["sha"] for entry in history["revisions"]] == [second, first]


def test_an_object_is_compared_as_pc_copy_would_write_it(ctx, repo):
    _, first, _ = repo

    compared = revisions.compare(ctx, ctx.root, "part", "cube", first)

    assert compared["revision"] == first
    assert compared["short"] == first[:8]
    assert compared["same"] is False
    changed = [row for row in compared["rows"] if row["tag"] != "equal"]
    assert changed == [
        {"tag": "replace", "left": "  cuboid: 10", "right": "  cuboid: 30", "leftLine": 4, "rightLine": 4}
    ]
    # Nothing PartCAD derives is on either side.
    assert not any("orig_name" in (row["left"] or "") for row in compared["rows"])


def test_a_package_is_compared_by_its_rendered_configuration(ctx, repo):
    _, first, _ = repo

    compared = revisions.compare(ctx, ctx.root, "package", None, first)

    lefts = [row["left"] for row in compared["rows"] if row["tag"] == "replace"]
    rights = [row["right"] for row in compared["rows"] if row["tag"] == "replace"]
    assert "desc: version one" in lefts
    assert "desc: version two" in rights


def test_an_object_not_declared_at_the_revision_is_compared_with_nothing(ctx, repo):
    root, first, _ = repo
    _write(root / "partcad.yaml", {"name": "//", "parts": {"cube": _cube(30), "new": _cube(1)}})
    context = pc.Context(str(root), search_root=False)
    context.user_config.internal_state_dir = ctx.user_config.internal_state_dir

    compared = revisions.compare(context, context.root, "part", "new", first)

    assert compared["left"]["missing"] is True
    assert compared["right"]["missing"] is False
    assert {row["tag"] for row in compared["rows"]} == {"insert"}


def test_side_by_side_pairs_changed_lines_and_leaves_a_gap_for_the_rest():
    rows = revisions.side_by_side("a\nb\nc\n", "a\nB\nc\nd\n")

    assert [row["tag"] for row in rows] == ["equal", "replace", "equal", "insert"]
    assert rows[1]["left"] == "b" and rows[1]["right"] == "B"
    assert rows[3]["left"] is None and rows[3]["leftLine"] is None and rows[3]["rightLine"] == 4


# ---- uses and used by ------------------------------------------------------


def test_what_uses_an_object_is_counted_among_what_is_loaded(ctx):
    assert usage.object_used_by(ctx, "//", "cube") == []

    ctx.get_project("//sub")

    assert usage.object_used_by(ctx, "//", "cube") == [
        {"object": "//sub:peg", "package": "//sub", "name": "peg", "kind": "part", "count": 1}
    ]


def test_what_uses_a_revision_is_what_names_it_by_any_of_its_names(ctx, repo, tmp_path):
    root, first, _ = repo
    _write(
        root / "users" / "partcad.yaml",
        {
            "parts": {
                "old": {"type": "alias", "source": "//@v1:cube"},
                "pinned": {"type": "alias", "source": "//@%s:cube" % first},
            }
        },
    )
    context = pc.Context(str(root), search_root=False)
    context.user_config.internal_state_dir = str(tmp_path / "state")
    context.get_project("//users")
    # Loaded, as the IDE would have by the time anyone asked.
    context.get_part("//users:old")

    used = usage.revision_used_by(context, "//", first)

    assert [(row["object"], row["count"]) for row in used] == [("//users:old", 1), ("//users:pinned", 1)]
    # The working tree's own objects use the working tree, not the revision.
    assert not any(row["package"].startswith("//@") for row in used)


def test_an_assembly_that_places_one_part_twice_uses_it_twice(ctx, repo, tmp_path):
    root, first, _ = repo
    _write(root / "users" / "partcad.yaml", {"assemblies": {"pair": {"type": "assy"}}})
    (root / "users" / "pair.assy").write_text(
        yaml.safe_dump(
            {
                "links": [
                    {"part": "cube", "package": "//@v1", "location": [[0, 0, 0], [0, 0, 1], 0]},
                    {"part": "cube", "package": "//@v1", "location": [[20, 0, 0], [0, 0, 1], 0]},
                ]
            }
        )
    )
    context = pc.Context(str(root), search_root=False)
    context.user_config.internal_state_dir = str(tmp_path / "state")
    assembly = context.get_assembly("//users:pair")
    asyncio.run(assembly.do_instantiate())

    used = usage.revision_used_by(context, "//", first)

    assert [(row["object"], row["count"]) for row in used] == [("//users:pair", 2)]


def test_the_dependencies_of_a_revision_each_with_its_commit(ctx, repo):
    _, first, _ = repo

    rows = usage.dependencies(ctx, ctx.get_project("//@v1"))

    # The fixture declares none: a package's sub-folders are not its dependencies.
    assert rows == []


# ---- a package's own requirements ------------------------------------------


def test_a_package_requires_features_and_what_every_part_has():
    declaration = requirements.parse_package({"features": {"bolts": "metric bolts"}, "has_weight": True})

    assert declaration.features == {"bolts": "metric bolts"}
    assert [entry.name for entry in declaration.has] == ["has_weight"]
    assert declaration.problems == []


def test_what_only_one_object_can_have_is_not_a_package_s_requirement():
    declaration = requirements.parse_package({"ports": {"top": None}, "physics": {"mass": ">0"}})

    assert sorted(problem.section for problem in declaration.problems) == ["physics", "ports"]
    assert declaration.ports == [] and declaration.physics == []


def test_a_package_s_requirements_are_read_from_its_configuration(tmp_path):
    _write(
        tmp_path / "pkg" / "partcad.yaml",
        {"name": "//", "requirements": {"features": {"cubes": "has cubes"}}, "parts": {"cube": _cube(10)}},
    )
    context = pc.Context(str(tmp_path / "pkg"), search_root=False)

    report = asyncio.run(requirements.check_package_async(context, context.root, verify=False)).to_dict()

    assert report["kind"] == "package"
    assert report["defined"] is True
    assert [feature["name"] for feature in report["features"]] == ["cubes"]
    assert report["requirements"] == []


def test_a_package_that_states_no_requirements_has_none(ctx):
    report = asyncio.run(requirements.check_package_async(ctx, ctx.root, verify=True)).to_dict()

    assert report["defined"] is False
