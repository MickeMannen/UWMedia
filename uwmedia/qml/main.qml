// Real app shell - Phase 0 of qml_development.md ("Option B, whole-app QML
// shell"). Replaces uwmedia/app.py's old MainWindow (QListWidget
// nav + QStackedWidget of QWidget pages) entirely. Adapted from the
// throwaway prototype at uwmedia/prototypes/qml/main.qml - same
// nav-rail/StackLayout shape, production naming (no "prototype" wording),
// real page list matching app.py's old PAGES order exactly.
//
// All eleven pages are real now (Phases 1-11, qml_development.md) - each is
// its own <Name>Page.qml + Python QObject backend under
// uwmedia/backends/. PlaceholderPage.qml is no longer used by
// this shell but stays in the tree as a stand-in shape for any future
// page. Nothing under uwmedia/pages/ (the old QWidget pages) is
// used by this shell - Option B has no QQuickWidget bridge - those files
// stay only as reference material for how each phase's business logic
// was ported, per qml_development.md.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1280
    height: 720
    visible: true
    title: "UWMedia"

    Material.theme: Material.Dark
    Material.accent: "#00A6ED"
    Material.primary: "#00A6ED"
    Material.background: "#1F1F1F"

    // Matches this app's own former PAGES order exactly (itself
    // matching the original Toga app's SECTIONS order, back when
    // this was uwmedia_qt_beta - see qml_development.md).
    property var navPages: [
        "🎨  Color",
        "🧩  Overlay Generator",
        "🎬  Convertion",
        "🖌  Color Tuning",
        "🏷  Tag Editor",
        "📄  Log Viewer",
        "✏️  Overlay Designer",
        "📈  Dive Profile Builder",
        "⚙️  Advanced",
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
                // Tight side margins/padding so the longest bold labels
                // ("Overlay Generator", "Dive Profile Builder") fit the
                // 220 px rail without eliding.
                anchors.margins: 4
                spacing: 2

                Repeater {
                    model: window.navPages
                    delegate: ItemDelegate {
                        Layout.fillWidth: true
                        text: modelData
                        highlighted: index === pageStack.currentIndex
                        font.pixelSize: 16
                        font.bold: highlighted
                        leftPadding: 8
                        rightPadding: 4
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
            OverlayGeneratorPage {}
            ConvertionPage {}
            ColorTuningPage {}
            TagEditorPage {}
            LogViewerPage {}
            OverlayDesignerPage {}
            DiveProfilePage {}
            AdvancedPage {}
            AboutPage {}
        }
    }
}
