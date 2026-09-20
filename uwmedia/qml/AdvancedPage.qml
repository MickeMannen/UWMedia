// Real Advanced page - qml_development.md Phase 9. Backed by
// uwmedia/backends/advanced_backend.py's AdvancedBackend, exposed
// as "advancedBackend" (app.py). Matches
// uwmedia/pages/advanced_page.py (kept as reference only).
// This page mutates real settings.json/config.yaml (Application
// Support) - see the backend's own module docstring for the CLAUDE.md
// live-testing caveat that applies here specifically.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window

Item {
    id: root
    width: 1060
    height: 720

    ScrollView {
        anchors.fill: parent
        anchors.margins: 20
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: Math.min(parent.width, 700)
            spacing: 16

            Label { text: "Advanced"; font.pixelSize: 24; font.bold: true }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 4
                    Label { text: "Flags"; font.bold: true; font.pixelSize: 14 }
                    CheckBox {
                        text: "Debug output"
                        checked: advancedBackend.debug
                        onToggled: advancedBackend.debug = checked
                    }
                    CheckBox {
                        text: "Show summary"
                        checked: advancedBackend.summary
                        onToggled: advancedBackend.summary = checked
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 10
                    Label { text: "Locations"; font.bold: true; font.pixelSize: 14 }

                    Repeater {
                        model: [
                            { label: "Layouts folder", kind: "layouts", text: advancedBackend.layoutsDirText },
                            { label: "Templates folder", kind: "templates", text: advancedBackend.templatesDirText },
                            { label: "Color profiles folder", kind: "color", text: advancedBackend.colorDirText }
                        ]
                        delegate: ColumnLayout {
                            Layout.fillWidth: true
                            required property var modelData
                            spacing: 2
                            Label { text: modelData.label; color: "#9AA0A6"; font.pixelSize: 11 }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    readOnly: true
                                    text: modelData.text
                                }
                                Button { text: "Change…"; onClicked: advancedBackend.choosePath(modelData.kind) }
                                Button { text: "Reset"; onClicked: advancedBackend.resetPath(modelData.kind) }
                            }
                        }
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 8
                    Label { text: "Sensor names"; font.bold: true; font.pixelSize: 14 }
                    Label { text: "Config file"; color: "#9AA0A6"; font.pixelSize: 11 }
                    TextField {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        readOnly: true
                        text: advancedBackend.tankNamesPathText
                    }
                    Button {
                        text: "Edit Tank Sensor Names…"
                        onClicked: advancedBackend.openTankNamesWindow()
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 10
                    Label { text: "External tools"; font.bold: true; font.pixelSize: 14 }

                    Repeater {
                        model: [
                            { label: "ffmpeg path", kind: "ffmpeg", text: advancedBackend.ffmpegPathText },
                            { label: "exiftool path", kind: "exiftool", text: advancedBackend.exiftoolPathText }
                        ]
                        delegate: ColumnLayout {
                            Layout.fillWidth: true
                            required property var modelData
                            spacing: 2
                            Label { text: modelData.label; color: "#9AA0A6"; font.pixelSize: 11 }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    readOnly: true
                                    text: modelData.text
                                }
                                Button { text: "Change…"; onClicked: advancedBackend.choosePath(modelData.kind) }
                                Button { text: "Reset"; onClicked: advancedBackend.resetPath(modelData.kind) }
                            }
                        }
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 8
                    Label { text: "Custom filename formats"; font.bold: true; font.pixelSize: 14 }
                    RowLayout {
                        Layout.fillWidth: true
                        TextField {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            placeholderText: "e.g. \"%Y-%m-%d_%H-%M-%S\""
                            text: advancedBackend.newFilenameFormatText
                            onTextEdited: advancedBackend.newFilenameFormatText = text
                        }
                        Button { text: "Add"; onClicked: advancedBackend.addFilenameFormat() }
                    }
                }
            }

            Item { Layout.preferredHeight: 20 }
        }
    }

    Window {
        id: tankWindow
        visible: advancedBackend.tankWindowVisible
        title: "Tank Sensor Names"
        width: 560
        height: 500
        onClosing: advancedBackend.closeTankNamesWindow()

        Rectangle {
            anchors.fill: parent
            color: "#1F1F1F"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10

                Label {
                    Layout.fillWidth: true
                    text: "Map Garmin tank sensor serial numbers to friendly names (e.g. \"Left\", \"Micke01\")."
                    color: "white"
                    wrapMode: Text.WordWrap
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: advancedBackend.tankRows
                    delegate: RowLayout {
                        width: ListView.view.width
                        required property var modelData
                        Label {
                            Layout.preferredWidth: 140
                            text: modelData.serial
                            color: "#E0E0E0"
                        }
                        TextField {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            font.pixelSize: 15
                            text: modelData.name
                            onTextEdited: advancedBackend.setTankName(modelData.serial, text)
                        }
                        Button {
                            text: "Remove"
                            onClicked: advancedBackend.removeTankRow(modelData.serial)
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Add serial manually"; color: "white" }
                    TextField {
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        placeholderText: "Serial number"
                        text: advancedBackend.newSerialText
                        onTextEdited: advancedBackend.newSerialText = text
                    }
                    Button { text: "Add"; onClicked: advancedBackend.addManualSerial() }
                    Item { Layout.fillWidth: true }
                }

                Label {
                    Layout.fillWidth: true
                    text: advancedBackend.tankStatusText
                    color: "#9AA0A6"
                    wrapMode: Text.WordWrap
                    visible: text.length > 0
                }

                RowLayout {
                    spacing: 8
                    Button { text: "Scan Logs Folder…"; onClicked: advancedBackend.scanLogsFolder() }
                    Button {
                        text: "Save"
                        highlighted: true
                        onClicked: advancedBackend.saveTankNames()
                    }
                    Item { Layout.fillWidth: true }
                }
            }
        }
    }
}
