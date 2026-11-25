# -*- coding: utf-8 -*-
"""
EventCenter 事件中心
====================
吸收 LyzenX 插件钩子设计：核心引擎只发事件，扩展全部通过订阅挂载。
业务方（推送/WebSocket/统计/自定义插件）只需订阅，不侵入核心。

事件类型：
    live_start     开播（进入录制）
    live_end       关播（录制结束）
    rec_finish     录制文件完成
    rec_error      录制出错
    session_update 会话状态变更（实时进度）
    cookie_invalid cookie 失效
    disk_low       磁盘空间不足
    engine_start   引擎启动完成
"""
from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..core.logger import get_logger

logger = get_logger("event")

Handler = Callable[..., Any]


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventCenter:
    """异步事件中心：支持同步/异步订阅者，广播式分发"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event_type: str):
        """订阅装饰器"""
        def decorator(fn: Handler) -> Handler:
            self.subscribe(event_type, fn)
            return fn
        return decorator

    def subscribe(self, event_type: str, fn: Handler) -> None:
        self._handlers[event_type].append(fn)
        logger.debug("订阅事件: %s <- %s", event_type, getattr(fn, "__name__", fn))

    def unsubscribe(self, event_type: str, fn: Handler) -> None:
        try:
            self._handlers[event_type].remove(fn)
        except ValueError:
            pass

    async def emit(self, event_type: str, **payload) -> None:
        """广播事件给所有订阅者。订阅者异常不影响其他订阅者。"""
        event = Event(type=event_type, payload=payload)
        for fn in list(self._handlers.get(event_type, [])):
            try:
                res = fn(event)
                if inspect.isawaitable(res):
                    await res
            except Exception:
                logger.exception("事件处理异常 [%s] %s", event_type, getattr(fn, "__name__", fn))

    # ---- 便捷方法 ----
    async def emit_live_start(self, room_id: int, url: str, platform: str, anchor: str, title: str = "") -> None:
        await self.emit("live_start", room_id=room_id, url=url, platform=platform,
                        anchor=anchor, title=title)

    async def emit_live_end(self, room_id: int, url: str, platform: str, anchor: str,
                            file_path: str = "", duration: int = 0) -> None:
        await self.emit("live_end", room_id=room_id, url=url, platform=platform,
                        anchor=anchor, file_path=file_path, duration=duration)

    async def emit_rec_error(self, room_id: int, url: str, error: str) -> None:
        await self.emit("rec_error", room_id=room_id, url=url, error=error)

    async def emit_session(self, room_id: int, state: str, detail: dict) -> None:
        await self.emit("session_update", room_id=room_id, state=state, **detail)

    async def emit_cookie_invalid(self, platform: str) -> None:
        await self.emit("cookie_invalid", platform=platform)

    async def emit_engine_start(self) -> None:
        await self.emit("engine_start")

    async def emit_disk_low(self, free_gb: float) -> None:
        await self.emit("disk_low", free_gb=free_gb)


# 全局单例
event_center = EventCenter()