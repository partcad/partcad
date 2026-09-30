#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The dialog shown when a part or an assembly is selected.

One control per declared parameter, chosen from the parameter's type -- the same
mapping the VS Code inspector applies, expressed in Qt:

===========  ==========================================
type         control
===========  ==========================================
``bool``     a check box
``enum``     a combo box (any type may declare ``enum``)
``int``      a spin box
``float``    a line edit that accepts decimals
``array``    a line edit holding a JSON list
``string``   a line edit
===========  ==========================================

Confirming the dialog is what triggers the export and the import; the values are
coerced back to their declared types first, so a typo is reported here rather
than as a failed render minutes later.
"""

from .. import params as _params
from ..model import KIND_ASSEMBLY
from .qt import QtCore, QtGui, QtWidgets

_INT_RANGE = 2**31 - 1


class ParameterDialog(QtWidgets.QDialog):
    """Collects the parameter values for one part or assembly."""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.specs = _params.parse_parameters(item.config)
        self._controls = {}

        kind = "assembly" if item.kind == KIND_ASSEMBLY else "part"
        self.setWindowTitle("Import %s '%s'" % (kind, item.name))
        self.setMinimumWidth(420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._build_summary())
        layout.addWidget(self._build_parameters())
        layout.addStretch(1)
        layout.addWidget(self._build_buttons())

    # ---- construction -------------------------------------------------------

    def _build_summary(self):
        box = QtWidgets.QGroupBox("Object", self)
        form = QtWidgets.QFormLayout(box)
        form.addRow("Name:", self._value_label(self.item.name))
        form.addRow("Package:", self._value_label(self.item.package))
        if self.item.type:
            form.addRow("Type:", self._value_label(self.item.type))
        if self.item.desc:
            description = self._value_label(self.item.desc)
            description.setWordWrap(True)
            form.addRow("Description:", description)
        return box

    def _value_label(self, text: str):
        label = QtWidgets.QLabel(text, self)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        return label

    def _build_parameters(self):
        box = QtWidgets.QGroupBox("Parameters", self)
        form = QtWidgets.QFormLayout(box)
        if not self.specs:
            hint = QtWidgets.QLabel("This object has no parameters.", self)
            hint.setEnabled(False)
            form.addRow(hint)
            return box
        for spec in self.specs:
            control = self._build_control(spec)
            self._controls[spec.name] = control
            if spec.desc:
                control.setToolTip(spec.desc)
            form.addRow("%s:" % spec.name, control)
        return box

    def _build_control(self, spec):
        if spec.is_enum:
            combo = QtWidgets.QComboBox(self)
            options = [_params.format_value(spec.type, option) for option in spec.enum]
            combo.addItems(options)
            current = _params.format_value(spec.type, spec.default)
            if current in options:
                combo.setCurrentIndex(options.index(current))
            return combo
        if spec.type == _params.TYPE_BOOL:
            check = QtWidgets.QCheckBox(self)
            check.setChecked(bool(spec.default))
            return check
        if spec.type == _params.TYPE_INT:
            spin = QtWidgets.QSpinBox(self)
            # PartCAD puts no bounds on an int parameter unless the object does,
            # so open the spin box up to what Qt can represent.
            spin.setRange(
                int(spec.min) if spec.min is not None else -_INT_RANGE,
                int(spec.max) if spec.max is not None else _INT_RANGE,
            )
            spin.setValue(int(spec.default or 0))
            return spin
        edit = QtWidgets.QLineEdit(self)
        edit.setText(spec.format_default())
        if spec.type == _params.TYPE_FLOAT:
            validator = QtGui.QDoubleValidator(self)
            validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
            validator.setDecimals(6)
            if spec.min is not None:
                validator.setBottom(float(spec.min))
            if spec.max is not None:
                validator.setTop(float(spec.max))
            edit.setValidator(validator)
        elif spec.type == _params.TYPE_ARRAY:
            edit.setPlaceholderText("JSON list, e.g. [1, 2, 3]")
        return edit

    def _build_buttons(self):
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Import")
        if self.specs:
            reset = buttons.addButton("Restore Defaults", QtWidgets.QDialogButtonBox.ResetRole)
            reset.clicked.connect(self.restore_defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        return buttons

    # ---- values -------------------------------------------------------------

    def _raw_values(self) -> dict:
        raw = {}
        for spec in self.specs:
            control = self._controls[spec.name]
            if isinstance(control, QtWidgets.QCheckBox):
                raw[spec.name] = control.isChecked()
            elif isinstance(control, QtWidgets.QComboBox):
                raw[spec.name] = control.currentText()
            elif isinstance(control, QtWidgets.QSpinBox):
                raw[spec.name] = control.value()
            else:
                raw[spec.name] = control.text()
        return raw

    def values(self) -> dict:
        """The parameter values, coerced to their declared types."""
        return _params.collect(self.specs, self._raw_values())

    def restore_defaults(self) -> None:
        for spec in self.specs:
            control = self._controls[spec.name]
            if isinstance(control, QtWidgets.QCheckBox):
                control.setChecked(bool(spec.default))
            elif isinstance(control, QtWidgets.QComboBox):
                current = _params.format_value(spec.type, spec.default)
                index = control.findText(current)
                if index >= 0:
                    control.setCurrentIndex(index)
            elif isinstance(control, QtWidgets.QSpinBox):
                control.setValue(int(spec.default or 0))
            else:
                control.setText(spec.format_default())

    def accept(self) -> None:
        """Validate before closing, so a bad value is reported where it was typed."""
        try:
            self.values()
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "Invalid parameter", str(e))
            return
        super().accept()
