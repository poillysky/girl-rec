# -*- coding: utf-8 -*-
"""
SQLAlchemy 数据模型（6张核心表）
================================
rooms       直播间配置（替代 URL_config.ini）
recordings  已完成录制历史（替代内存 recording）
sessions    正在进行的录制会话（olive bout 持久化）
events      事件日志（live_start/live_end/rec_error...）
configs     通用配置键值（替代 config.ini 热读）
push_logs   推送记录

平台扩展友好：platform 存中文名（来自适配器 platform_name），
加平台不需要改表结构。
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Room(Base):
    """直播间配置"""
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quality: Mapped[str] = mapped_column(String(16), default="原画")
    name: Mapped[str] = mapped_column(String(128), default="")        # 自定义备注
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)      # 替代 # 注释
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)     # 最近探测结果
    important: Mapped[bool] = mapped_column(Boolean, default=False)   # 重要房间（LyzenX 分级：独立线程/更高优先级探测）
    anchor_name: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(256), default="")       # 最近一次探测到的直播标题
    last_check_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)

    recordings: Mapped[list["CacheRecording"]] = relationship(back_populates="room")


class Session(Base):
    """正在进行的录制会话（bout 持久化）"""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(512), default="")
    platform: Mapped[str] = mapped_column(String(64), default="")
    anchor_name: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(String(24), default="idle")
    # idle -> checking -> preparing -> recording -> stopping -> finished/failed/stopped
    record_url: Mapped[str] = mapped_column(Text, default="")
    save_file_path: Mapped[str] = mapped_column(String(1024), default="")
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_update: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    error: Mapped[str] = mapped_column(Text, default="")

    room: Mapped[Room] = relationship()


class Event(Base):
    """事件日志（供前端事件墙 + 插件）"""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)     # live_start/live_end/rec_error...
    platform: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class Config(Base):
    """通用配置（替代 config.ini；key 沿用原 ini 的 option 名）"""
    __tablename__ = "configs"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now,
                                                    onupdate=dt.datetime.now)


class PushLog(Base):
    """推送记录"""
    __tablename__ = "push_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="")     # dingtalk/tg/email/bark...
    status: Mapped[str] = mapped_column(String(16), default="sent")   # sent/failed
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class RecordingSession_(Base):
    """录制会话记录（一次开播到停播的整体会话，含多批成品）——辅助统计，非核心"""
    __tablename__ = "recording_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String(64), default="")
    anchor_name: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class CacheRecording(Base):
    """下载缓存库（recordings 表）：录制过程中的 ts 分片等非成品，持续写入、可随时清理。
    这是「缓存库」——临时、可丢、写满可清。合并转出成成品后应删除对应缓存记录。"""
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    file_path: Mapped[str] = mapped_column(String(1024), default="")   # 缓存目录下分片路径
    file_size: Mapped[int] = mapped_column(Integer, default=0)         # 字节
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="recording")  # recording/stopped/failed/merged
    save_type: Mapped[str] = mapped_column(String(16), default="ts")
    platform: Mapped[str] = mapped_column(String(64), default="")
    anchor_name: Mapped[str] = mapped_column(String(128), default="")

    room: Mapped["Room"] = relationship()


class Product(Base):
    """成品库（products 表）：合并完成的完整 mp4 成品文件，已从缓存转移到成品目录。
    这是「成品库」——最终交付、长期保留、前端录制文件页管理的就是它。"""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    file_path: Mapped[str] = mapped_column(String(1024), default="")   # 成品目录下最终 mp4 路径
    file_name: Mapped[str] = mapped_column(String(512), default="")    # 展示用文件名
    file_size: Mapped[int] = mapped_column(Integer, default=0)         # 字节
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)   # 这段直播开始
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)     # 这段直播结束
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now) # 成品生成时间
    save_type: Mapped[str] = mapped_column(String(16), default="mp4")
    platform: Mapped[str] = mapped_column(String(64), default="")
    anchor_name: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(24), default="ready")   # ready/missing/deleted

    room: Mapped["Room"] = relationship()


def init_db(db_path: str) -> "SessionLocal":
    """初始化数据库引擎，返回会话工厂"""
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    _light_migrate(engine)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    set_session_factory(factory)
    return factory


def _light_migrate(engine) -> None:
    """轻量列迁移：create_all 不会给已有表加列，这里用 PRAGMA 检查缺失列并 ALTER。
    只处理增量新增列（老库升级场景），不处理删列/改类型。"""
    import sqlite3
    conn = sqlite3.connect(engine.url.database)
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(rooms)").fetchall()}
        if existing and "important" not in existing:
            conn.execute("ALTER TABLE rooms ADD COLUMN important BOOLEAN NOT NULL DEFAULT 0")
            print("[migrate] rooms 表新增列 important")
        if existing and "title" not in existing:
            conn.execute("ALTER TABLE rooms ADD COLUMN title VARCHAR(256) NOT NULL DEFAULT ''")
            print("[migrate] rooms 表新增列 title")
        conn.commit()
    except sqlite3.Error:
        pass  # 迁移失败不打紧：create_all 兜底（新库无此问题）
    finally:
        conn.close()


# 全局 session 工厂（main 启动时通过 init_db 设置，API 依赖从这里拿）
_session_factory = None


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


def get_session():
    """API/事件层拿 DB 会话"""
    if _session_factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return _session_factory()