// Real Log Viewer page - qml_development.md Phase 6. Backed by
// uwmedia/backends/log_viewer_backend.py's LogViewerBackend,
// exposed as "logViewerBackend" (app.py). Matches
// uwmedia/pages/log_viewer_page.py (kept as reference only).
// Read-only page - no destructive actions, no confirm dialogs needed.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Item {
    id: root
    width: 1060
    height: 720

    RowLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 20

        // --- Left: directory + file list -----------------------------
        ColumnLayout {
            Layout.preferredWidth: 260
            Layout.fillHeight: true
            spacing: 10

            Button {
                Layout.fillWidth: true
                text: "Select Log Directory"
                onClicked: logViewerBackend.selectDirectory()
            }
            Label {
                Layout.fillWidth: true
                text: logViewerBackend.dirLabel
                color: "#9AA0A6"
                wrapMode: Text.WrapAnywhere
                font.pixelSize: 12
            }
            ListView {
                id: fileListView
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: logViewerBackend.fileNames
                delegate: ItemDelegate {
                    width: ListView.view.width
                    text: modelData
                    highlighted: ListView.isCurrentItem
                    onClicked: {
                        ListView.view.currentIndex = index
                        logViewerBackend.selectFileAtIndex(index)
                    }
                }
            }
        }

        // --- Right: selected file / summary / sensors / table --------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                RowLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    Label { text: logViewerBackend.selectedFileName; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Label { text: "Dive:" }
                    ComboBox {
                        Layout.preferredWidth: 280
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        model: logViewerBackend.diveLabels
                        currentIndex: model.indexOf(logViewerBackend.currentDiveLabel)
                        onActivated: (index) => logViewerBackend.selectDive(model[index])
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 6
                    Label { text: "Dive summary"; font.bold: true; font.pixelSize: 14 }
                    Label {
                        Layout.fillWidth: true
                        text: logViewerBackend.summaryText
                        color: "#D0D0D0"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 6
                    Label { text: "Tank sensors found"; font.bold: true; font.pixelSize: 14 }
                    Label {
                        Layout.fillWidth: true
                        text: logViewerBackend.sensorsText
                        color: "#D0D0D0"
                        wrapMode: Text.WordWrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "Use these serial numbers in Advanced → Sensor names to map them to friendly names."
                        color: "#808080"
                        font.pixelSize: 10
                        wrapMode: Text.WordWrap
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Label { text: "Filter:" }
                TextField {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    font.pixelSize: 15
                    placeholderText: "Type to filter waypoints..."
                    text: logViewerBackend.filterText
                    onTextEdited: logViewerBackend.filterText = text
                }
            }

            Pane {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Material.elevation: 1
                padding: 0

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 6
                        spacing: 0
                        Repeater {
                            model: logViewerBackend.tableHeaders
                            delegate: Label {
                                required property string modelData
                                Layout.preferredWidth: index === 5 ? 70 : (index === 6 ? 260 : 90)
                                text: modelData
                                font.bold: true
                                elide: Text.ElideRight
                                required property int index
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#333" }

                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: logViewerBackend.tableRows
                        delegate: Rectangle {
                            id: rowDelegate
                            width: ListView.view.width
                            height: 24
                            color: index % 2 === 0 ? "#1A1A1A" : "#141414"
                            required property var modelData
                            required property int index

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                anchors.rightMargin: 6
                                spacing: 0
                                Repeater {
                                    model: rowDelegate.modelData
                                    delegate: Label {
                                        required property string modelData
                                        required property int index
                                        Layout.preferredWidth: index === 5 ? 70 : (index === 6 ? 260 : 90)
                                        text: modelData
                                        color: "#E0E0E0"
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                text: logViewerBackend.statusText
                color: "#9AA0A6"
                font.pixelSize: 12
            }
        }
    }
}
