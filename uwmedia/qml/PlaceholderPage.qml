// Stand-in for a page not yet ported to QML - see qml_development.md's
// per-page phases. Each phase replaces one of these (in main.qml's
// StackLayout) with a real <Name>Page.qml + Python backend.
import QtQuick
import QtQuick.Controls

Item {
    property string pageName: ""

    Label {
        anchors.centerIn: parent
        text: pageName + " – not yet ported to QML"
        color: "#9AA0A6"
        font.pixelSize: 16
    }
}
