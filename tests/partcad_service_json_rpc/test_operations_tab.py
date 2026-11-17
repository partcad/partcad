#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The daemon methods the IDE's Operations tabs are drawn from, and 'pc copy'.

'revisions.list', 'revisions.compare', 'revisions.uses', 'revisions.used_by' and
'usage.used_by', with 'requirements.check' asked of a package, and 'copy.object':
against a real context of a package with a history, written with pygit2 into a
temporary directory. What each answer says is pinned beside 'partcad.revisions',
'partcad.usage' and 'partcad.serialize' in 'tests/partcad/unit'; what is pinned
here is the methods -- what they are called, what they take, what they refuse.
"""

import pygit2
import pytest
import yaml

import partcad as pc
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError
from partcad_service_json_rpc.rpc.methods import build_registry


def _commit(path, message) -> str:
    repo = pygit2.Repository(str(path))
    index = repo.index
    index.add_all()
    index.write()
    signature = pygit2.Signature("Test", "test@example.com", 1_700_000_000, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    return str(repo.create_commit("HEAD", signature, signature, message, index.write_tree(), parents))


def _cube(length):
    return {"type": "basic", "cuboid": length}


@pytest.fixture
def session(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    pygit2.init_repository(str(root))
    (root / "partcad.yaml").write_text(yaml.safe_dump({"name": "//", "parts": {"cube": _cube(1)}}, sort_keys=False))
    first = _commit(root, "first")
    config = {
        "name": "//",
        "requirements": {"features": {"cubes": "it has cubes"}},
        "parts": {"cube": _cube(2), "user": {"type": "alias", "source": ":cube"}},
    }
    (root / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    session = Session(EventEmitter(lambda event, payload: None))
    session.partcad = pc
    session.partcad_ctx = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(session.partcad_ctx.user_config, "internal_state_dir", str(tmp_path / "state"))
    session.first = first
    return session


@pytest.mark.parametrize(
    "method, operation",
    [
        ("revisions.list", operations.revisions_list),
        ("revisions.compare", operations.revisions_compare),
        ("revisions.uses", operations.revisions_uses),
        ("revisions.used_by", operations.revisions_used_by),
        ("usage.used_by", operations.usage_used_by),
        ("copy.object", operations.copy_object),
    ],
)
def test_they_are_methods_of_the_daemon(method, operation):
    assert build_registry()[method].__wrapped__ is operation


def test_the_history_of_an_object_s_package(session):
    answer = operations.revisions_list(session, {"package": "//", "object": "cube", "kind": "part"})

    assert answer["package"] == "//"
    assert answer["published"] is True
    assert [entry["sha"] for entry in answer["revisions"]] == [session.first]


def test_the_history_of_a_package(session):
    answer = operations.revisions_list(session, {"package": "//", "kind": "package"})

    assert [entry["short"] for entry in answer["revisions"]] == [session.first[:8]]


def test_an_object_compared_with_a_revision(session):
    answer = operations.revisions_compare(
        session, {"package": "//", "object": "cube", "kind": "part", "revision": session.first}
    )

    assert answer["revision"] == session.first
    assert [(row["left"], row["right"]) for row in answer["rows"] if row["tag"] == "replace"] == [
        ("  cuboid: 1", "  cuboid: 2")
    ]


def test_a_package_compared_with_a_revision(session):
    answer = operations.revisions_compare(session, {"package": "//", "kind": "package", "revision": session.first})

    assert answer["same"] is False
    assert any(row["right"] == "requirements:" for row in answer["rows"] if row["tag"] == "insert")


def test_a_comparison_needs_a_revision(session):
    with pytest.raises(JsonRpcError):
        operations.revisions_compare(session, {"package": "//", "object": "cube", "kind": "part"})


def test_what_a_revision_uses_and_is_used_by(session):
    uses = operations.revisions_uses(session, {"package": "//", "revision": session.first})
    used_by = operations.revisions_used_by(session, {"package": "//", "revision": session.first})

    assert uses["revision"] == session.first
    assert uses["dependencies"] == []
    assert used_by["objects"] == []


def test_what_uses_an_object(session):
    answer = operations.usage_used_by(session, {"package": "//", "object": "cube", "kind": "part"})

    assert answer["object"] == "//:cube"
    assert [(row["object"], row["count"]) for row in answer["objects"]] == [("//:user", 1)]


def test_a_package_s_requirements(session):
    answer = operations.requirements_check(session, {"package": "//", "kind": "package", "verify": False})

    assert answer["kind"] == "package"
    assert answer["defined"] is True
    assert [feature["name"] for feature in answer["features"]] == ["cubes"]


def test_copy_writes_the_declaration_and_the_context_sees_it(session):
    answer = operations.copy_object(session, {"package": "//", "object": "cube", "target": "cube_copy"})

    assert answer["written"] is True
    assert answer["declaration"] == "cube_copy:\n  type: basic\n  cuboid: 2\n"
    # Without a stat telling it so: the package was written behind its back.
    assert session.partcad_ctx.get_part("//:cube_copy") is not None


def test_copy_from_a_revision(session):
    answer = operations.copy_object(
        session,
        {"package": "//", "object": "//@%s:cube" % session.first, "target": "cube_v1", "dry_run": True},
    )

    assert answer["source"] == "//@%s:cube" % session.first
    assert answer["declaration"].splitlines()[2] == "  cuboid: 1"


@pytest.mark.parametrize(
    "params",
    [
        {"package": "//", "object": "cube"},
        {"package": "//", "target": "x"},
        {"package": "//", "object": "nothing", "target": "x"},
        {"package": "//", "object": "cube", "target": "user"},
    ],
)
def test_copy_refuses(session, params):
    with pytest.raises(JsonRpcError):
        operations.copy_object(session, params)
