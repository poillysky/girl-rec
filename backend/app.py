# -*- coding: utf-8 -*-
"""
应用主入口
==========
FastAPI + uvicorn 单进程：
    - SQLite（6表）
    - RoomScheduler（每房间协程 + DB 热更新）
    - REST 路由（/api/rooms, /api/recordings, /api/sessions, /api/configs）
    - WebSocket（/ws/events 实时事件流）

启动：
    cd 项目根 && .venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import rooms_router, stats_router, ws_router, platforms_router
from .core.event_bus import event_center
from .core.logger import get_logger
from .engine.post_processor import post_processor
from .models import init_db
from .scheduler.room_scheduler import RoomScheduler

logger = get_logger("app")

# ---- 配置（后续从 configs 表/环境变量读）----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根
DB_PATH = os.environ.get("RECORDER_DB", os.path.join(BASE_DIR, "data", "recorder.db"))
CACHE_DIR = os.environ.get("RECORDER_CACHE_DIR", os.path.join(BASE_DIR, "cache"))   # 下载缓存库（ts 分片）
PRODUCT_DIR = os.environ.get("RECORDER_PRODUCT_DIR", os.path.join(BASE_DIR, "downloads"))  # 成品库（最终 mp4）
SAVE_DIR = CACHE_DIR  # 兼容：录制过程写缓存目录
DEFAULT_QUALITY = os.environ.get("RECORDER_QUALITY", "原画")
DEFAULT_SAVE_TYPE = os.environ.get("RECORDER_SAVE_TYPE", "TS")
SEG_TIME = int(os.environ.get("RECORDER_SEG_TIME", "1800"))
SPLIT = os.environ.get("RECORDER_SPLIT", "0") == "1"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：替代已废弃的 @app.on_event（FastAPI 0.93+ 推荐 lifespan）。

    scheduler 是模块级单例，在模块加载完成时才存在；lifespan 在启动阶段才执行，
    这里按名字延迟解析，不受定义顺序影响。
    """
    post_processor.start()
    from .core.msg_push import start as start_msg_push
    start_msg_push()          # 订阅 live_start/live_end -> 开播/关播推送
    await scheduler.start()
    await event_center.emit_engine_start()
    logger.info("引擎启动完成")
    try:
        yield
    finally:
        await scheduler.stop()
        await post_processor.stop()
        logger.info("引擎已停止")


app = FastAPI(title="直播录制中心", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 前端开发用；生产收紧
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB 初始化（模块级保证 API 依赖可用）
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(PRODUCT_DIR, exist_ok=True)
db_factory = init_db(DB_PATH)
logger.info("数据库初始化: %s", DB_PATH)

# ---- 静态文件（前端构建产物）注册延后到 API 路由之后 ----
_static_dir = os.path.join(BASE_DIR, "frontend", "dist")

# 路由（顺序重要：API 全部注册完，最后才是 SPA fallback）
app.include_router(rooms_router)
app.include_router(stats_router)
app.include_router(ws_router)
app.include_router(platforms_router)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "rooms": len(scheduler.tasks),
        "sessions": len(scheduler.sessions),
        "db": DB_PATH,
        "ffmpeg": shutil.which("ffmpeg") or "",
    }


# 调度器（进程级单例；模块导入即建，lifespan 里启停）
scheduler = RoomScheduler(
    db_factory,
    save_dir=SAVE_DIR,
    default_quality=DEFAULT_QUALITY,
    default_save_type=DEFAULT_SAVE_TYPE,
    seg_time=SEG_TIME,
    split=SPLIT,
)


# ---- 静态文件（前端构建产物）SPA fallback（必须在所有 API 路由之后注册） ----
# 真实文件（JS/CSS/图片）直接返回；其余路径（history 路由如 /rooms）回退 index.html
if os.path.isdir(_static_dir):
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        target = os.path.realpath(os.path.join(_static_dir, full_path))
        if (
            full_path
            and target.startswith(os.path.realpath(_static_dir) + os.sep)
            and os.path.isfile(target)
        ):
            return FileResponse(target)
        return FileResponse(os.path.join(_static_dir, "index.html"))