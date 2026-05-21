import sys
import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLineEdit, QLabel,
    QFormLayout, QFileDialog, QMessageBox, QGroupBox, QFrame
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QColor, QPalette, QIcon

from metadata.exif import MetadataHandler

# Tags to manage with metadata guidance
TAG_GUIDE = [
    {
        "tag": "QuickTime:CreationDate",
        "tz": "Local Time + Offset",
        "example": "2026:05:21 06:58:22+08:00",
        "hint": "Primary date used by Apple Photos for sorting."
    },
    {
        "tag": "QuickTime:CreateDate",
        "tz": "UTC (Universal Time)",
        "example": "2026:05:20 22:58:22",
        "hint": "Technical creation time, usually stored in UTC."
    },
    {
        "tag": "EXIF:DateTimeOriginal",
        "tz": "Local Time (Naive)",
        "example": "2026:05:21 06:58:22",
        "hint": "Original capture time for photos."
    },
    {
        "tag": "EXIF:CreateDate",
        "tz": "Local Time (Naive)",
        "example": "2026:05:21 06:58:22",
        "hint": "Standard digitized creation date for photos."
    }
]

TARGET_TAGS = [g["tag"] for g in TAG_GUIDE]

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
        self.file_name_label = QLabel("None")
        self.file_name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_layout.addWidget(self.file_name_label)
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
        
        # 3. Buttons
        self.button_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Revert Changes")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.clicked.connect(self.revert_changes)
        
        self.btn_update = QPushButton("Write to File")
        self.btn_update.setFixedHeight(40)
        self.btn_update.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
        self.btn_update.clicked.connect(self.update_tags)
        
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.btn_cancel)
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
            return
            
        item = self.file_list.item(index)
        file_path = Path(item.data(Qt.UserRole))
        self.current_file = file_path
        self.file_name_label.setText(file_path.name)
        
        # Load Tags
        self.current_tags = self.meta_handler.get_tags(file_path, TARGET_TAGS)
        for tag, value in self.current_tags.items():
            self.tag_inputs[tag].setText(value)

    def revert_changes(self):
        if not self.current_file:
            return
        # Just reload from current_tags
        for tag, value in self.current_tags.items():
            self.tag_inputs[tag].setText(value)

    def update_tags(self):
        if not self.current_file:
            return
            
        updates = {}
        for tag, edit in self.tag_inputs.items():
            new_val = edit.text().strip()
            if new_val != self.current_tags.get(tag):
                updates[tag] = new_val
                
        if not updates:
            QMessageBox.information(self, "No Changes", "No changes detected to update.")
            return
            
        try:
            self.meta_handler.set_tags(self.current_file, updates)
            # Confirm by reloading
            self.current_tags = self.meta_handler.get_tags(self.current_file, TARGET_TAGS)
            for tag, value in self.current_tags.items():
                self.tag_inputs[tag].setText(value)
            QMessageBox.information(self, "Success", f"Updated {len(updates)} tags successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update tags: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TagEditorApp()
    window.show()
    sys.exit(app.exec())
