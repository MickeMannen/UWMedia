// Real Convertion page - qml_development.md Phase 3. Backed by
// uwmedia/backends/convertion_backend.py's ConvertionBackend,
// exposed as "convertionBackend" (app.py). Simplest page so far - a
// single ffmpeg invocation, no cascading dropdowns, no persistence
// (matches uwmedia/pages/convertion_page.py, kept as reference
// only). Compacted 2026-09-20 (per the user, live): browse buttons beside
// their fields, resolutions as switches in two columns, tighter spacing.
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

    ColumnLayout {
        width: Math.min(root.availableWidth, 700)
        spacing: 10

        Label { text: "Convertion"; font.pixelSize: 22; font.bold: true }

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
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                readOnly: true
                                text: convertionBackend.contractPath(convertionBackend.sourceText)
                                ToolTip.text: convertionBackend.sourceText
                                ToolTip.visible: hovered && convertionBackend.sourceText.length > 0
                                ToolTip.delay: 400
                            }
                            ToolButton {
                                text: "📄"
                                onClicked: convertionBackend.browseSource()
                                ToolTip.text: "Choose file"
                                ToolTip.visible: hovered
                                ToolTip.delay: 400
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Label { text: "Destination" }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                readOnly: true
                                text: convertionBackend.contractPath(convertionBackend.destText)
                                ToolTip.text: convertionBackend.destText
                                ToolTip.visible: hovered && convertionBackend.destText.length > 0
                                ToolTip.delay: 400
                            }
                            ToolButton {
                                text: "📁"
                                onClicked: convertionBackend.browseDest()
                                ToolTip.text: "Choose folder"
                                ToolTip.visible: hovered
                                ToolTip.delay: 400
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: convertionBackend.sourceResolutionText
                    color: "#9AA0A6"
                    visible: text.length > 0
                }

                RowLayout {
                    Layout.fillWidth: true
                    // Used to live only on the Advanced page (see
                    // color_backend.py's hwAccel docstring for why it
                    // moved here instead).
                    Label { text: "Hardware acceleration"; color: "#9AA0A6" }
                    Switch {
                        checked: convertionBackend.hwAccel
                        onToggled: convertionBackend.hwAccel = checked
                    }
                    Item { Layout.fillWidth: true }
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
                spacing: 4

                Label { text: "Output resolutions"; font.bold: true; font.pixelSize: 14 }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 12
                    rowSpacing: 10
                    Repeater {
                        model: convertionBackend.resolutionNames
                        delegate: Switch {
                            Layout.fillWidth: true
                            text: modelData
                            checked: convertionBackend.checkedResolutions.indexOf(modelData) !== -1
                            enabled: convertionBackend.enabledResolutions.indexOf(modelData) !== -1
                            onToggled: convertionBackend.setChecked(modelData, checked)
                        }
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
                spacing: 4

                Label { text: "Output files"; font.bold: true; font.pixelSize: 14 }
                Label {
                    Layout.fillWidth: true
                    text: convertionBackend.outputPreviewText
                    color: "#9AA0A6"
                    font.pixelSize: 12
                    wrapMode: Text.WrapAnywhere
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
                spacing: 6

                Label { text: "Progress"; font.bold: true; font.pixelSize: 14 }

                ProgressBar {
                    Layout.fillWidth: true
                    indeterminate: true
                    visible: convertionBackend.isRunning
                }
                Label {
                    Layout.fillWidth: true
                    text: convertionBackend.statusText
                    color: "#9AA0A6"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Button {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    text: convertionBackend.isRunning ? "■  Abort" : "▶  Start"
                    highlighted: true
                    // Only one of Color/Overlay Generator/Convertion can run
                    // at a time (they'd otherwise all compete for ffmpeg/
                    // CPU) - see ColorPage.qml's own Start button.
                    enabled: convertionBackend.isRunning || !(colorBackend.isRunning || overlayGeneratorBackend.isRunning)
                    ToolTip.text: "Another operation (Color or Overlay Generator) is already running"
                    ToolTip.visible: hovered && !enabled
                    ToolTip.delay: 400
                    onClicked: convertionBackend.onStartClicked()
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
