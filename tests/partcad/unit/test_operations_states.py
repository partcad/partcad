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
import sys

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


# ---- what a review of the above found -------------------------------------------


def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def test_an_object_built_from_a_file_it_names_has_a_revision_where_only_that_file_changed(workspace, ctx):
    root, _ = workspace
    config = yaml.safe_load((root / "lib" / "partcad.yaml").read_text())
    config["parts"]["bolt"]["dependencies"] = ["helpers.py"]
    _write(root / "lib" / "partcad.yaml", config)
    (root / "lib" / "helpers.py").write_text("h = 1\n")
    _commit(root, "helpers")
    (root / "lib" / "helpers.py").write_text("h = 2\n")
    changed = _commit(root, "only the helper")
    ctx.reload_packages(["//lib"])

    listed = revisions.object_history(ctx, ctx.get_project("//lib"), "part", "bolt")

    assert listed["revisions"][0]["sha"] == changed and listed["revisions"][0]["how"] == ["source"]


def test_a_name_with_directories_in_it_is_built_from_the_file_in_them(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "brackets").mkdir()
    (root / "lib" / "brackets" / "left.py").write_text("z = 1\n")
    config = yaml.safe_load((root / "lib" / "partcad.yaml").read_text())
    config["parts"]["brackets/left"] = {"type": "cadquery"}
    _write(root / "lib" / "partcad.yaml", config)
    ctx.reload_packages(["//lib"])

    assert changes.object_files(ctx.get_project("//lib"), "part", "brackets/left") == ["brackets/left.py"]


def test_what_cannot_be_known_about_a_commit_is_not_kept(workspace, ctx, monkeypatch):
    root, _ = workspace
    _lib(root, desc="Changed")
    _commit(root, "second")
    with monkeypatch.context() as unknown:
        unknown.setattr(revisions, "changed_paths", lambda repository, sha: None)
        assert revisions.object_history(ctx, ctx.get_project("//lib"), "part", "bolt")["revisions"] == []

    # Not remembered as "no change": asked again, it is found.
    assert [row["how"] for row in revisions.object_history(ctx, ctx.get_project("//lib"), "part", "bolt")["revisions"]]


def test_what_is_kept_about_a_commit_is_kept_for_the_tags_it_was_found_under(workspace, ctx):
    repository = package_versions.repository_of(ctx.get_project("//lib").config_dir)
    key = revisions._cache_key(ctx, repository, "part", "bolt", "a" * 40)
    ctx.tags = set(ctx.tags) | {"elsewhere"}

    assert revisions._cache_key(ctx, repository, "part", "bolt", "a" * 40) != key


def test_the_cache_of_revisions_going_unwritten_loses_nothing(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(revisions.os, "makedirs", refuse)

    revisions._write_cache(str(tmp_path / "ro" / "object-revisions.json"), {"k": []})


def test_comparing_an_object_whose_file_alone_changed_is_a_change(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "bolt.py").write_text("x = 2\n")
    _stage(root, "lib/bolt.py")

    compared = revisions.compare_states(ctx, ctx.get_project("//lib"), "part", "bolt", "HEAD", package_versions.STAGED)

    assert compared["same"] is False and compared["unified"] == ""
    assert compared["sources"] == [{"path": "bolt.py", "how": "modified"}]


def test_a_first_commit_is_compared_with_nothing(workspace, ctx):
    _, first = workspace

    compared = revisions.compare_states(ctx, ctx.get_project("//lib"), "part", "bolt", first + "~1", first)

    assert compared["left"]["missing"] is True and compared["right"]["missing"] is False
    assert {row["tag"] for row in compared["rows"]} == {"insert"}


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git to make a conflict")
def test_a_conflicted_index_is_said_and_is_not_an_empty_package(workspace, ctx):
    root, _ = workspace
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "checkout", "-q", "-b", "other")
    (root / "lib" / "bolt.py").write_text("x = 'theirs'\n")
    _git(root, "commit", "-q", "-am", "theirs")
    _git(root, "checkout", "-q", "-")
    (root / "lib" / "bolt.py").write_text("x = 'ours'\n")
    _git(root, "commit", "-q", "-am", "ours")
    subprocess.run(["git", "merge", "-q", "other"], cwd=str(root), capture_output=True, check=False)

    with pytest.raises(ValueError, match="conflicts"):
        changes.changes(ctx, "//lib", "HEAD", package_versions.STAGED)


def test_a_file_is_read_a_piece_at_a_time(tmp_path):
    import hashlib

    data = b"x" * (3 << 20)
    (tmp_path / "big").write_bytes(data)

    assert changes._digest(str(tmp_path / "big")) == hashlib.sha256(data).hexdigest()


def test_a_symbolic_link_is_what_it_says(tmp_path):
    import hashlib

    try:
        (tmp_path / "link").symlink_to("/somewhere/else")
    except OSError as e:
        # Windows without the privilege to make one.
        pytest.skip("this host makes no symbolic links: %s" % e)

    assert changes._digest(str(tmp_path / "link")) == hashlib.sha256(b"link:/somewhere/else").hexdigest()


def test_a_package_of_too_many_files_compares_none_of_them_rather_than_all_as_removed(workspace, ctx, monkeypatch):
    root, _ = workspace
    monkeypatch.setattr(changes, "_FILES_LIMIT", 3)
    (root / "lib" / "more.txt").write_text("more\n")

    assert changes.package_files(ctx.get_project("//lib")) is None
    assert changes.changes(ctx, "//lib", "HEAD", None)["files"] == []


def test_a_tracked_dotfile_is_a_file_of_the_package_and_an_ignored_one_is_not(workspace, ctx):
    root, _ = workspace
    (root / "lib" / ".gitignore").write_text("*.log\n")
    _commit(root, "ignore logs")
    (root / "lib" / ".gitignore").write_text("*.log\n*.tmp\n")
    (root / "lib" / "build.log").write_text("noise\n")

    files = changes.changes(ctx, "//lib", "HEAD", None)["files"]

    assert {"path": ".gitignore", "how": "modified"} in files
    assert all(entry["path"] != "build.log" for entry in files)


def test_a_package_at_worktree_is_its_saved_configuration(workspace, ctx):
    root, _ = workspace
    assert ctx.get_project("//lib@WORKTREE").object_config("part", "bolt")["desc"] == "A bolt"
    _lib(root, desc="Saved since")

    assert ctx.get_project("//lib@WORKTREE").object_config("part", "bolt")["desc"] == "Saved since"


def test_revisions_page_on_from_where_the_last_page_ended_whatever_the_history_s_length(workspace, ctx, monkeypatch):
    root, first = workspace
    made = [first]
    for number in range(4):
        _lib(root, desc="Change %d" % number)
        made.append(_commit(root, "change %d" % number))
    lib = ctx.get_project("//lib")

    page = revisions.history(ctx, lib, limit=2)
    assert [row["sha"] for row in page["revisions"]] == made[:-3:-1] and page["next"] == made[-2]
    rest = revisions.history(ctx, lib, limit=10, after=page["next"])
    assert [row["sha"] for row in rest["revisions"]] == made[-3::-1] and rest["more"] is False

    # A walk that looks at fewer commits than there are says so, and goes on from where it stopped.
    monkeypatch.setattr(package_versions, "REVISIONS_SCAN_LIMIT", 2)
    stopped = revisions.history(ctx, lib, limit=10)
    assert stopped["more"] is True and stopped["next"] == made[-2]
    with pytest.raises(ValueError):
        revisions.history(ctx, lib, after="f" * 40)


def test_the_index_is_told_apart_by_what_it_holds_and_not_by_its_size_and_time(workspace, ctx):
    import os

    root, _ = workspace
    repository = package_versions.repository_of(str(root))
    index = root / ".git" / "index"
    (root / "lib" / "bolt.py").write_text("x = 2\n")
    _stage(root, "lib/bolt.py")
    one = index.read_bytes()
    tree_one = package_versions.index_tree(repository)
    (root / "lib" / "bolt.py").write_text("x = 3\n")
    _stage(root, "lib/bolt.py")
    two = index.read_bytes()
    assert len(one) == len(two)
    stat = os.stat(index)
    index.write_bytes(one)
    os.utime(index, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert package_versions.index_tree(repository) == tree_one
    index.write_bytes(two)
    os.utime(index, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    assert package_versions.index_tree(repository) != tree_one


def test_the_interfaces_an_interface_takes_in_are_what_it_depends_on_however_they_are_written(workspace, ctx):
    lib = ctx.get_project("//lib")

    mapping = usage.references_how(lib, "interface", {"inherits": {":base": None, "other": {"at": [0, 0, 0]}}})
    scalar = usage.references_how(lib, "interface", {"inherits": ":base"})

    assert sorted(mapping) == [("//lib", "base", "inherits"), ("//lib", "other", "inherits")]
    assert scalar == [("//lib", "base", "inherits")]


def test_a_pin_on_a_commit_that_changed_something_else_is_behind_by_what_changed_the_package_since(workspace):
    root, _ = workspace
    (root / "app" / "notes.txt").write_text("app only\n")
    pinned = _commit(root, "app only")
    _lib(root, desc="Later")
    _commit(root, "lib")

    assert usage._behind(package_versions.repository_of(str(root / "lib")), pinned) == 1


def test_a_commit_deleting_a_sub_package_alone_is_a_revision_in_it(workspace, ctx):
    root, _ = workspace
    shutil.rmtree(root / "app")
    repo = pygit2.Repository(str(root))
    repo.index.read(True)
    repo.index.remove_all(["app/*"])
    repo.index.write()
    signature = pygit2.Signature("Test", "test@example.com", 1_700_000_000, 0)
    gone = str(repo.create_commit("HEAD", signature, signature, "gone", repo.index.write_tree(), [repo.head.target]))

    row = revisions.history(ctx, ctx.root)["revisions"][0]

    assert row["sha"] == gone and row["in"] == ["app"]


def test_removing_a_dependency_from_a_template_is_refused_and_writes_nothing(workspace, ctx):
    root, _ = workspace
    text = "{% set where = 'lib' %}\ndependencies:\n  near:\n    type: local\n    path: {{ where }}\n"
    (root / "app" / "partcad.yaml").write_text(text)

    assert ctx.get_project("//app").remove_import("near") is False
    assert (root / "app" / "partcad.yaml").read_text() == text


def test_staging_one_declaration_takes_its_lines_alone_or_refuses(workspace):
    index = "parts:\n  a:\n    desc: A\n  b:\n    desc: B\n"
    work = "parts:\n  a:\n    desc: A2\n  b:\n    desc: B2\n  c:\n    desc: C\n"
    assert working_copy.stage_declaration(index, work, "part", "b") == "parts:\n  a:\n    desc: A\n  b:\n    desc: B2\n"
    assert (
        working_copy.stage_declaration(index, work, "part", "c")
        == "parts:\n  a:\n    desc: A\n  b:\n    desc: B\n  c:\n    desc: C\n"
    )
    side_by_side = "parts:\n  a: {cuboid: 1}\n  b: {cuboid: 1}\n"
    assert (
        working_copy.stage_declaration(side_by_side, "parts:\n  a: {cuboid: 2}\n  b: {cuboid: 2}\n", "part", "a")
        == "parts:\n  a: {cuboid: 2}\n  b: {cuboid: 1}\n"
    )
    assert working_copy.stage_declaration("name: //x\n", "name: //x\nparts:\n  a: {}\n", "part", "a") == (
        "name: //x\nparts:\n  a: {}\n"
    )
    # Two declarations on one line cannot be told apart.
    with pytest.raises(ValueError, match="cannot be staged alone"):
        working_copy.stage_declaration("parts: {a: 1, b: 1}\n", "parts: {a: 2, b: 2}\n", "part", "a")


def test_the_files_a_deleted_sub_package_had_are_still_its_own(workspace):
    root, _ = workspace
    (root / "lib" / "partcad.yaml").unlink()
    (root / "lib" / "bolt.py").unlink()
    repository = package_versions.repository_of(str(root))

    assert working_copy._package_dir_of(repository, "lib/bolt.py") == "lib"
    assert working_copy._package_dir_of(repository, "lib/nut.py") == ""


def test_a_revision_of_an_object_asks_before_taking_the_package_s_own_declaration_with_it(workspace, ctx):
    root, _ = workspace
    config = yaml.safe_load((root / "lib" / "partcad.yaml").read_text())
    config["parts"]["bolt"]["desc"] = "Staged"
    config["desc"] = "A library"
    _write(root / "lib" / "partcad.yaml", config)
    _stage(root, "lib/partcad.yaml")

    with pytest.raises(working_copy.Refused) as refused:
        working_copy.new_revision(ctx, ctx.get_project("//lib"), "Bolt", "part", "bolt")

    assert refused.value.code == "others-staged" and "the package's own declaration" in str(refused.value)


def test_a_revision_is_of_the_tree_its_checks_ran_on(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="Staged")
    _stage(root, "lib/partcad.yaml")

    def checks(result):
        # Something else is staged while the checks run.
        (root / "lib" / "nut.py").write_text("y = 3\n")
        _stage(root, "lib/nut.py")
        return []

    with pytest.raises(working_copy.Refused) as refused:
        working_copy.new_revision(ctx, ctx.get_project("//lib"), "Bolt", accept=True, checks=checks)

    assert refused.value.code == "index-changed"
    assert pygit2.Repository(str(root)).head.peel(pygit2.Commit).message.strip() == "first"


def test_a_revision_a_client_asks_for_names_its_author_whole(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="Staged")
    _stage(root, "lib/partcad.yaml")

    with pytest.raises(ValueError, match="author"):
        working_copy.new_revision(
            ctx, ctx.get_project("//lib"), "Bolt", author={"name": "Ann"}, accept=True, author_required=True
        )


def test_impact_checks_what_a_new_declaration_names(workspace, ctx):
    root, _ = workspace
    config = yaml.safe_load((root / "app" / "partcad.yaml").read_text())
    config["parts"]["stub"] = {"type": "alias", "source": "//lib:washer"}
    _write(root / "app" / "partcad.yaml", config)
    ctx.reload_packages(["//app"])

    found = impact.impact(ctx, ctx.get_project("//app"), "part", "stub")

    (row,) = found["affects"]
    assert any(finding["severity"] == impact.BREAKING and "washer" in finding["summary"] for finding in row["findings"])


def test_impact_of_what_is_staged_reaches_what_uses_it_as_staged(workspace, ctx):
    root, _ = workspace
    _write(root / "lib" / "partcad.yaml", {"parts": {"nut": {"type": "cadquery", "desc": "A nut"}}})
    _stage(root, "lib/partcad.yaml")
    # On disk only, not staged: the enrich no longer uses the bolt.
    config = yaml.safe_load((root / "app" / "partcad.yaml").read_text())
    config["parts"]["long_bolt"]["source"] = "//lib:nut"
    _write(root / "app" / "partcad.yaml", config)
    ctx.reload_packages(["//app", "//lib"])
    usage.load_workspace(ctx)

    found = impact.impact(ctx, ctx.get_project("//lib"), before="HEAD", after=package_versions.STAGED)

    bolt = next(row for row in found["affects"] if row["object"] == "//lib:bolt")
    assert bolt["users"] == ["//app:long_bolt"]
    assert any(finding["severity"] == impact.BREAKING for finding in bolt["findings"])


def test_a_change_of_prose_does_not_change_the_shape_of_what_uses_it(workspace, ctx):
    root, _ = workspace
    _lib(root, desc="Reworded")
    ctx.reload_packages(["//lib"])
    usage.load_workspace(ctx)

    found = impact.impact(ctx, ctx.get_project("//lib"), "part", "bolt")

    via = next(row for row in found["affects"] if row["object"] == "//app:long_bolt")
    assert via["geometry"] is False
    assert [finding["severity"] for finding in via["findings"]] == [impact.INFO]


def test_only_a_dependent_pinned_to_a_commit_is_held_back(workspace, ctx, monkeypatch):
    root, first = workspace
    branch = pygit2.Repository(str(root)).head.shorthand
    rows = [
        {"package": "//held", "type": "git", "pinned": first[:12], "track": branch},
        {"package": "//on_a_branch", "type": "git", "pinned": branch},
        {"package": "//follows", "type": "git", "pinned": None, "track": branch},
        {"package": "//nowhere", "type": "git", "pinned": "f" * 40},
        {"package": "//near", "type": "local"},
    ]
    monkeypatch.setattr(usage, "package_dependents", lambda ctx, project: rows)

    found = impact.impact(ctx, ctx.get_project("//lib"))

    assert [row["package"] for row in found["pinned"]] == ["//held"]


def test_a_package_of_another_repository_is_compared_as_loaded(workspace, ctx):
    graph = impact._Graph(ctx, ctx.get_project("//lib"), "HEAD", package_versions.STAGED)

    assert graph.states("//lib") == {"from": "HEAD", "to": package_versions.STAGED}
    assert graph.states("//elsewhere")["outside"] is True
    assert graph.plain("//lib@STAGED") == "//lib" and graph.plain("//@STAGED/lib") == "//lib"
    assert graph.plain("//lib@" + "a" * 40) == "//lib@" + "a" * 40


# ---- what a second review found -------------------------------------------------


def test_a_symbolic_link_an_object_is_built_from_is_its_file_wherever_it_points(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "bolt.py").unlink()
    try:
        (root / "lib" / "bolt.py").symlink_to("missing.py")
    except OSError as e:
        pytest.skip("this host makes no symbolic links: %s" % e)

    assert changes.object_files(ctx.get_project("//lib"), "part", "bolt") == ["bolt.py"]


def test_a_package_of_too_many_files_is_not_said_to_be_the_same(workspace, ctx, monkeypatch):
    monkeypatch.setattr(changes, "_FILES_LIMIT", 3)

    compared = revisions.compare_states(ctx, ctx.get_project("//lib"), revisions.PACKAGE, None, "HEAD")

    assert compared["changes"]["files_compared"] is False and compared["same"] is False


def test_a_package_deleted_from_the_files_on_disk_is_still_there_at_a_revision(workspace, tmp_path, monkeypatch):
    root, _ = workspace
    shutil.rmtree(root / "lib")
    context = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state2"))

    assert context.get_project("//lib") is None
    assert context.get_project("//lib@HEAD").object_config("part", "bolt") is not None
    found = changes.changes(context, "//lib", "HEAD", None)
    assert {row["name"]: row["how"] for row in found["objects"]} == {"bolt": ["removed"], "nut": ["removed"]}


def test_a_user_is_judged_by_the_declaration_it_was_found_by(ctx):
    user = {"package": "//app", "kind": "part", "name": "long_bolt", "declaration": {"with": {"width": 4}}}

    assert impact._passes(ctx, user, "width") is True
    assert impact._passes(ctx, {**user, "declaration": {"with": {}}}, "width") is False


def test_a_reference_to_an_object_of_the_wrong_kind_is_breaking(workspace, ctx):
    root, _ = workspace
    _write(
        root / "app" / "partcad.yaml",
        {
            **yaml.safe_load((root / "app" / "partcad.yaml").read_text()),
            **{"interfaces": {"mount": {"inherits": "//lib:bolt"}}},
        },
    )
    ctx.reload_packages(["//app"])

    found = impact.impact(ctx, ctx.get_project("//app"), "interface", "mount")

    (row,) = found["affects"]
    assert any("which is a part, not an interface" in finding["summary"] for finding in row["findings"])


def test_a_shape_change_passes_through_an_object_whose_own_change_was_prose(workspace, ctx):
    root, _ = workspace
    config = yaml.safe_load((root / "lib" / "partcad.yaml").read_text())
    config["parts"]["longer"] = {"type": "enrich", "source": ":bolt", "with": {"length": 30}, "desc": "Longer"}
    config["parts"]["same"] = {"type": "alias", "source": ":longer"}
    _write(root / "lib" / "partcad.yaml", config)
    _commit(root, "an enrich and an alias of it")
    config["parts"]["bolt"]["parameters"]["length"]["default"] = 12
    config["parts"]["longer"]["desc"] = "Reworded"
    _write(root / "lib" / "partcad.yaml", config)
    ctx.reload_packages(["//lib"])

    found = impact.impact(ctx, ctx.get_project("//lib"))

    rows = {row["object"]: row for row in found["affects"]}
    assert rows["//lib:longer"]["reached"] == "changed" and rows["//lib:longer"]["prose"] is True
    assert any(finding["analyzer"] == "geometry" for finding in rows["//lib:longer"]["findings"])
    assert rows["//lib:same"]["geometry"] is True


def test_what_an_object_uses_at_a_state_it_is_not_at_is_nothing(ctx):
    app = ctx.get_project("//app")
    graph = impact._Graph(ctx, app, "HEAD", package_versions.STAGED)
    graph.after_root = None

    assert impact._affected_by(graph, app, "part", "long_bolt", {"//lib:bolt": {"object": "//lib:bolt"}}) == []


def test_a_revision_a_declaration_names_itself_is_kept_as_written(workspace, ctx):
    root, first = workspace
    pygit2.Repository(str(root)).create_tag(
        "v1", pygit2.Oid(hex=first), pygit2.enums.ObjectType.COMMIT, pygit2.Signature("T", "t@example.com"), "v1"
    )
    config = yaml.safe_load((root / "app" / "partcad.yaml").read_text())
    config["parts"]["old_bolt"] = {"type": "alias", "source": "//lib@v1:bolt"}
    _write(root / "app" / "partcad.yaml", config)
    ctx.reload_packages(["//app"])
    app = ctx.get_project("//app")

    written = usage.object_dependencies(ctx, app, "part", "old_bolt", canonical=False)
    loaded = usage.object_dependencies(ctx, app, "part", "old_bolt")

    assert [row["package"] for row in written] == ["//lib@v1"]
    assert [row["package"] for row in loaded] == ["//lib@" + first]


def test_a_template_s_revisions_are_compared_in_full(workspace):
    root, _ = workspace
    (root / "lib" / "partcad.yaml").write_text(
        "parts:\n  bolt:\n    type: cadquery\n    path: \"{{ 'bolt' }}.py\"\n  nut:\n    type: cadquery\n"
    )
    sha = _commit(root, "templated")
    repository = package_versions.repository_of(str(root / "lib"))

    assert revisions._declared_files_at(repository, sha, "part", "bolt") is revisions._UNKNOWN


def test_comparing_with_a_revision_that_names_nothing_is_refused(ctx):
    with pytest.raises(ValueError):
        revisions.compare_states(ctx, ctx.get_project("//lib"), "part", "bolt", "HEAD", "no-such-branch")


def test_an_interface_named_with_an_expression_in_its_arguments_is_still_named(ctx):
    lib = ctx.get_project("//lib")

    assert usage.references_how(lib, "interface", {"inherits": {":base;size=%size%": None}}) == [
        ("//lib", "base", "inherits")
    ]
    assert usage.references_how(lib, "interface", {"inherits": {"%which%": None}}) == []


def test_a_pin_from_before_the_package_was_made_is_behind_by_every_revision_of_it(workspace):
    root, first = workspace
    _write(root / "late" / "partcad.yaml", {"parts": {"peg": {"type": "basic", "cuboid": 1}}})
    _commit(root, "late package")
    _write(root / "late" / "partcad.yaml", {"parts": {"peg": {"type": "basic", "cuboid": 2}}})
    _commit(root, "late package changed")

    assert usage._behind(package_versions.repository_of(str(root / "late")), first) == 2


def test_status_is_read_from_one_index_or_not_at_all(workspace, ctx, monkeypatch):
    moves = iter(range(100))
    monkeypatch.setattr(package_versions, "_index_identity", lambda path: next(moves))

    with pytest.raises(ValueError, match="kept changing"):
        working_copy.status(ctx, ctx.get_project("//lib"))


def test_a_declaration_after_a_last_line_with_no_line_break_is_on_a_line_of_its_own():
    assert working_copy.stage_declaration(
        "parts:\n  a: {type: basic}", "parts:\n  a: {type: basic}\n  b: {type: basic}\n", "part", "b"
    ) == ("parts:\n  a: {type: basic}\n  b: {type: basic}\n")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_git_commits_the_tree_it_is_given_and_the_index_follows(workspace, ctx, monkeypatch):
    root, _ = workspace
    monkeypatch.setattr(working_copy, "_git_executable", lambda: shutil.which("git"))
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _lib(root, desc="Committed by git")
    _stage(root, "lib/partcad.yaml")
    repository = package_versions.repository_of(str(root))
    tree = package_versions.index_tree(repository)

    sha = working_copy.commit(repository, "By git\n", {"name": "Ann", "email": "ann@example.com"}, tree=tree)

    repo = pygit2.Repository(str(root))
    assert str(repo[sha].tree.id) == tree and repo[sha].author.name == "Ann"
    assert package_versions.index_tree(repository) == tree


# ---- what a third review found --------------------------------------------------


def test_a_state_that_holds_the_package_but_will_not_load_is_an_error_not_a_deletion(workspace, ctx, monkeypatch):
    real = ctx.get_project
    monkeypatch.setattr(ctx, "get_project", lambda name: None if "@" in name else real(name))

    with pytest.raises(ValueError, match="could not be loaded"):
        changes.package_at(ctx, "//lib", "HEAD")


def test_a_link_to_a_directory_is_a_file_of_the_package(workspace, ctx):
    root, _ = workspace
    (root / "lib" / "real").mkdir()
    try:
        (root / "lib" / "assets").symlink_to("real", target_is_directory=True)
    except OSError as e:
        pytest.skip("this host makes no symbolic links: %s" % e)

    assert "assets" in changes.package_files(ctx.get_project("//lib"))


def test_a_reference_to_another_package_s_private_object_is_breaking(workspace, ctx):
    root, _ = workspace
    lib = yaml.safe_load((root / "lib" / "partcad.yaml").read_text())
    lib["parts"]["nut"]["private"] = True
    _write(root / "lib" / "partcad.yaml", lib)
    app = yaml.safe_load((root / "app" / "partcad.yaml").read_text())
    app["parts"]["nut_alias"] = {"type": "alias", "source": "//lib:nut"}
    _write(root / "app" / "partcad.yaml", app)
    ctx.reload_packages(["//app", "//lib"])

    found = impact.impact(ctx, ctx.get_project("//app"), "part", "nut_alias")

    (row,) = found["affects"]
    assert any("private" in finding["summary"] for finding in row["findings"])


def test_an_object_changed_in_prose_and_reached_by_a_shape_gets_its_tests_asked_for(workspace, ctx):
    root, _ = workspace
    config = yaml.safe_load((root / "lib" / "partcad.yaml").read_text())
    config["parts"]["longer"] = {
        "type": "enrich",
        "source": ":bolt",
        "with": {"length": 30},
        "desc": "Longer",
        "requirements": [{"name": "Long"}],
    }
    _write(root / "lib" / "partcad.yaml", config)
    _commit(root, "an enrich with requirements")
    config["parts"]["bolt"]["parameters"]["length"]["default"] = 12
    config["parts"]["longer"]["desc"] = "Reworded"
    _write(root / "lib" / "partcad.yaml", config)
    ctx.reload_packages(["//lib"])

    found = impact.impact(ctx, ctx.get_project("//lib"))

    longer = next(row for row in found["affects"] if row["object"] == "//lib:longer")
    assert {finding["analyzer"] for finding in longer["findings"]} >= {"prose", "geometry", "requirements"}


def test_a_dependent_pinned_to_where_the_change_goes_is_not_held_back(workspace, ctx, monkeypatch):
    root, first = workspace
    _lib(root, desc="Second")
    second = _commit(root, "second")
    rows = [
        {"package": "//at_first", "type": "git", "pinned": first},
        {"package": "//at_second", "type": "git", "pinned": second},
    ]
    monkeypatch.setattr(usage, "package_dependents", lambda ctx, project: rows)

    found = impact.impact(ctx, ctx.get_project("//lib"), before=first, after=second)

    assert [row["package"] for row in found["pinned"]] == ["//at_first"]


def test_the_index_is_read_from_the_repository_when_no_copy_of_it_can_be_made(workspace, monkeypatch):
    import tempfile

    root, _ = workspace
    repository = package_versions.repository_of(str(root))
    expected = str(pygit2.Repository(str(root)).index.write_tree())

    def refuse(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(tempfile, "mkdtemp", refuse)
    package_versions._index_trees.clear()

    assert package_versions.index_tree(repository) == expected


def test_a_package_read_out_of_the_index_is_at_no_commit():
    class Loaded:
        name = "//lib@STAGED"

    assert usage._commit_of(Loaded()) is None
    assert usage._commit_of(None) is None


def test_a_package_of_exactly_as_many_revisions_as_are_counted_is_counted_whole(workspace, monkeypatch):
    root, first = workspace
    _write(root / "late" / "partcad.yaml", {"parts": {"peg": {"type": "basic", "cuboid": 1}}})
    _commit(root, "late package")
    _write(root / "late" / "partcad.yaml", {"parts": {"peg": {"type": "basic", "cuboid": 2}}})
    _commit(root, "late package changed")
    monkeypatch.setattr(package_versions, "REVISIONS_LIMIT", 2)

    assert usage._behind(package_versions.repository_of(str(root / "late")), first) == 2


def test_a_revision_is_not_made_on_top_of_a_head_that_moved(workspace):
    root, _ = workspace
    _lib(root, desc="Staged")
    _stage(root, "lib/partcad.yaml")
    repository = package_versions.repository_of(str(root))
    tree = package_versions.index_tree(repository)

    with pytest.raises(working_copy.Refused) as refused:
        working_copy.commit(repository, "x\n", {"name": "A", "email": "a@example.com"}, tree=tree, parent="0" * 40)

    assert refused.value.code == "head-moved"


def test_the_index_is_not_written_over_while_git_holds_its_lock(workspace):
    root, first = workspace
    repository = package_versions.repository_of(str(root))
    lock = root / ".git" / "index.lock"
    lock.write_text("somebody staging\n")
    tree = package_versions.index_tree(repository)
    other = str(pygit2.Repository(str(root))[first].peel(pygit2.Commit).tree.id)

    assert working_copy._move_index(repository, tree, other) is False
    assert lock.read_text() == "somebody staging\n"


@pytest.mark.skipif(shutil.which("git") is None or sys.platform == "win32", reason="needs git and a POSIX hook")
def test_what_a_hook_adds_to_a_revision_is_said_and_the_index_follows_it(workspace, ctx, monkeypatch):
    root, _ = workspace
    monkeypatch.setattr(working_copy, "_git_executable", lambda: shutil.which("git"))
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho generated > lib/generated.txt\ngit add lib/generated.txt\n")
    hook.chmod(0o755)
    _lib(root, desc="Hooked")
    _stage(root, "lib/partcad.yaml")

    made = working_copy.new_revision(
        ctx, ctx.get_project("//lib"), "Hooked", author={"name": "Ann", "email": "ann@example.com"}, accept=True
    )

    assert made["hooks_changed"] == ["lib/generated.txt"]
    repository = package_versions.repository_of(str(root))
    assert package_versions.index_tree(repository) == str(pygit2.Repository(str(root)).head.peel(pygit2.Commit).tree.id)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_what_is_staged_while_git_commits_stays_staged_and_out_of_the_revision(workspace, monkeypatch):
    root, _ = workspace
    monkeypatch.setattr(working_copy, "_git_executable", lambda: shutil.which("git"))
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _lib(root, desc="Approved")
    _stage(root, "lib/partcad.yaml")
    repository = package_versions.repository_of(str(root))
    approved = package_versions.index_tree(repository)
    real_git = working_copy._git

    def git_with_a_stage_meanwhile(git, workdir, env, *args, **kwargs):
        if args and args[0] == "commit":
            # Somebody else stages a file into the user's index, after the
            # check and before git commits.
            (root / "lib" / "late.py").write_text("late = 1\n")
            _stage(root, "lib/late.py")
        return real_git(git, workdir, env, *args, **kwargs)

    monkeypatch.setattr(working_copy, "_git", git_with_a_stage_meanwhile)

    sha = working_copy.commit(repository, "Approved\n", {"name": "Ann", "email": "ann@example.com"}, tree=approved)

    repo = pygit2.Repository(str(root))
    assert str(repo[sha].tree.id) == approved
    repo.index.read(True)
    assert "lib/late.py" in repo.index and "lib/late.py" not in repo[sha].tree
