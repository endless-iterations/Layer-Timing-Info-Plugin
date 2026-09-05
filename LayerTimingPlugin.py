# Copyright (c) 2026 UltiMaker / Community
# Released under the terms of the LGPLv3 or higher.

import os
from typing import Dict, List, Optional, cast

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot, QTimer

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.PluginRegistry import PluginRegistry
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.i18n import i18nCatalog
from cura.CuraApplication import CuraApplication
from cura.Scene.GCodeListDecorator import GCodeListDecorator

i18n_catalog = i18nCatalog("cura")


class LayerTimingPlugin(QObject, Extension):
    """Extension plugin that calculates and displays real-time layer print times in the Preview stage."""

    timingChanged = pyqtSignal()
    currentLayerChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        Extension.__init__(self)

        self.setMenuName(i18n_catalog.i18nc("@item:inmenu", "Layer Timing"))

        self._layer_elapsed_times: Dict[int, float] = {}
        self._total_print_time: float = 0.0
        self._timing_cache_valid: bool = False
        self._current_layer: int = 0
        self._hud_view = None
        self._connected_view = None

        # Update debounce timer
        self._update_timer = QTimer()
        self._update_timer.setInterval(200)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._updateTimingCache)

        # Stage HUD attach timer
        self._attach_timer = QTimer()
        self._attach_timer.setInterval(100)
        self._attach_timer.setSingleShot(True)
        self._attach_timer.timeout.connect(self._attachHUDToStage)

        # Connect application signals
        app = CuraApplication.getInstance()
        app.initializationFinished.connect(self._onAppInitialized)
        app.mainWindowChanged.connect(self._onMainWindowChanged)

        # Controller, stage and view signals
        controller = app.getController()
        controller.activeStageChanged.connect(self._onActiveStageChanged)
        controller.activeViewChanged.connect(self._onActiveViewChanged)
        controller.getScene().sceneChanged.connect(self._onSceneChanged)

        # Backend slice signal
        app.getBackend().backendStateChange.connect(self._onBackendStateChanged)

    def _onAppInitialized(self) -> None:
        self._attachHUDToStage()
        self._onActiveViewChanged()
        self._updateTimingCache()

    def _onMainWindowChanged(self) -> None:
        self._attach_timer.start()

    def _onActiveStageChanged(self) -> None:
        self._onActiveViewChanged()
        self._attach_timer.start()
        self._updateTimingCache()

    def _onActiveViewChanged(self) -> None:
        controller = CuraApplication.getInstance().getController()
        if not controller:
            return
        active_view = controller.getActiveView()
        if active_view != self._connected_view:
            if self._connected_view and hasattr(self._connected_view, "currentLayerNumChanged"):
                try:
                    self._connected_view.currentLayerNumChanged.disconnect(self._onLayerChanged)
                except Exception:
                    pass
            self._connected_view = active_view
            if self._connected_view and hasattr(self._connected_view, "currentLayerNumChanged"):
                try:
                    self._connected_view.currentLayerNumChanged.connect(self._onLayerChanged)
                except Exception:
                    pass
        self._attach_timer.start()
        self.timingChanged.emit()
        self.currentLayerChanged.emit()

    def _onLayerChanged(self, *args, **kwargs) -> None:
        self.currentLayerChanged.emit()

    def _onBackendStateChanged(self, state) -> None:
        self._update_timer.start()

    def _onSceneChanged(self, *args, **kwargs) -> None:
        self._update_timer.start()

    def _findSimulationViewComponent(self, root_item):
        if root_item is None:
            return None
        if hasattr(root_item, "property") and root_item.property("layerSliderSafeYMin") is not None:
            return root_item
        if hasattr(root_item, "childItems"):
            for child in root_item.childItems():
                res = self._findSimulationViewComponent(child)
                if res is not None:
                    return res
        return None

    def _attachHUDToStage(self) -> None:
        try:
            app = CuraApplication.getInstance()
            main_window = app.getMainWindow()
            if main_window is None:
                return

            content_item = main_window.contentItem() if callable(getattr(main_window, "contentItem", None)) else getattr(main_window, "contentItem", main_window)
            if content_item is None:
                return

            sim_view_item = self._findSimulationViewComponent(content_item)
            if sim_view_item is None:
                # If not found yet and in preview stage, retry briefly
                if self.isPreviewActive:
                    self._attach_timer.start()
                return

            # Find playButton and layerSlider inside SimulationViewMainComponent
            plugin_path = PluginRegistry.getInstance().getPluginPath("LayerTimingPlugin")
            if not plugin_path:
                return

            qml_path = os.path.join(plugin_path, "LayerTimingHUD.qml")
            if not os.path.exists(qml_path):
                return

            if self._hud_view is None:
                self._hud_view = app.createQmlComponent(qml_path, {"manager": self})

            if self._hud_view is not None:
                if hasattr(self._hud_view, "setParentItem"):
                    self._hud_view.setParentItem(sim_view_item)
                self._hud_view.setProperty("parent", sim_view_item)
        except Exception as e:
            Logger.log("e", f"LayerTimingPlugin._attachHUDToStage error: {e}")

    def _updateTimingCache(self) -> None:
        """Parses and caches layer timing information from gcode_dict or GCodeListDecorator."""
        scene = CuraApplication.getInstance().getController().getScene()

        gcode_list: List[str] = []
        if hasattr(scene, "gcode_dict"):
            gcode_dict = getattr(scene, "gcode_dict", {})
            if gcode_dict:
                active_build_plate = 0
                try:
                    multi_build_plate = CuraApplication.getInstance().getMultiBuildPlateModel()
                    if multi_build_plate:
                        active_build_plate = multi_build_plate.activeBuildPlate
                except Exception:
                    pass
                gcode_list = gcode_dict.get(active_build_plate, [])
                if not gcode_list and len(gcode_dict) > 0:
                    gcode_list = next(iter(gcode_dict.values()))

        if not gcode_list:
            for node in DepthFirstIterator(scene.getRoot()):
                decorator = node.getDecorator(GCodeListDecorator)
                if decorator is not None:
                    gcode_list = decorator.getGCodeList()
                    if gcode_list:
                        break

        if not gcode_list:
            self._layer_elapsed_times.clear()
            self._total_print_time = 0.0
            self._timing_cache_valid = False
            self.timingChanged.emit()
            self.currentLayerChanged.emit()
            return

        self._layer_elapsed_times.clear()
        self._total_print_time = 0.0

        current_layer = -1
        for chunk in gcode_list:
            if not isinstance(chunk, str):
                continue
            for line in chunk.splitlines():
                line = line.strip()
                if line.startswith(";TIME:"):
                    try:
                        self._total_print_time = float(line.split(":")[1])
                    except (ValueError, IndexError):
                        pass
                elif line.startswith(";LAYER:"):
                    try:
                        current_layer = int(line.split(":")[1])
                    except (ValueError, IndexError):
                        pass
                elif line.startswith(";TIME_ELAPSED:"):
                    try:
                        elapsed = float(line.split(":")[1])
                        if current_layer >= 0:
                            self._layer_elapsed_times[current_layer] = elapsed
                    except (ValueError, IndexError):
                        pass

        if self._total_print_time == 0.0:
            if self._layer_elapsed_times:
                self._total_print_time = max(self._layer_elapsed_times.values())
            else:
                try:
                    print_info = CuraApplication.getInstance().getPrintInformation()
                    if print_info and hasattr(print_info, "currentPrintTime"):
                        self._total_print_time = float(print_info.currentPrintTime.getDuration())
                except Exception:
                    pass

        self._timing_cache_valid = len(self._layer_elapsed_times) > 0
        self.timingChanged.emit()
        self.currentLayerChanged.emit()

    @staticmethod
    def formatDuration(seconds: float) -> str:
        """Formats seconds into dynamic units without leading zeros: e.g. 45s, 1m 5s, 1h, 1h 1m 5s."""
        total_seconds = int(round(seconds))
        if total_seconds < 0:
            total_seconds = 0
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)

    @pyqtProperty(bool, notify=timingChanged)
    def hasTimingInfo(self) -> bool:
        return self._timing_cache_valid and len(self._layer_elapsed_times) > 0

    @pyqtProperty(bool, notify=timingChanged)
    def isPreviewActive(self) -> bool:
        controller = CuraApplication.getInstance().getController()
        if not controller:
            return False
        active_stage = controller.getActiveStage()
        if active_stage and active_stage.getPluginId() == "PreviewStage":
            return True
        active_view = controller.getActiveView()
        return active_view is not None and active_view.getPluginId() == "SimulationView"

    @pyqtProperty(int, notify=currentLayerChanged)
    def currentLayer(self) -> int:
        controller = CuraApplication.getInstance().getController()
        if controller:
            active_view = controller.getActiveView()
            if active_view and hasattr(active_view, "getCurrentLayer"):
                return active_view.getCurrentLayer()
        return self._current_layer

    @pyqtProperty(str, notify=currentLayerChanged)
    def currentElapsedTime(self) -> str:
        return self.getElapsedTime(self.currentLayer)

    @pyqtProperty(str, notify=currentLayerChanged)
    def currentLayerDuration(self) -> str:
        return self.getLayerDuration(self.currentLayer)

    @pyqtProperty(str, notify=currentLayerChanged)
    def currentRemainingTime(self) -> str:
        return self.getRemainingTime(self.currentLayer)

    @pyqtSlot(int, result=str)
    def getElapsedTime(self, layer_number: int) -> str:
        if not self._layer_elapsed_times:
            return "0s"
        if layer_number in self._layer_elapsed_times:
            elapsed = self._layer_elapsed_times[layer_number]
        elif layer_number < 0:
            elapsed = 0.0
        else:
            max_layer = max(self._layer_elapsed_times.keys())
            if layer_number >= max_layer:
                elapsed = self._total_print_time if self._total_print_time > 0 else self._layer_elapsed_times.get(max_layer, 0.0)
            else:
                prev_layers = [l for l in self._layer_elapsed_times.keys() if l <= layer_number]
                elapsed = self._layer_elapsed_times[max(prev_layers)] if prev_layers else 0.0
        return self.formatDuration(elapsed)

    @pyqtSlot(int, result=str)
    def getLayerDuration(self, layer_number: int) -> str:
        if not self._layer_elapsed_times:
            return "0s"
        current_elapsed = self._getLayerElapsedSeconds(layer_number)
        prev_elapsed = self._getLayerElapsedSeconds(layer_number - 1)
        duration = max(0.0, current_elapsed - prev_elapsed)
        return self.formatDuration(duration)

    @pyqtSlot(int, result=str)
    def getRemainingTime(self, layer_number: int) -> str:
        if not self._layer_elapsed_times:
            return "0s"
        current_elapsed = self._getLayerElapsedSeconds(layer_number)
        total = self._total_print_time if self._total_print_time > 0 else max(self._layer_elapsed_times.values(), default=0.0)
        remaining = max(0.0, total - current_elapsed)
        return self.formatDuration(remaining)

    def _getLayerElapsedSeconds(self, layer_number: int) -> float:
        if not self._layer_elapsed_times:
            return 0.0
        if layer_number in self._layer_elapsed_times:
            return self._layer_elapsed_times[layer_number]
        if layer_number < 0:
            return 0.0
        max_layer = max(self._layer_elapsed_times.keys())
        if layer_number >= max_layer:
            return self._total_print_time if self._total_print_time > 0 else self._layer_elapsed_times.get(max_layer, 0.0)
        prev_layers = [l for l in self._layer_elapsed_times.keys() if l <= layer_number]
        if prev_layers:
            return self._layer_elapsed_times[max(prev_layers)]
        return 0.0
