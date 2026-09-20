// Real Color page - qml_development.md Phase 1 (Pass 1). Backed by
// uwmedia/backends/color_backend.py's ColorBackend, exposed as
// the "colorBackend" context property (see app.py). Layout/field set
// mirrors uwmedia/pages/color_page.ui (kept as reference only).
//
// Every binding below uses the user-interaction-only signal on its
// control (onTextEdited, onToggled, onActivated, onMoved) rather than
// the "changed" signal that also fires for programmatic updates - avoids
// a feedback loop against the backend's own two-way Property/setter
// pattern (same reasoning throughout: QML sets text:/checked:/value:
// from the backend; only a real user action writes back).
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ScrollView {
    id: root
    width: 1060
    height: 720
    clip: true
    contentWidth: availableWidth

    readonly property int previewWidth: 528
    readonly property int previewHeight: Math.round(previewWidth * 9 / 16)

    RowLayout {
        width: root.availableWidth
        spacing: 10

        // --- Left column: live preview + overlays -----------------
        ColumnLayout {
            Layout.alignment: Qt.AlignTop
            spacing: 12

            Label {
                text: "Live preview"
                font.pixelSize: 24
                font.bold: true
            }

            Pane {
                Material.elevation: 1
                ColumnLayout {
                    spacing: 8

                    Rectangle {
                        Layout.preferredWidth: root.previewWidth
                        Layout.preferredHeight: root.previewHeight
                        color: "#000000"

                        Image {
                            id: previewImage
                            anchors.fill: parent
                            source: colorBackend.previewImageSource
                            fillMode: Image.Stretch
                            cache: false
                            asynchronous: false
                        }

                        // Live move/resize feedback, drawn natively instead
                        // of baked into previewImage - baking it in meant
                        // reloading/re-uploading a brand new texture on
                        // every single mouse-move (previewImage is
                        // cache:false, asynchronous:false), which is what
                        // made dragging feel stuck. This is a plain
                        // GPU-composited rectangle instead, repositioned by
                        // cheap arithmetic-only backend properties - the
                        // real HUD only gets re-baked once, on release.
                        Rectangle {
                            visible: colorBackend.dragBoxVisible && !colorBackend.isRunning
                            x: colorBackend.dragBoxX
                            y: colorBackend.dragBoxY
                            width: colorBackend.dragBoxW
                            height: colorBackend.dragBoxH
                            color: "#333B82F6"
                            border.color: "#3B82F6"
                            border.width: 2
                            Label {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.margins: 4
                                text: colorBackend.dragBoxLabel
                                color: "white"
                                font.pixelSize: 12
                                elide: Text.ElideRight
                                width: Math.max(0, parent.width - 8)
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            // root is a ScrollView (Flickable-backed) - without this,
                            // the Flickable steals the mouse grab from this MouseArea
                            // a few pixels into any drag (it's arbitrating "is this a
                            // scroll gesture?"), which is what made move/resize stop
                            // dead after a few pixels no matter how fast rendering was.
                            preventStealing: true
                            // Disabled while a batch is running - the overlay data
                            // was already snapshotted into the run's own temp
                            // --overlays-file at Start, so dragging/resizing now
                            // wouldn't do anything to the run in progress anyway,
                            // and left the translucent drag-box indicator visibly
                            // stuck on screen for the run's whole duration (the
                            // user's own report: "the transparent box shown when I
                            // start a video color process").
                            enabled: !colorBackend.isRunning
                            onPressed: (mouse) => colorBackend.onPreviewPressed(mouse.x, mouse.y)
                            onPositionChanged: (mouse) => {
                                if (pressed)
                                    colorBackend.onPreviewDragged(mouse.x, mouse.y)
                            }
                            onReleased: colorBackend.onPreviewReleased()
                        }
                    }

                    RowLayout {
                        Layout.preferredWidth: root.previewWidth
                        Slider {
                            id: scrubSlider
                            Layout.fillWidth: true
                            from: colorBackend.scrubMinimum
                            to: Math.max(colorBackend.scrubMinimum, colorBackend.scrubMaximum)
                            value: colorBackend.scrubValue
                            enabled: colorBackend.scrubEnabled
                            onMoved: colorBackend.onScrubChanged(Math.round(value))
                        }
                        Label { text: colorBackend.scrubTimeText }
                    }
                }
            }

            Pane {
                Material.elevation: 1
                ColumnLayout {
                    spacing: 10
                    Label { text: "Overlays"; font.bold: true; font.pixelSize: 14 }

                    Rectangle {
                        Layout.preferredWidth: root.previewWidth
                        Layout.preferredHeight: 120
                        color: "#3A3A3A"
                        border.color: "#4A4A4A"
                        radius: 4

                        ListView {
                            id: overlayListView
                            anchors.fill: parent
                            anchors.margins: 4
                            clip: true
                            model: colorBackend.overlayLabels
                            delegate: ItemDelegate {
                                width: ListView.view.width
                                text: modelData
                                highlighted: ListView.isCurrentItem
                                onClicked: ListView.view.currentIndex = index
                            }
                        }
                    }

                    RowLayout {
                        spacing: 8
                        Button {
                            text: "+ Add Overlay…"
                            highlighted: true
                            onClicked: {
                                colorBackend.resetAddHudCascade()
                                addHudPopup.open()
                            }
                        }
                        Button {
                            text: "Remove Selected"
                            onClicked: colorBackend.removeOverlayAtIndex(overlayListView.currentIndex)
                        }
                        Item { Layout.fillWidth: true }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        // --- Right column: color correction / source-output / progress -
        // Kept to a tight vertical budget deliberately (spacing/padding
        // below are all a bit smaller than the defaults) - the whole
        // column has to fit inside the page's fixed 720px height with no
        // scrolling, in both idle and running state (see the Progress
        // card's own note on why running never adds height any more).
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 6

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                padding: 8
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 6

                    Label { text: "Color correction"; font.bold: true; font.pixelSize: 14 }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Label { text: "Apply color correction" }
                        Switch {
                            checked: colorBackend.colorChecked
                            onToggled: colorBackend.colorChecked = checked
                        }
                        Item { Layout.fillWidth: true }
                        // Same row as "Apply color correction" rather than
                        // its own row, per the user's request - keeps the
                        // card's height unchanged. Used to live only on
                        // the Advanced page as one easy-to-miss global
                        // toggle - moved here (and to Overlay Generator/
                        // Convertion) since it's specifically this page's
                        // own Start button that needs to read it.
                        Label { text: "Hardware acceleration"; color: "#9AA0A6" }
                        Switch {
                            checked: colorBackend.hwAccel
                            onToggled: colorBackend.hwAccel = checked
                        }
                    }

                    ComboBox {
                        Layout.preferredWidth: 130
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        model: colorBackend.colorProfileList
                        currentIndex: model.indexOf(colorBackend.colorProfile)
                        onActivated: (index) => colorBackend.colorProfile = model[index]
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                padding: 8
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 6

                    Label { text: "Source & output"; font.bold: true; font.pixelSize: 14 }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label { text: "Source" }
                            TextField {
                                id: sourceField
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: activeFocus ? colorBackend.sourceText : colorBackend.contractPath(colorBackend.sourceText)
                                onTextEdited: colorBackend.sourceText = text
                                onTextChanged: if (!activeFocus) cursorPosition = text.length
                                ToolTip.text: colorBackend.sourceText
                                ToolTip.visible: hovered && !activeFocus && colorBackend.sourceText.length > 0
                                ToolTip.delay: 400
                            }
                            RowLayout {
                                Layout.alignment: Qt.AlignRight
                                spacing: 4
                                ToolButton {
                                    text: "📄"
                                    onClicked: colorBackend.browseSourceFile()
                                    ToolTip.text: "Choose file"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📁"
                                    onClicked: colorBackend.browseSourceFolder()
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
                            TextField {
                                id: outputField
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: activeFocus ? colorBackend.outputText : colorBackend.contractPath(colorBackend.outputText)
                                onTextEdited: colorBackend.outputText = text
                                onTextChanged: if (!activeFocus) cursorPosition = text.length
                                ToolTip.text: colorBackend.outputText
                                ToolTip.visible: hovered && !activeFocus && colorBackend.outputText.length > 0
                                ToolTip.delay: 400
                            }
                            RowLayout {
                                Layout.alignment: Qt.AlignRight
                                spacing: 4
                                ToolButton {
                                    text: "📄"
                                    onClicked: colorBackend.browseOutputFile()
                                    ToolTip.text: "Choose file"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📁"
                                    onClicked: colorBackend.browseOutputFolder()
                                    ToolTip.text: "Choose folder"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label { text: "Dive logs" }
                            TextField {
                                id: logsField
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: activeFocus ? colorBackend.logsText : colorBackend.contractPath(colorBackend.logsText)
                                onTextEdited: colorBackend.logsText = text
                                onTextChanged: if (!activeFocus) cursorPosition = text.length
                                ToolTip.text: colorBackend.logsText
                                ToolTip.visible: hovered && !activeFocus && colorBackend.logsText.length > 0
                                ToolTip.delay: 400
                            }
                            RowLayout {
                                Layout.alignment: Qt.AlignRight
                                spacing: 4
                                ToolButton {
                                    text: "📁"
                                    onClicked: colorBackend.browseLogsFolder()
                                    ToolTip.text: "Choose folder"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label { text: "Output filename" }
                            ComboBox {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: colorBackend.filenameFormatList
                                currentIndex: model.indexOf(colorBackend.filenameFormat)
                                onActivated: (index) => colorBackend.filenameFormat = model[index]
                            }
                        }
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                padding: 8
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 6

                    Label { text: "Progress"; font.bold: true; font.pixelSize: 14 }

                    Label {
                        Layout.fillWidth: true
                        text: colorBackend.sourceCountText
                        color: "#9AA0A6"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        visible: text.length > 0
                    }

                    // Label + bar + value all on one row (rather than a
                    // label row above the bar) - keeps two progress bars
                    // plus their value labels to one extra line each
                    // instead of two, so the page still fits in its
                    // default height without scrolling. Not visible:-gated
                    // on isRunning - that collapses height to zero when
                    // hidden, which was what made the Start button jump
                    // down the moment a run began; reserving the space
                    // from the start means nothing shifts, idle values
                    // (0%, blank) just look empty until a run is live.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Label { text: "Current"; color: "#9AA0A6"; font.pixelSize: 11; Layout.preferredWidth: 46 }
                        ProgressBar {
                            Layout.fillWidth: true
                            // Fills to a real aggregate percentage across
                            // the whole batch for the color-correction path
                            // (its progress lines are tagged per-file, so
                            // several files' percentages can be combined
                            // even when several run at once) - see
                            // progressCurrentFraction/Determinate in
                            // color_backend.py. Only falls back to a
                            // spinning indeterminate bar for the other,
                            // unlabeled emitters of this same marker
                            // (cli_main.py's HUD render-log frame loops)
                            // once more than one file is in play, since a
                            // bare percentage genuinely can't be pinned to
                            // any one of them there.
                            indeterminate: colorBackend.isRunning && !colorBackend.progressCurrentDeterminate
                            value: colorBackend.progressCurrentFraction
                        }
                        Label {
                            // Color-correction batches (labeled progress
                            // lines - see progressCurrentDeterminate in
                            // color_backend.py) now show a real aggregate
                            // percentage across the whole batch, so this
                            // shows that plus the active-file count when
                            // more than one file is genuinely in flight at
                            // once (e.g. "42% (3)"); other, unlabeled
                            // batches still fall back to just the count
                            // while the bar itself spins indeterminately.
                            // No hover tooltip (removed per the user's
                            // report - it read as "a transparent box"
                            // popping up over the preview during a run).
                            text: {
                                if (!colorBackend.isRunning) return ""
                                if (!colorBackend.progressCurrentDeterminate)
                                    return colorBackend.activeFilesCount + (colorBackend.activeFilesCount === 1 ? " file" : " files")
                                var pct = Math.round(colorBackend.progressCurrentFraction * 100) + "%"
                                return colorBackend.activeFilesCount > 1 ? pct + " (" + colorBackend.activeFilesCount + ")" : pct
                            }
                            color: "#9AA0A6"
                            font.pixelSize: 11
                            Layout.preferredWidth: 70
                            horizontalAlignment: Text.AlignRight
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Label { text: "Overall"; color: "#9AA0A6"; font.pixelSize: 11; Layout.preferredWidth: 46 }
                        ProgressBar {
                            Layout.fillWidth: true
                            value: colorBackend.progressOverallFraction
                        }
                        Label {
                            text: colorBackend.progressFilesTotal > 0
                                  ? (colorBackend.progressFilesDone + "/" + colorBackend.progressFilesTotal)
                                  : ""
                            color: "#9AA0A6"
                            font.pixelSize: 11
                            Layout.preferredWidth: 55
                            horizontalAlignment: Text.AlignRight
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: colorBackend.statusText
                        color: "#9AA0A6"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        text: colorBackend.isRunning ? "■  Abort" : "▶  Start"
                        highlighted: true
                        // Only one of Color/Overlay Generator/Convertion can
                        // run at a time (they'd otherwise all compete for
                        // ffmpeg/CPU) - stays enabled to Abort this page's
                        // own run, but can't Start a new one while either
                        // of the other two pages' backend is already going.
                        enabled: colorBackend.isRunning || !(overlayGeneratorBackend.isRunning || convertionBackend.isRunning)
                        ToolTip.text: "Another operation (Overlay Generator or Convertion) is already running"
                        ToolTip.visible: hovered && !enabled
                        ToolTip.delay: 400
                        onClicked: colorBackend.onStartClicked()
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }

    AddHudPopup {
        id: addHudPopup
    }
}
