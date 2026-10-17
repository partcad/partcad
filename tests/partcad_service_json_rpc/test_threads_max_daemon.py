#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A daemon sizes its sandbox process slots for the request it is serving.

The slots belong to the process and were sized once, at import, from the
daemon's own configuration -- whatever environment started it, possibly days
ago. So PC_THREADS_MAX and '--threads-max' did nothing to any command a warm
daemon served, although the configuration carrying them reached it with every
request. 'test_context_protocol.py' pins which configuration each step hands to
'sandbox_lock.follow'; this runs the real one -- the real 'partcad', the real
'UserConfig.from_dict', the real slots -- the way the daemon does.
"""

import importlib
from pathlib import Path

import pytest

from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.session import Session


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    """A session holding the real 'partcad', with slots of its own to move.

    The slots are replaced for the test so that the process's own, which every
    other test in this session runs its sandboxes through, are left as they were.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_THREADS_MAX", raising=False)
    (tmp_path / "home").mkdir()
    package = tmp_path / "package"
    package.mkdir()
    (package / "partcad.yaml").write_text("desc: a package with nothing in it\n")

    session = Session()
    session.partcad = importlib.import_module("partcad")
    sandbox_lock = session.partcad.sandbox_lock
    monkeypatch.setattr(sandbox_lock, "process_slots", sandbox_lock.ProcessSlots(5))
    return session, Path(package).as_uri()


def slots(session):
    return session.partcad.sandbox_lock.process_slots.count


def test_pc_threads_max_reaches_a_daemon_started_without_it(daemon, partcad_warnings):
    session, url = daemon

    operations.context_create(session, {"url": url, "userConfig": {"threadsMax": 6}})

    assert slots(session) == 6
    assert partcad_warnings == []


def test_a_low_value_is_raised_to_the_minimum_with_a_warning(daemon, partcad_warnings):
    session, url = daemon

    operations.context_create(session, {"url": url, "userConfig": {"threadsMax": 2}})

    assert slots(session) == 4
    assert partcad_warnings == [
        "threadsMax 2 (from the caller's configuration) is below the minimum of 4; using 4 instead"
    ]


def test_the_next_operation_is_served_with_its_own_context_s_slots(daemon, partcad_warnings):
    """Another client's request between this one's handshake and its operation."""
    session, url = daemon
    context = operations.context_create(session, {"url": url, "userConfig": {"threadsMax": 6}})["context"]
    session.partcad.sandbox_lock.follow(session.partcad.UserConfig.from_dict({"threadsMax": 9}))
    assert slots(session) == 9

    operations._ctx(session, {"context": context})

    assert slots(session) == 6
