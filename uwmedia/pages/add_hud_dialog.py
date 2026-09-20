"""Add HUD picker dialog - PySide6 port of uwmedia/app.py's
_show_add_hud_window (see pyside6_rework.md Phase 1). Built
programmatically rather than from a .ui file - its content is dynamic
(the brand/computer/page cascade depends on the HUD template manifest
loaded at runtime), same reasoning the Toga original already documents.
"""
from PySide6 import QtWidgets

from utils.hud_designer import ANCHORS

LAYOUT_CUSTOM = "Custom…"
HUD_LOCATION_PRESETS = [(anchor.replace("_", " ").title(), anchor) for anchor in ANCHORS]


def _prettify(key: str) -> str:
    return key.replace("_", " ").title()


class AddHudDialog(QtWidgets.QDialog):
    """On accept, self.result_instance holds the new overlay instance dict
    (see ColorPage.resolve_new_color_overlay, which resolve_callback should
    be) - stays None if the dialog is cancelled."""

    def __init__(self, hud_templates, resolve_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add HUD")
        self.resize(420, 260)
        self._hud_templates = hud_templates
        self._resolve_callback = resolve_callback
        self.result_instance = None
        self._brand_choices = {}
        self._computer_choices = {}
        self._page_choices = {}

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.brand_combo = QtWidgets.QComboBox()
        form.addRow("HUD brand", self.brand_combo)

        self.computer_combo = QtWidgets.QComboBox()
        form.addRow("Dive computer", self.computer_combo)
        self.computer_row_label = form.labelForField(self.computer_combo)

        self.page_combo = QtWidgets.QComboBox()
        form.addRow("Page", self.page_combo)
        self.page_row_label = form.labelForField(self.page_combo)

        custom_path_row = QtWidgets.QHBoxLayout()
        self.custom_path_input = QtWidgets.QLineEdit()
        custom_path_row.addWidget(self.custom_path_input)
        browse_button = QtWidgets.QPushButton("Browse…")
        # Qt otherwise gives the first QPushButton added to the dialog
        # autoDefault styling (macOS: the blue "default button" highlight) -
        # this one isn't the dialog's actual default action, "Add" is.
        browse_button.setAutoDefault(False)
        browse_button.clicked.connect(self._on_browse_custom_path)
        custom_path_row.addWidget(browse_button)
        form.addRow("Custom path", custom_path_row)
        self.custom_path_row_label = form.labelForField(custom_path_row)

        self.location_combo = QtWidgets.QComboBox()
        self.location_combo.addItems([label for label, _ in HUD_LOCATION_PRESETS])
        self.location_combo.setCurrentText("Bottom Left")
        form.addRow("Location", self.location_combo)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.setAutoDefault(False)
        cancel_button.clicked.connect(self.reject)
        add_button = QtWidgets.QPushButton("Add")
        add_button.setDefault(True)
        add_button.clicked.connect(self._on_add)
        button_row.addWidget(cancel_button)
        button_row.addWidget(add_button)
        layout.addLayout(button_row)

        self.brand_combo.currentTextChanged.connect(self._on_brand_change)
        self.computer_combo.currentTextChanged.connect(self._on_computer_change)

        self._brand_choices = {_prettify(key): key for key in sorted(self._hud_templates)}
        self.brand_combo.addItems(list(self._brand_choices.keys()) + [LAYOUT_CUSTOM])
        self._refresh_row_visibility()

    def _current_brand(self):
        return self._brand_choices.get(self.brand_combo.currentText())

    def _current_computer(self):
        brand = self._current_brand()
        return self._computer_choices.get(self.computer_combo.currentText()) if brand else None

    def _refresh_row_visibility(self):
        is_custom = self.brand_combo.currentText() == LAYOUT_CUSTOM
        self.custom_path_row_label.setVisible(is_custom)
        self.custom_path_input.setVisible(is_custom)
        brand = self._current_brand()
        computers = self._hud_templates.get(brand, {}) if brand else {}
        show_computer = (not is_custom) and len(computers) > 1
        self.computer_row_label.setVisible(show_computer)
        self.computer_combo.setVisible(show_computer)
        self.page_row_label.setVisible(not is_custom)
        self.page_combo.setVisible(not is_custom)

    def _refresh_computer_choices(self):
        brand = self._current_brand()
        computers = self._hud_templates.get(brand, {}) if brand else {}
        self._computer_choices = {_prettify(key): key for key in sorted(computers)}
        self.computer_combo.blockSignals(True)
        self.computer_combo.clear()
        self.computer_combo.addItems(list(self._computer_choices.keys()))
        self.computer_combo.blockSignals(False)
        self._refresh_page_choices()

    def _refresh_page_choices(self):
        brand = self._current_brand()
        computer = self._current_computer()
        manifest = self._hud_templates.get(brand, {}).get(computer) if brand and computer else None
        pages = manifest["pages"] if manifest else []
        self._page_choices = {page["name"]: page["id"] for page in pages}
        self.page_combo.clear()
        self.page_combo.addItems(list(self._page_choices.keys()))

    def _on_brand_change(self, text):
        self._refresh_row_visibility()
        if text != LAYOUT_CUSTOM:
            self._refresh_computer_choices()

    def _on_computer_change(self, _text):
        self._refresh_page_choices()

    def _on_browse_custom_path(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select layout file")
        if path:
            self.custom_path_input.setText(path)

    def _on_add(self):
        if self.brand_combo.currentText() == LAYOUT_CUSTOM:
            instance = self._resolve_callback(
                None, None, None, self.custom_path_input.text(), self.location_combo.currentText()
            )
        else:
            instance = self._resolve_callback(
                self._current_brand(),
                self._current_computer(),
                self._page_choices.get(self.page_combo.currentText()),
                None,
                self.location_combo.currentText(),
            )
        if instance is None:
            QtWidgets.QMessageBox.warning(self, "Add HUD", "Could not resolve a layout for that choice.")
            return
        self.result_instance = instance
        self.accept()
