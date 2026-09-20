// Overlay Designer page - overlay_rework.md Phase 1 (renamed from "HUD
// Designer" in Phase 0; originally qml_development.md Phase 7). Backed by
// uwmedia/backends/overlay_designer_backend.py's OverlayDesignerBackend,
// exposed as "overlayDesignerBackend" (app.py).
//
// Layout (overlay_rework.md §7.1): template cascade + undo/redo/dirty across
// the top, a zoomable editing canvas (OverlayDesignerCanvas.qml - Design view
// = skin at native px, Frame preview = 1920x1080 composite) with a telemetry
// row underneath, the optional "Background and dive logs" tools collapsed by
// default, and a right-hand column with the element list (+ Add element
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
    height: 720
    readonly property int rightColumnWidth: 350

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
            ToolButton {
                text: "⋯"
                onClicked: moreMenu.open()
                ToolTip.text: "Export / import a page as a zip"
                ToolTip.visible: hovered
                Menu {
                    id: moreMenu
                    y: parent.height
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

                // Canvas toolbar
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    ButtonGroup { id: viewGroup }
                    RadioButton {
                        text: "Design view"
                        ButtonGroup.group: viewGroup
                        checked: overlayDesignerBackend.viewMode === "design"
                        onClicked: overlayDesignerBackend.setViewMode("design")
                    }
                    RadioButton {
                        text: "Frame preview"
                        ButtonGroup.group: viewGroup
                        checked: overlayDesignerBackend.viewMode === "frame"
                        onClicked: overlayDesignerBackend.setViewMode("frame")
                    }

                    Item { Layout.fillWidth: true }

                    Label { text: "Zoom" }
                    ToolButton { text: "−"; onClicked: overlayDesignerBackend.zoomOut() }
                    Label {
                        Layout.preferredWidth: 46
                        horizontalAlignment: Text.AlignHCenter
                        text: overlayDesignerBackend.zoomPercent + "%"
                    }
                    ToolButton { text: "+"; onClicked: overlayDesignerBackend.zoomIn() }
                    Button {
                        text: "Fit"
                        flat: true
                        highlighted: overlayDesignerBackend.zoomIsFit
                        onClicked: overlayDesignerBackend.zoomFit()
                    }
                    Button {
                        text: "100%"
                        flat: true
                        onClicked: overlayDesignerBackend.setZoomPercent(100)
                    }
                }

                // Display toggles (own row so the toolbar fits the 1060 px page)
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    CheckBox {
                        text: "Bounds"
                        checked: overlayDesignerBackend.showBounds
                        onToggled: overlayDesignerBackend.setShowBounds(checked)
                    }
                    CheckBox {
                        text: "Grid"
                        checked: overlayDesignerBackend.showGrid
                        onToggled: overlayDesignerBackend.setShowGrid(checked)
                    }
                    CheckBox {
                        text: "Snap"
                        checked: overlayDesignerBackend.snapEnabled
                        onToggled: overlayDesignerBackend.setSnapEnabled(checked)
                        ToolTip.text: "Snap dragged elements to the grid and to other elements' edges"
                        ToolTip.visible: hovered
                    }
                    Label { text: "Grid size"; font.pixelSize: 12 }
                    ComboBox {
                        id: gridSizeCombo
                        Layout.preferredWidth: 72
                        Layout.preferredHeight: 30
                        font.pixelSize: 12
                        model: overlayDesignerBackend.gridSizes
                        Binding {
                            target: gridSizeCombo; property: "currentIndex"
                            value: Math.max(0, overlayDesignerBackend.gridSizes.indexOf(overlayDesignerBackend.gridSize))
                        }
                        onActivated: (index) => overlayDesignerBackend.setGridSize(model[index])
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        text: overlayDesignerBackend.selectionCount > 1
                            ? overlayDesignerBackend.selectionCount + " selected"
                            : (overlayDesignerBackend.hiddenIndices.length > 0 ? overlayDesignerBackend.hiddenIndices.length + " hidden" : "")
                        color: "#909090"
                        font.pixelSize: 12
                    }
                }

                // Canvas viewport (editing canvas - see OverlayDesignerCanvas.qml)
                OverlayDesignerCanvas {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 240
                }

                // Telemetry row: source, state, time scrub
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Label { text: "Telemetry" }
                    ButtonGroup { id: sourceGroup }
                    RadioButton {
                        text: "Dummy"
                        ButtonGroup.group: sourceGroup
                        checked: overlayDesignerBackend.telemetrySource === "dummy"
                        onClicked: overlayDesignerBackend.setTelemetrySource("dummy")
                    }
                    RadioButton {
                        text: "Loaded log"
                        ButtonGroup.group: sourceGroup
                        enabled: overlayDesignerBackend.logTelemetryAvailable
                        checked: overlayDesignerBackend.telemetrySource === "log"
                        onClicked: overlayDesignerBackend.setTelemetrySource("log")
                    }

                    Label { text: "State" }
                    CascadeCombo {
                        Layout.preferredWidth: 170
                        model: overlayDesignerBackend.stateList
                        backendIndex: overlayDesignerBackend.stateIndex
                        onActivated: (index) => overlayDesignerBackend.onStateSelected(model[index])
                    }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Time" }
                    Slider {
                        Layout.fillWidth: true
                        from: overlayDesignerBackend.timeMin
                        to: Math.max(overlayDesignerBackend.timeMin, overlayDesignerBackend.timeMax)
                        value: overlayDesignerBackend.timeValue
                        enabled: overlayDesignerBackend.timeEnabled
                        onMoved: overlayDesignerBackend.onTimeChanged(Math.round(value))
                    }
                    Label { Layout.preferredWidth: 80; text: overlayDesignerBackend.timeText }
                }

                Label {
                    Layout.fillWidth: true
                    text: overlayDesignerBackend.dataText
                    elide: Text.ElideRight
                }

                // --- Background & dive logs (optional, collapsed) ------------
                Pane {
                    id: mediaPane
                    Layout.fillWidth: true
                    Material.elevation: 1
                    padding: 8
                    property bool expanded: false

                    ColumnLayout {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 6

                        ItemDelegate {
                            Layout.fillWidth: true
                            text: (mediaPane.expanded ? "▾  " : "▸  ") + "Background and dive logs (optional)"
                            font.bold: true
                            onClicked: mediaPane.expanded = !mediaPane.expanded
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: mediaPane.expanded
                            spacing: 6

                            RowLayout {
                                spacing: 8
                                Button { text: "Load video/photo"; onClicked: overlayDesignerBackend.loadBackground() }
                                Button {
                                    text: "Clear background"
                                    enabled: overlayDesignerBackend.hasBackground
                                    onClicked: overlayDesignerBackend.clearBackground()
                                }
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

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: "Preview a found log directly (no video needed)" }
                                ComboBox {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    font.pixelSize: 14
                                    enabled: overlayDesignerBackend.logFileEnabled
                                    model: overlayDesignerBackend.logFileList
                                    onActivated: (index) => overlayDesignerBackend.onLogFileSelected(model[index])
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: overlayDesignerBackend.logText; color: "#808080"; Layout.fillWidth: true; elide: Text.ElideRight }
                                Button { text: "Show raw waypoint data"; onClicked: overlayDesignerBackend.showWaypoint() }
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: overlayDesignerBackend.statusText
                    color: "#808080"
                    elide: Text.ElideRight
                }
            }

            // --- Right column: template, element list, inspector ------------
            ScrollView {
                Layout.preferredWidth: root.rightColumnWidth
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth

                ColumnLayout {
                    width: parent.width
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
                            anchors.left: parent.left
                            anchors.right: parent.right
                            spacing: 4

                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    Layout.fillWidth: true
                                    text: "Elements (" + overlayDesignerBackend.elements.length + ")"
                                    font.bold: true
                                    font.pixelSize: 14
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
                                visible: overlayDesignerBackend.elements.length === 0
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
                    font.family: "Menlo"
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
