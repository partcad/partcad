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


def test_an_object_not_declared_at_the_revision_is_compared_with_nothing(ctx, repo, monkeypatch):
    root, first, _ = repo
    _write(root / "partcad.yaml", {"name": "//", "parts": {"cube": _cube(30), "new": _cube(1)}})
    context = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", ctx.user_config.internal_state_dir)

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


def test_what_uses_a_revision_is_what_names_it_by_any_of_its_names(ctx, repo, tmp_path, monkeypatch):
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
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))
    context.get_project("//users")
    # Loaded, as the IDE would have by the time anyone asked.
    context.get_part("//users:old")

    used = usage.revision_used_by(context, "//", first)

    assert [(row["object"], row["count"]) for row in used] == [("//users:old", 1), ("//users:pinned", 1)]
    # The working tree's own objects use the working tree, not the revision.
    assert not any(row["package"].startswith("//@") for row in used)


def test_an_assembly_that_places_one_part_twice_uses_it_twice(ctx, repo, tmp_path, monkeypatch):
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
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))
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


def test_a_yes_or_no_requirement_of_a_package_with_no_parts_holds(tmp_path):
    _write(tmp_path / "empty" / "partcad.yaml", {"name": "//", "requirements": {"has_weight": True}})
    context = pc.Context(str(tmp_path / "empty"), search_root=False)

    report = asyncio.run(requirements.check_package_async(context, context.root, verify=True)).to_dict()

    assert report["verified"] is True
    assert [(check["name"], check["passed"]) for check in report["requirements"]] == [("has_weight", True)]
    assert report["requirements"][0]["detail"] == "the package declares no parts"


def test_a_package_whose_parts_draw_on_nothing_else_has_no_dependencies(tmp_path, monkeypatch):
    _write(
        tmp_path / "own" / "partcad.yaml",
        {
            "name": "//",
            "requirements": {"has_dependencies": False, "has_private_dependencies": False},
            "parts": {"cube": _cube(10), "copy": {"type": "alias", "source": ":cube"}},
        },
    )
    context = pc.Context(str(tmp_path / "own"), search_root=False)

    async def built(self, ctx):
        # Nothing to build: what a part is in is not what this is about.
        self._metadata = {}
        return object()

    import partcad.part

    # Through monkeypatch, which takes the attribute off 'Part' again: 'Part'
    # inherits 'get_wrapped', and putting back what 'Part.get_wrapped' read
    # would leave 'Shape's method set on 'Part', where every later test that
    # patches 'Shape.get_wrapped' no longer reaches a part.
    monkeypatch.setattr(partcad.part.Part, "get_wrapped", built)
    report = asyncio.run(requirements.check_package_async(context, context.root, verify=True)).to_dict()

    assert {(check["name"], check["passed"]) for check in report["requirements"]} == {
        ("has_dependencies", True),
        ("has_private_dependencies", True),
    }


def test_unified_is_what_git_diff_writes():
    text = revisions.unified("a\nb\nc\n", "a\nB\nc\n", "//@x:o", "//:o", context=1)

    assert text == "--- //@x:o\n+++ //:o\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
    assert revisions.unified("same\n", "same\n", "x", "y") == ""


def test_unified_says_where_a_last_line_has_no_newline():
    text = revisions.unified("a", "b", "x", "y")

    assert text.splitlines()[-1] == "\\ No newline at end of file"


def test_load_workspace_loads_what_is_in_the_checkout_and_no_download(ctx):
    assert "//sub" not in ctx.projects

    usage.load_workspace(ctx)

    assert "//sub" in ctx.projects


# ---- what review found ------------------------------------------------------


def test_an_lfs_pointer_whose_id_is_not_a_sha256_is_never_read(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    repo = pygit2.init_repository(str(tmp_path / "r"))
    pointer = ("version https://git-lfs.github.com/spec/v1\noid sha256:%s\nsize 7\n" % secret).encode()

    assert package_versions._lfs_object(repo, pointer) is None


def test_a_commit_holding_the_export_guard_is_not_written_out(tmp_path):
    root = tmp_path / "evil"
    pygit2.init_repository(str(root))
    _write(root / "partcad.yaml", {"name": "//", "parts": {"cube": _cube(1)}})
    target = tmp_path / "victim.txt"
    target.write_text("keep me")
    os.symlink(str(target), str(root / package_versions.GUARD))
    sha = _commit(root, "first", tag="v1")
    # Not through 'repository_of', which the guard in the working tree already
    # turns away: what is pinned is that writing the commit out refuses it.
    repository = package_versions.Repository(pygit2.Repository(str(root)), "")
    cache = tmp_path / "state" / "git"

    with pytest.raises(Exception):
        package_versions.export(repository, sha, str(cache))
    assert target.read_text() == "keep me"
    # Nothing written out, half or whole: what is left is the export's lock.
    assert not [name for name in os.listdir(cache) if os.path.isdir(cache / name)]


def test_a_revision_inside_a_revision_is_read_as_one(ctx, repo):
    # 'sub' at v1 is in the export, which is no repository of its own: it has
    # no revisions, and is not taken for a sub-package named 'sub@main'.
    assert ctx.get_project("//@v1/sub@main") is None
    assert package_versions.selector_candidates("v1/sub@main") == [("v1", "sub@main")]
    assert package_versions.selector_candidates("feature/x") == [("feature/x", ""), ("feature", "x")]


def test_a_package_deleted_and_made_again_keeps_its_history(tmp_path, monkeypatch):
    root = tmp_path / "again"
    pygit2.init_repository(str(root))
    _write(root / "partcad.yaml", {"name": "//"})
    _write(root / "sub" / "partcad.yaml", {"parts": {"a": _cube(1)}})
    made = _commit(root, "made")
    import shutil

    shutil.rmtree(str(root / "sub"))
    deleted = _commit(root, "deleted")
    _write(root / "sub" / "partcad.yaml", {"parts": {"a": _cube(2)}})
    again = _commit(root, "made again")
    context = pc.Context(str(root), search_root=False)

    history = revisions.history(context, context.get_project("//sub"))

    assert [entry["sha"] for entry in history["revisions"]] == [again, deleted, made]


def test_load_workspace_leaves_what_the_root_downloads(tmp_path):
    root = tmp_path / "ws"
    _write(
        root / "partcad.yaml",
        {"name": "//", "dependencies": {"far": {"type": "git", "url": "https://example.invalid/far.git"}}},
    )
    _write(root / "near" / "partcad.yaml", {"parts": {"a": _cube(1)}})
    context = pc.Context(str(root), search_root=False)

    usage.load_workspace(context)

    assert "//near" in context.projects
    assert "//far" not in context.projects


def test_a_package_no_part_of_which_may_have_a_material_fails_when_one_has(tmp_path, monkeypatch):
    _write(
        tmp_path / "mixed" / "partcad.yaml",
        {"name": "//", "requirements": {"has_material": False}, "parts": {"a": _cube(1), "b": _cube(2)}},
    )
    context = pc.Context(str(tmp_path / "mixed"), search_root=False)

    async def lacking(ctx, parts, component, where, shape=None):
        # 'a' is in a material, 'b' is not.
        return ([] if parts[0].name == "a" else ["//:b: no material"]), []

    monkeypatch.setattr(requirements, "_parts_lacking", lacking)

    report = asyncio.run(requirements.check_package_async(context, context.root, verify=True)).to_dict()

    (check,) = report["requirements"]
    assert check["passed"] is False
    assert "//:a" in check["detail"]


def test_a_dependency_of_the_root_is_not_its_own(tmp_path, monkeypatch):
    _write(tmp_path / "own" / "partcad.yaml", {"name": "//"})
    _write(tmp_path / "own" / "sub" / "partcad.yaml", {"parts": {"a": _cube(1)}})
    context = pc.Context(str(tmp_path / "own"), search_root=False)
    context.get_project("//sub")
    downloaded = tmp_path / "state" / "git" / "abc"
    _write(downloaded / "partcad.yaml", {"parts": {"b": _cube(1)}})
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))
    context.projects["//pub"] = pc.Context(str(downloaded), search_root=False).root

    assert requirements._is_own(context, context.root, "//sub")
    assert not requirements._is_own(context, context.root, "//pub")
    assert not requirements._is_own(context, context.root, "//nowhere")


def test_nothing_is_written_into_a_revision(ctx):
    at_v1 = ctx.get_project("//@v1")

    assert at_v1.not_written_to() is not None
    assert at_v1.add_object_config("parts", "x", {"type": "basic", "cuboid": 1}) is False
    with pytest.raises(ValueError):
        at_v1.edit_object_declaration("part", "cube", lambda declaration: None)
    with pytest.raises(ValueError):
        at_v1.edit_package_declaration(lambda declaration: None)
    assert ctx.root.not_written_to() is None


def test_a_placement_with_parameter_values_uses_the_object_it_is_of():
    class Item:
        project_name = "//"
        name = "cube;length=10"

    class Child:
        item = Item()

    class Built:
        children = [Child(), Child()]

    class Project:
        name = "//users"

        def objects(self, kind):
            return {"pair": Built()}

        def resolve(self, value):
            return ("//", value)

    class Ctx:
        project_aliases = {}
        projects = {}

    count = usage._uses(Ctx(), Project(), "assembly", "pair", {"type": "assy"}, lambda p, n: (p, n) == ("//", "cube"))

    assert count == 2


def _downloaded(tmp_path, monkeypatch):
    """A package with a history, kept where PartCAD keeps what it downloads, and a context of it."""
    state = tmp_path / "state"
    checkout = state / "git" / "0123456789abcdef-main"
    pygit2.init_repository(str(checkout))
    _write(checkout / "partcad.yaml", {"name": "//", "parts": {"cube": _cube(1)}})
    _write(checkout / "sub" / "partcad.yaml", {"parts": {"peg": {"type": "alias", "source": "//:cube"}}})
    sha = _commit(checkout, "first")
    context = pc.Context(str(checkout), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(state))
    return context, checkout, sha


def test_a_downloaded_package_at_the_commit_it_is_checked_out_at_is_a_revision_of_its_own(tmp_path, monkeypatch):
    context, checkout, sha = _downloaded(tmp_path, monkeypatch)
    assert context.is_downloaded(context.root)

    at_head = context.get_project("//@" + sha)

    assert at_head is not context.root
    assert at_head.not_written_to() is not None
    assert context.root.not_written_to() is None
    # Beside the checkout, under a name no checkout has, and the checkout untouched.
    export = os.path.dirname(os.path.realpath(at_head.config_path))
    assert os.path.basename(export).startswith(package_versions.EXPORT_PREFIX)
    assert os.path.realpath(checkout) != export
    assert (checkout / ".git").exists()


def test_a_downloaded_package_s_own_sub_package_is_its_own(tmp_path, monkeypatch):
    context, _, _ = _downloaded(tmp_path, monkeypatch)
    context.get_project("//sub")
    elsewhere = tmp_path / "state" / "git" / "fedcba9876543210-main"
    _write(elsewhere / "partcad.yaml", {"parts": {"b": _cube(1)}})
    context.projects["//far"] = pc.Context(str(elsewhere), search_root=False).root

    assert requirements._is_own(context, context.root, "//sub")
    assert not requirements._is_own(context, context.root, "//far")


def test_each_revision_along_a_name_is_read_as_the_commit_it_names(ctx, repo, tmp_path):
    _, first, _ = repo
    dep = tmp_path / "dep"
    pygit2.init_repository(str(dep))
    _write(dep / "partcad.yaml", {"parts": {"a": _cube(1)}})
    inner = _commit(dep, "dep", tag="v2")
    outer = "//@" + first
    assert ctx.get_project("//@v1") is not None
    # A dependency of the revision, with a history of its own, loaded already.
    ctx.projects[outer + "/dep"] = pc.Context(str(dep), search_root=False).root
    ctx.get_project("//sub")

    assert usage._canonical(ctx, "//sub@v1") == "//sub@" + first
    assert usage._canonical(ctx, "//@v1/dep@v2") == "%s/dep@%s" % (outer, inner)
    # A package in no repository of its own keeps the revision it was asked at.
    assert usage._canonical(ctx, "//@v1/sub@v1") == "%s/sub@v1" % outer


def test_no_direct_writer_writes_into_a_revision(ctx):
    at_v1 = ctx.get_project("//@v1")
    before = open(at_v1.config_path, encoding="utf-8").read()

    with pytest.raises(ValueError):
        at_v1.set_part_config("cube", {"type": "basic", "cuboid": 1})
    with pytest.raises(ValueError):
        at_v1.update_part_config("cube", {"cuboid": 1})
    with pytest.raises(ValueError):
        at_v1.set_sketch_config("s", {"type": "basic", "circle": 1})
    assert at_v1.add_import("x", "../x") is False
    assert open(at_v1.config_path, encoding="utf-8").read() == before


# ---- the third review -------------------------------------------------------


def test_an_empty_lfs_object_is_written_out_as_an_empty_file(tmp_path):
    import hashlib

    root = tmp_path / "lfs"
    repo = pygit2.init_repository(str(root))
    oid = hashlib.sha256(b"").hexdigest()
    store = root / ".git" / "lfs" / "objects" / oid[0:2] / oid[2:4]
    store.mkdir(parents=True)
    (store / oid).write_bytes(b"")
    pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:%s\nsize 0\n" % oid
    (root / "empty.bin").write_text(pointer)
    _write(root / "partcad.yaml", {"name": "//"})
    sha = _commit(root, "first")

    dest = package_versions.export(package_versions.Repository(repo, ""), sha, str(tmp_path / "state" / "git"))

    assert (tmp_path / "state" / "git" / os.path.basename(dest) / "empty.bin").read_bytes() == b""


def test_a_sub_folder_of_a_revision_has_no_revisions_of_its_own_and_says_where_they_are(ctx, caplog):
    assert ctx.get_project("//@v1/sub@main") is None
    assert "name it as //sub@main" in caplog.text


# ---- the edges of reading a repository ----------------------------------------


def test_a_repository_with_nothing_committed_has_no_head_and_no_history(tmp_path):
    repo = pygit2.init_repository(str(tmp_path / "empty"))
    repository = package_versions.Repository(repo, "")

    assert repository.head() is None
    assert package_versions.revisions(repository) == []


def test_what_is_in_no_repository_has_none(tmp_path):
    assert package_versions.repository_of(str(tmp_path / "missing")) is None
    assert package_versions.repository_of("") is None
    assert package_versions.exported_sha("") is None


def test_a_bare_repository_has_no_working_tree_to_be_in(tmp_path):
    pygit2.init_repository(str(tmp_path / "bare.git"), bare=True)

    assert package_versions.repository_of(str(tmp_path / "bare.git")) is None


def test_an_unreadable_guard_says_no_commit(tmp_path, monkeypatch):
    (tmp_path / package_versions.GUARD).write_text("abc")
    real_open = open

    def refusing(path, *args, **kwargs):
        if str(path).endswith(package_versions.GUARD):
            raise OSError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refusing)

    assert package_versions.exported_sha(str(tmp_path)) is None


def test_a_revision_a_downloaded_copy_lacks_is_fetched_once(repo, monkeypatch):
    root, first, _ = repo
    from partcad import project_factory_git

    asked = []

    def fetch(repository, revision, depth=None, user_config=None):
        asked.append(revision)
        raise RuntimeError("offline")

    monkeypatch.setattr(project_factory_git, "_fetch", fetch)
    repository = package_versions.Repository(pygit2.Repository(str(root)), "")

    with pytest.raises(ValueError):
        package_versions.resolve(repository, "nowhere", fetch=True)
    assert asked == ["nowhere"]
    assert package_versions.resolve(repository, "v1", fetch=True) == first


def test_a_tree_is_written_out_as_a_checkout_would_be(tmp_path):
    root = tmp_path / "kinds"
    repo = pygit2.init_repository(str(root))
    _write(root / "partcad.yaml", {"name": "//"})
    (root / "run.sh").write_text("#!/bin/sh\n")
    os.chmod(str(root / "run.sh"), 0o755)
    os.symlink("partcad.yaml", str(root / "link.yaml"))
    sha = _commit(root, "first")
    repository = package_versions.Repository(repo, "")
    cache = tmp_path / "state" / "git"

    dest = package_versions.export(repository, sha, str(cache))

    assert os.access(os.path.join(dest, "run.sh"), os.X_OK)
    link = os.path.join(dest, "link.yaml")
    # A link where the system makes one, and its target as text where it will not (as git does).
    assert os.readlink(link) == "partcad.yaml" if os.path.islink(link) else open(link).read() == "partcad.yaml"
    # Written once: asked again, it is the same directory, not written again.
    assert package_versions.export(repository, sha, str(cache)) == dest


def test_a_half_written_export_is_replaced_and_a_missing_commit_is_refused(tmp_path):
    root = tmp_path / "half"
    repo = pygit2.init_repository(str(root))
    _write(root / "partcad.yaml", {"name": "//"})
    sha = _commit(root, "first")
    repository = package_versions.Repository(repo, "")
    cache = tmp_path / "state" / "git"
    from partcad.project_factory_git import cache_dir_name

    half = cache / (package_versions.EXPORT_PREFIX + cache_dir_name(repository.identity, sha))
    half.mkdir(parents=True)
    (half / "leftover").write_text("x")

    dest = package_versions.export(repository, sha, str(cache))

    assert not os.path.exists(os.path.join(dest, "leftover"))
    with pytest.raises(ValueError, match="missing"):
        package_versions.export(repository, "0" * 40, str(cache))


def test_a_history_stops_where_its_shallow_copy_does(repo, monkeypatch):
    root, first, second = repo
    repository = package_versions.Repository(pygit2.Repository(str(root)), "")

    assert [entry["sha"] for entry in package_versions.revisions(repository, limit=1)] == [second]
    monkeypatch.setattr(package_versions, "REVISIONS_SCAN_LIMIT", 1)
    assert [entry["sha"] for entry in package_versions.revisions(repository)] == [second]


# ---- what refers to what, at the edges ----------------------------------------


def test_a_revision_nothing_names_is_left_as_written_and_a_path_below_one_is_read(ctx, repo):
    _, first, _ = repo

    assert usage._canonical(ctx, "//sub@nowhere") == "//sub@nowhere"
    assert usage._canonical(ctx, "//@v1/sub") == "//@%s/sub" % first


@pytest.mark.parametrize(
    "config, found",
    [
        ({"sketch": "outline"}, [("//", "outline")]),
        ({"implements": ["//other:pad;size=3", "a b:c", "https://x.org/a:b"]}, [("//other", "pad")]),
        ("//other:cube", [("//other", "cube")]),
        (7, []),
    ],
)
def test_what_a_declaration_refers_to(ctx, config, found):
    assert usage.references(ctx.root, "part", config) == found


def test_a_reference_that_cannot_be_read_is_not_counted(ctx, monkeypatch):
    from partcad import reference as pc_reference

    def broken(*args, **kwargs):
        raise ValueError("no")

    monkeypatch.setattr(ctx.root, "resolve", broken)
    monkeypatch.setattr(pc_reference, "source_of", broken)

    assert usage.references(ctx.root, "part", {"type": "alias", "source": ":cube", "x": "//other:y"}) == []


def test_a_declaration_nested_too_deep_is_not_followed(ctx):
    config = current = {}
    for _ in range(40):
        current["nested"] = {}
        current = current["nested"]
    current["source"] = "//other:deep"

    assert usage.references(ctx.root, "part", config) == []


def test_what_uses_anything_in_a_package_and_what_could_not_be_read(ctx, monkeypatch):
    rows = usage.package_used_by(ctx, "//")
    assert rows == []

    def broken(*args, **kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(usage, "_uses", broken)
    assert usage.object_used_by(ctx, "//", "cube") == []


def test_load_workspace_goes_on_past_a_package_that_will_not_load(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    _write(root / "partcad.yaml", {"name": "//"})
    _write(root / "near" / "partcad.yaml", {"parts": {"a": _cube(1)}})
    context = pc.Context(str(root), search_root=False)
    real = context.get_project

    def refusing(name):
        if name == "//near":
            raise RuntimeError("broken")
        return real(name)

    monkeypatch.setattr(context, "get_project", refusing)

    assert usage.load_workspace(context) == 1


def test_a_dependency_is_listed_at_the_commit_it_is_at(tmp_path, monkeypatch):
    root = tmp_path / "deps"
    pygit2.init_repository(str(root))
    pinned = "a" * 40
    _write(
        root / "partcad.yaml",
        {
            "name": "//",
            "dependencies": {
                "near": {"type": "local", "path": "near"},
                "far": {"type": "git", "url": "https://example.invalid/far.git", "revision": pinned},
            },
        },
    )
    _write(root / "near" / "partcad.yaml", {"parts": {"a": _cube(1)}})
    sha = _commit(root, "first")
    context = pc.Context(str(root), search_root=False)
    real = context.get_project
    # Nothing downloaded: the pinned one is read from its declaration.
    monkeypatch.setattr(context, "get_project", lambda name: None if name == "//far" else real(name))

    rows = {row["name"]: row for row in usage.dependencies(context, context.root)}

    assert rows["near"]["sha"] == sha and rows["near"]["current"] == "//near"
    assert rows["far"]["sha"] == pinned and rows["far"]["current"] is None


# ---- a package's yes-or-no requirements, each way they can come out -------------


def _package(tmp_path, requirements_section, parts=None):
    _write(
        tmp_path / "req" / "partcad.yaml",
        {"name": "//", "requirements": requirements_section, "parts": parts if parts is not None else {}},
    )
    context = pc.Context(str(tmp_path / "req"), search_root=False)
    return context


def _checks(context):
    report = asyncio.run(requirements.check_package_async(context, context.root, verify=True)).to_dict()
    return {check["name"]: (check["passed"], check["detail"]) for check in report["requirements"]}


def test_a_part_that_cannot_be_made_leaves_every_requirement_not_known(tmp_path, monkeypatch):
    context = _package(tmp_path, {"has_material": True, "has_dependencies": False}, {"a": _cube(1), "b": _cube(2)})

    async def broken(name, quiet=False):
        if name == "a":
            raise RuntimeError("no kernel")
        return None

    monkeypatch.setattr(context.root, "get_part_async", broken)

    checks = _checks(context)
    assert checks["has_material"][0] is False and "not known" in checks["has_material"][1]
    assert checks["has_dependencies"][0] is False and "could not be made" in checks["has_dependencies"][1]


def test_every_part_s_mass_is_known_or_not(tmp_path, monkeypatch):
    context = _package(tmp_path, {"has_mass": True}, {"a": _cube(1), "b": _cube(2)})

    async def physics(ctx, part, paths):
        return {"mass": (2.0, "declared") if part.name == "a" else (None, "no density")}

    monkeypatch.setattr(requirements, "resolve_physics_async", physics)

    checks = _checks(context)
    passed, detail = checks.get("has_weight") or checks["has_mass"]
    assert passed is False
    assert "//:b: not known: no density" in detail


def test_a_part_not_built_yet_leaves_the_requirement_not_known(tmp_path, monkeypatch):
    context = _package(tmp_path, {"has_color": True}, {"a": _cube(1)})

    async def lacking(ctx, parts, component, where, shape=None):
        return [], ["//:a is not built"]

    monkeypatch.setattr(requirements, "_parts_lacking", lacking)

    passed, detail = _checks(context)["has_color"]
    assert passed is False and "not built" in detail


def test_a_required_component_a_part_lacks_is_named(tmp_path, monkeypatch):
    context = _package(tmp_path, {"has_finish": True}, {"a": _cube(1)})

    async def lacking(ctx, parts, component, where, shape=None):
        return ["//:a: no finish"], []

    monkeypatch.setattr(requirements, "_parts_lacking", lacking)

    assert _checks(context)["has_finish"] == (False, "//:a: no finish")


def test_what_a_package_s_parts_draw_on(tmp_path, monkeypatch):
    import types

    from partcad import object_dependencies

    context = _package(
        tmp_path,
        {"has_dependencies": False, "has_private_dependencies": True},
        {"a": _cube(1), "b": _cube(2)},
    )

    async def collect(ctx, part):
        if part.name == "b":
            raise RuntimeError("unreadable")
        return types.SimpleNamespace(packages={"//": [":x"], "//far": ["//far:bolt"]}, unknown=[])

    monkeypatch.setattr(object_dependencies, "collect_async", collect)

    checks = _checks(context)
    assert checks["has_dependencies"][0] is False
    assert "required not to draw on another package" in checks["has_dependencies"][1]
    assert checks["has_private_dependencies"][0] is True


def test_a_package_with_no_parts_draws_on_nothing(tmp_path):
    context = _package(tmp_path, {"has_dependencies": False})

    assert _checks(context)["has_dependencies"] == (True, "the package declares no parts")


def test_a_requirement_only_an_object_can_have_is_unreadable_and_a_failure_is_reported(tmp_path, monkeypatch):
    context = _package(tmp_path, {"has_material": True, "ports": {"top": None}}, {"a": _cube(1)})

    async def broken(ctx, project, entries):
        raise RuntimeError("checker broke")

    monkeypatch.setattr(requirements, "_verify_package_has", broken)
    report = asyncio.run(requirements.check_package_async(context, context.root, verify=True)).to_dict()

    unreadable = [check for check in report["requirements"] if check["requirement"] == "unreadable"]
    assert unreadable and unreadable[0]["passed"] is False
    (has,) = [check for check in report["requirements"] if check["name"] == "has_material"]
    assert has["passed"] is False and "checker broke" in has["detail"]


def test_a_package_is_its_own(ctx):
    assert requirements._is_own(ctx, ctx.root, "//")
