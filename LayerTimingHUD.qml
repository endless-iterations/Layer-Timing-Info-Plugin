// Copyright (c) 2026 UltiMaker / Community
// Released under the terms of the LGPLv3 or higher.

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.1

import UM 1.5 as UM
import Cura 1.0 as Cura

Item
{
    id: timingHUD

    // Only display during the Preview stage when simulation layer data is active and sliders are present
    visible: CuraApplication.platformActivity && (manager ? manager.hasTimingInfo && manager.isPreviewActive : false) && (manager && manager.playButtonItem !== null && manager.layerSliderItem !== null)

    // Aligned to the 3D viewport canvas:
    // Left edge (X) is aligned with the leftmost point of the play button
    // Bottom edge (Y) is aligned with Layer 0 of the vertical layer slider
    x: manager && manager.playButtonItem ? manager.playButtonItem.x : 0
    y: manager && manager.layerSliderItem ? Math.round(manager.layerSliderItem.y + manager.layerSliderItem.height - height) : 0

    width: timingColumn.width
    height: timingColumn.height

    // Active layer number linked directly to the slider handle value
    readonly property int activeLayer: (manager && manager.layerSliderItem) ? Math.round(manager.layerSliderItem.upperValue) : ((typeof UM !== "undefined" && UM.SimulationView) ? UM.SimulationView.currentLayer : (manager ? manager.currentLayer : 0))

    Connections
    {
        target: typeof UM !== "undefined" ? UM.SimulationView : null
        ignoreUnknownSignals: true
        function onCurrentLayerChanged() {}
        function onMaxLayersChanged() {}
    }

    UM.I18nCatalog
    {
        id: catalog
        name: "cura"
    }

    Column
    {
        id: timingColumn
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        spacing: UM.Theme.getSize("thin_margin").height

        UM.Label
        {
            id: elapsedLabel
            text: catalog.i18nc("@label", "Elapsed: ") + (manager ? manager.getElapsedTime(timingHUD.activeLayer) : "0s")
            color: UM.Theme.getColor("text_scene")
            horizontalAlignment: Text.AlignLeft
        }

        UM.Label
        {
            id: layerLabel
            text: catalog.i18nc("@label", "Layer: ") + (manager ? manager.getLayerDuration(timingHUD.activeLayer) : "0s")
            color: UM.Theme.getColor("text_scene")
            horizontalAlignment: Text.AlignLeft
        }

        UM.Label
        {
            id: remainingLabel
            text: catalog.i18nc("@label", "Remaining: ") + (manager ? manager.getRemainingTime(timingHUD.activeLayer) : "0s")
            color: UM.Theme.getColor("text_scene")
            horizontalAlignment: Text.AlignLeft
        }
    }
}
