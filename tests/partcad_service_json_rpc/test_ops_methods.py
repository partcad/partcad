#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Operations methods that write, and the views: 'ops.views', 'ops.rev.status|stage|new', 'ops.deps.*', 'ops.impact'.

Against a real context of a package in a repository written with pygit2 into a
temporary directory. What each answer says is pinned beside 'partcad.changes',
'partcad.working_copy', 'partcad.usage' and 'partcad.impact' in
'tests/partcad/unit'; what is pinned here is the methods -- what they take,
what they refuse and with which code, and that the checks before a new
revision run on what is staged.
"""

import pygit2
import pytest
import yaml

import partcad as pc
from partcad import working_copy
from partcad_service_json_rpc.core import ops
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError
from partcad_service_json_rpc.rpc.methods import build_registry


def _write(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False))


def _commit(root, message) -> str:
    repo = pygit2.Repository(str(root))
    index = repo.index
    index.read(True)
    index.add_all()
    index.write()
    signature = pygit2.Signature("Test", "test@example.com", 1_700_000_000, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    return str(repo.create_commit("HEAD", signature, signature, message, index.write_tree(), parents))


def _stage(root, path):
    repo = pygit2.Repository(str(root))
    repo.index.read(True)
    repo.index.add(path)
    repo.index.write()


@pytest.fixture
def session(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    pygit2.init_repository(str(root))
    pygit2.Repository(str(root)).config["commit.gpgsign"] = False
    _write(root / "partcad.yaml", {"parts": {"cube": {"type": "basic", "cuboid": 1}}})
    _write(root / "lib" / "partcad.yaml", {"parts": {"peg": {"type": "basic", "cuboid": 2}}})
    first = _commit(root, "first")
    session = Session(EventEmitter(lambda event, payload: None))
    session.partcad = pc
    session.partcad_ctx = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(session.partcad_ctx.user_config, "internal_state_dir", str(tmp_path / "state"))
    monkeypatch.setattr(working_copy, "_git_executable", lambda: None)
    session.root = root
    session.first = first
    return session


@pytest.mark.parametrize(
    "method, operation",
    [
        ("ops.views", ops.views),
        ("ops.rev.status", ops.rev_status),
        ("ops.rev.stage", ops.rev_stage),
        ("ops.rev.new", ops.rev_new),
        ("ops.deps.add", ops.deps_add),
        ("ops.deps.remove", ops.deps_remove),
        ("ops.deps.update", ops.deps_update),
        ("ops.impact", ops.impact),
    ],
)
def test_they_are_methods_of_the_daemon(method, operation):
    assert build_registry()[method].__wrapped__ is operation


def test_the_views_of_a_package_and_of_an_object(session):
    package = ops.views(session, {"package": "//", "summary": True})
    cube = ops.views(session, {"package": "//", "object": "cube"})

    assert [view["id"] for view in package["views"]] == ["revisions", "dependencies", "usedby", "impact"]
    assert package["summary"]["revisions"]["count"] == 1
    assert "pc ops deps add" in [command["command"] for view in package["views"] for command in view["commands"]]
    assert cube["subject"] == {"package": "//", "object": "//:cube", "kind": "part"}
    assert "pc ops deps add" not in [command["command"] for view in cube["views"] for command in view["commands"]]


def test_a_command_for_a_package_is_refused_for_an_object_in_words_that_say_so(session):
    with pytest.raises(JsonRpcError) as refused:
        ops.deps_add(session, {"package": "//", "object": "cube", "name": "std", "location": "../std"})

    assert str(refused.value) == "deps add applies to a package; //:cube is a part"


def test_status_stage_and_a_new_revision_of_an_object(session, monkeypatch):
    from partcad.qual import report

    tested = []

    async def run_async(ctx, shape, verify=False, subtypes=None):
        # What the tests would say, without building a sandbox to run them in.
        tested.append(shape.project_name)
        return []

    monkeypatch.setattr(report, "run_async", run_async)
    root = session.root
    _write(root / "partcad.yaml", {"parts": {"cube": {"type": "basic", "cuboid": 3}}})

    status = ops.rev_status(session, {"package": "//", "object": "cube"})
    assert [row["name"] for row in status["unstaged"]] == ["cube"] and status["advice"]

    staged = ops.rev_stage(session, {"package": "//", "object": "cube"})
    assert [row["name"] for row in staged["status"]["staged"]] == ["cube"]

    made = ops.rev_new(
        session,
        {
            "package": "//",
            "object": "cube",
            "message": "A bigger cube",
            "author": {"name": "Ann", "email": "ann@example.com"},
            "expect_index": staged["status"]["index"],
        },
    )

    head = pygit2.Repository(str(root)).head.peel(pygit2.Commit)
    assert made["sha"] == str(head.id) and head.author.name == "Ann"
    assert [entry["name"] for entry in made["checks"]] == ["lint", "qual test"]
    assert all(entry["passed"] for entry in made["checks"]), made["checks"]
    # The tests ran on what was staged, not on the files on disk.
    assert tested == ["//@STAGED"]


@pytest.mark.parametrize(
    "prepare, params, code",
    [
        (lambda root: None, {}, "nothing-staged"),
        (
            lambda root: (
                _write(root / "lib" / "partcad.yaml", {"parts": {"peg": {"type": "basic", "cuboid": 5}}}),
                _stage(root, "lib/partcad.yaml"),
                _write(root / "partcad.yaml", {"parts": {"cube": {"type": "basic", "cuboid": 3}}}),
                _stage(root, "partcad.yaml"),
            ),
            {"skip_checks": True},
            "others-staged",
        ),
        (
            lambda root: (
                _write(root / "partcad.yaml", {"parts": {"cube": {"type": "basic", "cuboid": 3}}}),
                _stage(root, "partcad.yaml"),
                (root / "notes.txt").write_text("not staged\n"),
            ),
            {"skip_checks": True},
            "warnings",
        ),
        (
            lambda root: (
                _write(root / "partcad.yaml", {"parts": {"cube": {"type": "basic", "cuboid": 3}}}),
                _stage(root, "partcad.yaml"),
            ),
            {"expect_index": "0" * 40, "skip_checks": True},
            "index-changed",
        ),
    ],
)
def test_a_new_revision_is_refused_with_a_code_and_the_status(session, prepare, params, code):
    prepare(session.root)

    with pytest.raises(JsonRpcError) as refused:
        ops.rev_new(session, {"package": "//", "message": "Change", **params})

    assert refused.value.data["code"] == code
    assert "staged" in refused.value.data["status"]


def test_a_new_revision_needs_a_message(session):
    with pytest.raises(JsonRpcError):
        ops.rev_new(session, {"package": "//", "message": " "})


def test_nothing_is_staged_or_committed_into_a_revision(session):
    for operation in (ops.rev_stage, ops.rev_new):
        with pytest.raises(JsonRpcError):
            operation(session, {"package": "//@%s" % session.first, "message": "x"})


def test_a_dependency_is_added_listed_and_removed_and_its_users_named(session):
    root = session.root
    added = ops.deps_add(session, {"package": "//", "name": "std", "location": "lib"})
    assert added["added"] is True
    session.partcad_ctx.reload_packages(["//"])
    listed = ops.deps_list(session, {"package": "//"})
    assert [row["name"] for row in listed["declared"]] == ["std"]

    config = yaml.safe_load((root / "partcad.yaml").read_text())
    config["parts"]["pin"] = {"type": "alias", "source": "//std:peg"}
    _write(root / "partcad.yaml", config)
    session.partcad_ctx.reload_packages(["//"])

    removed = ops.deps_remove(session, {"package": "//", "name": "std"})

    assert removed["users"] == ["//:pin"]
    assert "std" not in (yaml.safe_load((root / "partcad.yaml").read_text()).get("dependencies") or {})
    with pytest.raises(JsonRpcError):
        ops.deps_remove(session, {"package": "//", "name": "std"})


def test_updating_a_package_with_nothing_tracked_moves_nothing(session):
    answer = ops.deps_update(session, {"package": "//"})

    assert (answer["pinned"], answer["failed"]) == (0, 0) and answer["package"] == "//"


def test_used_by_a_package_names_the_packages_that_depend_on_it(session):
    root = session.root
    config = yaml.safe_load((root / "partcad.yaml").read_text())
    config["dependencies"] = {"near": {"type": "local", "path": "lib"}}
    _write(root / "partcad.yaml", config)
    session.partcad_ctx.reload_packages(["//"])

    answer = ops.used_by(session, {"package": "//near", "load": True})

    assert [(row["package"], row["name"], row["type"]) for row in answer["packages"]] == [("//", "near", "local")]


def test_impact_of_what_is_staged_and_of_a_revision_nobody_has_is_refused(session):
    root = session.root
    _write(root / "lib" / "partcad.yaml", {"parts": {"peg": {"type": "basic", "cuboid": 4}}})
    _stage(root, "lib/partcad.yaml")

    staged = ops.impact(session, {"package": "//lib", "from": "HEAD", "to": "STAGED"})

    assert [row["object"] for row in staged["changed"]] == ["//lib:peg"]
    assert staged["affects"][0]["reached"] == "changed"
    with pytest.raises(JsonRpcError):
        ops.impact(session, {"package": "//lib", "from": "no-such-tag"})
