#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the commands and the explorer actually do.

Holds the one service connection the addon keeps alive, and sequences the three
flows the user sees: opening a package, expanding it, and importing an object.
Every service call goes through :func:`~partcad_freecad.gui.worker.run_busy`, so
the Qt thread only ever does UI work and FreeCAD document work.
"""

import os
import shutil
from typing import Optional

from .. import importer, log, params, provision, settings
from ..model import PackageContents
from ..service import PartCadService
from .dialog import ParameterDialog
from .qt import QtWidgets, exec_dialog
from .worker import run_busy

_DOWNLOAD_PROMPT = (
    "PartCAD needs its standalone service (partcad-json-rpc), which FreeCAD's "
    "Python cannot provide. This is a large one-time download (roughly 290 MB "
    "compressed, ~875 MB unpacked).\n\nDownload it now?"
)

_instance = None


def instance():
    """The addon's controller, created on first use."""
    global _instance  # pylint: disable=global-statement
    if _instance is None:
        _instance = Controller()
    return _instance


def main_window():
    try:
        import FreeCADGui  # pylint: disable=import-outside-toplevel

        return FreeCADGui.getMainWindow()
    except ImportError:  # pragma: no cover - only outside FreeCAD
        return None


class Controller:
    """The addon's session: one service connection and one temporary directory."""

    def __init__(self):
        self.service: Optional[PartCadService] = None
        self._temp_dir: Optional[str] = None

    # ---- service ------------------------------------------------------------

    def executable(self, parent) -> Optional[str]:
        """The standalone service, downloading a bundle if the user agrees."""
        cache = settings.cache_dir()
        existing = provision.resolve_service_path(cache)
        if existing:
            return existing

        prompt = _DOWNLOAD_PROMPT
        if provision.want_devel():
            prompt += "\n\nPC_CAD_DEVEL is set, so the latest 'devel' build will be used."
        answer = QtWidgets.QMessageBox.question(
            parent,
            "PartCAD",
            prompt,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return None

        return run_busy(
            parent,
            "PartCAD",
            "Preparing the PartCAD service...",
            lambda progress: provision.ensure_service(cache, progress),
        )

    def temp_dir(self) -> str:
        if self._temp_dir is None or not os.path.isdir(self._temp_dir):
            self._temp_dir = provision.temporary_dir()
        return self._temp_dir

    def shutdown(self) -> None:
        """Close the connection and remove the temporary STEP files."""
        if self.service is not None:
            self.service.close()
            self.service = None
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    # ---- packages -----------------------------------------------------------

    def open_package(self, path: Optional[str] = None, parent=None) -> Optional[PackageContents]:
        """Open a PartCAD package directory and return its top-level contents."""
        parent = parent or main_window()
        if path is None:
            start = settings.package_dir() or os.path.expanduser("~")
            path = QtWidgets.QFileDialog.getExistingDirectory(parent, "Open a PartCAD package", start)
            if not path:
                return None
        path = os.path.abspath(path)

        create = False
        if not os.path.isfile(os.path.join(path, "partcad.yaml")):
            answer = QtWidgets.QMessageBox.question(
                parent,
                "PartCAD",
                "%s is not a PartCAD package (there is no partcad.yaml).\n\nCreate one there?" % path,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return None
            create = True

        executable = self.executable(parent)
        if not executable:
            return None

        # Kept local until the load succeeds. Assigning it up front would, on a
        # failure, leave a service that never loaded in place of the working one
        # -- with the explorer still showing the old tree and the Refresh/Import
        # commands still enabled, because they only test `service is not None`.
        service = PartCadService(executable, path, log=log.log)

        def work(progress):
            progress("Starting the PartCAD service...")
            service.ensure_loaded()
            if create:
                progress("Creating the package...")
                service.init_package()
            progress("Loading %s..." % path)
            return service.load_package()

        try:
            contents = run_busy(parent, "PartCAD", "Loading the package...", work)
        except Exception:
            service.close()
            raise

        if self.service is not None:
            self.service.close()
        self.service = service
        settings.set_package_dir(path)
        log.info("loaded the package at %s" % path)
        return contents

    def reopen(self, parent=None) -> Optional[PackageContents]:
        """Reload the package that is already open, if any."""
        path = settings.package_dir()
        if not path:
            return None
        return self.open_package(path, parent)

    def list_package(self, name: str, parent=None) -> PackageContents:
        """The contents of one package, for a node the user just expanded."""
        if self.service is None:
            return PackageContents(name, [])

        def work(progress):
            progress("Loading %s..." % name)
            return self.service.list_package(name)

        return run_busy(parent or main_window(), "PartCAD", "Loading %s..." % name, work)

    def refresh(self, parent=None) -> Optional[PackageContents]:
        """Re-fetch the imported packages and reload the tree."""
        if self.service is None:
            return self.reopen(parent)
        parent = parent or main_window()

        def work(progress):
            progress("Refreshing the packages...")
            self.service.refresh()
            return self.service.load_package()

        return run_busy(parent, "PartCAD", "Refreshing...", work)

    # ---- import -------------------------------------------------------------

    def import_item(self, item, parent=None) -> bool:
        """Ask for the parameters, export a STEP, and insert it into the document.

        Returns True when something was imported, False when the user cancelled.
        """
        parent = parent or main_window()
        if not item.is_importable:
            QtWidgets.QMessageBox.information(
                parent,
                "PartCAD",
                "Only parts and assemblies can be imported into a FreeCAD document.",
            )
            return False
        if self.service is None:
            QtWidgets.QMessageBox.warning(parent, "PartCAD", "Open a PartCAD package first.")
            return False

        dialog = ParameterDialog(item, parent)
        if exec_dialog(dialog) != QtWidgets.QDialog.Accepted:
            return False
        values = dialog.values()

        path = importer.step_filename(self.temp_dir(), item, values)

        def work(progress):
            progress("Exporting %s..." % item.qualified_name)
            return self.service.export(item, path, values)

        try:
            run_busy(parent, "PartCAD", "Exporting %s..." % item.name, work)
            label = item.name + params.instance_suffix(values)
            created = importer.insert_step(path, label)
        except Exception as e:  # pylint: disable=broad-except
            log.error("failed to import %s: %s" % (item.qualified_name, e))
            QtWidgets.QMessageBox.critical(parent, "PartCAD", "Failed to import %s:\n\n%s" % (item.name, e))
            return False
        finally:
            # The STEP is a hand-off to FreeCAD, which has read it by now.
            if os.path.exists(path):
                os.remove(path)

        log.info("imported %s as %d object(s)" % (item.qualified_name, len(created)))
        return True
