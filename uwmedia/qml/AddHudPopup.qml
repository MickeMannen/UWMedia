// Add Overlay picker - qml_development.md Phase 1 (Pass 1). QML Popup equivalent
// of uwmedia/pages/add_hud_dialog.py's AddHudDialog (kept as
// reference only) - brand/computer/page cascade. No Location preset any
// more - overlays are freely draggable once placed (Pass 2's 4-corner
// resize/move), so a placement preset up front was redundant; every new
// overlay seeds at "Bottom Left" internally (colorBackend.confirmAddHud).
// Custom-path escape hatch deliberately deferred, see
// backends/color_backend.py's own module docstring.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: popup
    modal: true
    focus: true
    anchors.centerIn: Overlay.overlay
    width: 380

    ColumnLayout {
        width: parent.width
        spacing: 10

        Label { text: "Add Overlay"; font.bold: true; font.pixelSize: 16 }

        GridLayout {
            columns: 2
            Layout.fillWidth: true
            columnSpacing: 12
            rowSpacing: 8

            Label { text: "Overlay brand" }
            ComboBox {
                id: brandCombo
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                font.pixelSize: 15
                model: colorBackend.addHudBrandList
                onActivated: (index) => colorBackend.onAddHudBrandSelected(model[index])
            }

            Label {
                text: "Dive computer"
                visible: colorBackend.addHudComputerVisible
            }
            ComboBox {
                id: computerCombo
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                font.pixelSize: 15
                visible: colorBackend.addHudComputerVisible
                model: colorBackend.addHudComputerList
                onActivated: (index) => colorBackend.onAddHudComputerSelected(model[index])
            }

            Label { text: "Page" }
            ComboBox {
                id: pageCombo
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                font.pixelSize: 15
                model: colorBackend.addHudPageList
                onActivated: (index) => colorBackend.onAddHudPageSelected(model[index])
            }
        }

        Label {
            Layout.fillWidth: true
            visible: colorBackend.addHudError.length > 0
            text: colorBackend.addHudError
            color: "#EF4444"
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button {
                text: "Cancel"
                onClicked: popup.close()
            }
            Button {
                text: "Add"
                highlighted: true
                onClicked: {
                    if (colorBackend.confirmAddHud())
                        popup.close()
                }
            }
        }
    }
}
