# -*- coding: utf-8 -*-
"""api 包：REST + WebSocket"""
from .rooms import router as rooms_router
from .stats import router as stats_router
from .platforms import router as platforms_router
from .ws import router as ws_router

__all__ = ["rooms_router", "stats_router", "ws_router", "platforms_router"]