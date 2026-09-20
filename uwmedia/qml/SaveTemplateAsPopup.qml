// Overlay Designer "Save as…" dialog - overlay_rework.md Phase 3. Saves the
// current page as a NEW user-owned page (the only way to change a built-in
// template in release mode - see the ownership model in §5.1): under the
// same computer, another existing computer (so the page inherits that
// computer's colour/warning rules), or a brand-new Custom computer.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Popup {
    id: popup
    modal: true
    focus: true
    anchors.centerIn: Overlay.overlay
    width: 470
    padding: 16
    // Popups live in the window Overlay; follow the app window's theme
    // explicitly (the attached theme did not reach them - rendered light).
    Material.theme: window.Material.theme
    Material.accent: window.Material.accent
    background: Rectangle {
        color: "#2B2B2B"
        radius: 6
        border.color: "#3F3F3F"
        border.width: 1
    }

    property string error: ""
    // Import mode (Phase 5): same form, but finishes with finishImport() on
    // the zip staged by importZip() instead of saving the current page.
    property bool importMode: false
    property string suggestedName: ""
    readonly property var targets: overlayDesignerBackend.saveAsTargets
    readonly property bool newComputer: targetCombo.currentIndex === targets.length - 1
    readonly property var target: targets[Math.max(0, Math.min(targetCombo.currentIndex, targets.length - 1))]

    onOpened: {
        error = ""
        pageNameField.text = importMode ? suggestedName : ""
        computerNameField.text = ""
        targetCombo.currentIndex = importMode ? targets.length - 1 : overlayDesignerBackend.saveAsCurrentTargetIndex
        pageNameField.forceActiveFocus()
    }
    onClosed: {
        if (importMode)
            overlayDesignerBackend.cancelImport()
        importMode = false
        suggestedName = ""
    }

    function doSave() {
        const err = importMode
            ? overlayDesignerBackend.finishImport(targetCombo.currentIndex, computerNameField.text, pageNameField.text)
            : overlayDesignerBackend.saveAs(targetCombo.currentIndex, computerNameField.text, pageNameField.text)
        if (err.length > 0) {
            popup.error = err
        } else {
            importMode = false  // a successful import must not be cancelled by onClosed
            popup.close()
        }
    }

    ColumnLayout {
        width: parent.width
        spacing: 10

        Label { text: popup.importMode ? "Import as new page" : "Save as new page"; font.bold: true; font.pixelSize: 16 }

        GridLayout {
            columns: 2
            Layout.fillWidth: true
            columnSpacing: 12
            rowSpacing: 8

            Label { text: "Under" }
            ComboBox {
                id: targetCombo
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                font.pixelSize: 14
                model: popup.targets
                textRole: "label"
            }

            Label { text: "Computer name"; visible: popup.newComputer }
            TextField {
                id: computerNameField
                Layout.fillWidth: true
                visible: popup.newComputer
                placeholderText: "e.g. GoPro HUD"
                selectByMouse: true
            }

            Label { text: "Page name" }
            TextField {
                id: pageNameField
                Layout.fillWidth: true
                placeholderText: "e.g. My main screen"
                selectByMouse: true
                onAccepted: popup.doSave()
            }
        }

        Label {
            Layout.fillWidth: true
            color: "#A0A0A0"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            text: {
                const brand = popup.target ? popup.target.brand : ""
                const computer = popup.newComputer ? overlayDesignerBackend.slugFor(computerNameField.text) : (popup.target ? popup.target.computer : "")
                const page = overlayDesignerBackend.slugFor(pageNameField.text)
                return "Will be saved as " + brand + "/" + (computer || "…") + "/" + (page || "…")
                    + (popup.newComputer ? " (default colour rules)" : " (inherits this computer's colour and warning rules)")
            }
        }

        Label {
            Layout.fillWidth: true
            visible: popup.error.length > 0
            text: popup.error
            color: "#EF4444"
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button { text: "Cancel"; onClicked: popup.close() }
            Button { text: popup.importMode ? "Import" : "Save"; highlighted: true; onClicked: popup.doSave() }
        }
    }
}
