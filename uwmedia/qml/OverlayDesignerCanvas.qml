// Overlay Designer canvas - overlay_rework.md Phase 2. The zoomable canvas
// viewport (Design view = skin at native px, Frame preview = full frame)
// with the editing overlay on top: per-element bounds (toggleable), the
// selection box, a MouseArea that forwards press/drag/release to the
// backend in image pixels, and keyboard handling (arrow nudge, Delete,
// Cmd/Ctrl-Z/Shift-Z, Cmd/Ctrl-D, Escape; Phase 5: Cmd/Ctrl-A/C/X/V,
// Cmd/Ctrl-]/[ for z-order). Phase 5 also draws the secondary selection
// boxes and the marquee, and forwards click modifiers for multi-select.
//
// Same performance posture as Color's own canvas: the selection/bounds
// rectangles are plain QML items driven by arithmetic-only backend
// properties, and the rendered image is only re-baked on release.
import QtQuick
import QtQuick.Controls

Rectangle {
    id: viewport
    color: "#141414"
    border.color: activeFocus ? "#3B82F6" : "#2A2A2A"
    border.width: 1
    clip: true
    focus: true

    onWidthChanged: overlayDesignerBackend.setViewportSize(width - 2, height - 2)
    onHeightChanged: overlayDesignerBackend.setViewportSize(width - 2, height - 2)
    Component.onCompleted: overlayDesignerBackend.setViewportSize(width - 2, height - 2)

    Keys.onPressed: (event) => {
        const ctrl = (event.modifiers & Qt.ControlModifier) || (event.modifiers & Qt.MetaModifier)
        const step = (event.modifiers & Qt.ShiftModifier) ? 10 : 1
        if (ctrl && event.key === Qt.Key_Z) {
            if (event.modifiers & Qt.ShiftModifier)
                overlayDesignerBackend.redo()
            else
                overlayDesignerBackend.undo()
            event.accepted = true
        } else if (ctrl && event.key === Qt.Key_D) {
            overlayDesignerBackend.duplicateSelected()
            event.accepted = true
        } else if (ctrl && event.key === Qt.Key_A) {
            overlayDesignerBackend.selectAll(); event.accepted = true
        } else if (ctrl && event.key === Qt.Key_C) {
            overlayDesignerBackend.copySelected(); event.accepted = true
        } else if (ctrl && event.key === Qt.Key_X) {
            overlayDesignerBackend.cutSelected(); event.accepted = true
        } else if (ctrl && event.key === Qt.Key_V) {
            overlayDesignerBackend.paste(); event.accepted = true
        } else if (ctrl && event.key === Qt.Key_BracketRight) {
            if (event.modifiers & Qt.ShiftModifier) overlayDesignerBackend.bringToFront()
            else overlayDesignerBackend.moveSelectedLayer(1)
            event.accepted = true
        } else if (ctrl && event.key === Qt.Key_BracketLeft) {
            if (event.modifiers & Qt.ShiftModifier) overlayDesignerBackend.sendToBack()
            else overlayDesignerBackend.moveSelectedLayer(-1)
            event.accepted = true
        } else if (event.key === Qt.Key_Left) {
            overlayDesignerBackend.nudgeSelected(-step, 0); event.accepted = true
        } else if (event.key === Qt.Key_Right) {
            overlayDesignerBackend.nudgeSelected(step, 0); event.accepted = true
        } else if (event.key === Qt.Key_Up) {
            overlayDesignerBackend.nudgeSelected(0, -step); event.accepted = true
        } else if (event.key === Qt.Key_Down) {
            overlayDesignerBackend.nudgeSelected(0, step); event.accepted = true
        } else if (event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace) {
            overlayDesignerBackend.removeSelected(); event.accepted = true
        } else if (event.key === Qt.Key_Escape) {
            overlayDesignerBackend.clearSelection(); event.accepted = true
        } else if (!ctrl && (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal)) {
            overlayDesignerBackend.resizeSelected(1); event.accepted = true
        } else if (!ctrl && (event.key === Qt.Key_Minus || event.key === Qt.Key_Underscore)) {
            overlayDesignerBackend.resizeSelected(-1); event.accepted = true
        }
    }

    Flickable {
        id: canvasFlick
        anchors.fill: parent
        anchors.margins: 1
        contentWidth: Math.max(width, canvasImage.width)
        contentHeight: Math.max(height, canvasImage.height)
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

        Item {
            width: canvasFlick.contentWidth
            height: canvasFlick.contentHeight

            // Click on the dark area around the image: focus + deselect.
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    viewport.forceActiveFocus()
                    overlayDesignerBackend.clearSelection()
                }
            }

            Image {
                id: canvasImage
                // Centered while smaller than the viewport, scrollable once larger.
                x: Math.max(0, (canvasFlick.width - width) / 2)
                y: Math.max(0, (canvasFlick.height - height) / 2)
                width: overlayDesignerBackend.canvasDisplayWidth
                height: overlayDesignerBackend.canvasDisplayHeight
                source: overlayDesignerBackend.previewImageSource
                fillMode: Image.Stretch
                cache: false
                asynchronous: false
                smooth: overlayDesignerBackend.viewMode === "frame"
            }

            // Editing overlay - shares the image's origin, so every
            // coordinate here is in canvas display pixels as the backend
            // defines them.
            Item {
                id: overlayLayer
                x: canvasImage.x
                y: canvasImage.y
                width: canvasImage.width
                height: canvasImage.height

                Repeater {
                    model: overlayDesignerBackend.showBounds ? overlayDesignerBackend.elementBoxes : []
                    delegate: Rectangle {
                        x: modelData[0]
                        y: modelData[1]
                        width: modelData[2]
                        height: modelData[3]
                        color: "transparent"
                        border.color: "#663B82F6"
                        border.width: 1
                    }
                }

                Repeater {
                    model: overlayDesignerBackend.secondarySelectionBoxes
                    delegate: Rectangle {
                        x: modelData[0]
                        y: modelData[1]
                        width: modelData[2]
                        height: modelData[3]
                        color: "#183B82F6"
                        border.color: "#3B82F6"
                        border.width: 1
                    }
                }

                Rectangle {
                    visible: overlayDesignerBackend.marqueeBox.visible
                    x: overlayDesignerBackend.marqueeBox.x
                    y: overlayDesignerBackend.marqueeBox.y
                    width: overlayDesignerBackend.marqueeBox.w
                    height: overlayDesignerBackend.marqueeBox.h
                    color: "#2222C55E"
                    border.color: "#22C55E"
                    border.width: 1
                }

                Rectangle {
                    visible: overlayDesignerBackend.selectionBoxVisible
                    x: overlayDesignerBackend.selectionBoxX
                    y: overlayDesignerBackend.selectionBoxY
                    width: overlayDesignerBackend.selectionBoxW
                    height: overlayDesignerBackend.selectionBoxH
                    color: "#223B82F6"
                    border.color: "#3B82F6"
                    border.width: 2

                    Rectangle {
                        anchors.left: parent.left
                        anchors.bottom: parent.top
                        anchors.bottomMargin: 2
                        width: selectionLabel.implicitWidth + 8
                        height: selectionLabel.implicitHeight + 4
                        color: "#3B82F6"
                        radius: 2
                        Label {
                            id: selectionLabel
                            anchors.centerIn: parent
                            text: overlayDesignerBackend.selectionBoxLabel
                            color: "white"
                            font.pixelSize: 11
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    // The page's canvas sits in a Flickable - without this the
                    // Flickable steals the grab a few pixels into any drag.
                    preventStealing: true
                    acceptedButtons: Qt.LeftButton
                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.ArrowCursor
                    onPressed: (mouse) => {
                        viewport.forceActiveFocus()
                        overlayDesignerBackend.onCanvasPressedMod(mouse.x, mouse.y, mouse.modifiers)
                    }
                    onPositionChanged: (mouse) => {
                        if (pressed)
                            overlayDesignerBackend.onCanvasDragged(mouse.x, mouse.y)
                    }
                    onReleased: overlayDesignerBackend.onCanvasReleased()
                }
            }
        }
    }

    Label {
        anchors.centerIn: parent
        visible: !overlayDesignerBackend.hasDocument
        text: "No template selected"
        color: "#808080"
    }
}
