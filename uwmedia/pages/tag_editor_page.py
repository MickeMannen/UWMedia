"""Tag Editor page - PySide6 port of uwmedia/app.py's
_build_tag_editor_fields/_build_tag_editor_section and friends, see
pyside6_rework.md Phase 5.

Built entirely in Python, no .ui file - same call as Phase 4's Color
Tuning page: the "Edit metadata tags" card's rows are generated from a
shared data table (utils/tag_editor.py's TAG_GUIDE), the same way the
Toga original builds them in a loop, and this page also needs a second,
dynamically-constructed window (the metadata viewer), so there is no
purely-static layout to hand-author as Designer XML anyway.

Reused verbatim: TAG_GUIDE/TARGET_TAGS/TAG_EDITOR_EXTENSIONS/TZ_OFFSETS/
TZ_MODE_OPTIONS/local_tz_offset_string/calculate_dji_datetimes/
apply_batch_timezone_to_file/filter_metadata_rows (utils.tag_editor) and
MetadataHandler.get_tags/set_tags/get_metadata/_parse_timezone
(metadata.exif) - all zero-Toga-dependency engine code.

No settings persistence - checked directly against PERSISTED_TEXT_FIELDS/
PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS in uwmedia/app.py: none
of this page's own fields are in those lists, so the Toga original doesn't
persist this page either - not an oversight.

"Update All (DJI)" and "Apply Timezone to All" loop over every file in the
selected directory - the Toga original does this via asyncio.to_thread
per file so the event loop stays responsive. Qt's QApplication has no
asyncio-style awaitable equivalent for a synchronous per-file exiftool
call; this port runs the same sequential loop directly on the UI thread
but calls QApplication.processEvents() after each file, keeping the
window responsive (status/progress visibly update, Abort-by-quitting
still works) without the added complexity of a QThread worker - a
first-pass simplification, not a functional gap: the loop's own semantics
(sequential, continues past a per-file error, one Confirm dialog up
front) are otherwise ported verbatim.
"""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from metadata.exif import MetadataHandler
from utils.tag_editor import (
    TAG_EDITOR_EXTENSIONS,
    TAG_GUIDE,
    TARGET_TAGS,
    TZ_MODE_OPTIONS,
    TZ_OFFSETS,
    apply_batch_timezone_to_file,
    calculate_dji_datetimes,
    filter_metadata_rows,
    local_tz_offset_string,
)


class MetadataViewerWindow(QtWidgets.QWidget):
    """Ported from _show_metadata_viewer - a separate top-level window
    listing every extracted tag, live-filterable by name or value."""

    def __init__(self, file_name, metadata):
        super().__init__()
        self.setWindowTitle(f"Metadata Viewer - {file_name}")
        self.resize(700, 600)

        self.rows = [
            {"tag": key, "value": str(value)}
            for key, value in sorted(metadata.items(), key=lambda kv: kv[0].lower())
        ]

        layout = QtWidgets.QVBoxLayout(self)

        search_row = QtWidgets.QHBoxLayout()
        search_row.addWidget(QtWidgets.QLabel("Filter:"))
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Type to filter tag names or values...")
        self.search_input.textChanged.connect(self._on_filter)
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Tag", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self._populate(self.rows)

    def _populate(self, rows):
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(row["tag"]))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(row["value"]))

    def _on_filter(self, text):
        self._populate(filter_metadata_rows(self.rows, text))


class TagEditorPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.tag_meta_handler = MetadataHandler()
        self.tag_editor_files = []
        self.tag_editor_current_file = None
        self.tag_editor_current_tags = {}
        self.tag_inputs = {}
        self._metadata_viewer_window = None

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Layout - ported from _build_tag_editor_section.
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)

        left = QtWidgets.QVBoxLayout()
        left_widget = QtWidgets.QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(260)
        self.select_dir_button = QtWidgets.QPushButton("Select Directory")
        left.addWidget(self.select_dir_button)
        self.tag_editor_dir_label = QtWidgets.QLabel("No directory selected")
        self.tag_editor_dir_label.setWordWrap(True)
        left.addWidget(self.tag_editor_dir_label)
        self.tag_editor_file_list = QtWidgets.QListWidget()
        left.addWidget(self.tag_editor_file_list, stretch=1)
        root.addWidget(left_widget)

        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_container = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(right_container)

        selected_group = QtWidgets.QGroupBox("Selected file")
        selected_layout = QtWidgets.QVBoxLayout(selected_group)
        file_header = QtWidgets.QHBoxLayout()
        self.tag_editor_file_name_label = QtWidgets.QLabel("None")
        self.tag_editor_file_name_label.setStyleSheet("font-weight: bold;")
        file_header.addWidget(self.tag_editor_file_name_label)
        file_header.addStretch(1)
        self.view_metadata_button = QtWidgets.QPushButton("View All Metadata")
        self.view_metadata_button.setEnabled(False)
        file_header.addWidget(self.view_metadata_button)
        selected_layout.addLayout(file_header)
        self.tag_editor_dji_label = QtWidgets.QLabel(
            "DJI file detected: values calculated from OriginalFilePath."
        )
        self.tag_editor_dji_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.tag_editor_dji_label.setVisible(False)
        selected_layout.addWidget(self.tag_editor_dji_label)
        right.addWidget(selected_group)

        tags_group = QtWidgets.QGroupBox("Edit metadata tags")
        tags_layout = QtWidgets.QVBoxLayout(tags_group)
        for guide in TAG_GUIDE:
            tag = guide["tag"]
            help_text = f"Intended: {guide['tz']}  |  Example: {guide['example']}  —  {guide['hint']}"
            tag_label = QtWidgets.QLabel(tag)
            tag_label.setStyleSheet("font-weight: bold;")
            tags_layout.addWidget(tag_label)
            tag_input = QtWidgets.QLineEdit()
            self.tag_inputs[tag] = tag_input
            tags_layout.addWidget(tag_input)
            help_label = QtWidgets.QLabel(help_text)
            help_label.setWordWrap(True)
            help_label.setStyleSheet("color: gray; font-size: 10px;")
            tags_layout.addWidget(help_label)
        right.addWidget(tags_group)

        tz_group = QtWidgets.QGroupBox("Batch set directory timezone")
        tz_row = QtWidgets.QHBoxLayout(tz_group)
        tz_row.addWidget(QtWidgets.QLabel("Timezone offset:"))
        local_tz = local_tz_offset_string()
        tz_items = list(TZ_OFFSETS)
        if local_tz not in tz_items:
            tz_items.insert(0, local_tz)
        self.tag_editor_tz_select = QtWidgets.QComboBox()
        self.tag_editor_tz_select.addItems(tz_items)
        self.tag_editor_tz_select.setCurrentText(local_tz)
        tz_row.addWidget(self.tag_editor_tz_select)
        tz_row.addWidget(QtWidgets.QLabel("Mode:"))
        self.tag_editor_tz_mode_select = QtWidgets.QComboBox()
        self.tag_editor_tz_mode_select.addItems(list(TZ_MODE_OPTIONS))
        tz_row.addWidget(self.tag_editor_tz_mode_select)
        self.apply_timezone_button = QtWidgets.QPushButton("Apply Timezone to All")
        tz_row.addWidget(self.apply_timezone_button)
        tz_row.addStretch(1)
        right.addWidget(tz_group)

        button_row = QtWidgets.QHBoxLayout()
        self.revert_button = QtWidgets.QPushButton("Revert Changes")
        button_row.addWidget(self.revert_button)
        self.update_all_button = QtWidgets.QPushButton("Update All (DJI)")
        button_row.addWidget(self.update_all_button)
        self.write_tags_button = QtWidgets.QPushButton("Write to File")
        button_row.addWidget(self.write_tags_button)
        button_row.addStretch(1)
        right.addLayout(button_row)

        self.tag_editor_progress_bar = QtWidgets.QProgressBar()
        self.tag_editor_progress_bar.setRange(0, 0)
        self.tag_editor_progress_bar.setVisible(False)
        right.addWidget(self.tag_editor_progress_bar)

        self.tag_editor_status_label = QtWidgets.QLabel("")
        self.tag_editor_status_label.setWordWrap(True)
        right.addWidget(self.tag_editor_status_label)

        right.addStretch(1)
        right_scroll.setWidget(right_container)
        root.addWidget(right_scroll, stretch=1)

    def _wire_signals(self):
        self.select_dir_button.clicked.connect(self._on_select_dir)
        self.tag_editor_file_list.itemSelectionChanged.connect(self._on_file_select)
        self.view_metadata_button.clicked.connect(self._on_view_all_metadata)
        self.apply_timezone_button.clicked.connect(self._on_batch_update_timezone)
        self.revert_button.clicked.connect(self._on_revert_tag_changes)
        self.update_all_button.clicked.connect(self._on_update_all_tags)
        self.write_tags_button.clicked.connect(self._on_write_tags)

    # ------------------------------------------------------------------
    # Tag Editor - ported from the same-named Toga methods.
    # ------------------------------------------------------------------

    def _set_tag_editor_busy(self, busy, text):
        self.tag_editor_progress_bar.setVisible(busy)
        self.tag_editor_status_label.setText(text)

    def _on_select_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select media directory")
        if not path:
            return
        directory = Path(path)
        self.tag_editor_dir_label.setText(str(directory))

        files = sorted(
            (f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in TAG_EDITOR_EXTENSIONS),
            key=lambda f: f.name.lower(),
        )
        self.tag_editor_files = files
        self.tag_editor_file_list.clear()
        for f in files:
            item = QtWidgets.QListWidgetItem(f.name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(f))
            self.tag_editor_file_list.addItem(item)
        self.tag_editor_current_file = None
        self.view_metadata_button.setEnabled(False)
        if files:
            self.tag_editor_file_list.setCurrentRow(0)

    def _on_file_select(self):
        items = self.tag_editor_file_list.selectedItems()
        if not items:
            self.view_metadata_button.setEnabled(False)
            return
        path = items[0].data(QtCore.Qt.ItemDataRole.UserRole)
        self._display_tag_editor_file(Path(path))

    def _display_tag_editor_file(self, file_path):
        self.tag_editor_current_file = file_path
        self.tag_editor_file_name_label.setText(file_path.name)
        self.view_metadata_button.setEnabled(True)

        tags_to_get = TARGET_TAGS + ["QuickTime:OriginalFilePath"]
        self.tag_editor_current_tags = self.tag_meta_handler.get_tags(file_path, tags_to_get)

        calculated = calculate_dji_datetimes(file_path, self.tag_editor_current_tags)
        if calculated:
            self.tag_editor_dji_label.setVisible(True)
            for tag in TARGET_TAGS:
                self.tag_inputs[tag].setText(calculated[tag])
        else:
            self.tag_editor_dji_label.setVisible(False)
            for tag in TARGET_TAGS:
                self.tag_inputs[tag].setText(self.tag_editor_current_tags.get(tag, ""))

    def _on_revert_tag_changes(self):
        if self.tag_editor_current_file:
            self._display_tag_editor_file(self.tag_editor_current_file)

    def _on_write_tags(self):
        if not self.tag_editor_current_file:
            return
        updates = {}
        for tag, tag_input in self.tag_inputs.items():
            new_val = tag_input.text().strip()
            if new_val != self.tag_editor_current_tags.get(tag, ""):
                updates[tag] = new_val

        if not updates:
            QtWidgets.QMessageBox.information(self, "No Changes", "No changes detected to update.")
            return

        try:
            self.tag_meta_handler.set_tags(self.tag_editor_current_file, updates)
            self._display_tag_editor_file(self.tag_editor_current_file)
            QtWidgets.QMessageBox.information(
                self, "Success", f"Updated {len(updates)} tags successfully."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to update tags: {e}")

    def _update_all_worker(self, file_path):
        tags_to_get = TARGET_TAGS + ["QuickTime:OriginalFilePath"]
        current_tags = self.tag_meta_handler.get_tags(file_path, tags_to_get)
        calculated = calculate_dji_datetimes(file_path, current_tags)
        if not calculated:
            return False
        updates = {
            tag: calculated[tag] for tag in TARGET_TAGS if calculated[tag] != current_tags.get(tag, "")
        }
        if updates:
            self.tag_meta_handler.set_tags(file_path, updates)
            return True
        return False

    def _on_update_all_tags(self):
        files = self.tag_editor_files
        if not files:
            QtWidgets.QMessageBox.information(self, "No Files", "No files in the list to update.")
            return

        proceed = QtWidgets.QMessageBox.question(
            self,
            "Confirm Update All",
            f"Scan all {len(files)} files and automatically update DJI videos with corrected datetimes?",
        )
        if proceed != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        self._set_tag_editor_busy(True, f"Processing 0/{len(files)}...")
        updated_count = 0
        error_count = 0
        for i, file_path in enumerate(files):
            self.tag_editor_status_label.setText(f"Processing {i + 1}/{len(files)}: {file_path.name}")
            QtWidgets.QApplication.processEvents()
            try:
                if self._update_all_worker(file_path):
                    updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating {file_path.name}: {e}")
        self._set_tag_editor_busy(False, "")

        if self.tag_editor_current_file:
            self._display_tag_editor_file(self.tag_editor_current_file)

        if error_count:
            QtWidgets.QMessageBox.critical(
                self,
                "Finished with Errors",
                f"Successfully updated {updated_count} files.\nFailed to update {error_count} files.",
            )
        else:
            QtWidgets.QMessageBox.information(
                self, "Success", f"Successfully updated {updated_count} files."
            )

    def _on_batch_update_timezone(self):
        files = self.tag_editor_files
        if not files:
            QtWidgets.QMessageBox.information(self, "No Files", "No files in the list to update.")
            return

        tz_str = self.tag_editor_tz_select.currentText()
        tz = self.tag_meta_handler._parse_timezone(tz_str)
        if not tz:
            QtWidgets.QMessageBox.critical(self, "Invalid Timezone", f"Invalid timezone format: '{tz_str}'.")
            return

        td = tz.utcoffset(None)
        offset_mins = int(td.total_seconds() / 60)
        sign = "+" if offset_mins >= 0 else "-"
        hours = abs(offset_mins) // 60
        mins = abs(offset_mins) % 60
        tz_iso = f"{sign}{hours:02}:{mins:02}"

        mode = self.tag_editor_tz_mode_select.currentText()

        proceed = QtWidgets.QMessageBox.question(
            self,
            "Confirm Batch Timezone Update",
            f"Update all {len(files)} files in the directory to timezone {tz_iso}?\n\nMode: {mode}",
        )
        if proceed != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        self._set_tag_editor_busy(True, f"Updating 0/{len(files)}...")
        updated_count = 0
        error_count = 0
        for i, file_path in enumerate(files):
            self.tag_editor_status_label.setText(f"Updating {i + 1}/{len(files)}: {file_path.name}")
            QtWidgets.QApplication.processEvents()
            try:
                if apply_batch_timezone_to_file(self.tag_meta_handler, file_path, mode, tz, tz_iso):
                    updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating timezone for {file_path.name}: {e}")
        self._set_tag_editor_busy(False, "")

        if self.tag_editor_current_file:
            self._display_tag_editor_file(self.tag_editor_current_file)

        if error_count:
            QtWidgets.QMessageBox.critical(
                self,
                "Finished with Errors",
                f"Successfully updated timezone for {updated_count} files.\n"
                f"Failed to update {error_count} files.",
            )
        else:
            QtWidgets.QMessageBox.information(
                self, "Success", f"Successfully updated timezone for {updated_count} files."
            )

    def _on_view_all_metadata(self):
        if not self.tag_editor_current_file:
            return
        try:
            metadata = self.tag_meta_handler.get_metadata(self.tag_editor_current_file)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load metadata: {e}")
            return
        if not metadata:
            QtWidgets.QMessageBox.information(
                self, "No Metadata", "No metadata could be extracted from this file."
            )
            return
        self._metadata_viewer_window = MetadataViewerWindow(self.tag_editor_current_file.name, metadata)
        self._metadata_viewer_window.show()
