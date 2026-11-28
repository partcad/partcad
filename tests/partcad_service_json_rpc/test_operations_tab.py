#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The daemon methods the IDE's Operations tabs are drawn from, and 'pc copy'.

'ops.rev.list', 'ops.rev.diff', 'ops.deps.list' and 'ops.used_by', with
'requirements.check' asked of a package, and 'copy.object':
against a real context of a package with a history, written with pygit2 into a
temporary directory. What each answer says is pinned beside 'partcad.revisions',
'partcad.usage' and 'partcad.serialize' in 'tests/partcad/unit'; what is pinned
here is the methods -- what they are called, what they take, what they refuse.
"""

import pygit2
import pytest
import yaml

import partcad as pc
from partcad_service_json_rpc.core import operations, ops
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
        ("ops.rev.list", ops.rev_list),
        ("ops.rev.diff", ops.rev_diff),
        ("ops.deps.list", ops.deps_list),
        ("ops.used_by", ops.used_by),
        ("copy.object", operations.copy_object),
    ],
)
def test_they_are_methods_of_the_daemon(method, operation):
    assert build_registry()[method].__wrapped__ is operation


def test_the_revisions_of_an_object_are_those_that_changed_it(session):
    answer = ops.rev_list(session, {"package": "//", "object": "cube", "kind": "part"})

    assert answer["package"] == "//" and answer["object"] == "//:cube"
    assert answer["published"] is True
    assert [(entry["sha"], entry["how"]) for entry in answer["revisions"]] == [(session.first, ["added"])]


def test_the_history_of_a_package(session):
    answer = ops.rev_list(session, {"package": "//"})

    assert [entry["short"] for entry in answer["revisions"]] == [session.first[:8]]


def test_an_object_compared_with_a_revision(session):
    answer = ops.rev_diff(session, {"package": "//", "object": "cube", "kind": "part", "from": session.first})

    assert answer["fromRevision"] == session.first and answer["to"] == "WORKTREE"
    assert [(row["left"], row["right"]) for row in answer["rows"] if row["tag"] == "replace"] == [
        ("  cuboid: 1", "  cuboid: 2")
    ]


def test_a_package_compared_with_a_revision(session):
    answer = ops.rev_diff(session, {"package": "//", "from": session.first})

    assert answer["same"] is False
    assert any(row["right"] == "requirements:" for row in answer["rows"] if row["tag"] == "insert")


def test_a_comparison_is_from_head_unless_told_otherwise(session):
    answer = ops.rev_diff(session, {"package": "//", "object": "cube", "kind": "part"})

    assert answer["from"] == "HEAD" and answer["fromRevision"] == session.first


def test_what_a_revision_uses_and_is_used_by(session):
    uses = ops.deps_list(session, {"package": "//@%s" % session.first})
    used_by = ops.used_by(session, {"package": "//@%s" % session.first})

    assert used_by["revision"] == session.first
    assert uses["declared"] == []
    assert used_by["objects"] == []


def test_what_uses_an_object(session):
    answer = ops.used_by(session, {"package": "//", "object": "cube", "kind": "part"})

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


def test_a_package_s_requirements_say_what_can_be_added_to_them(session):
    answer = operations.requirements_check(session, {"package": "//", "kind": "package"})

    assert answer["kinds"] == ["feature", "has"]
    assert answer["editable"] is None
    assert answer["declared"] == answer["section"]


def test_a_feature_and_a_yes_or_no_requirement_are_added_to_a_package_and_taken_out(session):
    added = operations.requirements_add(
        session,
        {"package": "//", "kind": "package", "requirement": "feature", "name": "light", "value": "weighs little"},
    )
    operations.requirements_add(
        session,
        {"package": "//", "kind": "package", "requirement": "has", "name": "private_dependencies", "value": False},
    )

    assert added["kind"] == "package"
    answer = operations.requirements_check(session, {"package": "//", "kind": "package"})
    assert [feature["name"] for feature in answer["features"]] == ["cubes", "light"]
    assert answer["declared"]["has_private_dependencies"] is False

    operations.requirements_remove(
        session, {"package": "//", "kind": "package", "requirement": "feature", "name": "light"}
    )

    answer = operations.requirements_check(session, {"package": "//", "kind": "package"})
    assert [feature["name"] for feature in answer["features"]] == ["cubes"]


def test_a_package_has_no_ports_of_its_own_to_require(session):
    with pytest.raises(JsonRpcError):
        operations.requirements_add(
            session, {"package": "//", "kind": "package", "requirement": "port", "name": "top", "value": None}
        )


def test_a_comparison_is_a_unified_diff_too(session):
    answer = ops.rev_diff(
        session, {"package": "//", "object": "cube", "kind": "part", "from": session.first, "lines": 0}
    )

    first = session.first[:8]
    assert answer["unified"].splitlines() == [
        "--- //@%s:cube" % first,
        "+++ //@WORKTREE:cube",
        "@@ -3 +3 @@",
        "-  cuboid: 1",
        "+  cuboid: 2",
    ]


def test_a_comparison_looks_the_kind_up(session):
    answer = ops.rev_diff(session, {"package": "//", "object": "cube", "from": session.first})

    assert answer["left"]["missing"] is False and answer["right"]["missing"] is False


def test_a_comparison_refuses_a_number_of_lines_that_is_none(session):
    with pytest.raises(JsonRpcError):
        ops.rev_diff(session, {"package": "//", "object": "cube", "from": session.first, "lines": "many"})


def test_used_by_can_load_the_workspace_first(session, tmp_path):
    root = tmp_path / "repo"
    (root / "users").mkdir()
    (root / "users" / "partcad.yaml").write_text(
        yaml.safe_dump({"parts": {"peg": {"type": "alias", "source": "//:cube"}}}, sort_keys=False)
    )
    session.partcad_ctx = pc.Context(str(root), search_root=False)

    before = ops.used_by(session, {"package": "//", "object": "cube", "kind": "part"})
    after = ops.used_by(session, {"package": "//", "object": "cube", "kind": "part", "load": True})

    assert "//users:peg" not in [row["object"] for row in before["objects"]]
    assert "//users:peg" in [row["object"] for row in after["objects"]]


def test_an_object_of_a_revision_has_requirements_that_are_not_edited(session):
    answer = operations.requirements_check(
        session, {"package": "//@%s" % session.first, "object": "cube", "kind": "part"}
    )

    assert answer["editable"] is not None
    with pytest.raises(JsonRpcError):
        operations.requirements_add(
            session,
            {
                "package": "//@%s" % session.first,
                "object": "cube",
                "kind": "part",
                "requirement": "feature",
                "name": "x",
                "value": "y",
            },
        )


def test_an_object_gone_since_the_revision_is_compared_as_what_it_was(session):
    config = yaml.safe_load(open(session.partcad_ctx.root.config_path).read())
    del config["parts"]["cube"]
    del config["parts"]["user"]
    with open(session.partcad_ctx.root.config_path, "w") as f:
        f.write(yaml.safe_dump(config, sort_keys=False))
    session.partcad_ctx.reload_packages(["//"])

    answer = ops.rev_diff(session, {"package": "//", "object": "cube", "from": session.first})

    assert answer["left"]["missing"] is False
    assert answer["right"]["missing"] is True
    assert answer["same"] is False


def test_copy_of_an_instance_is_that_instance(session):
    config = yaml.safe_load(open(session.partcad_ctx.root.config_path).read())
    config["parts"]["sized"] = {"type": "basic", "parameters": {"edge": 1}, "cuboid": 1}
    with open(session.partcad_ctx.root.config_path, "w") as f:
        f.write(yaml.safe_dump(config, sort_keys=False))
    session.partcad_ctx.reload_packages(["//"])

    answer = operations.copy_object(
        session, {"package": "//", "object": "sized", "params": ["edge=3"], "target": "big", "dry_run": True}
    )

    assert "    edge: 3" in answer["declaration"].splitlines()


def test_used_by_an_instance_is_used_by_its_object(session):
    answer = ops.used_by(session, {"package": "//", "object": "cube", "params": ["x=1"], "kind": "part"})

    assert answer["object"] == "//:cube"


def test_a_comparison_looks_up_a_kind_that_is_not_the_default(session):
    # A sketch, so that a lookup falling back to 'part' would read both sides as missing.
    root = session.partcad_ctx.root.config_dir
    config = yaml.safe_load(open(session.partcad_ctx.root.config_path).read())
    config["sketches"] = {"outline": {"type": "basic", "circle": 1}}
    with open(session.partcad_ctx.root.config_path, "w") as f:
        f.write(yaml.safe_dump(config, sort_keys=False))
    sketched = _commit(root, "sketched")
    config["sketches"]["outline"]["circle"] = 2
    with open(session.partcad_ctx.root.config_path, "w") as f:
        f.write(yaml.safe_dump(config, sort_keys=False))
    session.partcad_ctx.reload_packages(["//"])

    answer = ops.rev_diff(session, {"package": "//", "object": "outline", "from": sketched})

    assert answer["left"]["missing"] is False and answer["right"]["missing"] is False
    assert [(row["left"], row["right"]) for row in answer["rows"] if row["tag"] == "replace"] == [
        ("  circle: 1", "  circle: 2")
    ]


# ---- what each method answers when it cannot ------------------------------------


@pytest.mark.parametrize(
    "operation",
    [
        ops.views,
        ops.rev_list,
        ops.rev_diff,
        ops.rev_status,
        ops.rev_stage,
        ops.rev_new,
        ops.deps_list,
        ops.deps_add,
        ops.deps_remove,
        ops.deps_update,
        ops.used_by,
        ops.impact,
        operations.copy_object,
    ],
)
def test_with_no_context_there_is_no_answer(session, operation):
    session.partcad_ctx = None

    assert operation(session, {"package": "//", "object": "cube", "from": "x", "target": "y"}) is None


@pytest.mark.parametrize(
    "operation, params",
    [
        (ops.rev_list, {"package": "//nowhere"}),
        (ops.rev_diff, {"package": "//", "object": "cube", "from": "nowhere"}),
        (ops.deps_list, {"package": "//@nowhere"}),
        (ops.used_by, {"package": "//nowhere", "object": "x", "kind": "part"}),
        (ops.deps_add, {"package": "//", "object": "cube", "name": "x", "location": "../x"}),
        (ops.rev_list, {"package": "//", "object": "nothing"}),
        (operations.copy_object, {"package": "//", "object": "//nowhere:x", "target": "y"}),
        (operations.copy_object, {"package": "//", "object": "cube", "target": "//nowhere:y"}),
    ],
)
def test_what_is_not_there_is_refused(session, operation, params):
    with pytest.raises(JsonRpcError):
        operation(session, params)


def test_used_by_a_package_is_what_uses_anything_in_it(session):
    answer = ops.used_by(session, {"package": "//"})

    assert answer["package"] == "//" and answer["object"] is None
    assert answer["objects"] == [] and answer["packages"] == []


def test_a_package_s_declaration_that_cannot_be_written_says_why(session, tmp_path):
    import types

    root = session.partcad_ctx.root
    assert operations._package_not_editable(root) is None
    assert "no 'partcad.yaml'" in operations._package_not_editable(
        types.SimpleNamespace(not_written_to=lambda: None, config_path=None)
    )
    assert "cannot be read" in operations._package_not_editable(
        types.SimpleNamespace(not_written_to=lambda: None, config_path=str(tmp_path / "missing.yaml"))
    )
    template = tmp_path / "template.yaml"
    template.write_text("name: {{ name }}\n")
    assert "Jinja2" in operations._package_not_editable(
        types.SimpleNamespace(not_written_to=lambda: None, config_path=str(template))
    )
    at_first = session.partcad_ctx.get_project("//@" + session.first)
    assert "revision" in operations._package_not_editable(at_first)
    with pytest.raises(JsonRpcError):
        operations.requirements_add(
            session,
            {
                "package": "//@" + session.first,
                "kind": "package",
                "requirement": "feature",
                "name": "x",
                "value": "y",
            },
        )


def test_a_package_requirement_given_as_text_is_read_as_a_value_and_a_bad_edit_is_refused(session):
    operations.requirements_add(
        session,
        {
            "package": "//",
            "kind": "package",
            "requirement": "has",
            "name": "dependencies",
            "value": "false",
            "text": True,
        },
    )
    answer = operations.requirements_check(session, {"package": "//", "kind": "package", "verify": False})
    assert answer["declared"]["has_dependencies"] is False

    with pytest.raises(JsonRpcError):
        operations.requirements_remove(
            session, {"package": "//", "kind": "package", "requirement": "feature", "name": "nothing-of-that-name"}
        )


def test_only_what_has_a_declaration_is_copied(session):
    with pytest.raises(JsonRpcError, match="cannot be copied"):
        operations.copy_object(session, {"package": "//", "object": "cube", "kind": "provider", "target": "y"})
