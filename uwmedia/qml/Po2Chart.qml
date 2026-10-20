// A rebreather dive's PO2 strip under the depth profile: the PO2, the
// setpoint in force and the three O2 cells over time, with the stretches on
// a bailout shaded. ``samples`` is log_viewer_backend.dive_details'
// "po2_samples" - {time (s), po2, setpoint, c1, c2, c3 (bar, -1 for none),
// bailout (bool)}; the strip hides itself when there are none.
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: chart
    property var samples: []
    property int chartHeight: 110
    readonly property color po2Color: "#E5E7EB"
    readonly property color setpointColor: "#22C55E"
    readonly property var cellColors: ["#38BDF8", "#A78BFA", "#F472B6"]
    readonly property color bailoutColor: "#3A3418"
    readonly property color axisColor: "#444444"
    readonly property color labelColor: "#9AA0A6"
    readonly property bool hasCells: {
        var s = samples || []
        for (var i = 0; i < s.length; i++) if (s[i].c1 >= 0) return true
        return false
    }
    spacing: 4
    visible: (samples || []).length > 1
    onSamplesChanged: canvas.requestPaint()

    RowLayout {
        spacing: 12
        Text { text: "PO₂ (bar)"; color: chart.labelColor; font.pixelSize: 11 }
        Text { text: "● PO₂"; color: chart.po2Color; font.pixelSize: 11 }
        Text { text: "● setpoint"; color: chart.setpointColor; font.pixelSize: 11 }
        Text { visible: chart.hasCells; text: "● cells"; color: chart.cellColors[0]; font.pixelSize: 11 }
        Text { text: "▇ bailout"; color: "#8A7A2A"; font.pixelSize: 11 }
    }
    Canvas {
        id: canvas
        Layout.fillWidth: true
        Layout.preferredHeight: chart.chartHeight
        renderTarget: Canvas.FramebufferObject
        renderStrategy: Canvas.Cooperative
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var samples = chart.samples || []
            if (samples.length < 2 || width <= 0 || height <= 0) return

            // the same left/right padding as ProfileChart, so the two line up
            var pad = { left: 44, right: 12, top: 6, bottom: 14 }
            var plotW = width - pad.left - pad.right
            var plotH = height - pad.top - pad.bottom
            if (plotW <= 0 || plotH <= 0) return
            var t0 = samples[0].time || 0
            var maxTime = Math.max(1, (samples[samples.length - 1].time || 0) - t0)
            var maxPo2 = 1.6
            for (let i = 0; i < samples.length; i++) {
                for (const key of ["po2", "setpoint", "c1", "c2", "c3"])
                    if (samples[i][key] > maxPo2) maxPo2 = samples[i][key]
            }
            function xAt(t) { return pad.left + ((t - t0) / maxTime) * plotW }
            function yAt(v) { return pad.top + plotH - (v / maxPo2) * plotH }

            ctx.fillStyle = chart.bailoutColor
            for (let b = 0; b < samples.length - 1; b++) {
                if (!samples[b].bailout) continue
                ctx.fillRect(xAt(samples[b].time), pad.top, Math.max(1, xAt(samples[b + 1].time) - xAt(samples[b].time)), plotH)
            }

            ctx.strokeStyle = chart.axisColor
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(pad.left, pad.top)
            ctx.lineTo(pad.left, pad.top + plotH)
            ctx.lineTo(pad.left + plotW, pad.top + plotH)
            ctx.stroke()

            function series(key, color, lineWidth) {
                ctx.strokeStyle = color
                ctx.lineWidth = lineWidth
                ctx.beginPath()
                let drawing = false
                for (let j = 0; j < samples.length; j++) {
                    const v = samples[j][key]
                    if (v < 0) { drawing = false; continue }
                    const x = xAt(samples[j].time || 0), y = yAt(v)
                    if (!drawing) { ctx.moveTo(x, y); drawing = true } else ctx.lineTo(x, y)
                }
                ctx.stroke()
            }
            for (let c = 0; c < 3; c++) series("c" + (c + 1), chart.cellColors[c], 1)
            series("setpoint", chart.setpointColor, 1.5)
            series("po2", chart.po2Color, 1.2)

            ctx.fillStyle = chart.labelColor
            ctx.font = "10px sans-serif"
            ctx.fillText(maxPo2.toFixed(1), 4, pad.top + 8)
            ctx.fillText("0", 4, pad.top + plotH)
        }
    }
}
