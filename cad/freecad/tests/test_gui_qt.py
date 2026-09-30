#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The widgets, against a real Qt.

Skipped wherever no Qt binding is installed, which is the case in this
repository's CI -- Qt comes with FreeCAD, not with the test environment. Run
them with ``pip install PySide6-Essentials`` to exercise the parameter dialog
and the explorer for real; the stubbed :mod:`test_gui_imports` is what runs
everywhere.
"""

import os

import pytest
from partcad_freecad.model import KIND_PART, Item, parse_items

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="no Qt binding available")

from PySide6 import QtWidgets  # noqa: E402  pylint: disable=wrong-import-position

CONFIG = {
    "type": "cadquery",
    "desc": "A cube",
    "parameters": {
        "width": {"type": "float", "default": 10.0},
        "count": {"type": "int", "default": 3},
        "label": {"type": "string", "default": "front"},
        "hollow": {"type": "bool", "default": False},
        "finish": {"type": "string", "default": "raw", "enum": ["raw", "anodized"]},
        "offsets": {"type": "array", "default": [1, 2]},
    },
}


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def dialog(app):  # pylint: disable=unused-argument
    from partcad_freecad.gui.dialog import ParameterDialog

    return ParameterDialog(Item(KIND_PART, "cube", "//", CONFIG))


def test_the_dialog_starts_at_the_declared_defaults(dialog):
    assert dialog.values() == {
        "width": 10.0,
        "count": 3,
        "label": "front",
        "hollow": False,
        "finish": "raw",
        "offsets": [1, 2],
    }


def test_each_type_gets_the_control_it_needs(dialog):
    controls = dialog._controls  # pylint: disable=protected-access

    assert isinstance(controls["hollow"], QtWidgets.QCheckBox)
    assert isinstance(controls["finish"], QtWidgets.QComboBox)
    assert isinstance(controls["count"], QtWidgets.QSpinBox)
    assert isinstance(controls["width"], QtWidgets.QLineEdit)


def test_edits_are_read_back_and_coerced(dialog):
    controls = dialog._controls  # pylint: disable=protected-access
    controls["width"].setText("12,5")
    controls["count"].setValue(9)
    controls["hollow"].setChecked(True)
    controls["finish"].setCurrentIndex(1)

    values = dialog.values()

    assert values["width"] == 12.5
    assert values["count"] == 9
    assert values["hollow"] is True
    assert values["finish"] == "anodized"


def test_restoring_defaults_undoes_every_edit(dialog):
    controls = dialog._controls  # pylint: disable=protected-access
    controls["width"].setText("99.0")
    controls["hollow"].setChecked(True)

    dialog.restore_defaults()

    assert dialog.values()["width"] == 10.0
    assert dialog.values()["hollow"] is False


def test_an_object_without_parameters_still_gets_a_confirmation_dialog(app):  # pylint: disable=unused-argument
    from partcad_freecad.gui.dialog import ParameterDialog

    dialog = ParameterDialog(Item(KIND_PART, "plain", "//", {"type": "step"}))

    assert dialog.specs == []
    assert dialog.values() == {}


class FakeController:
    """Stands in for the controller so the widget can be driven without a service."""

    def __init__(self):
        self.service = object()
        self.imported = []

    def list_package(self, name, parent=None):  # pylint: disable=unused-argument
        return parse_items({"name": name, "parts": [{"name": "bolt", "type": "step"}]})

    def import_item(self, item, parent=None):  # pylint: disable=unused-argument
        self.imported.append(item.qualified_name)
        return True


@pytest.fixture
def explorer(app):  # pylint: disable=unused-argument
    from partcad_freecad.gui.explorer import ExplorerWidget

    controller = FakeController()
    widget = ExplorerWidget(controller)
    widget.set_root(
        parse_items(
            {
                "name": "//",
                "packages": [{"name": "//pub", "type": "git"}],
                "parts": [{"name": "cube", "type": "cadquery", "desc": "A cube\nsecond line"}],
            }
        )
    )
    return widget, controller


def test_a_package_starts_collapsed_and_is_fetched_on_expansion(explorer):
    widget, _controller = explorer
    package = widget.tree.topLevelItem(0)

    assert package.childCount() == 1  # the placeholder, not the contents

    package.setExpanded(True)

    assert [package.child(i).text(0) for i in range(package.childCount())] == ["bolt"]


def test_expanding_twice_does_not_fetch_twice(explorer):
    widget, _controller = explorer
    package = widget.tree.topLevelItem(0)
    package.setExpanded(True)
    package.setExpanded(False)
    package.setExpanded(True)

    assert package.childCount() == 1


def test_only_the_first_line_of_a_description_is_shown(explorer):
    widget, _controller = explorer

    assert widget.tree.topLevelItem(1).text(1) == "A cube"


def test_activating_a_part_imports_it(explorer):
    widget, controller = explorer
    part = widget.tree.topLevelItem(1)

    widget._on_activated(part, 0)  # pylint: disable=protected-access

    assert controller.imported == ["//:cube"]


def test_activating_a_package_expands_it_instead(explorer):
    widget, controller = explorer
    package = widget.tree.topLevelItem(0)

    widget._on_activated(package, 0)  # pylint: disable=protected-access

    assert package.isExpanded()
    assert controller.imported == []


def test_a_package_that_cannot_be_listed_stays_retryable(explorer, monkeypatch):
    from partcad_freecad.gui import explorer as explorer_module

    widget, controller = explorer
    reported = []
    monkeypatch.setattr(explorer_module.QtWidgets.QMessageBox, "critical", lambda *args: reported.append(args[2]))

    def failing(_name, parent=None):
        raise RuntimeError("needs 'pc update'")

    controller.list_package = failing
    package = widget.tree.topLevelItem(0)

    package.setExpanded(True)

    assert reported and "pc update" in reported[0]
    # The placeholder is back, so expanding again retries rather than showing an
    # empty package.
    assert package.childCount() == 1
    assert not package.isExpanded()


def test_the_import_button_uses_the_selected_item(explorer):
    widget, controller = explorer
    widget.tree.setCurrentItem(widget.tree.topLevelItem(1))

    widget.import_selected()

    assert controller.imported == ["//:cube"]


def test_a_failing_import_is_reported_rather_than_raised(explorer, monkeypatch):
    from partcad_freecad.gui import explorer as explorer_module

    widget, controller = explorer
    reported = []
    monkeypatch.setattr(explorer_module.QtWidgets.QMessageBox, "critical", lambda *args: reported.append(args[2]))

    def failing(_item, parent=None):
        # The controller guards the export and the insert, but not the dialog it
        # builds from the object's parameters.
        raise ValueError("width: expected a number")

    controller.import_item = failing
    widget.tree.setCurrentItem(widget.tree.topLevelItem(1))

    widget.import_selected()

    assert reported and "expected a number" in reported[0]


class FakeService:
    """A PartCadService stand-in whose load either succeeds or fails."""

    def __init__(self, contents=None, failure=None):
        self.contents = contents
        self.failure = failure
        self.closed = False

    def ensure_loaded(self):
        pass

    def init_package(self):
        pass

    def load_package(self):
        if self.failure is not None:
            raise self.failure
        return self.contents

    def close(self):
        self.closed = True


def _controller_with_package(app, monkeypatch, tmp_path, service):  # pylint: disable=unused-argument
    """A controller pointed at a real package directory, with a stubbed service."""
    from partcad_freecad.gui import controller as controller_module

    (tmp_path / "partcad.yaml").write_text("name: test\n")
    monkeypatch.setattr(controller_module.provision, "resolve_service_path", lambda _cache: "/opt/partcad-json-rpc")
    monkeypatch.setattr(controller_module.settings, "set_package_dir", lambda _path: None)
    monkeypatch.setattr(controller_module, "PartCadService", lambda *args, **kwargs: service)
    return controller_module.Controller()


def test_a_successful_load_installs_the_service(app, monkeypatch, tmp_path):
    contents = parse_items({"name": "//", "parts": [{"name": "cube"}]})
    service = FakeService(contents=contents)
    controller = _controller_with_package(app, monkeypatch, tmp_path, service)

    assert controller.open_package(str(tmp_path), parent=None) is contents
    assert controller.service is service


def test_a_failed_load_leaves_the_previous_package_in_place(app, monkeypatch, tmp_path):
    working = FakeService(contents=parse_items({"name": "//", "parts": [{"name": "cube"}]}))
    broken = FakeService(failure=RuntimeError("Package YAML file is not found"))
    controller = _controller_with_package(app, monkeypatch, tmp_path, working)
    controller.open_package(str(tmp_path), parent=None)

    from partcad_freecad.gui import controller as controller_module

    monkeypatch.setattr(controller_module, "PartCadService", lambda *args, **kwargs: broken)

    with pytest.raises(RuntimeError, match="not found"):
        controller.open_package(str(tmp_path), parent=None)

    # The working package is still the one loaded, and the service that never
    # loaded has been closed rather than left assigned.
    assert controller.service is working
    assert not working.closed
    assert broken.closed


def test_work_runs_off_the_qt_thread_and_returns_its_result(app):  # pylint: disable=unused-argument
    import threading

    from partcad_freecad.gui.worker import run_busy

    seen = {}

    def work(progress):
        progress("working...")
        seen["thread"] = threading.current_thread()
        return 42

    assert run_busy(None, "PartCAD", "...", work) == 42
    assert seen["thread"] is not threading.current_thread()


def test_a_failure_on_the_worker_thread_reaches_the_caller(app):  # pylint: disable=unused-argument
    from partcad_freecad.gui.worker import run_busy

    def work(_progress):
        raise RuntimeError("the service closed the connection")

    with pytest.raises(RuntimeError, match="closed the connection"):
        run_busy(None, "PartCAD", "...", work)
