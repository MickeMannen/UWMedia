import QtQuick
import QtQuick.Controls

Item {
    property string pageName: ""

    Label {
        anchors.centerIn: parent
        text: pageName + " – not part of this prototype"
        color: "#9AA0A6"
        font.pixelSize: 16
    }
}
