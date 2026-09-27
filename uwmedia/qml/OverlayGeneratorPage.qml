// Real Overlay Generator page - qml_development.md Phase 2. Backed by
// uwmedia/backends/overlay_generator_backend.py's
// OverlayGeneratorBackend, exposed as "overlayGeneratorBackend" (app.py).
// Layout mirrors uwmedia/pages/overlay_generator_page.py (kept
// as reference only). Compacted 2026-09-20 (per the user, live): browse
// buttons sit beside their fields, no "Source & output" header, tighter
// spacing and a shorter overlay list so the page fits 720 px unscrolled.
// Redesigned 2026-09-27: the separate "Log file" field and "Render from log
// file" button are gone. A "Log directory / Log file" switch above the Dive
// logs field decides what that one field holds (folder of logs matched to
// each video, or one log file rendered whole with no video) and the single
// Start button runs whichever mode is on.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ScrollView {
    id: root
    width: 1060
    height: 800
    clip: true
    contentWidth: availableWidth

    // Fixed field width (2026-09-27, per the user): wide enough for a full
    // path like "/Users/<me>/DivingMedia/20260829_Phuket/photos_converted/
    // 20260829_125818_534" (620 px at 15 px) plus the field's 16 px padding
    // each side, instead of stretching with the window. Every text field and
    // the Output filename combo take this; the panes follow the column it
    // sets, and with the 220 px nav rail the page is 1060 px wide, so the
    // Progress column gets what is left (see its preferredWidth).
    readonly property int fieldWidth: 652

    RowLayout {
        width: root.availableWidth
        spacing: 20

        ColumnLayout {
            // Sized by its content (the fixed-width fields), not the window.
            Layout.fillWidth: false
            Layout.alignment: Qt.AlignTop
            spacing: 10

            Label { text: "Overlay Generator"; font.pixelSize: 22; font.bold: true }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                padding: 10
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 6

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            // Source is only used in Log directory mode;
                            // in Log file mode the whole dive is rendered
                            // from the log alone, so it's dimmed, not hidden
                            // (keeps the card's height steady).
                            Label { text: "Source"; color: overlayGeneratorBackend.logFileMode ? "#9AA0A6" : Material.foreground }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                enabled: !overlayGeneratorBackend.logFileMode
                                TextField {
                                    id: sourceField
                                    Layout.preferredWidth: root.fieldWidth
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    text: activeFocus ? overlayGeneratorBackend.sourceText : overlayGeneratorBackend.contractPath(overlayGeneratorBackend.sourceText)
                                    onTextEdited: overlayGeneratorBackend.sourceText = text
                                    onTextChanged: if (!activeFocus) cursorPosition = text.length
                                    ToolTip.text: overlayGeneratorBackend.sourceText
                                    ToolTip.visible: hovered && !activeFocus && overlayGeneratorBackend.sourceText.length > 0
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📄"
                                    onClicked: overlayGeneratorBackend.browseSourceFile()
                                    ToolTip.text: "Choose file"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📁"
                                    onClicked: overlayGeneratorBackend.browseSourceFolder()
                                    ToolTip.text: "Choose folder"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label { text: "Output" }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                TextField {
                                    id: outputField
                                    Layout.preferredWidth: root.fieldWidth
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    text: activeFocus ? overlayGeneratorBackend.outputText : overlayGeneratorBackend.contractPath(overlayGeneratorBackend.outputText)
                                    onTextEdited: overlayGeneratorBackend.outputText = text
                                    onTextChanged: if (!activeFocus) cursorPosition = text.length
                                    ToolTip.text: overlayGeneratorBackend.outputText
                                    ToolTip.visible: hovered && !activeFocus && overlayGeneratorBackend.outputText.length > 0
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📄"
                                    onClicked: overlayGeneratorBackend.browseOutputFile()
                                    ToolTip.text: "Choose file"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📁"
                                    onClicked: overlayGeneratorBackend.browseOutputFolder()
                                    ToolTip.text: "Choose folder"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Label { text: "Dive logs" }
                                // Off: a FOLDER of logs, each video/photo in
                                // Source matched to its dive. On: one log
                                // FILE, rendered whole with no video (for a
                                // dive from the Dive Profile Builder).
                                Label {
                                    text: "Log directory"
                                    color: overlayGeneratorBackend.logFileMode ? "#9AA0A6" : Material.foreground
                                }
                                Switch {
                                    id: logModeSwitch
                                    checked: overlayGeneratorBackend.logFileMode
                                    onToggled: overlayGeneratorBackend.logFileMode = checked
                                    enabled: !overlayGeneratorBackend.isRunning
                                    ToolTip.text: "Log directory: render the videos and photos in Source, each matched to its dive in this folder.\nLog file: render the whole dive in one log file with no video, e.g. one saved by the Dive Profile Builder."
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                                Label {
                                    text: "Log file (render without video)"
                                    color: overlayGeneratorBackend.logFileMode ? Material.foreground : "#9AA0A6"
                                }
                                Item { Layout.fillWidth: true }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                TextField {
                                    id: logsField
                                    objectName: "logsField"
                                    Layout.preferredWidth: root.fieldWidth
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    // One field, two backing values: the
                                    // switch picks which one it shows/edits,
                                    // so flipping back restores the other.
                                    readonly property string backendText: overlayGeneratorBackend.logFileMode ? overlayGeneratorBackend.logFileText : overlayGeneratorBackend.logsText
                                    text: activeFocus ? backendText : overlayGeneratorBackend.contractPath(backendText)
                                    onTextEdited: {
                                        if (overlayGeneratorBackend.logFileMode)
                                            overlayGeneratorBackend.logFileText = text
                                        else
                                            overlayGeneratorBackend.logsText = text
                                    }
                                    onTextChanged: if (!activeFocus) cursorPosition = text.length
                                    // No placeholder: Material floats it above
                                    // a filled field, which collided with the
                                    // switch row; the switch labels and the
                                    // tooltip say what goes here.
                                    ToolTip.text: backendText
                                    ToolTip.visible: hovered && !activeFocus && backendText.length > 0
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: overlayGeneratorBackend.logFileMode ? "📄" : "📁"
                                    onClicked: overlayGeneratorBackend.logFileMode ? overlayGeneratorBackend.browseLogFile() : overlayGeneratorBackend.browseLogsFolder()
                                    ToolTip.text: overlayGeneratorBackend.logFileMode ? "Choose log file" : "Choose folder"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            // Only the video batch names files by this
                            // pattern; --render-log names them
                            // <log name>_<overlay>.mp4 and never overwrites.
                            Label { text: "Output filename"; color: overlayGeneratorBackend.logFileMode ? "#9AA0A6" : Material.foreground }
                            ComboBox {
                                Layout.preferredWidth: root.fieldWidth
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                enabled: !overlayGeneratorBackend.logFileMode
                                model: overlayGeneratorBackend.filenameFormatList
                                currentIndex: model.indexOf(overlayGeneratorBackend.filenameFormat)
                                onActivated: (index) => overlayGeneratorBackend.filenameFormat = model[index]
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            // 2026-09-27, per the user: the overlay videos
                            // were the template's 1080p size (tiny on 4K
                            // footage). See OVERLAY_SIZE_CHOICES.
                            Label { text: "Overlay size" }
                            ComboBox {
                                Layout.preferredWidth: root.fieldWidth
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: overlayGeneratorBackend.overlaySizeList
                                currentIndex: overlayGeneratorBackend.overlaySizeIndex
                                onActivated: (index) => overlayGeneratorBackend.overlaySize = model[index]
                                ToolTip.text: "1080p: the template's size in a 1920×1080 frame. 4K: twice that, 1:1 on 4K footage. Full frame: the whole 1920×1080 / 3840×2160 frame with the overlay placed as in the template - nothing to position in the editor."
                                ToolTip.visible: hovered
                                ToolTip.delay: 400
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Skip if target exists"; color: overlayGeneratorBackend.logFileMode ? "#9AA0A6" : Material.foreground }
                        Switch {
                            enabled: !overlayGeneratorBackend.logFileMode
                            checked: overlayGeneratorBackend.skipExisting
                            onToggled: overlayGeneratorBackend.skipExisting = checked
                        }
                        Item { Layout.fillWidth: true }
                        // Same row as "Skip if target exists" rather than
                        // its own row - keeps the card's height unchanged,
                        // matching the Color page's own placement. Used to
                        // live only on the Advanced page (see
                        // color_backend.py's hwAccel docstring for why it
                        // moved).
                        Label { text: "Hardware acceleration"; color: "#9AA0A6" }
                        Switch {
                            checked: overlayGeneratorBackend.hwAccel
                            onToggled: overlayGeneratorBackend.hwAccel = checked
                        }
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                padding: 10
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 8

                    Label { text: "Select overlay"; font.bold: true; font.pixelSize: 14 }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 12
                        rowSpacing: 6

                        Label { text: "HUD brand" }
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            model: overlayGeneratorBackend.brandList
                            currentIndex: overlayGeneratorBackend.brandIndex
                            onActivated: (index) => overlayGeneratorBackend.onBrandSelected(model[index])
                        }

                        Label { text: "Dive computer"; visible: overlayGeneratorBackend.computerVisible }
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            visible: overlayGeneratorBackend.computerVisible
                            model: overlayGeneratorBackend.computerList
                            currentIndex: overlayGeneratorBackend.computerIndex
                            onActivated: (index) => overlayGeneratorBackend.onComputerSelected(model[index])
                        }

                        Label { text: "Page"; visible: !overlayGeneratorBackend.isCustom }
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            visible: !overlayGeneratorBackend.isCustom
                            model: overlayGeneratorBackend.pageList
                            currentIndex: overlayGeneratorBackend.pageIndex
                            onActivated: (index) => overlayGeneratorBackend.onPageSelected(model[index])
                        }

                        Label { text: "Tank setup"; visible: overlayGeneratorBackend.variantVisible }
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            visible: overlayGeneratorBackend.variantVisible
                            model: overlayGeneratorBackend.variantList
                            currentIndex: overlayGeneratorBackend.variantIndex
                            onActivated: (index) => overlayGeneratorBackend.onVariantSelected(model[index])
                            ToolTip.text: "Which tank layout of the page to render - no tank, single tank, sidemount or multi-tank"
                            ToolTip.visible: hovered
                            ToolTip.delay: 400
                        }

                        Label { text: "Custom path"; visible: overlayGeneratorBackend.isCustom }
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: overlayGeneratorBackend.isCustom
                            spacing: 2
                            TextField {
                                id: customPathField
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: activeFocus ? overlayGeneratorBackend.customPathText : overlayGeneratorBackend.contractPath(overlayGeneratorBackend.customPathText)
                                onTextEdited: overlayGeneratorBackend.customPathText = text
                                onTextChanged: if (!activeFocus) cursorPosition = text.length
                                ToolTip.text: overlayGeneratorBackend.customPathText
                                ToolTip.visible: hovered && !activeFocus && overlayGeneratorBackend.customPathText.length > 0
                                ToolTip.delay: 400
                            }
                            RowLayout {
                                Layout.alignment: Qt.AlignRight
                                spacing: 4
                                ToolButton {
                                    text: "📄"
                                    onClicked: overlayGeneratorBackend.browseCustomPathFile()
                                    ToolTip.text: "Choose file"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📁"
                                    onClicked: overlayGeneratorBackend.browseCustomPathFolder()
                                    ToolTip.text: "Choose folder"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                            }
                        }
                    }

                    RowLayout {
                        spacing: 8
                        Button {
                            text: "+ Add"
                            highlighted: true
                            onClicked: overlayGeneratorBackend.addOverlay()
                        }
                        Button {
                            text: "Remove Selected"
                            onClicked: overlayGeneratorBackend.removeOverlayAtIndex(overlayListView.currentIndex)
                        }
                        Item { Layout.fillWidth: true }
                    }

                    ListView {
                        id: overlayListView
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        clip: true
                        model: overlayGeneratorBackend.overlayLabels
                        delegate: ItemDelegate {
                            width: ListView.view.width
                            text: modelData
                            highlighted: ListView.isCurrentItem
                            onClicked: ListView.view.currentIndex = index
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        ColumnLayout {
            // Progress/Start sit right beside the fields, not at the far
            // edge of a wide window - and 20 px short of the page's right
            // edge (2026-09-27, per the user).
            Layout.fillWidth: false
            Layout.preferredWidth: 248
            Layout.alignment: Qt.AlignTop
            spacing: 16

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 10

                    Label { text: "Progress"; font.bold: true; font.pixelSize: 14 }

                    // Two bars (2026-09-27, per the user): the overlay run
                    // in flight - its videos - and the whole batch, videos ×
                    // overlays. Indeterminate until the CLI reports the
                    // file count (backend.progressKnown).
                    //
                    // Every caption keeps its one-line height and the bars
                    // only fade (opacity, not visible) while idle, and the
                    // status is a fixed three-line box: the card's height -
                    // and so the Start/Abort button - never moves as the
                    // texts come and go or wrap (per the user).
                    FontMetrics { id: progressMetrics; font.pixelSize: 12 }
                    component Caption: Label {
                        Layout.fillWidth: true
                        Layout.preferredHeight: progressMetrics.height
                        color: "#9AA0A6"
                        font.pixelSize: 12
                        elide: Text.ElideMiddle
                        maximumLineCount: 1
                    }
                    Caption { text: overlayGeneratorBackend.overlayProgressText }
                    ProgressBar {
                        Layout.fillWidth: true
                        from: 0; to: 1
                        value: overlayGeneratorBackend.currentProgress
                        indeterminate: overlayGeneratorBackend.isRunning && !overlayGeneratorBackend.progressKnown
                        opacity: overlayGeneratorBackend.isRunning ? 1 : 0
                    }
                    Caption { text: overlayGeneratorBackend.currentProgressText }
                    Caption { text: overlayGeneratorBackend.isRunning ? "All overlays" : "" }
                    ProgressBar {
                        Layout.fillWidth: true
                        from: 0; to: 1
                        value: overlayGeneratorBackend.totalProgress
                        indeterminate: overlayGeneratorBackend.isRunning && !overlayGeneratorBackend.progressKnown
                        opacity: overlayGeneratorBackend.isRunning ? 1 : 0
                    }
                    Caption { text: overlayGeneratorBackend.totalProgressText }
                    // Elapsed / estimated remaining over the whole batch
                    // (2026-09-28, per the user); stays after the run ends.
                    Caption { text: overlayGeneratorBackend.timingText }
                    Label {
                        Layout.fillWidth: true
                        Layout.preferredHeight: progressMetrics.height * 3
                        text: overlayGeneratorBackend.statusText
                        color: "#9AA0A6"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignTop
                        ToolTip.text: overlayGeneratorBackend.statusText
                        ToolTip.visible: statusHover.hovered && truncated
                        ToolTip.delay: 400
                        HoverHandler { id: statusHover }
                    }
                    Button {
                        // Compact (2026-09-27, per the user): a normal-sized
                        // button at the left of the card, not a bar across it.
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 36
                        Layout.alignment: Qt.AlignLeft
                        text: overlayGeneratorBackend.isRunning ? "■  Abort" : "▶  Start"
                        highlighted: true
                        // Only one of Color/Overlay Generator/Convertion can
                        // run at a time (they'd otherwise all compete for
                        // ffmpeg/CPU) - see ColorPage.qml's own Start button.
                        enabled: overlayGeneratorBackend.isRunning || !(colorBackend.isRunning || convertionBackend.isRunning)
                        ToolTip.text: !enabled
                            ? "Another operation (Color or Convertion) is already running"
                            : (overlayGeneratorBackend.logFileMode
                                ? "Render every selected overlay for the whole dive in the log file, with no video - one video per overlay in the output folder"
                                : "Render every selected overlay for each video and photo in Source, matched to its dive in the logs folder")
                        ToolTip.visible: hovered
                        ToolTip.delay: 400
                        onClicked: overlayGeneratorBackend.onStartClicked()
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        Item { Layout.fillWidth: true }
    }
}
