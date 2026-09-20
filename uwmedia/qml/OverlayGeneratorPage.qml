// Real Overlay Generator page - qml_development.md Phase 2. Backed by
// uwmedia/backends/overlay_generator_backend.py's
// OverlayGeneratorBackend, exposed as "overlayGeneratorBackend" (app.py).
// Layout mirrors uwmedia/pages/overlay_generator_page.py (kept
// as reference only). Compacted 2026-09-20 (per the user, live): browse
// buttons sit beside their fields, no "Source & output" header, tighter
// spacing and a shorter overlay list so the page fits 720 px unscrolled.
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

    RowLayout {
        width: root.availableWidth
        spacing: 20

        ColumnLayout {
            Layout.preferredWidth: root.availableWidth * 0.6
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
                            Label { text: "Source" }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                TextField {
                                    id: sourceField
                                    Layout.fillWidth: true
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
                                    Layout.fillWidth: true
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
                            Label { text: "Dive logs" }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                TextField {
                                    id: logsField
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    text: activeFocus ? overlayGeneratorBackend.logsText : overlayGeneratorBackend.contractPath(overlayGeneratorBackend.logsText)
                                    onTextEdited: overlayGeneratorBackend.logsText = text
                                    onTextChanged: if (!activeFocus) cursorPosition = text.length
                                    ToolTip.text: overlayGeneratorBackend.logsText
                                    ToolTip.visible: hovered && !activeFocus && overlayGeneratorBackend.logsText.length > 0
                                    ToolTip.delay: 400
                                }
                                ToolButton {
                                    text: "📁"
                                    onClicked: overlayGeneratorBackend.browseLogsFolder()
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
                                model: overlayGeneratorBackend.filenameFormatList
                                currentIndex: model.indexOf(overlayGeneratorBackend.filenameFormat)
                                onActivated: (index) => overlayGeneratorBackend.filenameFormat = model[index]
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Skip if target exists" }
                        Switch {
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
                            onActivated: (index) => overlayGeneratorBackend.onBrandSelected(model[index])
                        }

                        Label { text: "Dive computer"; visible: overlayGeneratorBackend.computerVisible }
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            visible: overlayGeneratorBackend.computerVisible
                            model: overlayGeneratorBackend.computerList
                            onActivated: (index) => overlayGeneratorBackend.onComputerSelected(model[index])
                        }

                        Label { text: "Page"; visible: !overlayGeneratorBackend.isCustom }
                        ComboBox {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            visible: !overlayGeneratorBackend.isCustom
                            model: overlayGeneratorBackend.pageList
                            onActivated: (index) => overlayGeneratorBackend.onPageSelected(model[index])
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
            Layout.fillWidth: true
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

                    ProgressBar {
                        Layout.fillWidth: true
                        indeterminate: true
                        visible: overlayGeneratorBackend.isRunning
                    }
                    Label {
                        Layout.fillWidth: true
                        text: overlayGeneratorBackend.overlayProgressText
                        color: "#9AA0A6"
                        font.pixelSize: 12
                        visible: text.length > 0
                    }
                    Label {
                        Layout.fillWidth: true
                        text: overlayGeneratorBackend.statusText
                        color: "#9AA0A6"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        text: overlayGeneratorBackend.isRunning ? "■  Abort" : "▶  Start"
                        highlighted: true
                        // Only one of Color/Overlay Generator/Convertion can
                        // run at a time (they'd otherwise all compete for
                        // ffmpeg/CPU) - see ColorPage.qml's own Start button.
                        enabled: overlayGeneratorBackend.isRunning || !(colorBackend.isRunning || convertionBackend.isRunning)
                        ToolTip.text: "Another operation (Color or Convertion) is already running"
                        ToolTip.visible: hovered && !enabled
                        ToolTip.delay: 400
                        onClicked: overlayGeneratorBackend.onStartClicked()
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }
}
