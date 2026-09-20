"""Tag Editor page backend - qml_development.md Phase 5. QObject exposed to
uwmedia/qml/TagEditorPage.qml as the "tagEditorBackend" context
property.

Ported close to verbatim from uwmedia/pages/tag_editor_page.py
(the old Widgets page, kept as reference only) - reuses TAG_GUIDE/
TARGET_TAGS/TAG_EDITOR_EXTENSIONS/TZ_OFFSETS/TZ_MODE_OPTIONS/
local_tz_offset_string/calculate_dji_datetimes/apply_batch_timezone_to_file/
filter_metadata_rows (utils.tag_editor) and MetadataHandler.get_tags/
set_tags/get_metadata/_parse_timezone (metadata.exif) unchanged.

No settings persistence - matches the old Widgets page's own docstring
(checked directly against PERSISTED_TEXT_FIELDS/PERSISTED_SELECTION_FIELDS/
PERSISTED_SWITCH_FIELDS in uwmedia/app.py: none of this page's fields are
persisted in the Toga app either).

Update All/Apply Timezone loop synchronously with QApplication.
processEvents() per file, same first-pass simplification the old Widgets
page's own docstring already documents (no QThread worker) - unchanged
here, not revisited.

Deliberate UX simplification, not a functional gap: the *destructive*
confirm-before-batch-mutation dialogs (Confirm Update All/Confirm Batch
Timezone Update) ARE ported as real modal QML Dialogs, gating the same
mutations they always did - only the purely-informational alerts
(Success/No Changes/Error) are surfaced via the existing status label
instead of a second modal, to keep this first pass's dialog-plumbing
surface smaller. The confirm gate itself is never skipped.
"""
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

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


class TagEditorBackend(QObject):
    filesChanged = Signal()
    selectionChanged = Signal()
    tagValuesChanged = Signal()
    tzChanged = Signal()
    statusChanged = Signal()
    confirmRequested = Signal(str, str)
    metadataViewerChanged = Signal()

    def __init__(self):
        super().__init__()

        self.tag_meta_handler = MetadataHandler()
        self.tag_editor_files = []
        self.tag_editor_current_file = None
        self.tag_editor_current_tags = {}
        self._dir_label = "No directory selected"
        self._selected_index = -1
        self._file_name = "None"
        self._dji_visible = False
        self._view_metadata_enabled = False

        self._tag_values = {guide["tag"]: "" for guide in TAG_GUIDE}

        local_tz = local_tz_offset_string()
        self._tz_options = list(TZ_OFFSETS)
        if local_tz not in self._tz_options:
            self._tz_options.insert(0, local_tz)
        self._current_tz = local_tz
        self._current_tz_mode = TZ_MODE_OPTIONS[0]

        self._busy = False
        self._status_text = ""
        self._pending_action = None

        self._metadata_title = ""
        self._metadata_rows_all = []
        self._metadata_filter = ""
        self._metadata_visible = False

    # ------------------------------------------------------------------
    # Static structure
    # ------------------------------------------------------------------

    @Property("QVariant", constant=True)
    def tagGuide(self):
        return [
            {
                "tag": g["tag"],
                "help": f"Intended: {g['tz']}  |  Example: {g['example']}  —  {g['hint']}",
            }
            for g in TAG_GUIDE
        ]

    @Property(list, constant=True)
    def tzOptionList(self):
        return self._tz_options

    @Property(list, constant=True)
    def tzModeList(self):
        return list(TZ_MODE_OPTIONS)

    # ------------------------------------------------------------------
    # Directory/file list - ported close to verbatim from
    # _on_select_dir/_on_file_select/_display_tag_editor_file.
    # ------------------------------------------------------------------

    @Property(str, notify=filesChanged)
    def dirLabel(self):
        return self._dir_label

    @Property(list, notify=filesChanged)
    def fileNames(self):
        return [f.name for f in self.tag_editor_files]

    @Slot()
    def selectDirectory(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(None, "Select media directory")
        if not path:
            return
        directory = Path(path)
        self._dir_label = str(directory)

        self.tag_editor_files = sorted(
            (f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in TAG_EDITOR_EXTENSIONS),
            key=lambda f: f.name.lower(),
        )
        self.tag_editor_current_file = None
        self._view_metadata_enabled = False
        self.filesChanged.emit()
        if self.tag_editor_files:
            self.selectFileAtIndex(0)

    @Slot(int)
    def selectFileAtIndex(self, index):
        if index < 0 or index >= len(self.tag_editor_files):
            self._view_metadata_enabled = False
            self.selectionChanged.emit()
            return
        self._selected_index = index
        self._display_file(self.tag_editor_files[index])

    def _display_file(self, file_path: Path):
        self.tag_editor_current_file = file_path
        self._file_name = file_path.name
        self._view_metadata_enabled = True

        tags_to_get = TARGET_TAGS + ["QuickTime:OriginalFilePath"]
        self.tag_editor_current_tags = self.tag_meta_handler.get_tags(file_path, tags_to_get)

        calculated = calculate_dji_datetimes(file_path, self.tag_editor_current_tags)
        if calculated:
            self._dji_visible = True
            for tag in TARGET_TAGS:
                self._tag_values[tag] = calculated[tag]
        else:
            self._dji_visible = False
            for tag in TARGET_TAGS:
                self._tag_values[tag] = self.tag_editor_current_tags.get(tag, "")

        self.selectionChanged.emit()
        self.tagValuesChanged.emit()

    @Property(str, notify=selectionChanged)
    def selectedFileName(self):
        return self._file_name

    @Property(bool, notify=selectionChanged)
    def djiVisible(self):
        return self._dji_visible

    @Property(bool, notify=selectionChanged)
    def viewMetadataEnabled(self):
        return self._view_metadata_enabled

    @Property("QVariant", notify=tagValuesChanged)
    def tagValues(self):
        return dict(self._tag_values)

    @Slot(str, str)
    def setTagValue(self, tag, value):
        self._tag_values[tag] = value
        self.tagValuesChanged.emit()

    # ------------------------------------------------------------------
    # Timezone selectors
    # ------------------------------------------------------------------

    @Property(str, notify=tzChanged)
    def currentTz(self):
        return self._current_tz

    @currentTz.setter
    def currentTz(self, value):
        if value == self._current_tz:
            return
        self._current_tz = value
        self.tzChanged.emit()

    @Property(str, notify=tzChanged)
    def currentTzMode(self):
        return self._current_tz_mode

    @currentTzMode.setter
    def currentTzMode(self, value):
        if value == self._current_tz_mode:
            return
        self._current_tz_mode = value
        self.tzChanged.emit()

    # ------------------------------------------------------------------
    # Status/busy
    # ------------------------------------------------------------------

    @Property(bool, notify=statusChanged)
    def busy(self):
        return self._busy

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    def _set_busy(self, busy, text):
        self._busy = busy
        self._status_text = text
        self.statusChanged.emit()

    # ------------------------------------------------------------------
    # Revert/Write - ported close to verbatim from
    # _on_revert_tag_changes/_on_write_tags.
    # ------------------------------------------------------------------

    @Slot()
    def revertChanges(self):
        if self.tag_editor_current_file:
            self._display_file(self.tag_editor_current_file)

    @Slot()
    def writeTags(self):
        if not self.tag_editor_current_file:
            return
        updates = {}
        for tag, value in self._tag_values.items():
            value = value.strip()
            if value != self.tag_editor_current_tags.get(tag, ""):
                updates[tag] = value

        if not updates:
            self._set_busy(False, "No changes detected to update.")
            return

        try:
            self.tag_meta_handler.set_tags(self.tag_editor_current_file, updates)
            self._display_file(self.tag_editor_current_file)
            self._set_busy(False, f"Updated {len(updates)} tags successfully.")
        except Exception as e:
            self._set_busy(False, f"Failed to update tags: {e}")

    # ------------------------------------------------------------------
    # Update All (DJI) / Apply Timezone to All - ported close to verbatim
    # from _on_update_all_tags/_on_batch_update_timezone, gated by a real
    # confirm Dialog (see module docstring) instead of QMessageBox.question.
    # ------------------------------------------------------------------

    @Slot()
    def onUpdateAllTagsClicked(self):
        files = self.tag_editor_files
        if not files:
            self._set_busy(False, "No files in the list to update.")
            return
        self._pending_action = "update_all"
        self.confirmRequested.emit(
            "Confirm Update All",
            f"Scan all {len(files)} files and automatically update DJI videos with corrected datetimes?",
        )

    @Slot()
    def onApplyTimezoneClicked(self):
        files = self.tag_editor_files
        if not files:
            self._set_busy(False, "No files in the list to update.")
            return
        tz = self.tag_meta_handler._parse_timezone(self._current_tz)
        if not tz:
            self._set_busy(False, f"Invalid timezone format: '{self._current_tz}'.")
            return
        self._pending_action = "apply_timezone"
        self.confirmRequested.emit(
            "Confirm Batch Timezone Update",
            f"Update all {len(files)} files in the directory to timezone {self._current_tz}?\n\n"
            f"Mode: {self._current_tz_mode}",
        )

    @Slot()
    def confirmPendingAction(self):
        action, self._pending_action = self._pending_action, None
        if action == "update_all":
            self._run_update_all()
        elif action == "apply_timezone":
            self._run_apply_timezone()

    @Slot()
    def cancelPendingAction(self):
        self._pending_action = None

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

    def _run_update_all(self):
        from PySide6.QtWidgets import QApplication

        files = self.tag_editor_files
        self._set_busy(True, f"Processing 0/{len(files)}...")
        updated_count = 0
        error_count = 0
        for i, file_path in enumerate(files):
            self._status_text = f"Processing {i + 1}/{len(files)}: {file_path.name}"
            self.statusChanged.emit()
            QApplication.processEvents()
            try:
                if self._update_all_worker(file_path):
                    updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating {file_path.name}: {e}")

        if self.tag_editor_current_file:
            self._display_file(self.tag_editor_current_file)

        if error_count:
            self._set_busy(False, f"Updated {updated_count} files. Failed: {error_count}.")
        else:
            self._set_busy(False, f"Successfully updated {updated_count} files.")

    def _run_apply_timezone(self):
        from PySide6.QtWidgets import QApplication

        files = self.tag_editor_files
        tz = self.tag_meta_handler._parse_timezone(self._current_tz)
        td = tz.utcoffset(None)
        offset_mins = int(td.total_seconds() / 60)
        sign = "+" if offset_mins >= 0 else "-"
        hours = abs(offset_mins) // 60
        mins = abs(offset_mins) % 60
        tz_iso = f"{sign}{hours:02}:{mins:02}"
        mode = self._current_tz_mode

        self._set_busy(True, f"Updating 0/{len(files)}...")
        updated_count = 0
        error_count = 0
        for i, file_path in enumerate(files):
            self._status_text = f"Updating {i + 1}/{len(files)}: {file_path.name}"
            self.statusChanged.emit()
            QApplication.processEvents()
            try:
                if apply_batch_timezone_to_file(self.tag_meta_handler, file_path, mode, tz, tz_iso):
                    updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating timezone for {file_path.name}: {e}")

        if self.tag_editor_current_file:
            self._display_file(self.tag_editor_current_file)

        if error_count:
            self._set_busy(False, f"Updated timezone for {updated_count} files. Failed: {error_count}.")
        else:
            self._set_busy(False, f"Successfully updated timezone for {updated_count} files.")

    # ------------------------------------------------------------------
    # Metadata viewer - ported close to verbatim from
    # _on_view_all_metadata/MetadataViewerWindow, as backend state a QML
    # Window binds to instead of a second QWidget top-level window.
    # ------------------------------------------------------------------

    @Slot()
    def viewAllMetadata(self):
        if not self.tag_editor_current_file:
            return
        try:
            metadata = self.tag_meta_handler.get_metadata(self.tag_editor_current_file)
        except Exception as e:
            self._set_busy(False, f"Failed to load metadata: {e}")
            return
        if not metadata:
            self._set_busy(False, "No metadata could be extracted from this file.")
            return
        self._metadata_title = f"Metadata Viewer - {self.tag_editor_current_file.name}"
        self._metadata_rows_all = [
            {"tag": key, "value": str(value)} for key, value in sorted(metadata.items(), key=lambda kv: kv[0].lower())
        ]
        self._metadata_filter = ""
        self._metadata_visible = True
        self.metadataViewerChanged.emit()

    @Slot()
    def closeMetadataViewer(self):
        self._metadata_visible = False
        self.metadataViewerChanged.emit()

    @Property(bool, notify=metadataViewerChanged)
    def metadataVisible(self):
        return self._metadata_visible

    @Property(str, notify=metadataViewerChanged)
    def metadataTitle(self):
        return self._metadata_title

    @Property(str, notify=metadataViewerChanged)
    def metadataFilter(self):
        return self._metadata_filter

    @metadataFilter.setter
    def metadataFilter(self, value):
        if value == self._metadata_filter:
            return
        self._metadata_filter = value
        self.metadataViewerChanged.emit()

    @Property("QVariant", notify=metadataViewerChanged)
    def metadataRows(self):
        return filter_metadata_rows(self._metadata_rows_all, self._metadata_filter)
