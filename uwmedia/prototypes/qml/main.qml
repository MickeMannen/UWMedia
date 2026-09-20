// Visual prototype: the Color page re-skinned with Qt Quick Controls 2
// (Material style) instead of plain QWidget/QListWidget. Same throwaway,
// not-wired-into-the-real-app status as ../fluent_color_page.py - see that
// file's own module docstring for the full disclaimer. This is the QML/Qt
// Quick sibling, built to compare side by side against the Widgets+Fluent
// approach before picking a direction.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1300
    height: 820
    visible: true
    title: "UWMedia Qt (beta) – QML prototype"

    Material.theme: Material.Dark
    Material.accent: "#00A6ED"
    Material.primary: "#00A6ED"
    Material.background: "#1F1F1F"

    property var navPages: [
        "🎨  Color",
        "🧩  Overlay Generator",
        "🎬  Convertion",
        "🖌  Color Tuning",
        "🏷  Tag Editor",
        "📄  Log Viewer",
        "✏️  HUD Designer",
        "📈  Dive Profile Builder",
        "⚙️  Advanced",
        "🕒  Activity",
        "ℹ️  About"
    ]

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // --- Nav rail ------------------------------------------------
        Rectangle {
            Layout.preferredWidth: 220
            Layout.fillHeight: true
            color: "#171717"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 2

                Repeater {
                    model: window.navPages
                    delegate: ItemDelegate {
                        Layout.fillWidth: true
                        text: modelData
                        highlighted: index === pageStack.currentIndex
                        onClicked: pageStack.currentIndex = index
                    }
                }
                Item { Layout.fillHeight: true }
            }
        }

        // --- Page content ---------------------------------------------
        StackLayout {
            id: pageStack
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: 0

            ColorPage {}
            PlaceholderPage { pageName: "Overlay Generator" }
            PlaceholderPage { pageName: "Convertion" }
            PlaceholderPage { pageName: "Color Tuning" }
            PlaceholderPage { pageName: "Tag Editor" }
            PlaceholderPage { pageName: "Log Viewer" }
            PlaceholderPage { pageName: "HUD Designer" }
            PlaceholderPage { pageName: "Dive Profile Builder" }
            PlaceholderPage { pageName: "Advanced" }
            PlaceholderPage { pageName: "Activity" }
            PlaceholderPage { pageName: "About" }
        }
    }
}
