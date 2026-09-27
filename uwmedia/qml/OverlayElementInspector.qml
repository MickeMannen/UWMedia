// Overlay Designer inspector - overlay_rework.md Phase 2. Shows the selected
// element's attributes (type-specific form) or, when the skin is selected,
// the skin & placement attributes. Every edit goes through
// overlayDesignerBackend.setSelectedAttr / setSkinAttr; numeric fields apply
// on editingFinished and the backend parses/clamps.
//
// TextFields are fed through Binding elements (not plain `text:` bindings)
// so a user edit - which breaks a declarative binding - is still
// overwritten the next time the backend reports a new value (drag, nudge,
// undo).
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts

ColumnLayout {
    id: inspector
    spacing: 12

    readonly property var sel: overlayDesignerBackend.selectedElement
    readonly property var skin: overlayDesignerBackend.skinAttrs
    readonly property bool elementSelected: overlayDesignerBackend.selectedIndex >= 0
    readonly property bool skinSelected: overlayDesignerBackend.skinSelected
    readonly property string kind: elementSelected ? String(sel.kind) : ""
    readonly property bool sizedKind: kind === "tank_icon" || kind === "graph" || kind === "tissue_bar" || kind === "ascent_chevrons" || (kind === "badge" && String(sel.style) === "box")

    // Fixed field widths (2026-09-28, per the user): the fill-width fields
    // made the grid, and with it the whole right column, wider than the
    // window once an element was selected. Numbers fit 6 digits, text and
    // choice fields ~12-14 characters, a colour its "#RRGGBB".
    readonly property int numW: 70
    readonly property int textW: 150
    readonly property int fontW: 160
    readonly property int colorW: 84

    // --- reusable field widgets -------------------------------------------
    component NumField: TextField {
        id: numField
        property string attr
        property var value
        property bool forSkin: false
        Layout.preferredWidth: inspector.numW
        Layout.preferredHeight: 32
        leftPadding: 8
        rightPadding: 8
        font.pixelSize: 13
        selectByMouse: true
        Binding { target: numField; property: "text"; value: String(numField.value) }
        onEditingFinished: {
            if (forSkin)
                overlayDesignerBackend.setSkinAttr(attr, text)
            else
                overlayDesignerBackend.setSelectedAttr(attr, text)
        }
    }

    component ColorField: RowLayout {
        id: colorField
        property string attr
        property color value: "#FFFFFF"
        property bool forSkin: false
        spacing: 6
        function apply(text) {
            if (forSkin)
                overlayDesignerBackend.setSkinAttr(attr, text)
            else
                overlayDesignerBackend.setSelectedAttr(attr, text)
        }
        Rectangle {
            Layout.preferredWidth: 24; Layout.preferredHeight: 24; radius: 3
            color: colorField.value
            border.color: "#606060"
            MouseArea { anchors.fill: parent; onClicked: colorDialog.open() }
        }
        TextField {
            id: hexField
            Layout.preferredWidth: inspector.colorW
            Layout.preferredHeight: 32
            font.pixelSize: 13
            selectByMouse: true
            validator: RegularExpressionValidator { regularExpression: /^#[0-9a-fA-F]{6}$/ }
            Binding { target: hexField; property: "text"; value: String(colorField.value) }
            onEditingFinished: if (acceptableInput) colorField.apply(text)
        }
        ColorDialog {
            id: colorDialog
            selectedColor: colorField.value
            onAccepted: colorField.apply(String(selectedColor).substring(0, 7))
        }
    }

    // A folding group of inspector rows (2026-09-27, per the user: the
    // inspector outgrew the column). The header toggles it; the state is
    // kept for the session - fold what you are not using. Children go
    // into the 4-column grid, exactly as the old single grid laid them out.
    component Section: ColumnLayout {
        id: section
        property string title
        property bool open: true
        default property alias content: sectionGrid.data
        Layout.fillWidth: true
        spacing: 2
        ItemDelegate {
            Layout.fillWidth: true
            Layout.preferredHeight: 26
            text: (section.open ? "▾  " : "▸  ") + section.title
            font.pixelSize: 12
            font.bold: true
            onClicked: section.open = !section.open
        }
        GridLayout {
            id: sectionGrid
            Layout.fillWidth: true
            Layout.leftMargin: 8
            columns: 4
            columnSpacing: 6
            rowSpacing: 6
            visible: section.open
        }
    }

    component ChoiceRow: RowLayout {
        id: choiceRow
        property string attr
        property var options: []
        property var labels: []
        property string current
        spacing: 4
        Repeater {
            model: choiceRow.options
            delegate: Button {
                Layout.preferredWidth: 36
                Layout.preferredHeight: 30
                flat: true
                text: choiceRow.labels[index]
                highlighted: choiceRow.current === modelData
                font.pixelSize: 12
                onClicked: overlayDesignerBackend.setSelectedAttr(choiceRow.attr, modelData)
            }
        }
    }

    // --- nothing selected --------------------------------------------------
    Label {
        Layout.fillWidth: true
        visible: !inspector.elementSelected && !inspector.skinSelected
        text: "Click an element on the canvas (or pick one in the list) to edit it. Click the skin background to edit placement."
        wrapMode: Text.WordWrap
        color: "#909090"
        font.pixelSize: 12
    }

    // --- multi-selection: align / distribute (Phase 5) ----------------------
    Pane {
        Layout.fillWidth: true
        Material.elevation: 1
        visible: overlayDesignerBackend.selectionCount >= 2

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 6
            Label {
                text: overlayDesignerBackend.selectionCount + " elements selected"
                font.bold: true
                font.pixelSize: 14
            }
            RowLayout {
                spacing: 4
                Label { text: "Align"; Layout.preferredWidth: 64 }
                Repeater {
                    model: [["left", "⇤"], ["hcenter", "↔"], ["right", "⇥"], ["top", "⤒"], ["vcenter", "↕"], ["bottom", "⤓"]]
                    delegate: Button {
                        Layout.preferredWidth: 32
                        Layout.preferredHeight: 30
                        flat: true
                        text: modelData[1]
                        onClicked: overlayDesignerBackend.alignSelected(modelData[0])
                        ToolTip.text: "Align " + modelData[0]
                        ToolTip.visible: hovered
                    }
                }
            }
            RowLayout {
                spacing: 4
                Label { text: "Distribute"; Layout.preferredWidth: 64 }
                Button { Layout.preferredWidth: 36; Layout.preferredHeight: 30; flat: true; text: "⋯"; enabled: overlayDesignerBackend.selectionCount >= 3; onClicked: overlayDesignerBackend.distributeSelected("h"); ToolTip.text: "Distribute horizontally"; ToolTip.visible: hovered }
                Button { Layout.preferredWidth: 36; Layout.preferredHeight: 30; flat: true; text: "⋮"; enabled: overlayDesignerBackend.selectionCount >= 3; onClicked: overlayDesignerBackend.distributeSelected("v"); ToolTip.text: "Distribute vertically"; ToolTip.visible: hovered }
                Item { Layout.fillWidth: true }
                Button { flat: true; text: "Copy"; Layout.preferredWidth: 58; leftPadding: 6; rightPadding: 6; onClicked: overlayDesignerBackend.copySelected() }
                Button { flat: true; text: "Remove"; Layout.preferredWidth: 70; leftPadding: 6; rightPadding: 6; onClicked: overlayDesignerBackend.removeSelected() }
            }
            Label {
                Layout.fillWidth: true
                text: "Align moves the others onto the last-clicked element (the one with the label). The form below edits that element."
                color: "#909090"
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }
        }
    }

    // --- element inspector -------------------------------------------------
    Pane {
        Layout.fillWidth: true
        Material.elevation: 1
        visible: inspector.elementSelected

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    Layout.fillWidth: true
                    text: "Element · " + (inspector.kind === "tissue_bar" ? "tissue bar" : inspector.kind === "ascent_chevrons" ? "ascent chevrons" : inspector.kind)
                    font.bold: true
                    font.pixelSize: 14
                    elide: Text.ElideRight
                }
                ToolButton { text: "⤒"; Layout.preferredWidth: 30; onClicked: overlayDesignerBackend.sendToBack(); ToolTip.text: "Send to back (Shift-Cmd/Ctrl-[)"; ToolTip.visible: hovered }
                ToolButton { text: "▲"; Layout.preferredWidth: 30; onClicked: overlayDesignerBackend.moveSelectedLayer(-1); ToolTip.text: "Send backward (Cmd/Ctrl-[)"; ToolTip.visible: hovered }
                ToolButton { text: "▼"; Layout.preferredWidth: 30; onClicked: overlayDesignerBackend.moveSelectedLayer(1); ToolTip.text: "Bring forward (Cmd/Ctrl-])"; ToolTip.visible: hovered }
                ToolButton { text: "⤓"; Layout.preferredWidth: 30; onClicked: overlayDesignerBackend.bringToFront(); ToolTip.text: "Bring to front (Shift-Cmd/Ctrl-])"; ToolTip.visible: hovered }
                ToolButton { text: "⧉"; Layout.preferredWidth: 30; onClicked: overlayDesignerBackend.duplicateSelected(); ToolTip.text: "Duplicate (Cmd/Ctrl-D)"; ToolTip.visible: hovered }
                ToolButton { text: "🗑"; Layout.preferredWidth: 38; onClicked: overlayDesignerBackend.removeSelected(); ToolTip.text: "Remove (Delete)"; ToolTip.visible: hovered }
            }

            Section {
                title: "Element"
                visible: true
                // Display name (designer list label; saved as `label`)
                Label { text: "Name" }
                TextField {
                    id: nameField
                    Layout.columnSpan: 3
                    Layout.preferredWidth: inspector.textW
                    Layout.preferredHeight: 32
                    font.pixelSize: 13
                    placeholderText: "optional"
                    ToolTip.text: "Shown in the element list"
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    selectByMouse: true
                    Binding { target: nameField; property: "text"; value: String(inspector.sel.label) }
                    onEditingFinished: overlayDesignerBackend.setSelectedAttr("label", text)
                }

                // Field / custom text
                Label { text: inspector.sel.is_custom ? "Text" : "Field" }
                TextField {
                    id: customTextField
                    Layout.columnSpan: 3
                    Layout.preferredWidth: inspector.textW
                    Layout.preferredHeight: 32
                    font.pixelSize: 13
                    visible: inspector.sel.is_custom === true
                    selectByMouse: true
                    Binding { target: customTextField; property: "text"; value: String(inspector.sel.custom_text) }
                    onEditingFinished: overlayDesignerBackend.setSelectedAttr("custom_text", text)
                }
                ComboBox {
                    id: fieldCombo
                    Layout.columnSpan: 3
                    Layout.preferredWidth: inspector.textW
                    Layout.preferredHeight: 32
                    font.pixelSize: 13
                    popup.width: 240  // long field names stay readable in the list
                    visible: inspector.sel.is_custom !== true && (inspector.kind === "text" || inspector.kind === "tank_icon" || inspector.kind === "tissue_bar")
                    model: overlayDesignerBackend.availableFields
                    Binding {
                        target: fieldCombo; property: "currentIndex"
                        value: Math.max(0, overlayDesignerBackend.availableFields.indexOf(String(inspector.sel.field)))
                    }
                    onActivated: (index) => overlayDesignerBackend.setSelectedAttr("field", model[index])
                }
                Label {
                    Layout.columnSpan: 3
                    visible: inspector.sel.is_custom !== true && (inspector.kind === "badge" || inspector.kind === "graph")
                    text: String(inspector.sel.field)
                    color: "#A0A0A0"
                }

            }
            Section {
                title: "Position and size"
                visible: true
                // Position (native skin px)
                Label { text: "X" }
                NumField { attr: "x_px"; value: inspector.sel.x_px }
                Label { text: "Y" }
                NumField { attr: "y_px"; value: inspector.sel.y_px }

                // Text + badge typography
                Label { text: inspector.kind === "badge" ? "Label size" : "Size"; visible: inspector.kind === "text" || inspector.kind === "badge" }
                NumField { attr: "font_size"; value: inspector.sel.font_size; visible: inspector.kind === "text" || inspector.kind === "badge" }
                Label { text: inspector.kind === "badge" ? "Value size" : "Scale"; visible: inspector.kind === "text" || inspector.kind === "badge" }
                NumField {
                    attr: inspector.kind === "badge" ? "value_font_size" : "scale"
                    value: inspector.kind === "badge" ? inspector.sel.value_font_size : inspector.sel.scale
                    visible: inspector.kind === "text" || inspector.kind === "badge"
                }

                Label { text: "Quick size"; visible: inspector.kind === "text" || inspector.kind === "badge" }
                RowLayout {
                    Layout.columnSpan: 3
                    visible: inspector.kind === "text" || inspector.kind === "badge"
                    spacing: 4
                    Button { Layout.preferredWidth: 40; Layout.preferredHeight: 30; flat: true; text: "−"; onClicked: overlayDesignerBackend.resizeSelected(-1); ToolTip.text: "Shrink 5 % (or the − key on the canvas)"; ToolTip.visible: hovered }
                    Button { Layout.preferredWidth: 40; Layout.preferredHeight: 30; flat: true; text: "+"; onClicked: overlayDesignerBackend.resizeSelected(1); ToolTip.text: "Grow 5 % (or the + key on the canvas)"; ToolTip.visible: hovered }
                    Label { text: "5 % per step"; color: "#909090"; font.pixelSize: 11 }
                }

                // Tank icon + graph geometry, and the stop/deco box's own size
                // (a `style: "box"` badge - its label and value sizes are the text inside)
                Label { text: "Width"; visible: inspector.sizedKind }
                NumField { attr: "width"; value: inspector.sel.width; visible: inspector.sizedKind; ToolTip.text: inspector.kind === "badge" ? "Box width in skin px - the text inside follows Label size / Value size" : ""; ToolTip.visible: hovered && ToolTip.text.length > 0 }
                Label { text: "Height"; visible: inspector.sizedKind }
                NumField { attr: "height"; value: inspector.sel.height; visible: inspector.sizedKind }
                Label { text: "Up"; visible: inspector.kind === "ascent_chevrons" }
                NumField { attr: "up_count"; value: inspector.sel.up_count; visible: inspector.kind === "ascent_chevrons"; ToolTip.text: "Number of upward (ascent) chevrons"; ToolTip.visible: hovered }
                Label { text: "Down"; visible: inspector.kind === "ascent_chevrons" }
                NumField { attr: "down_count"; value: inspector.sel.down_count; visible: inspector.kind === "ascent_chevrons"; ToolTip.text: "Number of downward (descent) chevrons"; ToolTip.visible: hovered }
                CheckBox {
                    Layout.columnSpan: 4
                    text: "Divider bar"
                    visible: inspector.kind === "ascent_chevrons"
                    checked: inspector.sel.bar === true
                    onToggled: overlayDesignerBackend.setSelectedAttr("bar", checked)
                    ToolTip.text: "The white bar between the up and down chevrons (Garmin). A Perdix shows arrows only."
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                }
                Label { text: "Quick size"; visible: inspector.kind === "tank_icon" || inspector.kind === "graph" || inspector.kind === "tissue_bar" || inspector.kind === "ascent_chevrons" }
                RowLayout {
                    Layout.columnSpan: 3
                    visible: inspector.kind === "tank_icon" || inspector.kind === "graph" || inspector.kind === "tissue_bar" || inspector.kind === "ascent_chevrons"
                    spacing: 4
                    Button { Layout.preferredWidth: 40; Layout.preferredHeight: 30; flat: true; text: "−"; onClicked: overlayDesignerBackend.resizeSelected(-1); ToolTip.text: "Shrink width and height 5 % (or the − key)"; ToolTip.visible: hovered }
                    Button { Layout.preferredWidth: 40; Layout.preferredHeight: 30; flat: true; text: "+"; onClicked: overlayDesignerBackend.resizeSelected(1); ToolTip.text: "Grow width and height 5 % (or the + key)"; ToolTip.visible: hovered }
                    Label { text: "5 % per step"; color: "#909090"; font.pixelSize: 11 }
                }
                Label { text: "Radius"; visible: inspector.kind === "tank_icon" }
                NumField { Layout.columnSpan: 3; attr: "corner_radius"; value: inspector.sel.corner_radius; visible: inspector.kind === "tank_icon" }

            }
            Section {
                title: "Text"
                visible: inspector.kind === "text" || inspector.kind === "badge"
                Label { text: "Font"; visible: inspector.kind === "text" || inspector.kind === "badge" }
                ComboBox {
                    id: fontCombo
                    Layout.columnSpan: 3
                    Layout.preferredWidth: inspector.fontW
                    Layout.preferredHeight: 32
                    font.pixelSize: 13
                    popup.width: 260
                    visible: inspector.kind === "text" || inspector.kind === "badge"
                    model: overlayDesignerBackend.fontFamilies
                    Binding {
                        target: fontCombo; property: "currentIndex"
                        value: Math.max(0, overlayDesignerBackend.fontFamilies.indexOf(String(inspector.sel.font_family)))
                    }
                    onActivated: (index) => overlayDesignerBackend.setSelectedAttr("font_family", model[index])
                }
                Label { text: "Color"; visible: inspector.kind === "text" }
                ColorField { Layout.columnSpan: 3; attr: "color"; value: inspector.sel.color; visible: inspector.kind === "text" }

                // Small suffix: Garmin-style large "00" + small top-aligned ":00" / "12" + ".3"
                Label { text: "Small suffix"; visible: inspector.kind === "text" }
                ComboBox {
                    id: suffixCombo
                    Layout.columnSpan: 3
                    Layout.preferredWidth: inspector.textW
                    Layout.preferredHeight: 32
                    font.pixelSize: 13
                    visible: inspector.kind === "text"
                    model: overlayDesignerBackend.smallSuffixLabels
                    Binding {
                        target: suffixCombo; property: "currentIndex"
                        value: Math.max(0, overlayDesignerBackend.smallSuffixStyles.indexOf(String(inspector.sel.small_suffix)))
                    }
                    onActivated: (index) => overlayDesignerBackend.setSelectedAttr("small_suffix", overlayDesignerBackend.smallSuffixStyles[index])
                }
                Label { text: "Suffix size"; visible: inspector.kind === "text" && String(inspector.sel.small_suffix).length > 0 }
                NumField {
                    Layout.columnSpan: 3
                    attr: "small_suffix_scale"; value: inspector.sel.small_suffix_scale
                    visible: inspector.kind === "text" && String(inspector.sel.small_suffix).length > 0
                    ToolTip.text: "Fraction of the main font size (0.33 = one third)"
                    ToolTip.visible: hovered
                }

                Label { text: "Align"; visible: inspector.kind === "text" || inspector.kind === "badge" }
                ChoiceRow {
                    Layout.columnSpan: 3
                    visible: inspector.kind === "text" || inspector.kind === "badge"
                    attr: "align"; options: ["left", "center", "right"]; labels: ["L", "C", "R"]
                    current: String(inspector.sel.align)
                }
                Label { text: "V-align"; visible: inspector.kind === "text" || inspector.kind === "badge" }
                ChoiceRow {
                    Layout.columnSpan: 3
                    visible: inspector.kind === "text" || inspector.kind === "badge"
                    attr: "valign"; options: ["top", "middle", "bottom"]; labels: ["T", "M", "B"]
                    current: String(inspector.sel.valign)
                }
                // Vertical text (schema v2 `orientation`): stacked upright
                // letters, or the line turned to read up / down. Align and
                // V-align then place that vertical box on the anchor.
                Label { text: "Orientation"; visible: inspector.kind === "text" }
                ChoiceRow {
                    Layout.columnSpan: 3
                    visible: inspector.kind === "text"
                    attr: "orientation"; options: ["horizontal", "stacked", "up", "down"]; labels: ["H", "S", "↑", "↓"]
                    current: String(inspector.sel.orientation)
                    HoverHandler { id: orientationHover }
                    ToolTip.text: "H: horizontal. S: stacked, one upright letter under the other. ↑ / ↓: turned on its side, reading bottom-to-top / top-to-bottom."
                    ToolTip.visible: orientationHover.hovered
                    ToolTip.delay: 400
                }
                CheckBox {
                    Layout.columnSpan: 2
                    text: "Bold"
                    visible: inspector.kind === "text" || inspector.kind === "badge"
                    checked: inspector.sel.bold === true
                    onToggled: overlayDesignerBackend.setSelectedAttr("bold", checked)
                }
                CheckBox {
                    Layout.columnSpan: 2
                    text: "Black outline"
                    visible: inspector.kind === "text" || inspector.kind === "badge"
                    checked: inspector.sel.outline === true
                    onToggled: overlayDesignerBackend.setSelectedAttr("outline", checked)
                }

            }
            Section {
                title: "Tank icon"
                visible: inspector.kind === "tank_icon"
                // Tank icon style: upright fill (optionally with a drawn outline) or
                // Shearwater's horizontal segmented gauge (always draws its outline)
                Label { text: "Style"; visible: inspector.kind === "tank_icon" }
                ChoiceRow {
                    Layout.columnSpan: 3
                    visible: inspector.kind === "tank_icon"
                    attr: "style"; options: ["fill", "segments"]; labels: ["Fill", "Seg"]
                    current: String(inspector.sel.style)
                }
                Label { text: "Segments"; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                NumField { attr: "segments"; value: inspector.sel.segments; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                Label { text: "Gap"; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                NumField { attr: "segment_gap"; value: inspector.sel.segment_gap; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                Label { text: "Full at"; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                NumField { attr: "full_bar"; value: inspector.sel.full_bar; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments"; ToolTip.text: "Pressure (bar) at which every segment is lit"; ToolTip.visible: hovered }
                Label { text: "Outline"; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                ColorField { Layout.columnSpan: 3; attr: "outline_color"; value: inspector.sel.outline_color; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                Label { text: "Stroke"; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                NumField { attr: "outline_width"; value: inspector.sel.outline_width; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                Label { text: "Padding"; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }
                NumField { attr: "outline_gap"; value: inspector.sel.outline_gap; visible: inspector.kind === "tank_icon" && inspector.sel.style === "segments" }

                // Drawn outline (for skins whose image has no tank outline of its own)
                CheckBox {
                    Layout.columnSpan: 4
                    text: "Draw outline"
                    visible: inspector.kind === "tank_icon" && inspector.sel.style !== "segments"
                    checked: inspector.sel.draw_outline === true
                    onToggled: overlayDesignerBackend.setSelectedAttr("draw_outline", checked)
                    ToolTip.text: "Rounded rectangle + cap drawn around the fill, for skins without a baked tank outline"
                    ToolTip.visible: hovered
                }
                Label { text: "Outline"; visible: inspector.kind === "tank_icon" && inspector.sel.style !== "segments" && inspector.sel.draw_outline === true }
                ColorField {
                    Layout.columnSpan: 3; attr: "outline_color"; value: inspector.sel.outline_color
                    visible: inspector.kind === "tank_icon" && inspector.sel.style !== "segments" && inspector.sel.draw_outline === true
                }
                Label { text: "Stroke"; visible: inspector.kind === "tank_icon" && inspector.sel.style !== "segments" && inspector.sel.draw_outline === true }
                NumField { attr: "outline_width"; value: inspector.sel.outline_width; visible: inspector.kind === "tank_icon" && inspector.sel.style !== "segments" && inspector.sel.draw_outline === true }
                Label { text: "Gap"; visible: inspector.kind === "tank_icon" && inspector.sel.style !== "segments" && inspector.sel.draw_outline === true }
                NumField { attr: "outline_gap"; value: inspector.sel.outline_gap; visible: inspector.kind === "tank_icon" && inspector.sel.style !== "segments" && inspector.sel.draw_outline === true }

            }
            Section {
                title: "Tissue bar"
                visible: inspector.kind === "tissue_bar"
                Label { text: "Style"; visible: inspector.kind === "tissue_bar" }
                ChoiceRow {
                    Layout.columnSpan: 3
                    visible: inspector.kind === "tissue_bar"
                    attr: "style"; options: ["segments", "fill"]; labels: ["Seg", "Fill"]
                    current: String(inspector.sel.style)
                }
                Label { text: "Marker"; visible: inspector.kind === "tissue_bar" && inspector.sel.style !== "fill" }
                NumField { Layout.columnSpan: 3; attr: "marker_size"; value: inspector.sel.marker_size; visible: inspector.kind === "tissue_bar" && inspector.sel.style !== "fill"; ToolTip.text: "Radius of the white load marker"; ToolTip.visible: hovered }
                Label { text: "Frame"; visible: inspector.kind === "tissue_bar" && inspector.sel.style === "fill" }
                ColorField { Layout.columnSpan: 3; attr: "outline_color"; value: inspector.sel.outline_color; visible: inspector.kind === "tissue_bar" && inspector.sel.style === "fill" }
            }
            Section {
                title: "Graph colours and shading"
                visible: inspector.kind === "graph"
                Label { text: "Color"; visible: inspector.kind === "graph" }
                ColorField { Layout.columnSpan: 3; attr: "color"; value: inspector.sel.color; visible: inspector.kind === "graph" }
                Label { text: "Ceiling"; visible: inspector.kind === "graph" }
                ColorField { Layout.columnSpan: 3; attr: "ceiling_color"; value: inspector.sel.ceiling_color; visible: inspector.kind === "graph" }
                // Shading colour + opacity (2026-09-27, per the user: the
                // fixed tints were far too strong on footage). Opacities
                // are 0-1; 0 hides that area.
                Label { text: "Box"; visible: inspector.kind === "graph" }
                ColorField { Layout.columnSpan: 3; attr: "background_color"; value: inspector.sel.background_color; visible: inspector.kind === "graph" }
                Label { text: "Box opacity"; visible: inspector.kind === "graph" }
                NumField { attr: "background_opacity"; value: inspector.sel.background_opacity; visible: inspector.kind === "graph"; ToolTip.text: "The graph's background box and its border, 0 (none) to 1 (solid)"; ToolTip.visible: hovered }
                Item { Layout.columnSpan: 2; visible: inspector.kind === "graph" }
                Label { text: "Fill"; visible: inspector.kind === "graph" }
                ColorField { Layout.columnSpan: 3; attr: "fill_color"; value: inspector.sel.fill_color; visible: inspector.kind === "graph" }
                Label { text: "Fill opacity"; visible: inspector.kind === "graph" }
                NumField { attr: "fill_opacity"; value: inspector.sel.fill_opacity; visible: inspector.kind === "graph"; ToolTip.text: "Area under the profile line, 0 (none) to 1 (solid)"; ToolTip.visible: hovered }
                Label { text: "Ceiling opacity"; visible: inspector.kind === "graph" }
                NumField { attr: "ceiling_opacity"; value: inspector.sel.ceiling_opacity; visible: inspector.kind === "graph"; ToolTip.text: "The ceiling area (or, without Deco stops, the stop band), 0 to 1"; ToolTip.visible: hovered }
            }
            Section {
                title: "Graph options"
                visible: inspector.kind === "graph"
                CheckBox {
                    Layout.columnSpan: 4
                    text: "Deco stops"
                    visible: inspector.kind === "graph"
                    checked: inspector.sel.deco_stops === true
                    onToggled: overlayDesignerBackend.setSelectedAttr("deco_stops", checked)
                    ToolTip.text: "Shade each logged deco stop and the ceiling separately, kept on the graph after they clear"
                    ToolTip.visible: hovered
                }
                Label { text: "Stops"; visible: inspector.kind === "graph" && inspector.sel.deco_stops === true }
                ColorField {
                    Layout.columnSpan: 3; attr: "stops_color"; value: inspector.sel.stops_color
                    visible: inspector.kind === "graph" && inspector.sel.deco_stops === true
                }
                Label { text: "Stops opacity"; visible: inspector.kind === "graph" && inspector.sel.deco_stops === true }
                NumField { attr: "stops_opacity"; value: inspector.sel.stops_opacity; visible: inspector.kind === "graph" && inspector.sel.deco_stops === true; ToolTip.text: "The deco-stop steps, 0 to 1"; ToolTip.visible: hovered }
                Item { Layout.columnSpan: 2; visible: inspector.kind === "graph" && inspector.sel.deco_stops === true }
                CheckBox {
                    Layout.columnSpan: 4
                    text: "Reveal profile over time"
                    visible: inspector.kind === "graph"
                    checked: inspector.sel.reveal_profile === true
                    onToggled: overlayDesignerBackend.setSelectedAttr("reveal_profile", checked)
                    ToolTip.text: "Draw the depth line only up to the current time, instead of the whole dive"
                    ToolTip.visible: hovered
                }
                CheckBox {
                    Layout.columnSpan: 2
                    text: "Stop label"
                    visible: inspector.kind === "graph"
                    checked: inspector.sel.stop_label === true
                    onToggled: overlayDesignerBackend.setSelectedAttr("stop_label", checked)
                    ToolTip.text: "Current deco stop (or NDL) next to the cursor"
                    ToolTip.visible: hovered
                }
                Label { text: "Size"; visible: inspector.kind === "graph" && inspector.sel.stop_label === true }
                NumField { attr: "font_size"; value: inspector.sel.font_size; visible: inspector.kind === "graph" && inspector.sel.stop_label === true }
                Item { Layout.columnSpan: 2; visible: inspector.kind === "graph" && inspector.sel.stop_label !== true }
                Label { text: "Marker"; visible: inspector.kind === "graph" }
                ComboBox {
                    id: markerCombo
                    Layout.columnSpan: 3
                    Layout.preferredWidth: inspector.textW
                    Layout.preferredHeight: 32
                    font.pixelSize: 13
                    visible: inspector.kind === "graph"
                    model: overlayDesignerBackend.markerStyles
                    Binding {
                        target: markerCombo; property: "currentIndex"
                        value: Math.max(0, overlayDesignerBackend.markerStyles.indexOf(String(inspector.sel.marker_style)))
                    }
                    onActivated: (index) => overlayDesignerBackend.setSelectedAttr("marker_style", model[index])
                }
                Label { text: "Size"; visible: inspector.kind === "graph" }
                NumField { attr: "marker_size"; value: inspector.sel.marker_size; visible: inspector.kind === "graph" }
            }
        }
    }

    // --- skin & placement inspector -----------------------------------------
    Pane {
        Layout.fillWidth: true
        Material.elevation: 1
        visible: inspector.skinSelected

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 8

            Label { text: "Skin and placement"; font.bold: true; font.pixelSize: 14 }
            Label {
                Layout.fillWidth: true
                text: inspector.skin.type === "shape"
                    ? "Rounded rectangle " + inspector.skin.width + "×" + inspector.skin.height + " px"
                    : "Image " + inspector.skin.native_width + "×" + inspector.skin.native_height + " px"
                color: "#A0A0A0"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 4
                columnSpacing: 8
                rowSpacing: 6

                // image skins
                Label { text: "Scale"; visible: inspector.skin.type !== "shape" }
                NumField { forSkin: true; attr: "scale"; value: inspector.skin.scale; visible: inspector.skin.type !== "shape" }
                Label { text: "Opacity"; visible: inspector.skin.type !== "shape" }
                NumField { forSkin: true; attr: "opacity"; value: inspector.skin.opacity; visible: inspector.skin.type !== "shape" }
                Button {
                    Layout.columnSpan: 4
                    text: "Replace image…"
                    visible: inspector.skin.type !== "shape"
                    onClicked: overlayDesignerBackend.replaceSkinImage()
                }

                // shape skins
                Label { text: "Width"; visible: inspector.skin.type === "shape" }
                NumField { forSkin: true; attr: "width"; value: inspector.skin.width; visible: inspector.skin.type === "shape" }
                Label { text: "Height"; visible: inspector.skin.type === "shape" }
                NumField { forSkin: true; attr: "height"; value: inspector.skin.height; visible: inspector.skin.type === "shape" }
                Label { text: "Radius"; visible: inspector.skin.type === "shape" }
                NumField { forSkin: true; attr: "corner_radius"; value: inspector.skin.corner_radius; visible: inspector.skin.type === "shape" }
                Label { text: "Opacity"; visible: inspector.skin.type === "shape" }
                NumField { forSkin: true; attr: "opacity"; value: inspector.skin.opacity; visible: inspector.skin.type === "shape" }
                Label { text: "Color"; visible: inspector.skin.type === "shape" }
                ColorField { Layout.columnSpan: 3; forSkin: true; attr: "color"; value: inspector.skin.color; visible: inspector.skin.type === "shape" }

                // placement (both)
                Label { text: "Anchor" }
                ComboBox {
                    id: anchorCombo
                    Layout.columnSpan: 3
                    Layout.preferredWidth: inspector.textW
                    Layout.preferredHeight: 32
                    font.pixelSize: 13
                    model: overlayDesignerBackend.anchorList
                    Binding { target: anchorCombo; property: "currentIndex"; value: Number(inspector.skin.anchor_index) }
                    onActivated: (index) => overlayDesignerBackend.setSkinAttr("anchor", model[index])
                }
                Label { text: "Offset X" }
                NumField { forSkin: true; attr: "ref_offset_x"; value: inspector.skin.ref_offset_x }
                Label { text: "Offset Y" }
                NumField { forSkin: true; attr: "ref_offset_y"; value: inspector.skin.ref_offset_y }
            }

            Label {
                Layout.fillWidth: true
                text: "Offsets are in design pixels (1920-wide frame) from the anchor corner. In Frame preview you can also drag the skin."
                color: "#909090"
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }
        }
    }
}
