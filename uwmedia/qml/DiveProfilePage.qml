// Real Dive Profile Builder page - qml_development.md Phase 8. Backed by
// uwmedia/backends/dive_profile_backend.py's DiveProfileBackend,
// exposed as "diveProfileBackend" (app.py). Matches
// uwmedia/pages/dive_profile_page.py (kept as reference only).
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

        // --- Left: settings / gases / waypoints -------------------------
        ScrollView {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: 16

                Pane {
                    Layout.fillWidth: true
                    Material.elevation: 1
                    ColumnLayout {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 8
                        Label { text: "Dive settings"; font.bold: true; font.pixelSize: 14 }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            columnSpacing: 12
                            rowSpacing: 8

                            Label { text: "Name" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: diveProfileBackend.nameText
                                onTextEdited: diveProfileBackend.nameText = text
                            }

                            Label { text: "GF Low/High" }
                            RowLayout {
                                Layout.fillWidth: true
                                Slider {
                                    Layout.fillWidth: true
                                    from: 10; to: 99
                                    value: diveProfileBackend.gfLow
                                    onMoved: diveProfileBackend.onGfChanged(Math.round(value), diveProfileBackend.gfHigh)
                                }
                                Slider {
                                    Layout.fillWidth: true
                                    from: 10; to: 99
                                    value: diveProfileBackend.gfHigh
                                    onMoved: diveProfileBackend.onGfChanged(diveProfileBackend.gfLow, Math.round(value))
                                }
                                Label { Layout.preferredWidth: 50; text: diveProfileBackend.gfLabel }
                            }

                            Label { text: "Descent rate (m/min)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: diveProfileBackend.descentRateText
                                onTextEdited: diveProfileBackend.descentRateText = text
                            }

                            Label { text: "Ascent rate (m/min)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: diveProfileBackend.ascentRateText
                                onTextEdited: diveProfileBackend.ascentRateText = text
                            }

                            Label { text: "Water temp (°C)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: diveProfileBackend.waterTempText
                                onTextEdited: diveProfileBackend.waterTempText = text
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
                        Label { text: "Gases"; font.bold: true; font.pixelSize: 14 }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            RowLayout {
                                Layout.fillWidth: true
                                Repeater {
                                    model: diveProfileBackend.gasTableHeaders
                                    delegate: Label {
                                        required property string modelData
                                        Layout.fillWidth: true
                                        text: modelData
                                        font.bold: true
                                        font.pixelSize: 11
                                    }
                                }
                            }
                            ListView {
                                id: gasListView
                                Layout.fillWidth: true
                                Layout.preferredHeight: 120
                                clip: true
                                model: diveProfileBackend.gasTableRows
                                delegate: Rectangle {
                                    id: gasRow
                                    width: ListView.view.width
                                    height: 24
                                    color: ListView.isCurrentItem ? "#2A3F5F" : (index % 2 === 0 ? "#1A1A1A" : "#141414")
                                    required property var modelData
                                    required property int index
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: gasListView.currentIndex = gasRow.index
                                    }
                                    RowLayout {
                                        anchors.fill: parent
                                        Repeater {
                                            model: gasRow.modelData
                                            delegate: Label {
                                                required property string modelData
                                                Layout.fillWidth: true
                                                text: modelData
                                                color: "#E0E0E0"
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "e.g. Bottom"
                                text: diveProfileBackend.gasNameText
                                onTextEdited: diveProfileBackend.gasNameText = text
                            }
                            ComboBox {
                                Layout.preferredWidth: 90
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: diveProfileBackend.gasTypeList
                                onActivated: (index) => diveProfileBackend.onGasTypeSelected(model[index])
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "O2%" }
                            TextField {
                                Layout.preferredWidth: 50
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: diveProfileBackend.gasO2Text
                                onTextEdited: diveProfileBackend.gasO2Text = text
                            }
                            Label { text: "He%" }
                            TextField {
                                Layout.preferredWidth: 50
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: diveProfileBackend.gasHeText
                                onTextEdited: diveProfileBackend.gasHeText = text
                            }
                            Label { text: "SP" }
                            TextField {
                                Layout.preferredWidth: 50
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                enabled: diveProfileBackend.setpointEnabled
                                text: diveProfileBackend.gasSetpointText
                                onTextEdited: diveProfileBackend.gasSetpointText = text
                            }
                            Label { text: "Tank" }
                            TextField {
                                Layout.preferredWidth: 50
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                text: diveProfileBackend.gasTankText
                                onTextEdited: diveProfileBackend.gasTankText = text
                            }
                        }
                        RowLayout {
                            spacing: 8
                            Button { text: "Add Gas"; onClicked: diveProfileBackend.addGas() }
                            Button {
                                text: "Remove Selected"
                                onClicked: diveProfileBackend.removeGasAtRow(gasListView.currentIndex)
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: diveProfileBackend.gasStatusText
                            color: "#9AA0A6"
                            wrapMode: Text.WordWrap
                            visible: text.length > 0
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
                        Label { text: "Waypoints"; font.bold: true; font.pixelSize: 14 }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            RowLayout {
                                Layout.fillWidth: true
                                Repeater {
                                    model: diveProfileBackend.waypointHeaders
                                    delegate: Label {
                                        required property string modelData
                                        Layout.fillWidth: true
                                        text: modelData
                                        font.bold: true
                                        font.pixelSize: 11
                                    }
                                }
                            }
                            ListView {
                                id: wpListView
                                Layout.fillWidth: true
                                Layout.preferredHeight: 160
                                clip: true
                                model: diveProfileBackend.waypointRows
                                delegate: Rectangle {
                                    id: wpRow
                                    width: ListView.view.width
                                    height: 24
                                    color: ListView.isCurrentItem ? "#2A3F5F" : (index % 2 === 0 ? "#1A1A1A" : "#141414")
                                    required property var modelData
                                    required property int index
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: {
                                            wpListView.currentIndex = wpRow.index
                                            diveProfileBackend.selectWaypointRow(wpRow.index)
                                        }
                                    }
                                    RowLayout {
                                        anchors.fill: parent
                                        Repeater {
                                            model: wpRow.modelData
                                            delegate: Label {
                                                required property string modelData
                                                Layout.fillWidth: true
                                                text: modelData
                                                color: "#E0E0E0"
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "mm:ss or minutes"
                                text: diveProfileBackend.wpTimeText
                                onTextEdited: diveProfileBackend.wpTimeText = text
                            }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "meters"
                                text: diveProfileBackend.wpDepthText
                                onTextEdited: diveProfileBackend.wpDepthText = text
                            }
                            ComboBox {
                                Layout.preferredWidth: 90
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: diveProfileBackend.gasIdList
                                currentIndex: model.indexOf(diveProfileBackend.wpGasText)
                                onActivated: (index) => diveProfileBackend.onWpGasSelected(model[index])
                            }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "default"
                                text: diveProfileBackend.wpRateText
                                onTextEdited: diveProfileBackend.wpRateText = text
                            }
                        }
                        RowLayout {
                            spacing: 8
                            Button { text: "Add / Update"; onClicked: diveProfileBackend.addOrUpdateWaypoint() }
                            Button {
                                text: "Remove Selected"
                                onClicked: diveProfileBackend.removeWaypointAtRow(wpListView.currentIndex)
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: diveProfileBackend.wpStatusText
                            color: "#9AA0A6"
                            wrapMode: Text.WordWrap
                            visible: text.length > 0
                        }
                    }
                }

                Item { Layout.fillHeight: true }
            }
        }

        // --- Right: chart + save ----------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: 8

            Label {
                text: "Click and drag across the chart to scrub NDL/deco"
                color: "#9AA0A6"
            }

            Rectangle {
                Layout.preferredWidth: 700
                Layout.preferredHeight: 420
                color: "#000000"

                Image {
                    anchors.fill: parent
                    source: diveProfileBackend.previewImageSource
                    fillMode: Image.Stretch
                    cache: false
                }

                MouseArea {
                    anchors.fill: parent
                    onPressed: (mouse) => diveProfileBackend.onScrub(mouse.x)
                    onPositionChanged: (mouse) => {
                        if (pressed)
                            diveProfileBackend.onScrub(mouse.x)
                    }
                }
            }

            Label {
                Layout.preferredWidth: 700
                text: diveProfileBackend.statusText
                color: diveProfileBackend.statusIsError ? "#EF4444" : "#9AA0A6"
                wrapMode: Text.WordWrap
            }

            Button {
                Layout.preferredWidth: 200
                text: "Save as UDDF…"
                highlighted: true
                onClicked: diveProfileBackend.saveAsUddf()
            }

            Item { Layout.fillHeight: true }
        }
    }
}
