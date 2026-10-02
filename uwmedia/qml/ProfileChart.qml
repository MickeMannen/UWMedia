// The depth profile of one dive: a legend row and a Canvas drawing depth over
// time, plus the deco ceiling when the log has one. Taken from DiveSync's
// ProfileChart.qml (dive_sync repo); used by LogViewerPage.qml. Hides itself
// for fewer than two samples. ``samples`` is a list of {time (s), depth (m),
// ceiling (m, 0 for none)} - log_viewer_backend.dive_details' "samples".
// Temperature is not plotted: logs record it in whole degrees, so the curve
// is a staircase that reads as noise next to the depth line.
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: chart
    property var samples: []
    property bool showCeiling: false
    property int chartHeight: 180
    readonly property color depthColor: "#00A6ED"
    readonly property color ceilingColor: "#F59E0B"
    readonly property color axisColor: "#444444"
    readonly property color labelColor: "#9AA0A6"
    readonly property bool hasProfile: (samples || []).length > 1
    spacing: 4
    visible: hasProfile
    onSamplesChanged: canvas.requestPaint()
    onShowCeilingChanged: canvas.requestPaint()

    RowLayout {
        spacing: 12
        Text { text: "Depth profile"; color: chart.labelColor; font.pixelSize: 11 }
        Text { text: "● depth"; color: chart.depthColor; font.pixelSize: 11 }
        Text { visible: chart.showCeiling; text: "● ceiling"; color: chart.ceilingColor; font.pixelSize: 11 }
    }
    Canvas {
        id: canvas
        Layout.fillWidth: true
        Layout.preferredHeight: chart.chartHeight
        // drawn once into a texture off the GUI thread, then only moved
        // while the page scrolls
        renderTarget: Canvas.FramebufferObject
        renderStrategy: Canvas.Cooperative
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var samples = chart.samples || []
            if (samples.length < 2 || width <= 0 || height <= 0) return

            var pad = { left: 44, right: 12, top: 10, bottom: 20 }
            var plotW = width - pad.left - pad.right
            var plotH = height - pad.top - pad.bottom
            if (plotW <= 0 || plotH <= 0) return

            var t0 = samples[0].time || 0
            var maxTime = (samples[samples.length - 1].time || 0) - t0
            var maxDepth = 0
            for (var i = 0; i < samples.length; i++) {
                if (samples[i].depth > maxDepth) maxDepth = samples[i].depth
            }
            if (maxDepth <= 0) maxDepth = 1
            if (maxTime <= 0) maxTime = 1

            function xAt(t) { return pad.left + ((t - t0) / maxTime) * plotW }
            function yAt(d) { return pad.top + (d / maxDepth) * plotH }

            ctx.strokeStyle = chart.axisColor
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(pad.left, pad.top)
            ctx.lineTo(pad.left, pad.top + plotH)
            ctx.lineTo(pad.left + plotW, pad.top + plotH)
            ctx.stroke()

            ctx.strokeStyle = chart.depthColor
            ctx.lineWidth = 1.5
            ctx.beginPath()
            for (var j = 0; j < samples.length; j++) {
                var x = xAt(samples[j].time || 0)
                var y = yAt(samples[j].depth)
                if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
            }
            ctx.stroke()

            // the ceiling is drawn only where there is one, in separate runs
            if (chart.showCeiling) {
                ctx.strokeStyle = chart.ceilingColor
                ctx.lineWidth = 1.2
                ctx.beginPath()
                var drawing = false
                for (var k = 0; k < samples.length; k++) {
                    var c = samples[k].ceiling || 0
                    if (c <= 0) { drawing = false; continue }
                    var cx = xAt(samples[k].time || 0)
                    var cy = yAt(c)
                    if (!drawing) { ctx.moveTo(cx, cy); drawing = true } else ctx.lineTo(cx, cy)
                }
                ctx.stroke()
            }

            ctx.fillStyle = chart.labelColor
            ctx.font = "10px sans-serif"
            ctx.fillText("0 m", 4, pad.top + 8)
            ctx.fillText(maxDepth.toFixed(1) + " m", 4, pad.top + plotH)
            ctx.fillText(Math.round(maxTime / 60) + " min", pad.left + plotW - 30, height - 4)
        }
    }
}
