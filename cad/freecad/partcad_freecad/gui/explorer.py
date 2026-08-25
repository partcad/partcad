#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD explorer: packages and their objects, as a tree.

The same hierarchy ``pc list all -r`` prints, expanded lazily -- a package's
contents are fetched the first time its node is opened, because a recursive walk
of the public repository clones every package it reaches.

Activating a part or an assembly (double click, Enter, or the Import command) is
what opens the parameter dialog and, on confirmation, imports the object.
"""

from .. import log, model
from .qt import QtCore, QtGui, QtWidgets, exec_menu

_ITEM_ROLE = QtCore.Qt.UserRole
_PLACEHOLDER = "__partcad_placeholder__"

# The tree shows what the object is, so the icon only has to separate the kinds.
_ICONS = {
    model.KIND_PACKAGE: QtWidgets.QStyle.SP_DirIcon,
    model.KIND_ASSEMBLY: QtWidgets.QStyle.SP_FileDialogDetailedView,
    model.KIND_PART: QtWidgets.QStyle.SP_FileIcon,
    model.KIND_INTERFACE: QtWidgets.QStyle.SP_FileDialogInfoView,
    model.KIND_SKETCH: QtWidgets.QStyle.SP_FileDialogContentsView,
}


def _icon(kind):
    style = QtWidgets.QApplication.style()
    return style.standardIcon(_ICONS.get(kind, QtWidgets.QStyle.SP_FileIcon))


class ExplorerWidget(QtWidgets.QWidget):
    """The tree, its toolbar, and the lazy expansion behind them."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addLayout(self._build_toolbar())

        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setHeaderLabels(["Object", "Description"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)

        self.status = QtWidgets.QLabel("No package is open.", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    # ---- construction -------------------------------------------------------

    def _build_toolbar(self):
        row = QtWidgets.QHBoxLayout()
        for text, tooltip, slot in (
            ("Open...", "Open a PartCAD package directory", self.open_package),
            ("Refresh", "Reload the packages and their contents", self.refresh),
            ("Import", "Import the selected part or assembly", self.import_selected),
        ):
            button = QtWidgets.QPushButton(text, self)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        return row

    # ---- tree ---------------------------------------------------------------

    def _add_items(self, parent, contents):
        """Fill ``parent`` (or the tree root) with one package's contents."""
        for item in contents:
            node = QtWidgets.QTreeWidgetItem([item.label, item.desc.split("\n")[0]])
            node.setIcon(0, _icon(item.kind))
            node.setData(0, _ITEM_ROLE, item)
            node.setToolTip(0, "%s (%s)" % (item.qualified_name, item.type or item.kind))
            if item.kind == model.KIND_PACKAGE:
                # A child that is only created once the package is expanded: the
                # contents are one round trip away and may clone a repository.
                node.addChild(QtWidgets.QTreeWidgetItem([_PLACEHOLDER]))
            elif not item.is_importable:
                node.setForeground(0, QtGui.QBrush(QtCore.Qt.gray))
            if parent is None:
                self.tree.addTopLevelItem(node)
            else:
                parent.addChild(node)

    def _is_unexpanded(self, node) -> bool:
        return node.childCount() == 1 and node.child(0).text(0) == _PLACEHOLDER

    def set_root(self, contents) -> None:
        """Replace the tree with a freshly loaded package."""
        self.tree.clear()
        if contents is None:
            self.status.setText("No package is open.")
            return
        self._add_items(None, contents)
        self.status.setText("%s: %d item(s)" % (contents.name, len(contents)))

    def selected_item(self):
        node = self.tree.currentItem()
        return node.data(0, _ITEM_ROLE) if node is not None else None

    # ---- actions ------------------------------------------------------------

    def _guard(self, what: str, work):
        """Run ``work``, reporting a failure instead of raising out of a Qt slot.

        A package that cannot be loaded is ordinary (a broken ``partcad.yaml``,
        a dependency that needs updating, a repository that will not clone), and
        an exception escaping a signal handler would surface as a traceback in
        the console with nothing in the UI to explain it.
        """
        try:
            return work()
        except Exception as e:  # pylint: disable=broad-except
            log.error("%s: %s" % (what, e))
            QtWidgets.QMessageBox.critical(self.window(), "PartCAD", "%s:\n\n%s" % (what, e))
            return None

    def open_package(self) -> None:
        contents = self._guard("Failed to open the package", lambda: self.controller.open_package(parent=self.window()))
        if contents is not None:
            self.set_root(contents)

    def refresh(self) -> None:
        contents = self._guard("Failed to refresh", lambda: self.controller.refresh(parent=self.window()))
        if contents is not None:
            self.set_root(contents)

    def import_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            QtWidgets.QMessageBox.information(
                self.window(), "PartCAD", "Select a part or an assembly in the explorer first."
            )
            return
        self.import_item(item)

    def import_item(self, item) -> None:
        """Import one object, reporting a failure rather than raising into Qt.

        The controller guards only the export and the insert; everything before
        that -- building the dialog from the object's parameters, reading the
        values back -- would otherwise escape into the signal handler.
        """
        self._guard("Failed to import %s" % item.name, lambda: self.controller.import_item(item, parent=self.window()))

    def _on_expanded(self, node) -> None:
        item = node.data(0, _ITEM_ROLE)
        if item is None or item.kind != model.KIND_PACKAGE or not self._is_unexpanded(node):
            return
        node.takeChildren()
        contents = self._guard(
            "Failed to list %s" % item.name, lambda: self.controller.list_package(item.name, parent=self.window())
        )
        if contents is None:
            # Put the placeholder back, so the failure can be retried by
            # collapsing and expanding the node again.
            node.addChild(QtWidgets.QTreeWidgetItem([_PLACEHOLDER]))
            node.setExpanded(False)
            return
        self._add_items(node, contents)
        if node.childCount() == 0:
            empty = QtWidgets.QTreeWidgetItem(["(empty)"])
            empty.setForeground(0, QtGui.QBrush(QtCore.Qt.gray))
            node.addChild(empty)

    def _on_activated(self, node, _column) -> None:
        item = node.data(0, _ITEM_ROLE)
        if item is None:
            return
        if item.kind == model.KIND_PACKAGE:
            node.setExpanded(not node.isExpanded())
            return
        if item.is_importable:
            self.import_item(item)

    def _on_context_menu(self, point) -> None:
        node = self.tree.itemAt(point)
        if node is None:
            return
        item = node.data(0, _ITEM_ROLE)
        if item is None:
            return
        menu = QtWidgets.QMenu(self)
        if item.is_importable:
            # Bound to the node under the cursor, like "Expand" below, rather
            # than to the current item -- a right-click does not have to have
            # moved the current item to the node it landed on.
            menu.addAction("Import into the document...", lambda: self.import_item(item))
        if item.kind == model.KIND_PACKAGE:
            menu.addAction("Expand", lambda: node.setExpanded(True))
        menu.addAction("Copy name", lambda: QtWidgets.QApplication.clipboard().setText(item.qualified_name))
        exec_menu(menu, self.tree.viewport().mapToGlobal(point))


class ExplorerDock(QtWidgets.QDockWidget):
    """The explorer, docked where FreeCAD's own tree views live."""

    OBJECT_NAME = "PartCADExplorer"

    def __init__(self, controller, parent=None):
        super().__init__("PartCAD", parent)
        self.setObjectName(self.OBJECT_NAME)
        self.widget = ExplorerWidget(controller, self)
        self.setWidget(self.widget)


def show(controller, parent=None) -> ExplorerDock:
    """Create the dock if needed, then raise it. Returns the dock."""
    parent = parent or _main_window()
    existing = parent.findChild(ExplorerDock, ExplorerDock.OBJECT_NAME) if parent else None
    if existing is None:
        existing = ExplorerDock(controller, parent)
        if parent is not None:
            parent.addDockWidget(QtCore.Qt.LeftDockWidgetArea, existing)
    existing.show()
    existing.raise_()
    return existing


def _main_window():
    from .controller import main_window  # pylint: disable=import-outside-toplevel

    return main_window()
