"""Activity page - PySide6 port of uwmedia/app.py's Activity-related
fields/_build_activity_section and friends, see pyside6_rework.md
Phase 10.

Known, deliberate limitation of this first pass, documented rather than
silently accepted (same posture as Phase 9's Advanced-page write-up): in
the Toga original, this page is a *shared* run/terminal-output viewer -
Color's/Convertion's/Overlay Generator's own Start buttons all funnel
through one shared on_run/_run_one_invocation implementation that writes
into this page's activity_status_label/log_output regardless of which
page's Start was clicked (see uwmedia/app.py's `_set_status`/
`self.log_output.value +=` call sites). This Qt port's Color/Convertion/
Overlay Generator pages (Phases 1-3) were each built with their own
independent, page-local status label + progress bar instead - a
reasonable design on its own (matches the same "independent state per
page" posture used throughout this migration), but it means nothing in
this beta currently calls into this page's own _set_status/_append_log
methods. They're ported here as working, correct mechanics (show/hide
the terminal output correctly, status text settable) so a later phase
can wire them up for real if a shared cross-page activity log turns out
to be worth building - not a new gap, the same kind of "ported the
widget, cross-page wiring deferred" limitation Phase 9 already flagged
for Advanced's own folder-override refresh.

No settings persistence - checked directly against PERSISTED_TEXT_FIELDS/
PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS in uwmedia/app.py:
none of this page's own fields (show_terminal_switch included) are in
those lists, so the Toga original doesn't persist this page either.
"""
from PySide6 import QtWidgets


class ActivityPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Layout - ported from _build_activity_section.
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        run_log_group = QtWidgets.QGroupBox("Run log")
        run_log_layout = QtWidgets.QVBoxLayout(run_log_group)

        self.activity_status_label = QtWidgets.QLabel("Idle")
        self.activity_status_label.setStyleSheet("color: gray;")
        run_log_layout.addWidget(self.activity_status_label)

        self.show_terminal_switch = QtWidgets.QCheckBox("Show terminal output")
        run_log_layout.addWidget(self.show_terminal_switch)

        self.log_label = QtWidgets.QLabel("Terminal output")
        self.log_label.setVisible(False)
        run_log_layout.addWidget(self.log_label)

        self.log_output = QtWidgets.QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(200)
        self.log_output.setVisible(False)
        run_log_layout.addWidget(self.log_output, stretch=1)

        root.addWidget(run_log_group)
        root.addStretch(1)

    def _wire_signals(self):
        self.show_terminal_switch.toggled.connect(self._on_show_terminal_toggle)

    # ------------------------------------------------------------------
    # Terminal visibility / status - ported from on_show_terminal_toggle/
    # _set_terminal_visible/_set_status. _append_log mirrors the Toga
    # original's own `self.log_output.value += text` call sites.
    # ------------------------------------------------------------------

    def _on_show_terminal_toggle(self, checked):
        self._set_terminal_visible(checked)

    def _set_terminal_visible(self, visible):
        self.show_terminal_switch.blockSignals(True)
        self.show_terminal_switch.setChecked(visible)
        self.show_terminal_switch.blockSignals(False)
        self.log_output.setVisible(visible)
        self.log_label.setVisible(visible)
        if visible:
            scrollbar = self.log_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _set_status(self, text):
        self.activity_status_label.setText(text)

    def _append_log(self, text):
        self.log_output.setPlainText(self.log_output.toPlainText() + text)
        if self.show_terminal_switch.isChecked():
            scrollbar = self.log_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
