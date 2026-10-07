// Log Viewer page, backed by uwmedia/backends/log_viewer_backend.py's
// LogViewerBackend, exposed as "logViewerBackend" (app.py). The layout
// follows DiveSync's Convert page (dive_sync repo, desktop/qml/ConvertPage.qml)
// without its save/send parts: Open adds dives to a working list, Remove
// (or Delete/Backspace) and Clear take them off it, and the selected dive is
// shown on the right - fields, tanks, depth profile, channels and events -
// above UWMedia's own sample table (folded by default).
// Nothing is written except by "Adjust time…" (Garmin FIT only), which saves
// a corrected copy through a Save As dialog; the original is never changed.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Item {
    id: root
    width: 1060
    height: 800

    readonly property var sel: logViewerBackend.selected
    readonly property bool hasDive: !!sel.start
    readonly property color textColor: "#E0E0E0"
    readonly property color mutedColor: "#9AA0A6"
    readonly property color warnColor: "#F59E0B"
    property bool samplesOpen: false

    // Opening the sample table scrolls it into view: it sits below the fold.
    function scrollToSamples() {
        var flick = detailScroll.contentItem as Flickable
        flick.contentY = Math.max(0, Math.min(samplesCard.y, flick.contentHeight - flick.height))
    }

    // A read-only value with its label above; hidden when empty, so the grid
    // shows only what the log holds.
    component Field: ColumnLayout {
        property string label: ""
        property string value: ""
        property int fieldWidth: 150
        visible: value !== ""
        spacing: 1
        Layout.fillWidth: true
        Layout.preferredWidth: fieldWidth
        Layout.minimumWidth: 90
        Layout.alignment: Qt.AlignTop
        Text { text: label; color: root.mutedColor; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
        // preferredWidth 1: a wrapping TextEdit asks for its unwrapped width,
        // which would push the whole grid past the card's edge
        SelectableText { text: value; font.pixelSize: 13; Layout.fillWidth: true; Layout.preferredWidth: 1; wrapMode: TextEdit.Wrap }
    }
    component Cell: Text {
        property int cellWidth: 70
        Layout.preferredWidth: cellWidth
        color: root.textColor
        font.pixelSize: 12
        elide: Text.ElideRight
    }
    // Read-only text that can be selected and copied (Cmd/Ctrl+C) - sensor
    // serials go into Advanced → Sensor names, GPS positions elsewhere.
    component SelectableText: TextEdit {
        readOnly: true
        selectByMouse: true
        persistentSelection: false
        color: root.textColor
        selectionColor: "#00A6ED"
        selectedTextColor: "#FFFFFF"
        font.pixelSize: 12
    }
    component SelectableCell: SelectableText {
        property int cellWidth: 70
        Layout.preferredWidth: cellWidth
        clip: true
    }
    component HeadCell: Cell {
        color: root.mutedColor
        font.pixelSize: 11
    }
    component SmallButton: Button {
        flat: true
        font.pixelSize: 12
        topInset: 0
        bottomInset: 0
        implicitHeight: 30
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        // --- Top: open / status ---------------------------------------
        Card {
            id: topCard
            title: "Dive logs"
            headerContent: [
                Button {
                    text: "Open files…"
                    enabled: !logViewerBackend.busy
                    ToolTip.visible: hovered
                    ToolTip.delay: 600
                    ToolTip.text: "Garmin .fit, UDDF, Subsurface (.ssrf/.xml/.csv) and Shearwater Cloud (.xml/.csv) logs; several at once. The dives are added to the list."
                    onClicked: logViewerBackend.openFiles()
                },
                Button {
                    text: "Open folder…"
                    enabled: !logViewerBackend.busy
                    ToolTip.visible: hovered
                    ToolTip.delay: 600
                    ToolTip.text: "Adds the dives of every log file in a folder to the list"
                    onClicked: logViewerBackend.openFolder()
                },
                Text {
                    text: logViewerBackend.files.join(", ")
                    color: root.mutedColor
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
            ]
            Text {
                visible: logViewerBackend.diveCount === 0
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: root.mutedColor
                font.pixelSize: 12
                text: "Open dive logs to see them the way UWMedia reads them - to check what an overlay will show before rendering. Open adds to the list; Remove takes a dive off it. The files themselves are never changed; Adjust time saves a corrected copy of a Garmin log."
            }
            ProgressBar { Layout.fillWidth: true; indeterminate: true; visible: logViewerBackend.busy }
            Text {
                visible: text !== ""
                text: logViewerBackend.message
                color: root.mutedColor
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Repeater {
                model: logViewerBackend.warnings
                delegate: Text {
                    required property string modelData
                    text: "⚠ " + modelData
                    color: root.warnColor
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            // --- Left: the dive list ------------------------------------
            Card {
                Layout.preferredWidth: 430
                Layout.minimumWidth: 360
                Layout.fillWidth: false
                Layout.fillHeight: true
                title: "Dives (" + logViewerBackend.diveCount + ")"
                headerContent: [
                    Item { Layout.fillWidth: true },
                    SmallButton {
                        text: "Remove"
                        enabled: logViewerBackend.currentRow >= 0
                        ToolTip.visible: hovered
                        ToolTip.delay: 600
                        ToolTip.text: "Takes the selected dive off the list (Delete or Backspace does the same); the file is not touched"
                        onClicked: logViewerBackend.removeSelected()
                    },
                    SmallButton {
                        text: "Clear"
                        enabled: logViewerBackend.diveCount > 0
                        ToolTip.visible: hovered
                        ToolTip.delay: 600
                        ToolTip.text: "Empties the list; the files are not touched"
                        onClicked: logViewerBackend.clear()
                    }
                ]
                RowLayout {
                    spacing: 8
                    Layout.leftMargin: 6
                    HeadCell { text: "Date"; cellWidth: 78 }
                    HeadCell { text: "Time"; cellWidth: 40 }
                    HeadCell { text: "Depth"; cellWidth: 54 }
                    HeadCell { text: "Duration"; cellWidth: 70 }
                    HeadCell { text: "File"; cellWidth: 100; Layout.fillWidth: true }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 120
                    color: "transparent"
                    border.color: "#333333"
                    radius: 6
                    clip: true
                    ListView {
                        id: diveList
                        anchors { fill: parent; margins: 1 }
                        clip: true
                        model: logViewerBackend.dives
                        currentIndex: logViewerBackend.currentRow
                        onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                        ScrollBar.vertical: ScrollBar {}
                        keyNavigationEnabled: false
                        Keys.onUpPressed: logViewerBackend.select(logViewerBackend.currentRow - 1)
                        Keys.onDownPressed: logViewerBackend.select(logViewerBackend.currentRow + 1)
                        Keys.onDeletePressed: function (event) { logViewerBackend.removeSelected(); event.accepted = true }
                        Keys.onPressed: function (event) {
                            if (event.key === Qt.Key_Backspace) { logViewerBackend.removeSelected(); event.accepted = true }
                        }
                        delegate: Rectangle {
                            id: row
                            required property int index
                            required property var modelData
                            readonly property bool current: logViewerBackend.currentRow === index
                            width: diveList.width
                            implicitHeight: 28
                            color: current ? Qt.rgba(0, 0.65, 0.93, 0.28) : (index % 2 ? "#1A1A1A" : "#202020")
                            RowLayout {
                                anchors { fill: parent; leftMargin: 6; rightMargin: 6 }
                                spacing: 8
                                Cell { text: row.modelData.date; cellWidth: 78 }
                                Cell { text: row.modelData.time; cellWidth: 40 }
                                Cell { text: row.modelData.max_depth; cellWidth: 54 }
                                Cell { text: row.modelData.duration; cellWidth: 70 }
                                Cell { text: row.modelData.file; cellWidth: 100; Layout.fillWidth: true; color: root.mutedColor }
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    diveList.forceActiveFocus()
                                    logViewerBackend.select(row.index)
                                }
                            }
                        }
                    }
                }
                Text {
                    visible: logViewerBackend.diveCount > 0
                    text: "↑/↓ moves through the list · Delete removes the selected dive from it"
                    color: root.mutedColor
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            // --- Right: the selected dive -------------------------------
            ScrollView {
                id: detailScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                Component.onCompleted: {
                    var flick = detailScroll.contentItem as Flickable
                    flick.boundsBehavior = Flickable.StopAtBounds
                    flick.pixelAligned = true
                }
                ColumnLayout {
                    width: detailScroll.availableWidth
                    spacing: 12

                    Card {
                        title: "Dive"
                        headerContent: [
                            Item { Layout.fillWidth: true },
                            SmallButton {
                                visible: root.hasDive
                                text: "Adjust time…"
                                enabled: logViewerBackend.canAdjustTime && !logViewerBackend.busy
                                ToolTip.visible: hovered
                                ToolTip.delay: 600
                                ToolTip.text: logViewerBackend.canAdjustTime
                                              ? "For a dive computer whose clock was wrong: set this dive's real start time and time zone and save a corrected copy of the log"
                                              : "Garmin FIT logs only"
                                onClicked: adjustDialog.open()
                            }
                        ]
                        Text {
                            text: root.hasDive ? root.sel.title : "No dive selected"
                            color: root.textColor
                            font.bold: true
                            font.pixelSize: 14
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text {
                            visible: root.hasDive
                            text: root.hasDive ? root.sel.file + (root.sel.format ? " · " + root.sel.format : "") : ""
                            color: root.mutedColor
                            font.pixelSize: 11
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                        GridLayout {
                            visible: root.hasDive
                            Layout.fillWidth: true
                            columns: 4
                            columnSpacing: 16
                            rowSpacing: 8
                            Field { label: "Start"; value: root.sel.start || "" }
                            Field { label: "End"; value: root.sel.end || "" }
                            Field { label: "Time zone"; value: root.sel.timezone || "" }
                            Field { label: "Duration"; value: root.sel.duration || "" }
                            Field { label: "Max depth"; value: root.sel.max_depth || "" }
                            Field { label: "Avg depth"; value: root.sel.avg_depth || "" }
                            Field { label: "Water temp (min)"; value: root.sel.temp_min || "" }
                            Field { label: "Water temp (max)"; value: root.sel.temp_max || "" }
                            Field { label: "Dive computer"; value: root.sel.device || ""; fieldWidth: 316; Layout.columnSpan: 2 }
                            Field { label: "Latitude"; value: root.sel.lat || "" }
                            Field { label: "Longitude"; value: root.sel.lng || "" }
                            Field { label: "Exit latitude"; value: root.sel.exit_lat || "" }
                            Field { label: "Exit longitude"; value: root.sel.exit_lng || "" }
                        }

                        // tanks and their sensors
                        ColumnLayout {
                            visible: root.hasDive
                            spacing: 4
                            Layout.fillWidth: true
                            Text { text: "Tanks / sensors"; color: root.mutedColor; font.pixelSize: 11 }
                            Text { visible: (root.sel.tanks || []).length === 0; text: "No tank data in this dive"; color: root.textColor; font.pixelSize: 12 }
                            RowLayout {
                                visible: (root.sel.tanks || []).length > 0
                                spacing: 8
                                HeadCell { text: "#"; cellWidth: 20 }
                                HeadCell { text: "Sensor"; cellWidth: 80 }
                                HeadCell { text: "Serial"; cellWidth: 95 }
                                HeadCell { text: "Name"; cellWidth: 90 }
                                HeadCell { text: "Mix"; cellWidth: 70 }
                                HeadCell { text: "Start"; cellWidth: 65 }
                                HeadCell { text: "End"; cellWidth: 65 }
                            }
                            Repeater {
                                model: root.sel.tanks || []
                                delegate: RowLayout {
                                    required property var modelData
                                    spacing: 8
                                    Cell { text: String(modelData.index); cellWidth: 20 }
                                    SelectableCell { text: modelData.key; cellWidth: 80 }
                                    SelectableCell { text: modelData.serial; cellWidth: 95 }
                                    Cell { text: modelData.name; cellWidth: 90 }
                                    Cell { text: modelData.mix; cellWidth: 70 }
                                    Cell { text: modelData.start_pressure; cellWidth: 65 }
                                    Cell { text: modelData.end_pressure; cellWidth: 65 }
                                }
                            }
                            Text {
                                visible: (root.sel.tanks || []).length > 0
                                text: "Select a sensor or serial and copy it (Cmd/Ctrl+C) to give it a friendly name under Advanced → Sensor names; overlays then show that name."
                                color: "#808080"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }

                        ProfileChart {
                            Layout.fillWidth: true
                            samples: root.sel.samples || []
                            showCeiling: !!root.sel.has_ceiling
                        }
                        Text {
                            visible: root.hasDive
                            text: root.sel.sample_count > 0
                                  ? (root.sel.sample_count + " samples"
                                     + ((root.sel.channels || []).length > 0 ? " · logged: " + root.sel.channels.join(", ") : ""))
                                  : "No dive profile in the log"
                            color: root.mutedColor
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                        ColumnLayout {
                            visible: root.hasDive && (root.sel.events || []).length > 0
                            spacing: 1
                            Text { text: "Events"; color: root.mutedColor; font.pixelSize: 11 }
                            Repeater {
                                model: root.sel.events || []
                                delegate: Text {
                                    required property string modelData
                                    text: modelData
                                    color: root.textColor
                                    font.pixelSize: 11
                                    font.family: Qt.platform.os === "osx" ? "Menlo" : Qt.platform.os === "windows" ? "Consolas" : "monospace"
                                }
                            }
                        }
                    }

                    // --- Samples: UWMedia's waypoint table, folded --------
                    Card {
                        id: samplesCard
                        visible: root.hasDive
                        title: "Samples (" + (root.sel.sample_count || 0) + ")"
                        headerContent: [
                            Item { Layout.fillWidth: true },
                            SmallButton {
                                text: root.samplesOpen ? "Hide" : "Show"
                                onClicked: {
                                    root.samplesOpen = !root.samplesOpen
                                    if (root.samplesOpen) Qt.callLater(root.scrollToSamples)
                                }
                            }
                        ]
                        Text {
                            visible: !root.samplesOpen
                            text: "Every sample as the overlays read it: time, depth, temperature, NDL, TTS, gas and tank pressures."
                            color: root.mutedColor
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                        RowLayout {
                            visible: root.samplesOpen
                            Layout.fillWidth: true
                            spacing: 8
                            Label { text: "Filter:" }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                font.pixelSize: 14
                                placeholderText: "Type to filter samples..."
                                text: logViewerBackend.filterText
                                onTextEdited: logViewerBackend.filterText = text
                            }
                            Text {
                                text: sampleList.count + " shown"
                                color: root.mutedColor
                                font.pixelSize: 11
                            }
                        }
                        RowLayout {
                            visible: root.samplesOpen
                            Layout.fillWidth: true
                            Layout.leftMargin: 6
                            spacing: 0
                            Repeater {
                                model: logViewerBackend.tableHeaders
                                delegate: Label {
                                    required property string modelData
                                    required property int index
                                    Layout.preferredWidth: index === 5 ? 60 : (index === 6 ? 260 : 80)
                                    Layout.fillWidth: index === 6
                                    text: modelData
                                    font.bold: true
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                            }
                        }
                        ListView {
                            id: sampleList
                            visible: root.samplesOpen
                            Layout.fillWidth: true
                            Layout.preferredHeight: 380
                            clip: true
                            model: root.samplesOpen ? logViewerBackend.tableRows : []
                            ScrollBar.vertical: ScrollBar {}
                            delegate: Rectangle {
                                id: sampleRow
                                required property var modelData
                                required property int index
                                width: ListView.view.width
                                height: 24
                                color: index % 2 === 0 ? "#1A1A1A" : "#141414"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 6
                                    spacing: 0
                                    Repeater {
                                        model: sampleRow.modelData
                                        delegate: Label {
                                            required property string modelData
                                            required property int index
                                            Layout.preferredWidth: index === 5 ? 60 : (index === 6 ? 260 : 80)
                                            Layout.fillWidth: index === 6
                                            text: modelData
                                            color: root.textColor
                                            font.pixelSize: 12
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
    }

    Dialog {
        id: adjustDialog
        anchors.centerIn: Overlay.overlay
        width: 520
        modal: true
        title: "Adjust the dive's time"
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
        standardButtons: Dialog.Save | Dialog.Cancel
        property string errorText: ""

        onAboutToShow: {
            errorText = ""
            startField.text = logViewerBackend.adjustStartText
            offsetField.text = logViewerBackend.adjustOffsetText
            startField.forceActiveFocus()
        }
        onAccepted: {
            const err = logViewerBackend.adjustTime(startField.text, offsetField.text)
            if (err.length > 0) {
                open()
                errorText = err
            }
        }

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 12

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "For a dive computer whose clock was wrong before the dive. Enter when the dive really started, in the dive site's local time, and that place's time zone. Every sample moves by the same amount; the corrected log is saved as a new file and added to the list."
            }
            GridLayout {
                columns: 2
                columnSpacing: 12
                rowSpacing: 8
                Label { text: "Start (local time)" }
                TextField {
                    id: startField
                    Layout.preferredWidth: 220
                    Layout.preferredHeight: 34
                    font.pixelSize: 15
                    placeholderText: "YYYY-MM-DD HH:MM:SS"
                    onAccepted: adjustDialog.accept()
                }
                Label { text: "Time zone (UTC offset)" }
                TextField {
                    id: offsetField
                    Layout.preferredWidth: 120
                    Layout.preferredHeight: 34
                    font.pixelSize: 15
                    placeholderText: "e.g. +07:00"
                    onAccepted: adjustDialog.accept()
                }
            }
            Label {
                Layout.fillWidth: true
                text: adjustDialog.errorText
                color: "#EF4444"
                wrapMode: Text.WordWrap
                visible: text.length > 0
            }
        }
    }
}
