// Real Color Tuning page - qml_development.md Phase 4. Backed by
// uwmedia/backends/color_tuning_backend.py's ColorTuningBackend,
// exposed as "colorTuningBackend" (app.py). 26 sliders across 7 groups,
// generated from the backend's own `groups` structure via nested
// Repeaters - matches uwmedia/pages/color_tuning_page.py's own
// PARAM_GROUPS-driven loop (kept as reference only).
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
        width: root.availableWidth
        spacing: 16

        Label { text: "Color Tuning"; font.pixelSize: 24; font.bold: true }

        Pane {
            Layout.fillWidth: true
            Material.elevation: 1
            ColumnLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 10

                Label { text: "Sample image"; font.bold: true; font.pixelSize: 14 }

                RowLayout {
                    spacing: 10
                    Button { text: "Load Image…"; onClicked: colorTuningBackend.loadImage() }
                    Label { text: "Profile:" }
                    ComboBox {
                        Layout.preferredWidth: 160
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        model: colorTuningBackend.profileList
                        currentIndex: model.indexOf(colorTuningBackend.currentProfile)
                        onActivated: (index) => colorTuningBackend.currentProfile = model[index]
                    }
                    CheckBox {
                        text: "Use legacy pipeline"
                        checked: colorTuningBackend.legacyPipeline
                        onToggled: colorTuningBackend.legacyPipeline = checked
                    }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    spacing: 10
                    Button { text: "Save Profile"; onClicked: colorTuningBackend.saveProfile() }
                    TextField {
                        Layout.preferredWidth: 220
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        placeholderText: "New profile name (max 10 chars)"
                        maximumLength: 10
                        text: colorTuningBackend.newProfileName
                        onTextEdited: colorTuningBackend.newProfileName = text
                    }
                    Button { text: "Save As New"; onClicked: colorTuningBackend.saveNewProfile() }
                    Item { Layout.fillWidth: true }
                }

                Label {
                    Layout.fillWidth: true
                    text: colorTuningBackend.statusText
                    color: "#9AA0A6"
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
                spacing: 10

                Label { text: "Preview"; font.bold: true; font.pixelSize: 14 }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 16

                    // Both columns get preferredWidth 1 so the RowLayout splits
                    // the width exactly in half (otherwise the halves follow
                    // the images' own implicit sizes and end up unequal).
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Label { text: "Original"; font.bold: true }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 260
                            color: "black"
                            Image {
                                anchors.fill: parent
                                anchors.margins: 2
                                source: colorTuningBackend.originalImageSource
                                fillMode: Image.PreserveAspectFit
                                cache: false
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Label { text: "Adjusted"; font.bold: true }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 260
                            color: "black"
                            Image {
                                anchors.fill: parent
                                anchors.margins: 2
                                source: colorTuningBackend.resultImageSource
                                fillMode: Image.PreserveAspectFit
                                cache: false
                            }
                        }
                    }
                }
            }
        }

        Repeater {
            model: colorTuningBackend.groups

            delegate: Pane {
                id: groupDelegate
                Layout.fillWidth: true
                Material.elevation: 1
                required property var modelData

                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 8

                    Label { text: groupDelegate.modelData.title; font.bold: true; font.pixelSize: 14 }

                    Repeater {
                        model: groupDelegate.modelData.params

                        delegate: RowLayout {
                            Layout.fillWidth: true
                            required property var modelData
                            spacing: 8

                            Label {
                                Layout.preferredWidth: 190
                                text: modelData.label
                            }
                            Slider {
                                Layout.fillWidth: true
                                from: modelData.sliderMin
                                to: modelData.sliderMax
                                stepSize: 1
                                value: colorTuningBackend.sliderValues[modelData.key]
                                onMoved: colorTuningBackend.setSliderValue(modelData.key, Math.round(value))
                            }
                            Label {
                                Layout.preferredWidth: 60
                                text: colorTuningBackend.sliderTexts[modelData.key]
                            }
                            Button {
                                Layout.preferredWidth: 32
                                text: "↺"
                                onClicked: colorTuningBackend.resetSlider(modelData.key)
                            }
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
