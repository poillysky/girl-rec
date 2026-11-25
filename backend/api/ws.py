# -*- coding: utf-8 -*-
"""WebSocket 实时推送：把 EventCenter 事件桥接到前端连接"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.event_bus import event_center

router = APIRouter()


class ConnectionManager:
    """管理所有前端 WS 连接，广播事件"""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        dead = []
        msg = json.dumps({"type": event_type, "data": payload}, ensure_ascii=False, default=str)
        for ws in list(self._connections):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def _bridge(event) -> None:
    """EventCenter 订阅者：把事件转发给所有 WS 连接"""
    await manager.broadcast(event.type, event.payload)


# 启动即订阅（幂等：模块只加载一次）
event_center.subscribe("live_start", _bridge)
event_center.subscribe("live_end", _bridge)
event_center.subscribe("rec_error", _bridge)
event_center.subscribe("session_update", _bridge)
event_center.subscribe("cookie_invalid", _bridge)
event_center.subscribe("engine_start", _bridge)


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    """前端事件流。连接后自动接收所有录制事件。"""
    await manager.connect(ws)
    try:
        while True:
            # 监听客户端消息（心跳/断线检测）；不处理业务
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)