// Real Tag Editor page - qml_development.md Phase 5. Backed by
// uwmedia/backends/tag_editor_backend.py's TagEditorBackend,
// exposed as "tagEditorBackend" (app.py). Matches
// uwmedia/pages/tag_editor_page.py (kept as reference only).
// Destructive-action confirms are real modal Dialogs (see backend's own
// module docstring); purely-informational alerts surface via the status
// label instead of a second modal - a deliberate first-pass UX
// simplification, not a functional gap.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window

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
                text: "Select Directory"
                onClicked: tagEditorBackend.selectDirectory()
            }
            Label {
                Layout.fillWidth: true
                text: tagEditorBackend.dirLabel
                color: "#9AA0A6"
                wrapMode: Text.WrapAnywhere
                font.pixelSize: 12
            }
            ListView {
                id: fileListView
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: tagEditorBackend.fileNames
                delegate: ItemDelegate {
                    width: ListView.view.width
                    // compact rows (the Material default is ~48 px per row)
                    height: 30
                    font.pixelSize: 13
                    text: modelData
                    highlighted: ListView.isCurrentItem
                    onClicked: {
                        ListView.view.currentIndex = index
                        tagEditorBackend.selectFileAtIndex(index)
                    }
                }
            }
        }

        // --- Right: selected file / tags / timezone / actions --------
        ScrollView {
            Layout.fillWidth: true
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

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                text: tagEditorBackend.selectedFileName
                                font.bold: true
                            }
                            Item { Layout.fillWidth: true }
                            Button {
                                text: "View All Metadata"
                                enabled: tagEditorBackend.viewMetadataEnabled
                                onClicked: tagEditorBackend.viewAllMetadata()
                            }
                        }
                        Label {
                            visible: tagEditorBackend.djiVisible
                            text: "DJI file detected: values calculated from OriginalFilePath."
                            color: "#4CAF50"
                            font.bold: true
                        }
                    }
                }

                Pane {
                    Layout.fillWidth: true
                    Material.elevation: 1
                    ColumnLayout {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 4

                        Label { text: "Edit metadata tags"; font.bold: true; font.pixelSize: 14 }

                        Repeater {
                            model: tagEditorBackend.tagGuide
                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                required property var modelData
                                spacing: 2

                                Label { text: modelData.tag; font.bold: true }
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    text: tagEditorBackend.tagValues[modelData.tag] || ""
                                    onTextEdited: tagEditorBackend.setTagValue(modelData.tag, text)
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.help
                                    color: "#808080"
                                    font.pixelSize: 10
                                    wrapMode: Text.WordWrap
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

                        Label { text: "Batch set directory timezone"; font.bold: true; font.pixelSize: 14 }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Label { text: "Timezone offset:" }
                            ComboBox {
                                Layout.preferredWidth: 120
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: tagEditorBackend.tzOptionList
                                currentIndex: model.indexOf(tagEditorBackend.currentTz)
                                onActivated: (index) => tagEditorBackend.currentTz = model[index]
                            }
                            Label { text: "Mode:" }
                            ComboBox {
                                Layout.preferredWidth: 260
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: tagEditorBackend.tzModeList
                                currentIndex: model.indexOf(tagEditorBackend.currentTzMode)
                                onActivated: (index) => tagEditorBackend.currentTzMode = model[index]
                            }
                            Button {
                                text: "Apply Timezone to All"
                                onClicked: tagEditorBackend.onApplyTimezoneClicked()
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                RowLayout {
                    spacing: 8
                    Button { text: "Revert Changes"; onClicked: tagEditorBackend.revertChanges() }
                    Button { text: "Update All (DJI)"; onClicked: tagEditorBackend.onUpdateAllTagsClicked() }
                    Button {
                        text: "Write to File"
                        highlighted: true
                        onClicked: tagEditorBackend.writeTags()
                    }
                    Item { Layout.fillWidth: true }
                }

                ProgressBar {
                    Layout.fillWidth: true
                    indeterminate: true
                    visible: tagEditorBackend.busy
                }
                Label {
                    Layout.fillWidth: true
                    text: tagEditorBackend.statusText
                    color: "#9AA0A6"
                    wrapMode: Text.WordWrap
                    visible: text.length > 0
                }

                Item { Layout.fillHeight: true }
            }
        }
    }

    Connections {
        target: tagEditorBackend
        function onConfirmRequested(title, message) {
            confirmDialog.title = title
            confirmLabel.text = message
            confirmDialog.open()
        }
    }

    Dialog {
        id: confirmDialog
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 420
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: tagEditorBackend.confirmPendingAction()
        onRejected: tagEditorBackend.cancelPendingAction()

        Label {
            id: confirmLabel
            width: parent.width
            wrapMode: Text.WordWrap
        }
    }

    Window {
        id: metadataWindow
        visible: tagEditorBackend.metadataVisible
        title: tagEditorBackend.metadataTitle
        width: 700
        height: 600
        onClosing: tagEditorBackend.closeMetadataViewer()

        Rectangle {
            anchors.fill: parent
            color: "#1F1F1F"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Filter:"; color: "white" }
                    TextField {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        font.pixelSize: 15
                        placeholderText: "Type to filter tag names or values..."
                        text: tagEditorBackend.metadataFilter
                        onTextEdited: tagEditorBackend.metadataFilter = text
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: "#141414"
                    border.color: "#333"

                    ListView {
                        anchors.fill: parent
                        anchors.margins: 1
                        clip: true
                        model: tagEditorBackend.metadataRows
                        delegate: Rectangle {
                            width: ListView.view.width
                            height: 26
                            color: index % 2 === 0 ? "#1A1A1A" : "#141414"
                            required property var modelData
                            required property int index

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                Label {
                                    Layout.preferredWidth: 260
                                    text: modelData.tag
                                    color: "#E0E0E0"
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.value
                                    color: "#E0E0E0"
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
