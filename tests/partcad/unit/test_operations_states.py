"""Operations over the states of a package: STAGED and WORKTREE, what changed, staging and new revisions, Impact.

Against real repositories written with pygit2 into a temporary directory, and a
real context of each: what 'STAGED' and 'WORKTREE' load, what the change engine
says changed ('partcad.changes'), the revisions of one object, what is staged and
what is not, staging an object's declaration alone, the checks before a new
revision ('partcad.working_copy'), what an object depends on and what depends on
a package ('partcad.usage'), and what a change reaches ('partcad.impact').
"""

import shutil
import subprocess

import pygit2
import pytest
import yaml

import partcad as pc
from partcad import changes, impact, package_versions, revisions, usage, working_copy


def _write(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False))


def _stage(root, *paths):
    repo = pygit2.Repository(str(root))
    index = repo.index
    index.read(True)
    if paths:
        for path in paths:
            index.add(path)
    else:
        index.add_all()
    index.write()


def _commit(root, message) -> str:
    _stage(root)
    repo = pygit2.Repository(str(root))
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test", "test@example.com", 1_700_000_000, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    return str(repo.create_commit("HEAD", signature, signature, message, tree, parents))


def _bolt(desc="A bolt", parameter="length"):
    return {"type": "cadquery", "desc": desc, "parameters": {parameter: {"type": "float", "default": 10}}}


@pytest.fixture
def workspace(tmp_path):
    """A root with two sub-packages: '//lib' declares a bolt, '//app' enriches it into a longer one."""
    root = tmp_path / "ws"
    pygit2.init_repository(str(root))
    # Whatever this machine's git says, this repository does not sign its commits.
    pygit2.Repository(str(root)).config["commit.gpgsign"] = False
    _write(root / "partcad.yaml", {"name": "//"})
    _write(root / "lib" / "partcad.yaml", {"parts": {"bolt": _bolt(), "nut": {"type": "cadquery", "desc": "A nut"}}})
    (root / "lib" / "bolt.py").write_text("x = 1\n")
    (root / "lib" / "nut.py").write_text("y = 1\n")
    (root / "lib" / "bolt.svg").write_text("<svg/>\n")
    _write(
        root / "app" / "partcad.yaml",
        {
            "parts": {
                "long_bolt": {
                    "type": "enrich",
                    "source": "//lib:bolt",
                    "with": {"length": 20},
                    "requirements": [{"name": "Long enough"}],
                }
            }
        },
    )
    first = _commit(root, "first")
    return root, first


@pytest.fixture
def ctx(workspace, tmp_path, monkeypatch):
    root, _ = workspace
    context = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))
    # pygit2 commits, never the git on this machine: no hooks, no signing, no global identity.
    monkeypatch.setattr(working_copy, "_git_executable", lambda: None)
    return context


def _lib(root, **bolt):
    _write(
        root / "lib" / "partcad.yaml", {"parts": {"bolt": _bolt(**bolt), "nut": {"type": "cadquery", "desc": "A nut"}}}
    )


# ---- STAGED and WORKTREE ---------------------------------------------------


def test_staged_is_what_the_index_holds_and_worktree_is_the_files_on_disk(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="A staged bolt")
    _stage(root, "lib/partcad.yaml")
    _lib(root, desc="A bolt on disk")

    staged = ctx.get_project("//lib@STAGED")
    assert staged.object_config("part", "bolt")["desc"] == "A staged bolt"
    assert ctx.get_project("//lib@WORKTREE") is ctx.get_project("//lib")
    assert ctx.get_project("//lib").object_config("part", "bolt")["desc"] == "A bolt on disk"
    assert ctx.get_project("//lib@HEAD").object_config("part", "bolt")["desc"] == "A bolt"
    assert staged.not_written_to() is not None
    # An unchanged index is one package...
    assert ctx.get_project("//lib@STAGED") is staged


def test_staged_is_read_again_once_the_index_has_moved(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="Staged once")
    _stage(root, "lib/partcad.yaml")
    assert ctx.get_project("//lib@STAGED").object_config("part", "bolt")["desc"] == "Staged once"

    _lib(root, desc="Staged twice")
    _stage(root, "lib/partcad.yaml")

    assert ctx.get_project("//lib@STAGED").object_config("part", "bolt")["desc"] == "Staged twice"


def test_the_states_are_not_revisions_and_names_staged_says_so():
    assert package_versions.is_state("STAGED") and package_versions.is_state("WORKTREE")
    assert not package_versions.is_state("staged")
    assert package_versions.names_staged("//a@STAGED/sub")
    assert not package_versions.names_staged("//a@v1/STAGED")
    assert not package_versions.names_staged("//a")


# ---- the change engine -----------------------------------------------------


def test_a_change_of_prose_alone_changes_no_geometry(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="A shiny bolt")

    found = changes.changes(ctx, "//lib", "HEAD", None)

    assert [(row["name"], row["how"], row["geometry"], row["prose"]) for row in found["objects"]] == [
        ("bolt", ["declaration"], False, True)
    ]
    assert found["to"] == "WORKTREE"


def test_a_source_file_is_compared_by_content_and_a_drawing_beside_it_is_not_one(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "bolt.py").write_text("x = 2\n")
    (root / "lib" / "bolt.svg").write_text("<svg>redrawn</svg>\n")

    found = changes.changes(ctx, "//lib", "HEAD", None)

    assert [(row["name"], row["how"], row["geometry"]) for row in found["objects"]] == [("bolt", ["source"], True)]
    assert found["files"] == [{"path": "bolt.svg", "how": "modified"}]


def test_an_object_added_and_one_removed(workspace, ctx):
    root, _ = workspace
    _write(root / "lib" / "partcad.yaml", {"parts": {"bolt": _bolt(), "washer": {"type": "cadquery"}}})
    (root / "lib" / "washer.py").write_text("z = 1\n")

    found = changes.changes(ctx, "//lib", "HEAD", None)

    assert {row["name"]: row["how"] for row in found["objects"]} == {"nut": ["removed"], "washer": ["added"]}


def test_a_package_that_declares_a_dependency_changed_itself(workspace, ctx):
    root, _ = workspace
    _write(root / "app" / "partcad.yaml", {**yaml.safe_load((root / "app" / "partcad.yaml").read_text()), "desc": "x"})

    assert changes.changes(ctx, "//app", "HEAD", None)["package_changed"] is True


# ---- revisions ---------------------------------------------------------------


def test_an_object_lists_only_the_revisions_that_changed_it(workspace, ctx):
    root, first = workspace
    (root / "lib" / "nut.py").write_text("y = 2\n")
    second = _commit(root, "the nut")
    _lib(root, desc="A longer bolt")
    third = _commit(root, "the bolt")

    bolt = revisions.object_history(ctx, ctx.get_project("//lib"), "part", "bolt")
    nut = revisions.object_history(ctx, ctx.get_project("//lib"), "part", "nut")
    package = revisions.history(ctx, ctx.get_project("//lib"))

    assert [(row["sha"], row["how"]) for row in bolt["revisions"]] == [(third, ["declaration"]), (first, ["added"])]
    assert [(row["sha"], row["how"]) for row in nut["revisions"]] == [(second, ["source"]), (first, ["added"])]
    assert [row["sha"] for row in package["revisions"]] == [third, second, first]


def test_a_package_lists_its_revisions_a_page_at_a_time(workspace, ctx):
    root, first = workspace
    (root / "lib" / "nut.py").write_text("y = 2\n")
    second = _commit(root, "second")

    page = revisions.history(ctx, ctx.get_project("//lib"), limit=1)
    rest = revisions.history(ctx, ctx.get_project("//lib"), limit=1, after=page["revisions"][-1]["sha"])

    assert [row["sha"] for row in page["revisions"]] == [second] and page["more"] is True
    assert [row["sha"] for row in rest["revisions"]] == [first] and rest["more"] is False


def test_a_commit_that_changed_only_a_sub_package_says_which(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "nut.py").write_text("y = 2\n")
    _commit(root, "the nut")

    rows = revisions.history(ctx, ctx.root)["revisions"]

    assert rows[0]["in"] == ["lib"]
    assert "in" not in rows[-1]


def test_two_states_are_compared_by_what_they_mean(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="A staged bolt")
    _stage(root, "lib/partcad.yaml")

    compared = revisions.compare_states(ctx, ctx.get_project("//lib"), "part", "bolt", "HEAD", "STAGED")

    assert compared["left"]["label"] != "STAGED" and compared["right"]["label"] == "STAGED"
    assert "-  desc: A bolt" in compared["unified"] and "+  desc: A staged bolt" in compared["unified"]
    package = revisions.compare_states(ctx, ctx.get_project("//lib"), revisions.PACKAGE, None, "HEAD", "STAGED")
    assert [row["name"] for row in package["changes"]["objects"]] == ["bolt"]


# ---- status, staging and new revisions -------------------------------------


def test_status_says_what_is_staged_and_what_is_not_by_object(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="A staged bolt")
    _stage(root, "lib/partcad.yaml")
    (root / "lib" / "nut.py").write_text("y = 2\n")
    (root / "app" / "notes.txt").write_text("elsewhere\n")

    found = working_copy.status(ctx, ctx.get_project("//lib"))

    assert [row["name"] for row in found["staged"]] == ["bolt"]
    assert [row["name"] for row in found["unstaged"]] == ["nut"]
    assert found["index"] == package_versions.index_tree(package_versions.repository_of(str(root / "lib")))
    assert [(entry["directory"], entry["unstaged"]) for entry in found["elsewhere"]] == [("app", 1)]
    assert "nut" in found["advice"]


def test_staging_an_object_stages_its_own_declaration_and_files_and_nothing_else(workspace, ctx):
    root, _ = workspace
    _write(
        root / "lib" / "partcad.yaml",
        {"parts": {"bolt": _bolt(desc="A new bolt"), "nut": {"type": "cadquery", "desc": "A new nut"}}},
    )
    (root / "lib" / "bolt.py").write_text("x = 2\n")
    (root / "lib" / "nut.py").write_text("y = 2\n")

    staged = working_copy.stage(ctx, ctx.get_project("//lib"), "part", "bolt")

    assert "bolt.py" in staged["staged"]
    found = working_copy.status(ctx, ctx.get_project("//lib"))
    assert [row["name"] for row in found["staged"]] == ["bolt"]
    assert [row["name"] for row in found["unstaged"]] == ["nut"]


def test_staging_a_package_stages_its_own_files_and_not_its_sub_packages(workspace, ctx):
    root, _ = workspace
    (root / "README.md").write_text("root\n")
    (root / "lib" / "nut.py").write_text("y = 2\n")

    working_copy.stage(ctx, ctx.root)

    found = working_copy.status(ctx, ctx.root)
    assert [entry["path"] for entry in found["files"] if "staged" in entry["sections"]] == ["README.md"]
    assert [(entry["directory"], entry["staged"], entry["unstaged"]) for entry in found["elsewhere"]] == [("lib", 0, 1)]


def test_stage_declaration_takes_the_lines_of_one_object_only():
    index = "parts:\n  a:\n    desc: A\n  b:\n    desc: B\n"
    work = "parts:\n  a:\n    desc: A2\n  b:\n    desc: B2\n  c:\n    desc: C\n"

    assert working_copy.stage_declaration(index, work, "part", "a") == "parts:\n  a:\n    desc: A2\n  b:\n    desc: B\n"
    assert working_copy.stage_declaration(index, work, "part", "c").endswith("  c:\n    desc: C\n")
    assert working_copy.stage_declaration("{% if x %}", "{% if y %}", "part", "a") is None


def test_a_new_revision_refuses_until_its_terms_are_met_and_then_commits_what_is_staged(workspace, ctx):
    root, first = workspace
    lib = ctx.get_project("//lib")

    with pytest.raises(working_copy.Refused) as nothing:
        working_copy.new_revision(ctx, lib, "Nothing", "part", "bolt")
    assert nothing.value.code == "nothing-staged"

    _lib(root, desc="A new bolt")
    (root / "lib" / "nut.py").write_text("y = 2\n")
    _stage(root, "lib/partcad.yaml", "lib/nut.py")
    looked = working_copy.status(ctx, lib, "part", "bolt")["index"]

    with pytest.raises(working_copy.Refused) as others:
        working_copy.new_revision(ctx, lib, "Bolt", "part", "bolt", expect_index=looked)
    assert others.value.code == "others-staged" and "//lib:nut" in str(others.value)

    with pytest.raises(working_copy.Refused) as failed:
        working_copy.new_revision(
            ctx,
            lib,
            "Bolt",
            "part",
            "bolt",
            include_others=True,
            checks=lambda status: [{"name": "lint", "passed": False}],
        )
    assert failed.value.code == "checks-failed"

    made = working_copy.new_revision(
        ctx,
        lib,
        "Bolt\n\nLonger.",
        "part",
        "bolt",
        author={"name": "Ann", "email": "ann@example.com"},
        expect_index=looked,
        include_others=True,
        checks=lambda status: [{"name": "lint", "passed": True}],
    )

    repo = pygit2.Repository(str(root))
    head = repo[repo.head.target]
    assert made["sha"] == str(head.id) and made["summary"] == "Bolt"
    assert head.author.name == "Ann" and head.parents[0].id == pygit2.Oid(hex=first)
    assert working_copy.status(ctx, lib)["staged"] == []


def test_a_new_revision_of_an_index_that_moved_is_refused(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="A new bolt")
    _stage(root, "lib/partcad.yaml")

    with pytest.raises(working_copy.Refused) as moved:
        working_copy.new_revision(ctx, ctx.get_project("//lib"), "Bolt", expect_index="0" * 40)
    assert moved.value.code == "index-changed"


def test_a_revision_is_never_staged_into():
    class Revision:
        name = "//lib@STAGED"

        def not_written_to(self):
            return "it is a revision"

    with pytest.raises(ValueError):
        working_copy.stage(None, Revision())


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_new_revision_is_made_by_git_where_it_is_installed(workspace, tmp_path, monkeypatch):
    root, _ = workspace
    context = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _lib(root, desc="A new bolt")
    _stage(root, "lib/partcad.yaml")

    made = working_copy.new_revision(
        context, context.get_project("//lib"), "Bolt", author={"name": "Ann", "email": "ann@example.com"}
    )

    log = subprocess.run(
        ["git", "log", "-1", "--format=%H %an %s"], cwd=str(root), capture_output=True, text=True, check=True
    ).stdout.split()
    assert log == [made["sha"], "Ann", "Bolt"]


# ---- dependencies and dependents ---------------------------------------------


def test_an_object_lists_what_it_names_and_how(ctx):
    usage.load_workspace(ctx)

    rows = usage.object_dependencies(ctx, ctx.get_project("//app"), "part", "long_bolt")

    assert [(row["object"], row["how"], row["kind"]) for row in rows] == [("//lib:bolt", ["source (enrich)"], "part")]
    assert usage.object_used_by(ctx, "//lib", "bolt")[0]["how"] == ["source (enrich)"]


def test_a_package_lists_what_it_uses_without_declaring_it_and_its_sub_packages(ctx):
    usage.load_workspace(ctx)

    app = usage.package_dependencies(ctx, ctx.get_project("//app"))
    root = usage.package_dependencies(ctx, ctx.root)

    assert app["undeclared"] == [
        {"package": "//lib", "users": [{"name": "long_bolt", "object": "//app:long_bolt", "kind": "part", "count": 1}]}
    ]
    assert sorted(row["name"] for row in root["subpackages"]) == ["app", "lib"]


def test_a_package_declaring_another_as_a_dependency_is_one_of_its_dependents(workspace, ctx):
    root, _ = workspace
    config = yaml.safe_load((root / "app" / "partcad.yaml").read_text())
    config["dependencies"] = {"lib": {"type": "local", "path": "../lib"}}
    _write(root / "app" / "partcad.yaml", config)
    usage.load_workspace(ctx)

    rows = usage.package_dependents(ctx, ctx.get_project("//app/lib"))

    assert [(row["package"], row["name"], row["type"]) for row in rows] == [("//app", "lib", "local")]


# ---- Impact --------------------------------------------------------------------


def test_impact_finds_a_removed_parameter_that_a_user_passes_and_follows_it_through(workspace, ctx):
    root, _ = workspace
    _lib(root, parameter="size")
    (root / "lib" / "bolt.py").write_text("x = 2\n")
    usage.load_workspace(ctx)

    found = impact.impact(ctx, ctx.get_project("//lib"))

    rows = {row["object"]: row for row in found["affects"]}
    bolt = rows["//lib:bolt"]
    assert bolt["reached"] == "changed"
    assert any(f["severity"] == "breaking" and "'length' removed" in f["summary"] for f in bolt["findings"])
    longer = rows["//app:long_bolt"]
    assert longer["reached"] == "via" and longer["via"] == ["//lib:bolt"]
    assert {f["analyzer"] for f in longer["findings"]} == {"geometry", "requirements"}
    assert found["summary"]["breaking"] == 1


def test_impact_of_what_is_staged_leaves_out_what_is_not(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "bolt.py").write_text("x = 2\n")
    _stage(root, "lib/bolt.py")
    (root / "lib" / "nut.py").write_text("y = 2\n")
    usage.load_workspace(ctx)

    staged = impact.impact(ctx, ctx.get_project("//lib"), before="HEAD", after="STAGED")
    unstaged = impact.impact(ctx, ctx.get_project("//lib"), before="STAGED", after=None)

    assert [row["name"] for row in staged["changed"]] == ["bolt"]
    assert [row["name"] for row in unstaged["changed"]] == ["nut"]


def test_an_object_is_affected_by_what_it_uses_that_changed(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "bolt.py").write_text("x = 2\n")
    usage.load_workspace(ctx)

    found = impact.impact(ctx, ctx.get_project("//app"), "part", "long_bolt")

    assert [(row["object"], row["path"]) for row in found["affected_by"]] == [("//lib:bolt", ["//lib:bolt"])]
    assert found["affects"] == []


def test_a_moved_pin_is_said_with_where_it_was_and_where_it_is(workspace, ctx):
    root, _ = workspace
    config = yaml.safe_load((root / "app" / "partcad.yaml").read_text())
    config["dependencies"] = {"std": {"type": "git", "url": "https://example.com/std.git", "revision": "a" * 40}}
    _write(root / "app" / "partcad.yaml", config)
    _commit(root, "pinned")
    config["dependencies"]["std"]["revision"] = "b" * 40
    _write(root / "app" / "partcad.yaml", config)

    assert impact.moved_pins(ctx, ctx.get_project("//app"), "HEAD", None) == [
        {"name": "std", "how": "pin moved", "from": "a" * 40, "to": "b" * 40}
    ]
