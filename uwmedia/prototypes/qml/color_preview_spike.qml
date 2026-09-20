// Phase 0 spike - see qml_color_preview_spike.py's own module docstring
// for what this proves and why. Drag anywhere on the image to move the
// real composited HUD overlay; the status line's redraw counter proves
// each mouse-move round-trips through Python's real draw_hud() pipeline,
// not a cached/static image.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material

ApplicationWindow {
    id: window
    width: 860
    height: 540
    visible: true
    title: "QML Color preview spike (Phase 0)"

    Material.theme: Material.Dark
    Material.accent: "#00A6ED"
    Material.background: "#1F1F1F"

    Column {
        anchors.centerIn: parent
        spacing: 10

        Rectangle {
            width: 800
            height: 450
            color: "black"
            border.color: "#444"

            Image {
                id: previewImage
                anchors.fill: parent
                source: backend.imageSource
                fillMode: Image.Stretch
                cache: false
                asynchronous: false
            }

            MouseArea {
                anchors.fill: parent
                onPressed: (mouse) => backend.setOverlayPosition(mouse.x / width, mouse.y / height)
                onPositionChanged: (mouse) => {
                    if (pressed)
                        backend.setOverlayPosition(mouse.x / width, mouse.y / height)
                }
            }
        }

        Label {
            text: backend.statusText
            color: "#9AA0A6"
        }

        Label {
            text: "Drag anywhere on the frame above to move the overlay"
            color: "#6B7280"
            font.pixelSize: 12
        }
    }
}
