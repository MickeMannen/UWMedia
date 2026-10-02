// A titled card: an uppercase title row (with optional header controls
// beside it) over a column of content. Taken from DiveSync's Card.qml
// (dive_sync repo, desktop/qml/Card.qml) with UWMedia's dark palette in
// place of its Theme singleton - this folder has no qmldir to register one.
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: card
    property string title: ""
    default property alias content: body.data
    // Controls that belong beside the title rather than in the body. Assign
    // one item or a list of them; an Item { Layout.fillWidth: true } pushes
    // later ones to the right.
    property alias headerContent: headerExtras.data
    readonly property int pad: 14
    color: "#262626"
    border.color: "#333333"
    radius: 8
    Layout.fillWidth: true
    implicitHeight: column.implicitHeight + pad * 2

    ColumnLayout {
        id: column
        // Filled, not just pinned to the top, so a card given a height by its
        // layout (Layout.fillHeight) passes it on to a fillHeight child.
        anchors { fill: parent; margins: card.pad }
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            visible: card.title !== "" || headerExtras.children.length > 0
            Text {
                visible: card.title !== ""
                text: card.title
                color: "#9AA0A6"
                font.pixelSize: 12
                font.capitalization: Font.AllUppercase
                font.letterSpacing: 1
            }
            RowLayout { id: headerExtras; spacing: 8; Layout.fillWidth: true }
        }
        ColumnLayout { id: body; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8 }
    }
}
