#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the shared operations core.

These lock in the event contract the VS Code extension depends on. The heavy
``partcad`` context is replaced by a faithful fake so the operation glue (param
extraction, event emission, guards) is exercised without a real CAD
environment.
"""

import contextlib

import pytest
from partcad_service_json_rpc.core import events, operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session


class FakeLogging:
    @contextlib.contextmanager
    def Process(self, *args, **kwargs):
        yield

    @contextlib.contextmanager
    def Action(self, *args, **kwargs):
        yield

    def exception(self, *args, **kwargs):
        pass


class FakePartcad:
    __version__ = "0.7.146"

    def __init__(self):
        self.logging = FakeLogging()


class FakeShape:
    def __init__(self):
        self.shown = False

    def show(self):
        self.shown = True

    def render(self, ctx, export_type, filepath=None):
        self.rendered = (export_type, filepath)


class FakeProject:
    def __init__(self, path="pkgdir"):
        self.path = path


class FakeContext:
    def __init__(self):
        self.config_path = "/abs/partcad.yaml"
        self.requested = []
        self._project = FakeProject()
        # Stats attributes read by the info/getStats operation.
        for name in (
            "stats_packages",
            "stats_packages_instantiated",
            "stats_sketches",
            "stats_sketches_instantiated",
            "stats_interfaces",
            "stats_interfaces_instantiated",
            "stats_parts",
            "stats_parts_instantiated",
            "stats_assemblies",
            "stats_assemblies_instantiated",
            "stats_memory",
        ):
            setattr(self, name, 0)

    def stats_recalc(self):
        self.stats_packages = 3

    def get_part(self, name, params=None):
        self.requested.append(("part", name, params))
        return FakeShape()

    def get_project(self, name):
        return self._project


def make_session():
    seen = []
    session = Session(EventEmitter(lambda e, p: seen.append((e, p))))
    session.partcad = FakePartcad()
    session.partcad_ctx = FakeContext()
    return session, seen


def test_bind_log_stream_exposes_the_external_write_stream():
    import io

    session = Session()
    stream = io.StringIO()
    session.bind_log_stream(stream)
    assert session.log_write_stream is stream


def test_inspect_part_shows_the_part_and_signals_done():
    session, seen = make_session()
    operations.inspect_part(session, {"package": "//", "name": "foo"})
    assert ("part", "//:foo", None) in session.partcad_ctx.requested
    assert seen[-1] == (events.SHOW_PART_DONE, None)


def test_inspect_part_without_context_is_a_silent_noop():
    seen = []
    session = Session(EventEmitter(lambda e, p: seen.append((e, p))))
    session.partcad_ctx = None
    assert operations.inspect_part(session, {"package": "//", "name": "foo"}) is None
    assert seen == []


def test_info_emits_stats_with_version_and_recalculated_counts():
    session, seen = make_session()
    operations.info(session, {})
    event, payload = seen[-1]
    assert event == events.STATS
    assert payload["version"] == "0.7.146"
    assert payload["stats"]["packages"] == 3
    assert payload["stats"]["path"] == "/abs/partcad.yaml"


def test_package_path_emits_execute_with_the_callback(tmp_path):
    session, seen = make_session()
    session.partcad_ctx._project = FakeProject(path=str(tmp_path))
    operations.package_path(session, {"package": "//sub", "callback": "partcad.addPart2"})
    event, payload = seen[-1]
    assert event == events.EXECUTE
    assert payload["command"] == "partcad.addPart2"
    assert payload["args"][0]["packageName"] == "//sub"
    assert payload["args"][0]["isAbsolute"] is True


def test_export_part_renders_to_filepath_and_signals_export_done():
    session, seen = make_session()
    operations.export_part(
        session,
        {"type": "stl", "path": "/tmp/out.stl", "package": "//", "name": "foo"},
    )
    assert seen[-1] == (events.EXPORT_PART_DONE, None)
