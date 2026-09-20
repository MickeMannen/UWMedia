// Real About page - qml_development.md Phase 11 (final page - completes
// every entry that started as a PlaceholderPage in main.qml). Backed by
// uwmedia/backends/about_backend.py's AboutBackend, exposed as
// "aboutBackend" (app.py). Matches uwmedia/pages/about_page.py
// (kept as reference only).
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Item {
    id: root
    width: 1060
    height: 720

    ScrollView {
        anchors.fill: parent
        anchors.margins: 20
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: Math.min(parent.width, 700)
            spacing: 16

            Label { text: "About"; font.pixelSize: 24; font.bold: true }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 4
                    Label { text: "UWMedia"; font.bold: true; font.pixelSize: 14 }
                    Label { text: "Version " + aboutBackend.appVersion; font.bold: true }
                    Label {
                        Layout.fillWidth: true
                        text: "Underwater media processor - color correction and dive telemetry overlays for videos and photos."
                        color: "#9AA0A6"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 8
                    Label { text: "Updates"; font.bold: true; font.pixelSize: 14 }
                    Button {
                        text: "Check for updates"
                        implicitWidth: 200
                        onClicked: aboutBackend.checkForUpdate()
                    }
                    Label {
                        Layout.fillWidth: true
                        text: aboutBackend.updateText
                        color: aboutBackend.updateColor
                        wrapMode: Text.WordWrap
                        visible: text.length > 0
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 4
                    Label { text: "License"; font.bold: true; font.pixelSize: 14 }
                    Label { text: "MIT License"; font.bold: true }
                    Label {
                        Layout.fillWidth: true
                        text: "Copyright (c) 2025 " + aboutBackend.authorName + ". See the LICENSE file in the repository for the full text."
                        color: "#9AA0A6"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 8
                    Label { text: "Third-Party Licenses"; font.bold: true; font.pixelSize: 14 }
                    Label {
                        Layout.fillWidth: true
                        text: "UWMedia invokes these as separate external programs, not linked libraries - this does not affect UWMedia's own MIT license above."
                        color: "#9AA0A6"
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: aboutBackend.thirdPartyLicenses
                        delegate: ColumnLayout {
                            id: licenseDelegate
                            Layout.fillWidth: true
                            required property var modelData
                            spacing: 2
                            Label {
                                Layout.fillWidth: true
                                text: licenseDelegate.modelData.versionLine
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }
                            Label {
                                Layout.fillWidth: true
                                text: licenseDelegate.modelData.licenseDesc
                                color: "#9AA0A6"
                                wrapMode: Text.WordWrap
                                visible: text.length > 0
                            }
                            Button {
                                text: "View license text"
                                implicitWidth: 160
                                visible: licenseDelegate.modelData.licensePath.length > 0
                                onClicked: aboutBackend.openLicense(licenseDelegate.modelData.licensePath)
                            }
                        }
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 4
                    Label { text: "Dependencies"; font.bold: true; font.pixelSize: 14 }
                    Repeater {
                        model: aboutBackend.dependencies
                        delegate: Label {
                            required property var modelData
                            text: "- " + modelData
                            color: "#9AA0A6"
                        }
                    }
                }
            }

            Pane {
                Layout.fillWidth: true
                Material.elevation: 1
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 8
                    Label { text: "Links"; font.bold: true; font.pixelSize: 14 }
                    Label { text: "By " + aboutBackend.authorName }
                    RowLayout {
                        spacing: 8
                        Button { text: "GitHub"; onClicked: aboutBackend.openGithub() }
                        Button { text: "YouTube"; onClicked: aboutBackend.openYoutube() }
                        Item { Layout.fillWidth: true }
                    }
                }
            }

            Item { Layout.preferredHeight: 20 }
        }
    }
}
