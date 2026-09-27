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

    readonly property string helpText:
        "<b>1. Set the scale.</b> Enter the deepest depth you plan to reach and roughly how long "
        + "the dive will last. This fixes the chart's axes so a click maps to a time and a depth. "
        + "Both can be changed later under Dive settings, and the time axis grows automatically "
        + "when you place points near its end.<br><br>"
        + "<b>2. Click in the chart to place waypoints.</b> Time snaps to whole minutes and depth to "
        + "whole metres. Between two waypoints the diver moves at the default descent/ascent rate, "
        + "then holds the new depth until the next waypoint's time.<br><br>"
        + "<b>3. Edit on the chart.</b> Drag a waypoint to move it, right-click it to delete it, or "
        + "click it to load it into the Waypoints editor. Hover over the profile to see time, depth, "
        + "gas, PO2, NDL or deco stop, TTS, CNS and tank pressure at that point. The line is drawn in "
        + "each gas's colour (click a colour swatch in the Gases panel to change it) and the grey "
        + "shaded bands show the planned deco stops (darker = longer stop).<br><br>"
        + "<b>4. Gases by depth.</b> In the Gases panel give each gas the depth range and phase it is "
        + "used in, e.g. Air (any), EAN50 0-21 m Ascent/deco, O2 0-6 m Ascent/deco. Each waypoint then "
        + "gets the gas covering its depth automatically - deco gases only on the way up (after the "
        + "deepest point). A gas is never auto-picked deeper than its MOD, which follows your own "
        + "Max PO2 bottom/deco under Dive settings (the table's MOD column uses the deco PO2 for "
        + "Ascent/deco gases). A gas without a range is the fallback. Pick a specific gas in the "
        + "Waypoints editor to override a waypoint.<br><br>"
        + "<b>5. End the dive.</b> Press End dive to ascend from the last waypoint at the default "
        + "ascent rate: a 3 m / 3 min safety stop when no deco is needed, otherwise the deco stops "
        + "for your GF settings (3 m levels, whole minutes), switching to each deco gas as soon as "
        + "its range and MOD allow, with a 1 min hold at each gas switch (counted as part of a "
        + "deco stop at the same depth).<br><br>"
        + "<b>6. Dive type.</b> Open circuit breathes each gas from its own tank. Sidemount breathes a "
        + "gas ticked \"Sidemount pair\" from two tanks, left and right, switching side whenever the "
        + "one in use gets the set pressure below the other. CCR makes the gas ticked \"Diluent\" the "
        + "loop, held at the low setpoint above the switch depth and the high one below it, with an O2 "
        + "cylinder drawn at a metabolic rate; every other gas is open-circuit bailout, only used where "
        + "you pick it for a waypoint.<br><br>"
        + "<b>7. Save log.</b> Saves the profile as UDDF, Garmin FIT or Subsurface XML, logged as if by "
        + "the dive computer chosen under Log details (FIT needs a Garmin). Set the start date and time "
        + "to match your photos and videos - left blank, the time of saving is used."

    // Chart click made before the scale was defined - placed once the
    // scale dialog is accepted.
    property real pendingClickX: -1
    property real pendingClickY: -1

    // Not a dive planner - this page only makes synthetic logs to drive
    // overlay rendering, and must say so where it can't be missed.
    Rectangle {
        id: testDataBanner
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 20
        anchors.bottomMargin: 0
        height: bannerText.implicitHeight + 16
        color: "#3B0D0D"
        border.color: "#EF4444"
        border.width: 2
        radius: 4

        Label {
            id: bannerText
            anchors.fill: parent
            anchors.margins: 8
            text: "⚠ DO NOT USE THIS FOR DIVE PLANNING - THIS IS FOR TEST DATA FOR OVERLAYS ⚠"
            color: "#EF4444"
            font.bold: true
            font.pixelSize: 16
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
        }
    }

    RowLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: testDataBanner.bottom
        anchors.bottom: parent.bottom
        anchors.margins: 20
        anchors.topMargin: 12
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

                            Label { text: "Dive type" }
                            ComboBox {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: diveProfileBackend.diveTypeList
                                currentIndex: model.indexOf(diveProfileBackend.diveTypeLabel)
                                onActivated: (index) => diveProfileBackend.onDiveTypeSelected(model[index])
                            }

                            Label { text: "GF Low/High" }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    placeholderText: "low"
                                    inputMethodHints: Qt.ImhDigitsOnly
                                    text: diveProfileBackend.gfLowText
                                    onTextEdited: diveProfileBackend.gfLowText = text
                                }
                                Label { text: "/" }
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    placeholderText: "high"
                                    inputMethodHints: Qt.ImhDigitsOnly
                                    text: diveProfileBackend.gfHighText
                                    onTextEdited: diveProfileBackend.gfHighText = text
                                }
                            }
                            Label {
                                Layout.columnSpan: 2
                                Layout.fillWidth: true
                                text: diveProfileBackend.gfErrorText
                                color: "#EF4444"
                                wrapMode: Text.WordWrap
                                visible: text.length > 0
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

                            Label { text: "SAC rate (L/min)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "20"
                                text: diveProfileBackend.sacText
                                onTextEdited: diveProfileBackend.sacText = text
                            }

                            Label { text: "Max PO2 bottom (bar)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "1.4"
                                text: diveProfileBackend.bottomPo2Text
                                onTextEdited: diveProfileBackend.bottomPo2Text = text
                            }

                            Label { text: "Max PO2 deco (bar)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "1.6"
                                text: diveProfileBackend.decoPo2Text
                                onTextEdited: diveProfileBackend.decoPo2Text = text
                            }

                            Label { text: "Setpoint low/high"; visible: diveProfileBackend.isCcr }
                            RowLayout {
                                Layout.fillWidth: true
                                visible: diveProfileBackend.isCcr
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    placeholderText: "0.7"
                                    text: diveProfileBackend.ccrLowSetpointText
                                    onTextEdited: diveProfileBackend.ccrLowSetpointText = text
                                }
                                Label { text: "/" }
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    placeholderText: "1.3"
                                    text: diveProfileBackend.ccrHighSetpointText
                                    onTextEdited: diveProfileBackend.ccrHighSetpointText = text
                                }
                            }
                            Label {
                                Layout.columnSpan: 2
                                Layout.fillWidth: true
                                text: diveProfileBackend.ccrErrorText
                                color: "#EF4444"
                                wrapMode: Text.WordWrap
                                visible: diveProfileBackend.isCcr && text.length > 0
                            }

                            Label { text: "SP switch depth (m)"; visible: diveProfileBackend.isCcr }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                visible: diveProfileBackend.isCcr
                                placeholderText: "6"
                                text: diveProfileBackend.ccrSwitchDepthText
                                onTextEdited: diveProfileBackend.ccrSwitchDepthText = text
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: "Low setpoint shallower than this, high setpoint at and below it"
                            }

                            Label { text: "O2 cylinder (L / bar)"; visible: diveProfileBackend.isCcr }
                            RowLayout {
                                Layout.fillWidth: true
                                visible: diveProfileBackend.isCcr
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    placeholderText: "3"
                                    text: diveProfileBackend.ccrO2SizeText
                                    onTextEdited: diveProfileBackend.ccrO2SizeText = text
                                }
                                Label { text: "/" }
                                TextField {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 15
                                    placeholderText: "200"
                                    text: diveProfileBackend.ccrO2StartText
                                    onTextEdited: diveProfileBackend.ccrO2StartText = text
                                }
                            }

                            Label { text: "Switch tanks every (bar)"; visible: diveProfileBackend.isSidemount }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                visible: diveProfileBackend.isSidemount
                                placeholderText: "30"
                                text: diveProfileBackend.sidemountSwitchText
                                onTextEdited: diveProfileBackend.sidemountSwitchText = text
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: "Switch to the other tank once the one in use is this far below it"
                            }

                            Label { text: "Max depth (m)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "chart scale"
                                text: diveProfileBackend.maxDepthText
                                onTextEdited: diveProfileBackend.maxDepthText = text
                            }

                            Label { text: "Planned runtime (min)" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "chart scale"
                                text: diveProfileBackend.runtimeText
                                onTextEdited: diveProfileBackend.runtimeText = text
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
                        Label { text: "Log details"; font.bold: true; font.pixelSize: 14 }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            columnSpacing: 12
                            rowSpacing: 8

                            Label { text: "Dive computer" }
                            ComboBox {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                model: diveProfileBackend.computerList
                                currentIndex: model.indexOf(diveProfileBackend.computerLabel)
                                onActivated: (index) => diveProfileBackend.onComputerSelected(model[index])
                            }

                            Label { text: "Serial number" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                inputMethodHints: Qt.ImhDigitsOnly
                                text: diveProfileBackend.serialText
                                onTextEdited: diveProfileBackend.serialText = text
                            }

                            Label { text: "Start" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "YYYY-MM-DD HH:MM (blank = now)"
                                text: diveProfileBackend.startTimeText
                                onTextEdited: diveProfileBackend.startTimeText = text
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: "Local date and time the dive starts - set it to match your photos and videos"
                            }

                            Label {
                                Layout.columnSpan: 2
                                Layout.fillWidth: true
                                text: diveProfileBackend.logErrorText
                                color: "#EF4444"
                                wrapMode: Text.WordWrap
                                visible: text.length > 0
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
                                Item { Layout.preferredWidth: 16 }
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
                                    // Highlight follows the backend's selection, not ListView's
                                    // currentIndex (which a model reset moves back to row 0).
                                    color: index === diveProfileBackend.selectedGasRow ? "#2A3F5F"
                                           : (index % 2 === 0 ? "#1A1A1A" : "#141414")
                                    required property var modelData
                                    required property int index
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: diveProfileBackend.selectGasRow(gasRow.index)
                                    }
                                    RowLayout {
                                        anchors.fill: parent
                                        Rectangle {
                                            Layout.preferredWidth: 16
                                            Layout.preferredHeight: 16
                                            Layout.leftMargin: 2
                                            radius: 3
                                            color: diveProfileBackend.gasColors[gasRow.index] || "transparent"
                                            border.color: "#606060"
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: colorPopup.openFor(gasRow.index, parent)
                                            }
                                            ToolTip.visible: swatchHover.hovered
                                            ToolTip.text: "Change line colour"
                                            HoverHandler { id: swatchHover }
                                        }
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
                                currentIndex: model.indexOf(diveProfileBackend.gasType)
                                onActivated: (index) => diveProfileBackend.onGasTypeSelected(model[index])
                            }
                            Rectangle {
                                id: editorSwatch
                                Layout.preferredWidth: 34
                                Layout.preferredHeight: 34
                                radius: 4
                                color: diveProfileBackend.gasColor
                                border.color: "#606060"
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: colorPopup.openFor(-1, editorSwatch)
                                }
                                ToolTip.visible: editorSwatchHover.hovered
                                ToolTip.text: "Line colour for this gas"
                                HoverHandler { id: editorSwatchHover }
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
                            Layout.fillWidth: true
                            Label { text: "Volume (L)" }
                            TextField {
                                Layout.preferredWidth: 60
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "11.1"
                                text: diveProfileBackend.gasVolumeText
                                onTextEdited: diveProfileBackend.gasVolumeText = text
                            }
                            Label { text: "Start (bar)" }
                            TextField {
                                Layout.preferredWidth: 60
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "207"
                                text: diveProfileBackend.gasStartPressureText
                                onTextEdited: diveProfileBackend.gasStartPressureText = text
                            }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: diveProfileBackend.isCcr || diveProfileBackend.isSidemount
                            CheckBox {
                                text: "Diluent (the loop)"
                                visible: diveProfileBackend.isCcr
                                checked: diveProfileBackend.gasDiluent
                                onToggled: diveProfileBackend.gasDiluent = checked
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: "Unticked gases are open-circuit bailout"
                            }
                            CheckBox {
                                text: "Sidemount pair (left/right)"
                                visible: diveProfileBackend.isSidemount
                                checked: diveProfileBackend.gasSidemountPair
                                onToggled: diveProfileBackend.gasSidemountPair = checked
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: "Breathed from two tanks, <tank>L and <tank>R, each with this volume and start pressure"
                            }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Use from" }
                            TextField {
                                Layout.preferredWidth: 50
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "0"
                                text: diveProfileBackend.gasMinDepthText
                                onTextEdited: diveProfileBackend.gasMinDepthText = text
                            }
                            Label { text: "to" }
                            TextField {
                                Layout.preferredWidth: 50
                                Layout.preferredHeight: 34
                                font.pixelSize: 15
                                placeholderText: "∞"
                                text: diveProfileBackend.gasMaxDepthText
                                onTextEdited: diveProfileBackend.gasMaxDepthText = text
                            }
                            Label { text: "m" }
                            ComboBox {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 13
                                model: diveProfileBackend.gasPhaseList
                                currentIndex: model.indexOf(diveProfileBackend.gasPhaseLabel)
                                onActivated: (index) => diveProfileBackend.onGasPhaseSelected(model[index])
                            }
                        }
                        RowLayout {
                            spacing: 8
                            // Update edits the selected row; New deselects so Add
                            // creates a new gas.
                            Button {
                                text: diveProfileBackend.selectedGasRow >= 0 ? "Update" : "Add"
                                highlighted: true
                                onClicked: diveProfileBackend.addGas()
                            }
                            Button {
                                text: "New"
                                enabled: diveProfileBackend.selectedGasRow >= 0
                                onClicked: diveProfileBackend.newGas()
                            }
                            Button {
                                text: "Remove"
                                enabled: diveProfileBackend.selectedGasRow >= 0
                                onClicked: diveProfileBackend.removeGasAtRow(diveProfileBackend.selectedGasRow)
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
                                            // Column 2 is the gas - drawn in its line colour.
                                            delegate: Label {
                                                required property string modelData
                                                required property int index
                                                readonly property bool isGas: index === 2
                                                Layout.fillWidth: true
                                                text: isGas ? "● " + modelData : modelData
                                                color: isGas ? (diveProfileBackend.waypointGasColors[wpRow.index] || "#E0E0E0")
                                                             : "#E0E0E0"
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
                                model: diveProfileBackend.wpGasChoices
                                currentIndex: Math.max(0, model.indexOf(diveProfileBackend.wpGasText))
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

            RowLayout {
                Layout.preferredWidth: 700
                Label {
                    Layout.fillWidth: true
                    text: "Click to add a waypoint · drag a point to move it · right-click to delete · hover for NDL/PO2"
                    color: "#9AA0A6"
                    elide: Text.ElideRight
                }
                Button {
                    text: "How it works"
                    flat: true
                    onClicked: helpDialog.open()
                }
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

                // Gesture split: a short left click on empty space adds a
                // waypoint, press on a waypoint + drag moves it, drag on
                // empty space scrubs, right-click on a waypoint deletes it.
                MouseArea {
                    id: chartMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    hoverEnabled: true
                    readonly property real dragThreshold: 4
                    property int dragRow: -1
                    property int hoverRow: -1
                    property real pressX: 0
                    property real pressY: 0
                    property bool moved: false
                    property real hoverX: 0
                    property real hoverY: 0
                    cursorShape: dragRow >= 0 ? Qt.ClosedHandCursor
                                 : hoverRow >= 0 ? Qt.OpenHandCursor : Qt.CrossCursor

                    onPressed: (mouse) => {
                        if (mouse.button === Qt.RightButton) {
                            const row = diveProfileBackend.waypointIndexAt(mouse.x, mouse.y)
                            if (row >= 0)
                                diveProfileBackend.removeWaypointAtRow(row)
                            hoverRow = -1
                            return
                        }
                        pressX = mouse.x
                        pressY = mouse.y
                        moved = false
                        dragRow = diveProfileBackend.waypointIndexAt(mouse.x, mouse.y)
                    }
                    onPositionChanged: (mouse) => {
                        hoverX = mouse.x
                        hoverY = mouse.y
                        if (!(pressedButtons & Qt.LeftButton)) {
                            hoverRow = diveProfileBackend.waypointIndexAt(mouse.x, mouse.y)
                            diveProfileBackend.onScrub(mouse.x)
                            return
                        }
                        if (!moved && Math.hypot(mouse.x - pressX, mouse.y - pressY) > dragThreshold)
                            moved = true
                        if (!moved)
                            return
                        if (dragRow >= 0)
                            diveProfileBackend.moveWaypoint(dragRow, mouse.x, mouse.y)
                        else
                            diveProfileBackend.onScrub(mouse.x)
                    }
                    onReleased: (mouse) => {
                        if (mouse.button !== Qt.LeftButton)
                            return
                        if (dragRow >= 0 && moved) {
                            diveProfileBackend.dropWaypoint(dragRow)
                        } else if (dragRow >= 0) {
                            wpListView.currentIndex = dragRow
                            diveProfileBackend.selectWaypointRow(dragRow)
                        } else if (!moved) {
                            if (diveProfileBackend.scaleDefined) {
                                diveProfileBackend.addWaypointAt(mouse.x, mouse.y)
                            } else {
                                root.pendingClickX = mouse.x
                                root.pendingClickY = mouse.y
                                scaleDialog.open()
                            }
                        }
                        dragRow = -1
                    }
                    onExited: {
                        hoverRow = -1
                        diveProfileBackend.clearCursor()
                    }
                }

                // Hover readout for the profile point under the mouse
                // (DiveProfileBackend.cursorInfo), kept inside the chart.
                Rectangle {
                    id: hoverBox
                    visible: chartMouse.containsMouse && chartMouse.dragRow < 0
                             && diveProfileBackend.cursorInfo.length > 0
                    width: hoverGrid.implicitWidth + 16
                    height: hoverGrid.implicitHeight + 12
                    x: Math.max(0, chartMouse.hoverX + 16 + width > parent.width
                                   ? chartMouse.hoverX - 16 - width : chartMouse.hoverX + 16)
                    y: Math.max(0, Math.min(parent.height - height, chartMouse.hoverY - height / 2))
                    color: "#E6111827"
                    radius: 4
                    border.color: "#4B5563"

                    ColumnLayout {
                        id: hoverGrid
                        anchors.centerIn: parent
                        spacing: 2
                        Repeater {
                            model: diveProfileBackend.cursorInfo
                            delegate: RowLayout {
                                required property var modelData
                                spacing: 10
                                Label {
                                    Layout.preferredWidth: 64
                                    text: modelData.label
                                    color: "#9CA3AF"
                                    font.pixelSize: 12
                                }
                                Label {
                                    text: modelData.value
                                    color: modelData.color
                                    font.pixelSize: 12
                                    font.bold: modelData.label === "Gas"
                                }
                            }
                        }
                    }
                }
            }

            Label {
                Layout.preferredWidth: 700
                text: diveProfileBackend.statusText
                color: diveProfileBackend.statusIsError ? "#EF4444" : "#9AA0A6"
                wrapMode: Text.WordWrap
            }

            RowLayout {
                spacing: 8
                Button {
                    Layout.preferredWidth: 200
                    text: "End dive"
                    enabled: diveProfileBackend.waypointRows.length > 0
                    ToolTip.visible: hovered
                    ToolTip.delay: 500
                    ToolTip.text: "Ascend from the last waypoint: 3m/3min safety stop if no deco is needed, otherwise the deco stops"
                    onClicked: diveProfileBackend.endDive()
                }
                Button {
                    Layout.preferredWidth: 200
                    text: "Save log…"
                    highlighted: true
                    ToolTip.visible: hovered
                    ToolTip.delay: 500
                    ToolTip.text: "Save as UDDF, Garmin FIT or Subsurface XML"
                    onClicked: diveProfileBackend.saveLog()
                }
            }
            Label {
                Layout.preferredWidth: 700
                text: diveProfileBackend.endDiveStatusText
                color: "#9AA0A6"
                wrapMode: Text.WordWrap
                visible: text.length > 0
            }

            Item { Layout.fillHeight: true }
        }
    }

    Dialog {
        id: scaleDialog
        anchors.centerIn: Overlay.overlay
        width: 560
        modal: true
        title: "Set up the dive profile"
        // Popups live in the window Overlay; follow the app window's theme
        // explicitly (same as OverlayDesignerPage's dialogs).
        Material.theme: window.Material.theme
        Material.accent: window.Material.accent
        background: Rectangle {
            color: "#2B2B2B"
            radius: 6
            border.color: "#3F3F3F"
            border.width: 1
        }
        standardButtons: Dialog.Ok | Dialog.Cancel
        property string errorText: ""

        onAboutToShow: {
            errorText = ""
            depthField.text = diveProfileBackend.maxDepthText
            runtimeField.text = diveProfileBackend.runtimeText
            depthField.forceActiveFocus()
        }
        onAccepted: {
            const err = diveProfileBackend.defineScale(depthField.text, runtimeField.text)
            if (err.length > 0) {
                open()
                errorText = err
                return
            }
            if (root.pendingClickX >= 0)
                diveProfileBackend.addWaypointAt(root.pendingClickX, root.pendingClickY)
            root.pendingClickX = -1
            root.pendingClickY = -1
        }
        onRejected: {
            root.pendingClickX = -1
            root.pendingClickY = -1
        }

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 12

            Label {
                Layout.fillWidth: true
                text: root.helpText
                textFormat: Text.StyledText
                wrapMode: Text.WordWrap
            }
            GridLayout {
                columns: 2
                columnSpacing: 12
                rowSpacing: 8
                Label { text: "Max depth (m)" }
                TextField {
                    id: depthField
                    Layout.preferredWidth: 120
                    Layout.preferredHeight: 34
                    font.pixelSize: 15
                    placeholderText: "e.g. 40"
                    onAccepted: scaleDialog.accept()
                }
                Label { text: "Planned runtime (min)" }
                TextField {
                    id: runtimeField
                    Layout.preferredWidth: 120
                    Layout.preferredHeight: 34
                    font.pixelSize: 15
                    placeholderText: "e.g. 60"
                    onAccepted: scaleDialog.accept()
                }
            }
            Label {
                Layout.fillWidth: true
                text: scaleDialog.errorText
                color: "#EF4444"
                wrapMode: Text.WordWrap
                visible: text.length > 0
            }
        }
    }

    Dialog {
        id: helpDialog
        anchors.centerIn: Overlay.overlay
        width: 560
        modal: true
        title: "How the profile builder works"
        // Popups live in the window Overlay; follow the app window's theme
        // explicitly (same as OverlayDesignerPage's dialogs).
        Material.theme: window.Material.theme
        Material.accent: window.Material.accent
        background: Rectangle {
            color: "#2B2B2B"
            radius: 6
            border.color: "#3F3F3F"
            border.width: 1
        }
        standardButtons: Dialog.Close

        Label {
            anchors.left: parent.left
            anchors.right: parent.right
            text: root.helpText
            textFormat: Text.StyledText
            wrapMode: Text.WordWrap
        }
    }

    // Gas line-colour palette - for a gas-table row's swatch (targetRow >= 0,
    // recolours that gas at once) or the gas editor's swatch (targetRow -1,
    // colour for the next Add/Update).
    Popup {
        id: colorPopup
        property int targetRow: -1
        padding: 8
        modal: false
        focus: true
        Material.theme: window.Material.theme
        background: Rectangle {
            color: "#2B2B2B"
            radius: 6
            border.color: "#3F3F3F"
            border.width: 1
        }

        function openFor(row, anchorItem) {
            targetRow = row
            const p = anchorItem.mapToItem(root, 0, anchorItem.height + 4)
            x = p.x
            y = p.y
            open()
        }

        GridLayout {
            columns: 5
            columnSpacing: 6
            rowSpacing: 6
            Repeater {
                model: diveProfileBackend.gasColorPalette
                delegate: Rectangle {
                    required property string modelData
                    width: 26
                    height: 26
                    radius: 4
                    color: modelData
                    border.color: "#606060"
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (colorPopup.targetRow >= 0)
                                diveProfileBackend.setGasColor(colorPopup.targetRow, parent.modelData)
                            else
                                diveProfileBackend.onGasColorSelected(parent.modelData)
                            colorPopup.close()
                        }
                    }
                }
            }
        }
    }
}
