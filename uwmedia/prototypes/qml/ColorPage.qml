import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

// Same fields as pages/color_page.ui (preview, scrub slider, HUD overlays,
// color correction, source/output/dive-logs/output-filename, progress/
// start) - static sample data only, see main.qml's own header comment.
ScrollView {
    id: root
    clip: true
    contentWidth: availableWidth

    readonly property int previewWidth: 480
    readonly property int previewHeight: Math.round(previewWidth * 9 / 16)

    RowLayout {
        width: root.availableWidth
        spacing: 20

        // --- Left column: live preview + HUD overlays -----------------
        ColumnLayout {
            Layout.preferredWidth: root.availableWidth * 0.58
            Layout.alignment: Qt.AlignTop
            spacing: 12

            Label {
                text: "Live preview"
                font.pixelSize: 24
                font.bold: true
            }

            Pane {
                Layout.fillWidth: false
                Material.elevation: 1
                ColumnLayout {
                    spacing: 8

                    Rectangle {
                        Layout.preferredWidth: root.previewWidth
                        Layout.preferredHeight: root.previewHeight
                        color: "#000000"
                        radius: 8
                        clip: true

                        Image {
                            anchors.fill: parent
                            source: typeof previewImageUrl !== "undefined" ? previewImageUrl : ""
                            fillMode: Image.Stretch
                            asynchronous: true
                        }
                    }

                    RowLayout {
                        Layout.preferredWidth: root.previewWidth
                        Slider {
                            Layout.fillWidth: true
                            from: 0
                            to: 100
                            value: 35
                        }
                        Label { text: "00:42" }
                    }
                }
            }

            Pane {
                Material.elevation: 1
                ColumnLayout {
                    spacing: 10
                    Label { text: "HUD overlays"; font.bold: true; font.pixelSize: 14 }

                    ListView {
                        Layout.preferredWidth: root.previewWidth
                        Layout.preferredHeight: 120
                        clip: true
                        model: ["Garmin x50i – Main Screen", "Generic Dive Profile – Main"]
                        currentIndex: 0
                        delegate: ItemDelegate {
                            width: ListView.view.width
                            text: modelData
                            highlighted: ListView.isCurrentItem
                            onClicked: ListView.view.currentIndex = index
                        }
                    }

                    RowLayout {
                        spacing: 8
                        Button {
                            text: "+ Add HUD…"
                            highlighted: true
                        }
                        Button {
                            text: "Remove Selected"
                        }
                        Item { Layout.fillWidth: true }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        // --- Right column: color correction / source-output / progress -
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

                    Label { text: "Color correction"; font.bold: true; font.pixelSize: 14 }

                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Apply color correction" }
                        Item { Layout.fillWidth: true }
                        Switch { checked: true }
                    }

                    ComboBox {
                        Layout.fillWidth: true
                        model: ["Default", "Vivid", "Deep Blue", "Green Water", "Muted"]
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 12

                    Label { text: "Source & output"; font.bold: true; font.pixelSize: 14 }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 12
                        rowSpacing: 10

                        Label { text: "Source" }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            TextField {
                                Layout.fillWidth: true
                                text: "/DivingMedia/2026-09-12_raja-ampat/raw"
                            }
                            Button { text: "File…" }
                            Button { text: "Folder…" }
                        }

                        Label { text: "Output" }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            TextField {
                                Layout.fillWidth: true
                                text: "/DivingMedia/2026-09-12_raja-ampat/corrected"
                            }
                            Button { text: "File…" }
                            Button { text: "Folder…" }
                        }

                        Label { text: "Dive logs" }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            TextField {
                                Layout.fillWidth: true
                                text: "/DivingMedia/logs/descent_mk3i.fit"
                            }
                            Button { text: "Browse" }
                        }

                        Label { text: "Output filename" }
                        ComboBox {
                            Layout.fillWidth: true
                            model: ["Original filename", "Date taken", "Date + time", "Date + time + color"]
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
                    spacing: 10

                    Label { text: "Progress"; font.bold: true; font.pixelSize: 14 }

                    ProgressBar {
                        Layout.fillWidth: true
                        value: 0.42
                    }
                    Label {
                        text: "Processing 3 of 7 files…"
                        color: "#9AA0A6"
                        font.pixelSize: 12
                    }
                    Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        text: "▶  Start"
                        highlighted: true
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }
}
