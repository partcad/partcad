#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The service facade: turning notifications into a tree, and failures into errors."""

import logging
import os

import pytest
from partcad_freecad.model import KIND_ASSEMBLY, KIND_PART, Item
from partcad_freecad.service import PartCadService, ServiceFailure


class FakeClient:
    """Replays a scripted notification stream for each method called."""

    def __init__(self, script=None, side_effect=None):
        self.script = script or {}
        self.side_effect = side_effect
        self.calls = []
        self.closed = False

    def call(self, method, params=None, on_event=None):
        self.calls.append((method, params))
        for event, payload in self.script.get(method, []):
            if on_event is not None:
                on_event(event, payload)
        if self.side_effect is not None:
            self.side_effect(method, params)
        return None

    def close(self):
        self.closed = True


def _service(script=None, log=None, side_effect=None, package_dir="/w"):
    client = FakeClient(script, side_effect)
    return PartCadService("/opt/partcad-json-rpc", package_dir, log=log, client=client), client


ITEMS = ("items", {"name": "//", "parts": [{"name": "cube", "type": "cadquery"}]})
LOADED = ("packageLoaded", {"root": "//", "configPath": "/w/partcad.yaml"})


def test_load_package_returns_the_root_contents():
    service, client = _service({"package.load": [LOADED, ITEMS]})

    contents = service.load_package()

    assert contents.name == "//"
    assert [item.name for item in contents] == ["cube"]
    assert service.config_path == "/w/partcad.yaml"
    assert client.calls == [("package.load", {"path": "/w"})]


def test_load_package_reports_a_load_failure():
    service, _ = _service({"package.load": [("error", "Package YAML file is not found"), ("packageLoadFailed", None)]})

    with pytest.raises(ServiceFailure, match="could not be loaded"):
        service.load_package()


def test_load_package_without_contents_reports_the_logged_error():
    service, _ = _service({"package.load": [("error", "boom")]})

    with pytest.raises(ServiceFailure, match="boom"):
        service.load_package()


def test_the_contents_are_taken_from_the_package_that_actually_loaded():
    # The root is only known once `packageLoaded` has arrived, and a package
    # loaded from a subdirectory is not named '//'.
    service, _ = _service(
        {
            "package.load": [
                ("packageLoaded", {"root": "//sub", "configPath": "/w/sub/partcad.yaml"}),
                ("items", {"name": "//sub", "assemblies": [{"name": "logo", "type": "assy"}]}),
            ]
        }
    )

    contents = service.load_package()

    assert contents.name == "//sub"
    assert service.root == "//sub"


def test_needs_update_is_reported_rather_than_silently_empty():
    service, _ = _service({"package.load": [("needsUpdate", None)]})

    with pytest.raises(ServiceFailure, match="pc update"):
        service.load_package()


def test_list_package_returns_that_packages_contents():
    service, client = _service({"list.all": [("items", {"name": "//pub", "parts": [{"name": "bolt"}]})]})

    contents = service.list_package("//pub")

    assert [item.name for item in contents] == ["bolt"]
    assert client.calls == [("list.all", {"name": "//pub"})]


def test_list_package_is_empty_when_nothing_was_reported():
    service, _ = _service()

    assert len(service.list_package("//pub")) == 0


def test_ensure_loaded_warms_the_daemon_for_this_directory():
    service, client = _service()

    service.ensure_loaded()

    assert client.calls == [("ensure_loaded", {"path": "/w"})]


def test_log_events_reach_the_sink_at_their_level():
    lines = []
    service, _ = _service(
        {
            "list.all": [
                ("log", {"kind": "log", "levelno": logging.INFO, "message": "loading"}),
                ("log", {"kind": "action", "op": "Render", "package": "//"}),
                ("warn", "a warning"),
            ]
        },
        log=lambda level, message: lines.append((level, message)),
    )

    service.list_package("//")

    # The progress marker carries no message and must not be rendered as a log line.
    assert lines == [(logging.INFO, "loading"), (logging.WARNING, "a warning")]


def test_errors_are_remembered_for_the_last_call():
    service, _ = _service({"list.all": [("log", {"kind": "log", "levelno": logging.ERROR, "message": "no such part"})]})

    service.list_package("//")

    assert service.last_errors == ["no such part"]


def test_the_error_list_is_reset_between_calls():
    service, client = _service({"list.all": [("error", "first")]})
    service.list_package("//")

    client.script = {}
    service.list_package("//")

    assert service.last_errors == []


def test_export_asks_for_the_right_method_and_returns_the_path(tmp_path):
    target = tmp_path / "cube.step"
    service, client = _service(side_effect=lambda *_: target.write_text("ISO-10303-21;"))
    item = Item(KIND_PART, "cube", "//", {"type": "cadquery"})

    assert service.export(item, str(target), {"width": 2.0}) == str(target)
    assert client.calls == [
        (
            "export.part",
            {
                "package": "//",
                "name": "cube",
                "params": {"width": 2.0},
                "type": "step",
                "path": str(target),
            },
        )
    ]


def test_an_assembly_is_exported_through_export_assembly(tmp_path):
    target = tmp_path / "logo.step"
    service, client = _service(side_effect=lambda *_: target.write_text("x"))

    service.export(Item(KIND_ASSEMBLY, "logo", "//", {}), str(target))

    assert client.calls[0][0] == "export.assembly"


def test_export_that_produced_no_file_is_a_failure(tmp_path):
    service, _ = _service({"export.part": [("error", "Cannot render 'cube': shape is empty")]})
    item = Item(KIND_PART, "cube", "//", {})

    with pytest.raises(ServiceFailure, match="shape is empty"):
        service.export(item, str(tmp_path / "cube.step"))


def test_export_of_an_empty_file_is_a_failure(tmp_path):
    target = tmp_path / "cube.step"
    target.write_text("")
    service, _ = _service()

    with pytest.raises(ServiceFailure, match="no output"):
        service.export(Item(KIND_PART, "cube", "//", {}), str(target))
    assert os.path.exists(target)


def test_close_drops_the_connection():
    service, client = _service()

    service.close()

    assert client.closed
    assert not service.connected
