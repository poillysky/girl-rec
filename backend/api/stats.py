# -*- coding: utf-8 -*-
"""汇总统计接口：总览页数据（房间/会话/录制/磁盘一次取齐）"""
from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session as OrmSession

from ..models import Product, Room, Session
from .rooms import get_db

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats")
def get_stats(db: OrmSession = Depends(get_db)) -> dict:
    """总览统计：房间/会话/录制汇总 + 录制目录磁盘占用"""
    rooms = db.query(Room).all()
    sessions = db.query(Session).all()
    # 成品库统计（只统计成品 mp4，缓存中的 ts 分片不计入"录制成品"）
    rec_total, rec_finished, rec_size, rec_duration = 0, 0, 0, 0
    for r in db.query(Product).all():
        rec_total += 1
        if (r.status or "ready") == "ready":
            rec_finished += 1
        rec_size += r.file_size or 0
        rec_duration += r.duration_seconds or 0

    # 磁盘：录制目录所在文件系统
    disk = {"free_gb": 0, "total_gb": 0, "used_gb": 0, "used_pct": 0}
    try:
        # 旧实现读 RECORDER_SAVE_DIR（app.py 从未设置该 env）-> 恒定回退 "."，
        # 统计的是启动目录所在盘，和真实录制盘不是一个盘
        from ..core.config_service import config_service
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        save_dir = config_service.get_cache_dir(os.path.join(base_dir, "cache"))
        if not os.path.isdir(save_dir):
            save_dir = os.path.join(base_dir, "cache")
        target = save_dir if os.path.isdir(save_dir) else "."
        u = shutil.disk_usage(target)
        total = u.total / 1024**3
        used = (u.total - u.free) / 1024**3
        disk = {
            "free_gb": round(u.free / 1024**3, 2),
            "total_gb": round(total, 2),
            "used_gb": round(used, 2),
            "used_pct": round(used / total * 100, 1) if total else 0,
        }
    except OSError:
        pass

    return {
        "rooms": {
            "total": len(rooms),
            "enabled": sum(1 for r in rooms if r.enabled),
            "live": sum(1 for r in rooms if r.is_live),
            "important": sum(1 for r in rooms if r.important),
        },
        "sessions": {
            "total": len(sessions),
            "recording": sum(1 for s in sessions if s.state == "recording"),
            "checking": sum(1 for s in sessions if s.state == "checking"),
        },
        "recordings": {
            "total": rec_total,
            "finished": rec_finished,
            "total_size": rec_size,
            "total_duration": rec_duration,
        },
        "disk": disk,
        "ffmpeg": shutil.which("ffmpeg") or "",
    }