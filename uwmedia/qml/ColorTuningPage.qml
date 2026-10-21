// Real Color Tuning page - qml_development.md Phase 4. Backed by
// uwmedia/backends/color_tuning_backend.py's ColorTuningBackend,
// exposed as "colorTuningBackend" (app.py). 26 sliders across 7 groups,
// generated from the backend's own `groups` structure via nested
// Repeaters - matches uwmedia/pages/color_tuning_page.py's own
// PARAM_GROUPS-driven loop (kept as reference only).
//
// Layout (2026-10-21, per the user): the image and profile controls are
// one row, and they and the Original / Adjusted previews stay put at the
// top; only the slider groups below scroll, so both images stay in view
// while a slider is moved.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Item {
    id: root
    width: 1060
    height: 800

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Label { text: "Color Tuning"; font.pixelSize: 24; font.bold: true }

        Pane {
            Layout.fillWidth: true
            Material.elevation: 1
            ColumnLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
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
                    Button { text: "Save Profile"; onClicked: colorTuningBackend.saveProfile() }
                    TextField {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 120
                        Layout.maximumWidth: 220
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        placeholderText: "New profile name"
                        maximumLength: 10
                        text: colorTuningBackend.newProfileName
                        onTextEdited: colorTuningBackend.newProfileName = text
                        ToolTip.text: "Name for Save As New, at most 10 characters"
                        ToolTip.visible: hovered
                    }
                    Button { text: "Save As New"; onClicked: colorTuningBackend.saveNewProfile() }
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

            RowLayout {
                anchors.left: parent.left
                anchors.right: parent.right
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

        // The slider groups - the only part of the page that scrolls.
        ScrollView {
            id: slidersView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.vertical.policy: ScrollBar.AlwaysOn

            ColumnLayout {
                // inset so the permanent scroll bar never covers a reset button
                width: slidersView.availableWidth - 20
                spacing: 16

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
            }
        }
    }
}
