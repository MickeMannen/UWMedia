// Overlay Designer "New custom template" wizard - overlay_rework.md Phase 4
// (decision Q8). Creates an EMPTY page from a background of the user's
// choosing - an arbitrary image (a dive-computer screenshot, a HUD graphic,
// a transparent PNG) or a rounded-rectangle shape - either under an
// existing computer (so it inherits that computer's colour/warning rules)
// or under a brand-new Custom computer with a chosen rules profile. Fields
// are then added and placed exactly like on a built-in template.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Popup {
    id: popup
    modal: true
    focus: true
    anchors.centerIn: Overlay.overlay
    width: 540
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
    property string backgroundKind: "image"
    property string imagePath: ""
    readonly property var targets: overlayDesignerBackend.saveAsTargets
    readonly property bool newComputer: targetCombo.currentIndex === targets.length - 1
    readonly property var target: targets[Math.max(0, Math.min(targetCombo.currentIndex, targets.length - 1))]

    onOpened: {
        error = ""
        backgroundKind = "image"
        imagePath = ""
        pageNameField.text = "Main"
        computerNameField.text = ""
        widthField.text = "400"
        heightField.text = "200"
        colorField.text = "#000000"
        rulesCombo.currentIndex = 0
        targetCombo.currentIndex = targets.length - 1
        computerNameField.forceActiveFocus()
    }

    function create() {
        const err = overlayDesignerBackend.createCustomTemplate(
            targetCombo.currentIndex, computerNameField.text, pageNameField.text,
            backgroundKind, imagePath, rulesCombo.currentText,
            Number(widthField.text), Number(heightField.text), colorField.text)
        if (err.length > 0)
            popup.error = err
        else
            popup.close()
    }

    ColumnLayout {
        width: parent.width
        spacing: 10

        Label { text: "New custom template"; font.bold: true; font.pixelSize: 16 }

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

            Label { text: "Colour rules"; visible: popup.newComputer }
            ComboBox {
                id: rulesCombo
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                font.pixelSize: 14
                visible: popup.newComputer
                model: overlayDesignerBackend.rulesProfiles
            }

            Label { text: "Page name" }
            TextField {
                id: pageNameField
                Layout.fillWidth: true
                placeholderText: "e.g. Main"
                selectByMouse: true
            }

            Label { text: "Background" }
            RowLayout {
                ButtonGroup { id: kindGroup }
                RadioButton { text: "Image"; checked: popup.backgroundKind === "image"; ButtonGroup.group: kindGroup; onClicked: popup.backgroundKind = "image" }
                RadioButton { text: "Shape"; checked: popup.backgroundKind === "shape"; ButtonGroup.group: kindGroup; onClicked: popup.backgroundKind = "shape" }
            }

            Label { text: "Image file"; visible: popup.backgroundKind === "image" }
            RowLayout {
                Layout.fillWidth: true
                visible: popup.backgroundKind === "image"
                TextField {
                    Layout.fillWidth: true
                    readOnly: true
                    text: popup.imagePath
                    placeholderText: "PNG, JPEG, WebP or BMP - PNG with transparency works best"
                }
                Button {
                    text: "Browse…"
                    onClicked: {
                        const chosen = overlayDesignerBackend.browseImageFile()
                        if (chosen.length > 0)
                            popup.imagePath = chosen
                    }
                }
            }

            Label { text: "Size (px)"; visible: popup.backgroundKind === "shape" }
            RowLayout {
                visible: popup.backgroundKind === "shape"
                TextField {
                    id: widthField
                    Layout.preferredWidth: 80
                    selectByMouse: true
                    validator: IntValidator { bottom: 1; top: 4000 }
                }
                Label { text: "×" }
                TextField {
                    id: heightField
                    Layout.preferredWidth: 80
                    selectByMouse: true
                    validator: IntValidator { bottom: 1; top: 4000 }
                }
                Label { text: "Colour" }
                TextField {
                    id: colorField
                    Layout.preferredWidth: 100
                    validator: RegularExpressionValidator { regularExpression: /^#[0-9a-fA-F]{6}$/ }
                    selectByMouse: true
                }
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
                return "Creates " + brand + "/" + (computer || "…") + "/" + (page || "…")
                    + (popup.newComputer ? "" : " (inherits this computer's colour and warning rules)")
                    + ". An image background is copied in and scaled to fit; add fields afterwards with + Add."
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
            Button { text: "Create"; highlighted: true; onClicked: popup.create() }
        }
    }
}
