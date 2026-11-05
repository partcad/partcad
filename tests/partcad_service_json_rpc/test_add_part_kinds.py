#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# 'add.object' takes the part types 'pc add part' takes, and refuses every
# other: it is what the CLI, the editor extension and an agent's 'execute' all
# end in, and only the CLI checked the type before it. Real PartCAD, not the
# fakes 'test_operations.py' uses: the list is half PartCAD's own declarations.
#

import pytest
import yaml

import partcad
from partcad.actions.part import addable_part_kinds
from partcad_cli.click.commands.add.part import PART_KINDS
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError
from partcad_utils import part_kinds

PLATE = "tests/partcad/unit/data/import_iges/plate.igs"


@pytest.fixture
def session(tmp_path, monkeypatch):
    (tmp_path / "partcad.yaml").write_text("name: //\n")
    monkeypatch.chdir(tmp_path)
    session = Session()
    session.partcad = partcad
    session.partcad_ctx = partcad.init(str(tmp_path))
    return session


def declared(tmp_path) -> dict:
    return yaml.safe_load((tmp_path / "partcad.yaml").read_text()).get("parts") or {}


def test_the_daemon_takes_the_types_the_cli_takes(session):
    """One list, read at both ends: a type one takes and the other refuses is a
    part that can be added from one client and not another."""
    assert list(addable_part_kinds(session.partcad_ctx)) == PART_KINDS


def test_every_file_factory_is_one_partcad_has():
    assert set(part_kinds.FILE_PART_FACTORIES) <= set(partcad.factory.all["part"])


def test_a_native_type_is_added(session, tmp_path, request):
    plate = tmp_path / "plate.igs"
    plate.write_bytes((request.config.rootpath / PLATE).read_bytes())

    assert operations.add_object(session, {"obj_kind": "part", "kind": "iges", "path": str(plate)}) == {"name": "plate"}
    assert declared(tmp_path) == {"plate": {"type": "iges", "path": "plate.igs"}}


@pytest.mark.parametrize("kind", ["3dm", "basic", ":mytype", None])
def test_any_other_type_is_refused_and_nothing_is_written(session, tmp_path, kind):
    thing = tmp_path / "thing.3dm"
    thing.write_text("not a part\n")
    params = {"obj_kind": "part", "path": str(thing)}
    if kind is not None:
        params["kind"] = kind

    with pytest.raises(JsonRpcError) as refused:
        operations.add_object(session, params)

    assert refused.value.code == operations.USAGE_ERROR
    # The refusal names what would have been taken, the way the CLI's does.
    assert "iges" in refused.value.message and "step" in refused.value.message
    assert declared(tmp_path) == {}


def test_a_url_is_refused_before_anything_is_fetched(session, tmp_path):
    # Nothing listens there: a fetch would fail with another message.
    params = {"obj_kind": "part", "kind": "3dm", "url": "http://127.0.0.1:9/thing.3dm"}
    with pytest.raises(JsonRpcError, match="cannot be added as '3dm'"):
        operations.add_object(session, params)
    assert declared(tmp_path) == {}
