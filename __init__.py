# Copyright (c) 2026 UltiMaker / Community
# Released under the terms of the LGPLv3 or higher.

from . import LayerTimingPlugin


def getMetaData():
    return {}


def register(app):
    return {"extension": LayerTimingPlugin.LayerTimingPlugin()}
