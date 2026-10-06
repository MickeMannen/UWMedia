// Overlay Designer page - overlay_rework.md Phase 1 (renamed from "HUD
// Designer" in Phase 0; originally qml_development.md Phase 7). Backed by
// uwmedia/backends/overlay_designer_backend.py's OverlayDesignerBackend,
// exposed as "overlayDesignerBackend" (app.py).
//
// Layout (overlay_rework.md §7.1): template cascade + undo/redo/dirty across
// the top, a zoomable editing canvas (OverlayDesignerCanvas.qml - Design view
// = skin at native px, Frame preview = 1920x1080 composite) with a telemetry
// row underneath, the optional "Background and dive logs" tools in a popup
// behind the More menu (mediaPopup), and a right-hand column with the element list (+ Add element
// popup) and the inspector (OverlayElementInspector.qml). Phase 2 made it an
// editor; Phase 3 added Save / Save as… (SaveTemplateAsPopup.qml) / Revert,
// the write-target line, and the unsaved-changes guard on the cascade;
// Phase 4 added "New custom…" (NewCustomTemplatePopup.qml).
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window

Item {
    id: root
    width: 1060
    height: 800
    // 340 (2026-09-28): the inspector's fields have fixed widths now, so the
    // column can be narrower and the canvas wider.
    readonly property int rightColumnWidth: 340

    // Unsaved-changes guard: cascade picks go through guardedSelect() so a
    // dirty template asks before being replaced. On Cancel the combo is
    // snapped back to the backend's selection.
    property var pendingApply: null
    property var pendingCombo: null
    function guardedSelect(combo, applyFn) {
        if (overlayDesignerBackend.isDirty) {
            pendingApply = applyFn
            pendingCombo = combo
            unsavedDialog.open()
        } else {
            applyFn()
        }
    }

    // Combo boxes are driven by backend index properties through Binding
    // elements (not a plain `currentIndex:` binding) so a user pick, which
    // breaks a declarative binding, still gets overridden the next time the
    // backend re-resolves a selection (e.g. the variant auto-pick after a
    // dive log is loaded).
    component CascadeCombo: ComboBox {
        id: combo
        property int backendIndex: 0
        Layout.preferredHeight: 34
        font.pixelSize: 14
        Binding { target: combo; property: "currentIndex"; value: combo.backendIndex }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        // --- Top bar: template cascade -----------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label { text: "Brand" }
            CascadeCombo {
                id: brandCombo
                Layout.preferredWidth: 150
                model: overlayDesignerBackend.brandList
                backendIndex: overlayDesignerBackend.brandIndex
                onActivated: (index) => {
                    const name = model[index]
                    root.guardedSelect(brandCombo, () => overlayDesignerBackend.onBrandSelected(name))
                }
            }

            Label { text: "Computer"; visible: overlayDesignerBackend.computerVisible }
            CascadeCombo {
                id: computerCombo
                Layout.preferredWidth: 150
                visible: overlayDesignerBackend.computerVisible
                model: overlayDesignerBackend.computerList
                backendIndex: overlayDesignerBackend.computerIndex
                onActivated: (index) => {
                    const name = model[index]
                    root.guardedSelect(computerCombo, () => overlayDesignerBackend.onComputerSelected(name))
                }
            }

            Label { text: "Page" }
            CascadeCombo {
                id: pageCombo
                Layout.preferredWidth: 170
                model: overlayDesignerBackend.pageList
                backendIndex: overlayDesignerBackend.pageIndex
                onActivated: (index) => {
                    const name = model[index]
                    root.guardedSelect(pageCombo, () => overlayDesignerBackend.onPageSelected(name))
                }
            }

            Label { text: "Variant"; visible: overlayDesignerBackend.variantVisible }
            CascadeCombo {
                id: variantCombo
                Layout.preferredWidth: 140
                visible: overlayDesignerBackend.variantVisible
                model: overlayDesignerBackend.variantList
                backendIndex: overlayDesignerBackend.variantIndex
                onActivated: (index) => {
                    const name = model[index]
                    root.guardedSelect(variantCombo, () => overlayDesignerBackend.onVariantSelected(name))
                }
            }

            Item { Layout.fillWidth: true }

            ToolButton {
                text: "↶"
                enabled: overlayDesignerBackend.canUndo
                onClicked: overlayDesignerBackend.undo()
                ToolTip.text: "Undo (Cmd/Ctrl-Z)"; ToolTip.visible: hovered
            }
            ToolButton {
                text: "↷"
                enabled: overlayDesignerBackend.canRedo
                onClicked: overlayDesignerBackend.redo()
                ToolTip.text: "Redo (Shift-Cmd/Ctrl-Z)"; ToolTip.visible: hovered
            }
            Label {
                text: overlayDesignerBackend.isDirty ? "● Unsaved changes" : "Saved"
                color: overlayDesignerBackend.isDirty ? "#F59E0B" : "#707070"
                font.pixelSize: 12
            }
        }

        // --- Save row ------------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Button {
                text: "New custom…"
                onClicked: root.guardedSelect(null, () => newCustomPopup.open())
            }
            Button {
                text: "Save"
                highlighted: overlayDesignerBackend.isDirty && overlayDesignerBackend.canSave
                enabled: overlayDesignerBackend.canSave && overlayDesignerBackend.isDirty
                onClicked: overlayDesignerBackend.save()
            }
            Button {
                text: "Save as…"
                enabled: overlayDesignerBackend.hasDocument
                onClicked: saveAsPopup.open()
            }
            Button {
                text: "Revert"
                flat: true
                enabled: overlayDesignerBackend.isDirty
                onClicked: overlayDesignerBackend.revert()
            }
            Button {
                // A labelled button (2026-09-28, per the user): the "⋯"
                // glyph was too easy to miss now that the Background and
                // dive logs tools live behind it.
                text: "More ▾"
                flat: true
                onClicked: moreMenu.open()
                ToolTip.text: "Background and dive logs, export / import a page as a zip"
                ToolTip.visible: hovered
                Menu {
                    id: moreMenu
                    y: parent.height
                    MenuItem {
                        text: "Background and dive logs…"
                        onTriggered: mediaPopup.open()
                    }
                    MenuSeparator {}
                    MenuItem {
                        text: "Export page as zip…"
                        enabled: overlayDesignerBackend.hasDocument
                        onTriggered: overlayDesignerBackend.exportZip()
                    }
                    MenuItem {
                        text: "Import page from zip…"
                        onTriggered: root.guardedSelect(null, () => {
                            const suggested = overlayDesignerBackend.importZip()
                            if (suggested.length > 0) {
                                saveAsPopup.importMode = true
                                saveAsPopup.suggestedName = suggested
                                saveAsPopup.open()
                            }
                        })
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label {
                    Layout.fillWidth: true
                    visible: overlayDesignerBackend.readOnlyHint.length > 0
                    text: overlayDesignerBackend.readOnlyHint
                    color: "#F59E0B"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: overlayDesignerBackend.writeTargetText
                    color: overlayDesignerBackend.isDevMode ? "#22C55E" : "#909090"
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            // --- Left column: canvas + telemetry + optional media/logs ------
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 8

                // Canvas toolbar - one row (2026-09-28, per the user): view
                // mode and display toggles as checkable flat buttons instead
                // of RadioButtons/CheckBoxes. Every control has a fixed,
                // compact width: the row must stay under the left column's
                // ~670 px or the RowLayout pushes the right column off the
                // window (which is what the first cut of this row did).
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 3

                    component ToolBtn: Button {
                        flat: true
                        font.pixelSize: 13
                        leftPadding: 6
                        rightPadding: 6
                        Layout.preferredHeight: 34
                    }

                    ToolBtn {
                        text: "Design view"
                        Layout.preferredWidth: 90
                        checkable: true
                        checked: overlayDesignerBackend.viewMode === "design"
                        onClicked: overlayDesignerBackend.setViewMode("design")
                    }
                    ToolBtn {
                        text: "Frame preview"
                        Layout.preferredWidth: 104
                        checkable: true
                        checked: overlayDesignerBackend.viewMode === "frame"
                        onClicked: overlayDesignerBackend.setViewMode("frame")
                    }

                    Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 22; Layout.leftMargin: 3; Layout.rightMargin: 3; color: "#3F3F3F" }

                    ToolBtn {
                        text: "Bounds"
                        Layout.preferredWidth: 60
                        checkable: true
                        checked: overlayDesignerBackend.showBounds
                        onToggled: overlayDesignerBackend.setShowBounds(checked)
                    }
                    ToolBtn {
                        text: "Grid"
                        Layout.preferredWidth: 44
                        checkable: true
                        checked: overlayDesignerBackend.showGrid
                        onToggled: overlayDesignerBackend.setShowGrid(checked)
                    }
                    ToolBtn {
                        text: "Snap"
                        Layout.preferredWidth: 48
                        checkable: true
                        checked: overlayDesignerBackend.snapEnabled
                        onToggled: overlayDesignerBackend.setSnapEnabled(checked)
                        ToolTip.text: "Snap dragged elements to the grid and to other elements' edges"
                        ToolTip.visible: hovered
                    }
                    ComboBox {
                        id: gridSizeCombo
                        Layout.preferredWidth: 64
                        Layout.preferredHeight: 30
                        font.pixelSize: 12
                        model: overlayDesignerBackend.gridSizes
                        ToolTip.text: "Grid size"
                        ToolTip.visible: hovered
                        Binding {
                            target: gridSizeCombo; property: "currentIndex"
                            value: Math.max(0, overlayDesignerBackend.gridSizes.indexOf(overlayDesignerBackend.gridSize))
                        }
                        onActivated: (index) => overlayDesignerBackend.setGridSize(model[index])
                    }

                    Item { Layout.fillWidth: true }

                    ToolBtn { text: "−"; Layout.preferredWidth: 30; onClicked: overlayDesignerBackend.zoomOut() }
                    Label {
                        Layout.preferredWidth: 40
                        horizontalAlignment: Text.AlignHCenter
                        font.pixelSize: 12
                        text: overlayDesignerBackend.zoomPercent + "%"
                    }
                    ToolBtn { text: "+"; Layout.preferredWidth: 30; onClicked: overlayDesignerBackend.zoomIn() }
                    ToolBtn {
                        text: "Fit"
                        Layout.preferredWidth: 38
                        highlighted: overlayDesignerBackend.zoomIsFit
                        onClicked: overlayDesignerBackend.zoomFit()
                    }
                    ToolBtn {
                        text: "100%"
                        Layout.preferredWidth: 50
                        onClicked: overlayDesignerBackend.setZoomPercent(100)
                    }
                }

                // Canvas viewport (editing canvas - see OverlayDesignerCanvas.qml)
                OverlayDesignerCanvas {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 240
                }

                // Telemetry row - source, state and time scrub on one line
                // (2026-09-28, per the user). The data readout moved to the
                // status line below.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label { text: "Telemetry"; font.pixelSize: 12 }
                    Button {
                        text: "Dummy"
                        flat: true
                        checkable: true
                        Layout.preferredHeight: 34
                        checked: overlayDesignerBackend.telemetrySource === "dummy"
                        onClicked: overlayDesignerBackend.setTelemetrySource("dummy")
                    }
                    Button {
                        text: "Loaded log"
                        flat: true
                        checkable: true
                        Layout.preferredHeight: 34
                        enabled: overlayDesignerBackend.logTelemetryAvailable
                        checked: overlayDesignerBackend.telemetrySource === "log"
                        onClicked: overlayDesignerBackend.setTelemetrySource("log")
                    }

                    Label { text: "State"; font.pixelSize: 12; Layout.leftMargin: 8 }
                    CascadeCombo {
                        Layout.preferredWidth: 170
                        model: overlayDesignerBackend.stateList
                        backendIndex: overlayDesignerBackend.stateIndex
                        onActivated: (index) => overlayDesignerBackend.onStateSelected(model[index])
                    }

                    Label { text: "Time"; font.pixelSize: 12; Layout.leftMargin: 8 }
                    Slider {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 80
                        from: overlayDesignerBackend.timeMin
                        to: Math.max(overlayDesignerBackend.timeMin, overlayDesignerBackend.timeMax)
                        value: overlayDesignerBackend.timeValue
                        enabled: overlayDesignerBackend.timeEnabled
                        onMoved: overlayDesignerBackend.onTimeChanged(Math.round(value))
                    }
                    Label { Layout.preferredWidth: 64; font.pixelSize: 12; text: overlayDesignerBackend.timeText }
                }

                // Status line: data readout left, status right. The
                // "Background and dive logs" tools live in the More menu
                // (mediaPopup) since 2026-09-28 so their collapsed header no
                // longer takes a row here.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Label {
                        // "3 selected" / "2 hidden" - was on the toolbar row
                        visible: text.length > 0
                        text: overlayDesignerBackend.selectionCount > 1
                            ? overlayDesignerBackend.selectionCount + " selected"
                            : (overlayDesignerBackend.hiddenIndices.length > 0 ? overlayDesignerBackend.hiddenIndices.length + " hidden" : "")
                        color: "#909090"
                        font.pixelSize: 12
                    }
                    Label {
                        Layout.fillWidth: true
                        text: overlayDesignerBackend.dataText
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignRight
                        text: overlayDesignerBackend.statusText
                        color: "#808080"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }
            }

            // --- Right column: template, element list, inspector ------------
            ScrollView {
                id: rightColumn
                objectName: "rightColumn"
                Layout.preferredWidth: root.rightColumnWidth
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                // A permanent scroll bar (2026-09-27, per the user): the
                // inspector is taller than the window and the Material
                // bar only showed while scrolling, so nothing said more was
                // below. The content is inset so the bar never covers it.
                ScrollBar.vertical.policy: ScrollBar.AlwaysOn
                ScrollBar.vertical.interactive: true

                ColumnLayout {
                    width: rightColumn.availableWidth - 14
                    spacing: 12

                    Label {
                        Layout.fillWidth: true
                        text: overlayDesignerBackend.templateTitle
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }

                    Pane {
                        Layout.fillWidth: true
                        Material.elevation: 1
                        ColumnLayout {
                            id: elementsColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            spacing: 4

                            // The list folds (2026-09-27, per the user) to give
                            // the inspector below its space; collapsed, the
                            // header names what is selected.
                            property bool listOpen: true
                            RowLayout {
                                Layout.fillWidth: true
                                ItemDelegate {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 30
                                    text: (elementsColumn.listOpen ? "▾  " : "▸  ") + "Elements (" + overlayDesignerBackend.elements.length + ")"
                                          + (!elementsColumn.listOpen && overlayDesignerBackend.selectionBoxLabel.length > 0 ? "  ·  " + overlayDesignerBackend.selectionBoxLabel : "")
                                    font.bold: true
                                    font.pixelSize: 14
                                    onClicked: elementsColumn.listOpen = !elementsColumn.listOpen
                                    ToolTip.text: elementsColumn.listOpen ? "Fold the element list" : "Show the element list"
                                    ToolTip.visible: hovered
                                    ToolTip.delay: 400
                                }
                                Button {
                                    text: "+ Add"
                                    flat: true
                                    enabled: overlayDesignerBackend.hasDocument
                                    onClicked: addElementPopup.open()
                                }
                            }

                            ItemDelegate {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                visible: elementsColumn.listOpen
                                text: "Skin and placement"
                                font.pixelSize: 12
                                highlighted: overlayDesignerBackend.skinSelected
                                onClicked: overlayDesignerBackend.selectSkin()
                            }

                            // Bounded, scrollable list so the inspector below stays
                            // reachable on a page with many elements.
                            ListView {
                                id: elementListView
                                Layout.fillWidth: true
                                visible: elementsColumn.listOpen
                                Layout.preferredHeight: Math.min(contentHeight, 6 * 28)
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                model: overlayDesignerBackend.elements
                                currentIndex: overlayDesignerBackend.selectedIndex
                                onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                delegate: ItemDelegate {
                                    id: elementRow
                                    width: ListView.view.width
                                    height: 28
                                    text: modelData.label + "  ·  " + modelData.kind
                                    font.pixelSize: 12
                                    opacity: modelData.hidden ? 0.45 : 1.0
                                    highlighted: overlayDesignerBackend.selectedIndices.indexOf(modelData.index) >= 0
                                    // plain click selects; Cmd/Ctrl/Shift-click toggles membership
                                    TapHandler {
                                        acceptedModifiers: Qt.NoModifier
                                        onTapped: overlayDesignerBackend.selectElement(modelData.index)
                                    }
                                    TapHandler {
                                        acceptedModifiers: Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier
                                        onTapped: overlayDesignerBackend.toggleElement(modelData.index)
                                    }
                                    ToolButton {
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 28; height: 28
                                        text: modelData.hidden ? "◌" : "◉"
                                        font.pixelSize: 12
                                        onClicked: overlayDesignerBackend.toggleHidden(modelData.index)
                                        ToolTip.text: modelData.hidden ? "Show element (designer only)" : "Hide element (designer only)"
                                        ToolTip.visible: hovered
                                    }
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                visible: elementsColumn.listOpen && overlayDesignerBackend.elements.length === 0
                                text: "No elements - use + Add"
                                color: "#808080"
                                font.pixelSize: 12
                            }
                        }
                    }

                    OverlayElementInspector { Layout.fillWidth: true }

                    Item { Layout.fillHeight: true }
                }
            }
        }
    }

    AddElementPopup { id: addElementPopup }

    // Background and dive logs (optional) - formerly a collapsed Pane under
    // the canvas; a popup since 2026-09-28 so the canvas keeps its height.
    Popup {
        id: mediaPopup
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: 560
        padding: 16
        Material.theme: window.Material.theme
        Material.accent: window.Material.accent
        background: Rectangle {
            color: "#2B2B2B"
            radius: 6
            border.color: "#3F3F3F"
            border.width: 1
        }

        ColumnLayout {
            width: parent.width
            spacing: 10

            Label {
                text: "Background and dive logs (optional)"
                font.bold: true
                Layout.fillWidth: true
            }

            RowLayout {
                spacing: 8
                Button { text: "Load video/photo"; onClicked: overlayDesignerBackend.loadBackground() }
                Button {
                    text: "Clear background"
                    enabled: overlayDesignerBackend.hasBackground
                    onClicked: overlayDesignerBackend.clearBackground()
                }
            }
            RowLayout {
                spacing: 8
                Button { text: "Select log file"; onClicked: overlayDesignerBackend.loadLogFile() }
                Button { text: "Select log directory"; onClicked: overlayDesignerBackend.loadLogs() }
            }

            RowLayout {
                Layout.fillWidth: true
                Label { text: "TZ offset (log vs media)" }
                Slider {
                    Layout.fillWidth: true
                    from: -24; to: 24
                    value: overlayDesignerBackend.tzValue
                    onMoved: overlayDesignerBackend.onTzChanged(Math.round(value))
                }
                Label { Layout.preferredWidth: 40; text: overlayDesignerBackend.tzText }
            }

            Label { text: "Preview a loaded log directly (no video needed)" }
            ComboBox {
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                font.pixelSize: 14
                enabled: overlayDesignerBackend.logFileEnabled
                model: overlayDesignerBackend.logFileList
                onActivated: (index) => overlayDesignerBackend.onLogFileSelected(model[index])
            }

            Label {
                Layout.fillWidth: true
                text: overlayDesignerBackend.logText
                color: "#808080"
                elide: Text.ElideRight
            }

            RowLayout {
                Layout.fillWidth: true
                Button { text: "Show raw waypoint data"; onClicked: overlayDesignerBackend.showWaypoint() }
                Item { Layout.fillWidth: true }
                Button { text: "Close"; flat: true; onClicked: mediaPopup.close() }
            }
        }
    }
    SaveTemplateAsPopup { id: saveAsPopup }
    NewCustomTemplatePopup { id: newCustomPopup; objectName: "newCustomPopup" }

    Dialog {
        id: unsavedDialog
        modal: true
        title: "Unsaved changes"
        anchors.centerIn: Overlay.overlay
        width: 420
        standardButtons: Dialog.NoButton
        closePolicy: Popup.NoAutoClose
        Material.theme: window.Material.theme
        Material.accent: window.Material.accent
        background: Rectangle {
            color: "#2B2B2B"
            radius: 6
            border.color: "#3F3F3F"
            border.width: 1
        }

        ColumnLayout {
            width: parent.width
            spacing: 12
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "This template has unsaved changes. Switching templates will lose them unless you save first."
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    text: "Cancel"
                    onClicked: {
                        unsavedDialog.close()
                        if (root.pendingCombo)
                            root.pendingCombo.currentIndex = root.pendingCombo.backendIndex
                        root.pendingApply = null
                    }
                }
                Button {
                    text: "Discard"
                    onClicked: {
                        unsavedDialog.close()
                        const apply = root.pendingApply
                        root.pendingApply = null
                        if (apply) apply()
                    }
                }
                Button {
                    text: "Save"
                    highlighted: true
                    visible: overlayDesignerBackend.canSave
                    onClicked: {
                        if (overlayDesignerBackend.save()) {
                            unsavedDialog.close()
                            const apply = root.pendingApply
                            root.pendingApply = null
                            if (apply) apply()
                        }
                    }
                }
            }
        }
    }

    Window {
        id: waypointWindow
        visible: overlayDesignerBackend.waypointVisible
        title: "Current Waypoint Raw Data"
        width: 500
        height: 700
        onClosing: overlayDesignerBackend.closeWaypointViewer()

        Rectangle {
            anchors.fill: parent
            color: "#1F1F1F"
            ScrollView {
                anchors.fill: parent
                anchors.margins: 12
                TextArea {
                    readOnly: true
                    text: overlayDesignerBackend.waypointJson
                    color: "#E0E0E0"
                    font.family: Qt.platform.os === "osx" ? "Menlo" : Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
