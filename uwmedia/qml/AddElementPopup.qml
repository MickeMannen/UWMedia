// Overlay Designer "Add element" dialog - overlay_rework.md Phase 2. One
// popup for every element kind: a telemetry field (from the backend's
// addableFields - availableFields, which follows the dive currently
// rendered, plus presets: "depth_small_decimals" and
// "dive_time_small_seconds", the field with a small decimal part / small
// seconds, as on Garmin and Shearwater computers), a custom text label,
// the state badge, a tank icon, or the depth graph.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Popup {
    id: popup
    modal: true
    focus: true
    anchors.centerIn: Overlay.overlay
    width: 420
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

    property string kind: "text"

    onOpened: {
        kind = "text"
        customText.text = ""
        fieldCombo.currentIndex = Math.max(0, overlayDesignerBackend.addableFields.indexOf("depth"))
    }

    function add() {
        if (kind === "custom") {
            if (customText.text.trim().length === 0)
                return
            overlayDesignerBackend.addCustomLabel(customText.text)
        } else if (kind === "text" || kind === "tank_icon") {
            overlayDesignerBackend.addElement(fieldCombo.currentText, kind)
        } else {
            overlayDesignerBackend.addElement("", kind)
        }
        popup.close()
    }

    ColumnLayout {
        width: parent.width
        spacing: 10

        Label { text: "Add element"; font.bold: true; font.pixelSize: 16 }

        ButtonGroup { id: kindGroup }
        GridLayout {
            columns: 2
            RadioButton { text: "Telemetry field"; checked: popup.kind === "text"; ButtonGroup.group: kindGroup; onClicked: popup.kind = "text" }
            RadioButton { text: "Custom label"; checked: popup.kind === "custom"; ButtonGroup.group: kindGroup; onClicked: popup.kind = "custom" }
            RadioButton { text: "State badge"; checked: popup.kind === "badge"; ButtonGroup.group: kindGroup; onClicked: popup.kind = "badge" }
            RadioButton { text: "Tank icon"; checked: popup.kind === "tank_icon"; ButtonGroup.group: kindGroup; onClicked: popup.kind = "tank_icon" }
            RadioButton { text: "Depth graph"; checked: popup.kind === "graph"; ButtonGroup.group: kindGroup; onClicked: popup.kind = "graph" }
            RadioButton { text: "Tissue load bar"; checked: popup.kind === "tissue_bar"; ButtonGroup.group: kindGroup; onClicked: popup.kind = "tissue_bar" }
            RadioButton { text: "Ascent chevrons"; checked: popup.kind === "ascent_chevrons"; ButtonGroup.group: kindGroup; onClicked: popup.kind = "ascent_chevrons" }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: popup.kind === "text" || popup.kind === "tank_icon"
            Label { text: "Field" }
            ComboBox {
                id: fieldCombo
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                font.pixelSize: 14
                model: overlayDesignerBackend.addableFields
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: popup.kind === "custom"
            Label { text: "Text" }
            TextField {
                id: customText
                Layout.fillWidth: true
                placeholderText: "e.g. NDL, m, BAR"
                onAccepted: popup.add()
            }
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: "#A0A0A0"
            font.pixelSize: 12
            text: popup.kind === "badge" ? "Label + ceiling depth + countdown for safety stop / deco / clear, styled by the computer's hud_rules.json."
                : popup.kind === "graph" ? "Whole-dive depth profile with a playback cursor and deco-ceiling shading."
                : popup.kind === "tank_icon" ? "Colour fill (red / yellow / green by pressure), optionally with its own drawn outline."
                : popup.kind === "tissue_bar" ? "Garmin-style vertical nitrogen-loading bar (green / yellow / red) with a marker at the current load."
                : popup.kind === "ascent_chevrons" ? "Ascent-rate indicator in the template's brand style: Garmin - chevrons over a bar, green / yellow / red, the lower one on descent; Shearwater - six arrows, white / yellow / flashing red, one per 3 m/min (Perdix 2 manual p.12)."
                : (popup.kind === "text" && fieldCombo.currentText === "depth_small_decimals") ? "Depth with the decimal part in a small font, top-aligned with the metres (e.g. 12 and a small .3) - the way Garmin and Shearwater computers show it. Saved as a depth element with the Small suffix style set; adjust Suffix size in the inspector."
                : (popup.kind === "text" && fieldCombo.currentText === "dive_time_small_seconds") ? "Dive time with the seconds in a small font, top-aligned with the minutes (e.g. 32 and a small :15) - the way Garmin and Shearwater computers show it. Saved as a dive_time element with the Small suffix style set; adjust Suffix size in the inspector."
                : "New elements appear at the centre of the skin - drag them into place or type X/Y in the inspector."
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button { text: "Cancel"; onClicked: popup.close() }
            Button { text: "Add"; highlighted: true; onClicked: popup.add() }
        }
    }
}
