import sys
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLineEdit, QLabel,
    QFormLayout, QFileDialog, QMessageBox, QGroupBox, QFrame,
    QProgressDialog, QComboBox, QDialog, QTableWidget, QTableWidgetItem,
    QHeaderView
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QColor, QPalette, QIcon

from metadata.exif import MetadataHandler
from utils.dependency_check import check_dependencies
from utils.tag_editor import (
    TAG_GUIDE,
    TARGET_TAGS,
    calculate_dji_datetimes as _calculate_dji_datetimes,
    parse_date_from_filename as _parse_date_from_filename,
)

class TagEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UWMedia - Metadata Tag Editor")
        self.setMinimumSize(950, 750)
        
        self.meta_handler = MetadataHandler()
        self.current_file: Optional[Path] = None
        self.current_tags: Dict[str, str] = {}
        
        self.setup_ui()
        self.apply_dark_theme()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # Left Column: File List
        self.left_panel = QWidget()
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_panel.setFixedWidth(250)
        
        self.btn_select_dir = QPushButton("Select Directory")
        self.btn_select_dir.setFixedHeight(40)
        self.btn_select_dir.clicked.connect(self.select_directory)
        self.left_layout.addWidget(self.btn_select_dir)
        
        self.dir_label = QLabel("No directory selected")
        self.dir_label.setWordWrap(True)
        self.dir_label.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        self.left_layout.addWidget(self.dir_label)
        
        self.file_list = QListWidget()
        self.file_list.currentRowChanged.connect(self.on_file_selected)
        self.left_layout.addWidget(self.file_list)
        
        self.main_layout.addWidget(self.left_panel)

        # Right Column: Editor
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        # 1. File Info Group
        info_group = QGroupBox("Selected File")
        info_layout = QVBoxLayout(info_group)
        
        file_header_layout = QHBoxLayout()
        self.file_name_label = QLabel("None")
        self.file_name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        file_header_layout.addWidget(self.file_name_label)
        
        file_header_layout.addStretch()
        
        self.btn_view_metadata = QPushButton("View All Metadata")
        self.btn_view_metadata.setFixedHeight(30)
        self.btn_view_metadata.setStyleSheet("background-color: #37474F; color: white;")
        self.btn_view_metadata.clicked.connect(self.view_all_metadata)
        self.btn_view_metadata.setEnabled(False)
        file_header_layout.addWidget(self.btn_view_metadata)
        
        info_layout.addLayout(file_header_layout)
        
        self.dji_label = QLabel("DJI sets datetaken correct. Values calculated using OriginalFilePath.")
        self.dji_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 13px; margin-top: 5px;")
        self.dji_label.setVisible(False)
        info_layout.addWidget(self.dji_label)
        
        self.right_layout.addWidget(info_group)

        # 2. Tags Group
        tags_group = QGroupBox("Edit Metadata Tags")
        self.form_layout = QFormLayout(tags_group)
        self.form_layout.setSpacing(10)
        self.form_layout.setContentsMargins(20, 20, 20, 20)
        
        self.tag_inputs: Dict[str, QLineEdit] = {}
        
        for guide in TAG_GUIDE:
            tag = guide["tag"]
            
            # Row container to hold input and tiny directions
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)
            
            edit = QLineEdit()
            edit.setFixedHeight(35)
            self.tag_inputs[tag] = edit
            row_layout.addWidget(edit)
            
            # Tiny directions label
            help_text = f"Intended: {guide['tz']}  |  Example: {guide['example']}\n{guide['hint']}"
            help_label = QLabel(help_text)
            help_label.setStyleSheet("color: #888888; font-size: 10px; font-style: italic; margin-bottom: 10px;")
            row_layout.addWidget(help_label)
            
            label = QLabel(tag)
            label.setStyleSheet("color: #CCCCCC; font-size: 13px; font-weight: bold;")
            self.form_layout.addRow(label, row_widget)
            
        self.right_layout.addWidget(tags_group)
        
        # 3. Batch Timezone Group
        tz_group = QGroupBox("Batch Set Directory Timezone")
        tz_layout = QHBoxLayout(tz_group)
        tz_layout.setContentsMargins(15, 15, 15, 15)
        tz_layout.setSpacing(10)
        
        tz_layout.addWidget(QLabel("Timezone Offset:"))
        self.tz_combo = QComboBox()
        self.tz_combo.setEditable(True)
        
        # Try to detect local system timezone offset
        local_tz_str = "+00:00"
        try:
            from datetime import datetime
            now_tz = datetime.now().astimezone().tzinfo
            if now_tz:
                td = now_tz.utcoffset(None)
                if td is not None:
                    offset_mins = int(td.total_seconds() / 60)
                    sign = "+" if offset_mins >= 0 else "-"
                    hours = abs(offset_mins) // 60
                    mins = abs(offset_mins) % 60
                    local_tz_str = f"{sign}{hours:02}:{mins:02}"
        except Exception:
            pass

        offsets = [
            "+14:00", "+13:00", "+12:45", "+12:00", "+11:00", "+10:30", "+10:00",
            "+09:30", "+09:00", "+08:00", "+07:00", "+06:30", "+06:00", "+05:45",
            "+05:30", "+05:00", "+04:30", "+04:00", "+03:30", "+03:00", "+02:00",
            "+01:00", "+00:00", "-01:00", "-02:00", "-03:00", "-03:30", "-04:00",
            "-05:00", "-06:00", "-07:00", "-08:00", "-09:00", "-09:30", "-10:00",
            "-11:00", "-12:00"
        ]
        if local_tz_str not in offsets:
            offsets.insert(0, local_tz_str)
            
        self.tz_combo.addItems(offsets)
        self.tz_combo.setCurrentText(local_tz_str)
        self.tz_combo.setFixedWidth(100)
        tz_layout.addWidget(self.tz_combo)

        tz_layout.addWidget(QLabel("Mode:"))
        self.tz_mode_combo = QComboBox()
        self.tz_mode_combo.addItems([
            "Keep local time, set offset",
            "Recalculate local time from UTC"
        ])
        self.tz_mode_combo.setFixedWidth(240)
        tz_layout.addWidget(self.tz_mode_combo)
        
        self.btn_batch_tz = QPushButton("Apply Timezone to All")
        self.btn_batch_tz.setFixedHeight(35)
        self.btn_batch_tz.setStyleSheet("background-color: #6A1B9A; color: white; font-weight: bold;")
        self.btn_batch_tz.clicked.connect(self.batch_update_timezone)
        tz_layout.addWidget(self.btn_batch_tz)
        
        self.right_layout.addWidget(tz_group)
        
        # 4. Buttons
        self.button_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Revert Changes")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.clicked.connect(self.revert_changes)
        
        self.btn_update_all = QPushButton("Update All")
        self.btn_update_all.setFixedHeight(40)
        self.btn_update_all.setStyleSheet("background-color: #1565C0; color: white; font-weight: bold;")
        self.btn_update_all.clicked.connect(self.update_all)
        
        self.btn_update = QPushButton("Write to File")
        self.btn_update.setFixedHeight(40)
        self.btn_update.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
        self.btn_update.clicked.connect(self.update_tags)
        
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.btn_cancel)
        self.button_layout.addWidget(self.btn_update_all)
        self.button_layout.addWidget(self.btn_update)
        self.right_layout.addLayout(self.button_layout)
        
        self.right_layout.addStretch()
        self.main_layout.addWidget(self.right_panel, stretch=2)

    def apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(45, 45, 45))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(30, 30, 30))
        palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(palette)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #2D2D2D; }
            QGroupBox { color: #FFFFFF; font-weight: bold; border: 1px solid #555555; margin-top: 10px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }
            QLineEdit { background-color: #1E1E1E; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; padding: 5px; font-size: 14px; }
            QLineEdit:focus { border: 1px solid #2A82DA; }
            QPushButton { background-color: #444444; border: 1px solid #555555; border-radius: 4px; padding: 5px 15px; }
            QPushButton:hover { background-color: #555555; }
            QPushButton:pressed { background-color: #333333; }
            QListWidget { background-color: #1E1E1E; border: 1px solid #555555; border-radius: 4px; color: #FFFFFF; }
            QListWidget::item:selected { background-color: #2A82DA; }
            QComboBox { background-color: #1E1E1E; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; padding: 5px; font-size: 14px; }
            QComboBox:focus { border: 1px solid #2A82DA; }
            QComboBox QAbstractItemView { background-color: #1E1E1E; color: #FFFFFF; selection-background-color: #2A82DA; }
        """)

    def select_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Media Directory")
        if dir_path:
            self.dir_label.setText(dir_path)
            self.load_files(dir_path)

    def load_files(self, dir_path):
        self.file_list.clear()
        path = Path(dir_path)
        extensions = {'.mp4', '.mov', '.m4v', '.jpg', '.jpeg', '.png', '.fit'}
        
        files = []
        for f in path.iterdir():
            if f.is_file() and f.suffix.lower() in extensions:
                files.append(f)
        
        # Sort files by name
        files.sort(key=lambda x: x.name.lower())
        
        for f in files:
            item = QListWidgetItem(f.name)
            item.setData(Qt.UserRole, str(f))
            self.file_list.addItem(item)
            
        if files:
            self.file_list.setCurrentRow(0)

    def on_file_selected(self, index):
        if index < 0:
            self.btn_view_metadata.setEnabled(False)
            return
            
        item = self.file_list.item(index)
        file_path = Path(item.data(Qt.UserRole))
        self.current_file = file_path
        self.file_name_label.setText(file_path.name)
        self.btn_view_metadata.setEnabled(True)
        
        # Load Tags (include OriginalFilePath to detect DJI and extract local time)
        tags_to_get = TARGET_TAGS + ["QuickTime:OriginalFilePath"]
        self.current_tags = self.meta_handler.get_tags(file_path, tags_to_get)
        
        calculated_tags = self.calculate_dji_datetimes(file_path, self.current_tags)
        if calculated_tags:
            self.dji_label.setText("DJI sets datetaken correct. Values calculated using OriginalFilePath.")
            self.dji_label.setVisible(True)
            for tag in TARGET_TAGS:
                self.tag_inputs[tag].setText(calculated_tags[tag])
        else:
            self.dji_label.setVisible(False)
            for tag in TARGET_TAGS:
                self.tag_inputs[tag].setText(self.current_tags.get(tag, ""))

    def calculate_dji_datetimes(self, file_path: Path, current_tags: Dict[str, str]) -> Optional[Dict[str, str]]:
        return _calculate_dji_datetimes(file_path, current_tags)

    def revert_changes(self):
        if not self.current_file:
            return
        self.on_file_selected(self.file_list.currentRow())

    def update_tags(self):
        if not self.current_file:
            return
            
        updates = {}
        for tag, edit in self.tag_inputs.items():
            new_val = edit.text().strip()
            if new_val != self.current_tags.get(tag, ""):
                updates[tag] = new_val
                
        if not updates:
            QMessageBox.information(self, "No Changes", "No changes detected to update.")
            return
            
        try:
            self.meta_handler.set_tags(self.current_file, updates)
            # Confirm by reloading
            self.on_file_selected(self.file_list.currentRow())
            QMessageBox.information(self, "Success", f"Updated {len(updates)} tags successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update tags: {e}")

    def update_all(self):
        count = self.file_list.count()
        if count == 0:
            QMessageBox.information(self, "No Files", "No files in the list to update.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Update All",
            f"Are you sure you want to scan all {count} files and automatically update DJI videos with corrected datetimes?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        progress = QProgressDialog("Updating files...", "Cancel", 0, count, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        updated_count = 0
        error_count = 0

        for i in range(count):
            if progress.wasCanceled():
                break

            item = self.file_list.item(i)
            file_path = Path(item.data(Qt.UserRole))

            progress.setLabelText(f"Processing {file_path.name}...")
            progress.setValue(i)
            QApplication.processEvents()

            try:
                tags_to_get = TARGET_TAGS + ["QuickTime:OriginalFilePath"]
                current_tags = self.meta_handler.get_tags(file_path, tags_to_get)

                calculated_tags = self.calculate_dji_datetimes(file_path, current_tags)
                if calculated_tags:
                    updates = {}
                    for tag in TARGET_TAGS:
                        new_val = calculated_tags[tag]
                        curr_val = current_tags.get(tag, "")
                        if new_val != curr_val:
                            updates[tag] = new_val

                    if updates:
                        self.meta_handler.set_tags(file_path, updates)
                        updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating {file_path.name}: {e}")

        progress.setValue(count)

        if self.current_file:
            self.on_file_selected(self.file_list.currentRow())

        if error_count > 0:
            QMessageBox.warning(
                self,
                "Finished with Errors",
                f"Successfully updated {updated_count} files.\nFailed to update {error_count} files."
            )
        else:
            QMessageBox.information(
                self,
                "Success",
                f"Successfully updated {updated_count} files."
            )

    def parse_date_from_filename(self, file_path: Path) -> Optional[datetime]:
        return _parse_date_from_filename(file_path)

    def batch_update_timezone(self):
        count = self.file_list.count()
        if count == 0:
            QMessageBox.information(self, "No Files", "No files in the list to update.")
            return

        tz_str = self.tz_combo.currentText().strip()
        if tz_str.upper() in ("Z", "UTC", "GMT"):
            tz_str = "+00:00"
            
        tz = self.meta_handler._parse_timezone(tz_str)
        if not tz:
            # Try to parse as basic hours integer (e.g. +8, -5)
            match = re.match(r"^([+-])?(\d{1,2})$", tz_str)
            if match:
                sign, hh = match.groups()
                sign = sign or "+"
                tz_str = f"{sign}{int(hh):02d}:00"
                tz = self.meta_handler._parse_timezone(tz_str)
                
        if not tz:
            QMessageBox.critical(self, "Invalid Timezone", f"Invalid timezone format: '{self.tz_combo.currentText()}'. Use format like +08:00 or -05:00.")
            return

        # Format offset string cleanly as [+-]HH:MM
        td = tz.utcoffset(None)
        offset_mins = int(td.total_seconds() / 60)
        sign = "+" if offset_mins >= 0 else "-"
        hours = abs(offset_mins) // 60
        mins = abs(offset_mins) % 60
        tz_iso = f"{sign}{hours:02}:{mins:02}"

        mode = self.tz_mode_combo.currentText()

        reply = QMessageBox.question(
            self,
            "Confirm Batch Timezone Update",
            f"Are you sure you want to update all {count} files in the directory to timezone {tz_iso}?\n\nMode: {mode}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        progress = QProgressDialog("Updating file timezones...", "Cancel", 0, count, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        updated_count = 0
        error_count = 0

        for i in range(count):
            if progress.wasCanceled():
                break

            item = self.file_list.item(i)
            file_path = Path(item.data(Qt.UserRole))

            progress.setLabelText(f"Updating {file_path.name}...")
            progress.setValue(i)
            QApplication.processEvents()

            try:
                updates = {}
                local_dt = None

                if mode == "Keep local time, set offset":
                    try:
                        local_dt = self.meta_handler.get_local_creation_date(file_path)
                    except Exception:
                        pass
                    
                    if not local_dt:
                        local_dt = self.parse_date_from_filename(file_path)
                    
                    if not local_dt:
                        try:
                            mtime = file_path.stat().st_mtime
                            local_dt = datetime.fromtimestamp(mtime)
                        except Exception:
                            pass

                elif mode == "Recalculate local time from UTC":
                    utc_dt = None
                    try:
                        utc_dt = self.meta_handler.get_standardized_creation_date(file_path)
                    except Exception:
                        # Fallback to reading QuickTime:CreateDate or CreateDate
                        tags_got = self.meta_handler.get_tags(file_path, ["QuickTime:CreateDate", "CreateDate"])
                        create_str = tags_got.get("QuickTime:CreateDate") or tags_got.get("CreateDate")
                        if create_str:
                            try:
                                utc_dt = datetime.strptime(str(create_str)[:19], "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            except Exception:
                                pass
                                
                    if utc_dt:
                        local_dt = utc_dt.astimezone(tz).replace(tzinfo=None)
                    else:
                        # Fallback to local time detection
                        try:
                            local_dt = self.meta_handler.get_local_creation_date(file_path)
                        except Exception:
                            pass
                        
                        if not local_dt:
                            local_dt = self.parse_date_from_filename(file_path)
                            
                        if not local_dt:
                            try:
                                mtime = file_path.stat().st_mtime
                                local_dt = datetime.fromtimestamp(mtime)
                            except Exception:
                                pass

                if local_dt:
                    local_str = local_dt.strftime("%Y:%m:%d %H:%M:%S")
                    suffix = file_path.suffix.lower()
                    if suffix in ('.mp4', '.mov', '.m4v'):
                        updates["QuickTime:CreationDate"] = local_str + tz_iso
                        updates["QuickTime:Timezone"] = tz_iso
                        updates["QuickTime:TimeZone"] = tz_iso
                        updates["EXIF:DateTimeOriginal"] = local_str
                        updates["EXIF:CreateDate"] = local_str
                    else:
                        updates["EXIF:DateTimeOriginal"] = local_str
                        updates["EXIF:CreateDate"] = local_str
                        updates["EXIF:OffsetTime"] = tz_iso
                        updates["EXIF:OffsetTimeOriginal"] = tz_iso
                        updates["EXIF:OffsetTimeDigitized"] = tz_iso

                if updates:
                    self.meta_handler.set_tags(file_path, updates)
                    updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating timezone for {file_path.name}: {e}")

        progress.setValue(count)

        if self.current_file:
            self.on_file_selected(self.file_list.currentRow())

        if error_count > 0:
            QMessageBox.warning(
                self,
                "Finished with Errors",
                f"Successfully updated timezone for {updated_count} files.\nFailed to update {error_count} files."
            )
        else:
            QMessageBox.information(
                self,
                "Success",
                f"Successfully updated timezone for {updated_count} files."
            )

    def view_all_metadata(self):
        if not self.current_file:
            return
            
        progress = QProgressDialog("Reading all metadata...", None, 0, 1, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)
        QApplication.processEvents()
        
        try:
            metadata = self.meta_handler.get_metadata(self.current_file)
            progress.setValue(1)
            if not metadata:
                QMessageBox.warning(self, "No Metadata", "No metadata could be extracted from this file.")
                return
                
            dialog = MetadataViewerDialog(self.current_file.name, metadata, self)
            dialog.exec()
        except Exception as e:
            progress.setValue(1)
            QMessageBox.critical(self, "Error", f"Failed to load metadata: {e}")

class MetadataViewerDialog(QDialog):
    def __init__(self, file_name: str, metadata: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Metadata Viewer - {file_name}")
        self.setMinimumSize(700, 600)
        self.metadata = metadata
        
        self.setup_ui()
        self.apply_theme()
        self.populate_table()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Search layout
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Filter Tags:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type to filter tag names or values...")
        self.search_input.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Tag", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        
        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setFixedHeight(35)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

    def apply_theme(self):
        self.setStyleSheet("""
            QDialog { background-color: #2D2D2D; }
            QLabel { color: #FFFFFF; font-size: 13px; }
            QLineEdit { background-color: #1E1E1E; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; padding: 5px; font-size: 14px; }
            QLineEdit:focus { border: 1px solid #2A82DA; }
            QPushButton { background-color: #444444; border: 1px solid #555555; border-radius: 4px; padding: 5px 15px; color: #FFFFFF; }
            QPushButton:hover { background-color: #555555; }
            QTableWidget { background-color: #1E1E1E; gridline-color: #444444; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; alternate-background-color: #262626; }
            QTableWidget::item:selected { background-color: #2A82DA; color: #FFFFFF; }
            QHeaderView::section { background-color: #333333; color: #FFFFFF; padding: 5px; border: 1px solid #444444; font-weight: bold; }
        """)

    def populate_table(self):
        self.table.setRowCount(0)
        self.rows_data = []
        
        sorted_keys = sorted(self.metadata.keys(), key=lambda x: x.lower())
        
        self.table.setRowCount(len(sorted_keys))
        for row_idx, key in enumerate(sorted_keys):
            val = self.metadata[key]
            val_str = str(val)
            
            key_item = QTableWidgetItem(key)
            val_item = QTableWidgetItem(val_str)
            
            self.table.setItem(row_idx, 0, key_item)
            self.table.setItem(row_idx, 1, val_item)
            
            self.rows_data.append((key, val_str, row_idx))
            
        self.table.resizeColumnToContents(0)
        if self.table.columnWidth(0) > 300:
            self.table.setColumnWidth(0, 300)

    def filter_table(self, text):
        text = text.lower()
        for key, val_str, row_idx in self.rows_data:
            match = text in key.lower() or text in val_str.lower()
            self.table.setRowHidden(row_idx, not match)

def main():
    check_dependencies(is_gui=True)
    app = QApplication.instance() or QApplication(sys.argv)
    window = TagEditorApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
