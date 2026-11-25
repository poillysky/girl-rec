# -*- coding: utf-8 -*-
"""API 请求/响应模型（FastAPI Pydantic schemas）"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class RoomIn(BaseModel):
    """新增/更新直播间"""
    url: str = Field(..., min_length=5, description="直播间URL")
    platform: str = ""
    quality: str = "原画"
    name: str = ""
    enabled: bool = True
    important: bool = False        # 重要房间：更快探测节奏（LyzenX 分级）


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    platform: str
    quality: str
    name: str
    enabled: bool
    important: bool
    is_live: bool
    anchor_name: str
    title: str = ""
    session_state: str = ""       # 录制状态（来自 sessions.state：idle/checking/preparing/recording/…）
    last_check_at: dt.datetime | None = None
    created_at: dt.datetime


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int | None = None
    file_path: str
    file_size: int
    start_time: dt.datetime | None = None
    end_time: dt.datetime | None = None
    duration_seconds: int
    status: str
    save_type: str
    platform: str
    anchor_name: str


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    url: str
    platform: str
    anchor_name: str
    state: str
    record_url: str
    save_file_path: str
    start_time: dt.datetime | None = None
    last_update: dt.datetime
    error: str


class ConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    updated_at: dt.datetime


class ConfigSetIn(BaseModel):
    """配置写入入参（body 式，避免 key 含 / 时路径参数路由失败）"""
    key: str
    value: str


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int | None = None
    type: str
    platform: str
    content: str
    created_at: dt.datetime

class ProductOut(BaseModel):
    """成品库（下载完成的完整 mp4）——录制文件页展示对象"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int | None = None
    file_path: str
    file_name: str
    file_size: int
    duration_seconds: int
    start_time: dt.datetime | None = None
    end_time: dt.datetime | None = None
    created_at: dt.datetime | None = None
    save_type: str
    platform: str
    anchor_name: str
    title: str
    status: str          # ready/missing/deleted
    exists: bool = True  # 磁盘文件是否存在（运行时填充，非 DB 列）
