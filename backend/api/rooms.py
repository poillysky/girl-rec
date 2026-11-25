# -*- coding: utf-8 -*-
"""REST 路由：直播间的增删改查 + 录制历史 + 配置"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as OrmSession

from ..adapters import match_platform
from ..models import Config, Event, Product, Room, Session
from .schemas import (ConfigOut, ConfigSetIn, EventOut, ProductOut, RoomIn, RoomOut, SessionOut)

router = APIRouter(prefix="/api", tags=["rooms"])


# ---------- 依赖 ----------
def get_db():
    from ..models import get_session

    db = get_session()
    try:
        yield db
    finally:
        db.close()


# ---------- 直播间 CRUD ----------
@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(db: OrmSession = Depends(get_db)) -> list[RoomOut]:
    """全部直播间（含实时状态字段：在线状态 is_live / 录制状态 session_state）"""
    rooms = db.query(Room).order_by(Room.id).all()
    # 会话状态映射（room_id -> state）：录制状态列展示用
    sess_map = {s.room_id: s.state for s in db.query(Session).all()}
    out: list[RoomOut] = []
    for r in rooms:
        item = RoomOut.model_validate(r)
        item.session_state = sess_map.get(r.id, "")
        out.append(item)
    return out


@router.post("/rooms/resolve")
async def resolve_room_identifier(payload: dict, db: OrmSession = Depends(get_db)) -> dict:
    """按主播名/ID 解析直播间（不落库）。
    入参: {platform: "抖音", identifier: "335354047186" 或 "主播昵称"}
    出参: {ok, url, platform, info:{anchor_name,title}, error}
    info 为 best-effort：解析成功后尝试调 extract 拿主播名/标题，失败则空。
    """
    from ..adapters import get_platform

    platform = (payload.get("platform") or "").strip()
    identifier = (payload.get("identifier") or "").strip()
    if not platform or not identifier:
        return {"ok": False, "error": "缺少 platform 或 identifier"}
    cls = get_platform(platform)
    if cls is None:
        return {"ok": False, "error": f"未知平台: {platform}"}
    try:
        adapter = cls()
        url = await adapter.resolve_identifier(identifier)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"解析失败: {e}"}
    if not url:
        return {"ok": False, "error": f"{platform} 暂不支持按名字解析，请粘贴直播间链接"}

    # best-effort：尝试提取主播名/标题（失败不阻塞）
    info = {"anchor_name": "", "title": ""}
    try:
        data = await adapter.extract(url)
        if isinstance(data, dict):
            info["anchor_name"] = data.get("anchor_name", "") or ""
            info["title"] = data.get("title", "") or ""
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "url": url, "platform": cls.platform_name, "info": info}


@router.post("/rooms", response_model=RoomOut, status_code=201)
def create_room(payload: RoomIn, db: OrmSession = Depends(get_db)) -> Room:
    """新增直播间。platform 自动从 URL 探测（未指定时）。"""
    exists = db.query(Room).filter(Room.url == payload.url).first()
    if exists:
        raise HTTPException(409, "该直播间已存在")
    cls = match_platform(payload.url)
    if cls is None:
        raise HTTPException(422, f"无法识别平台: {payload.url}")
    room = Room(
        url=payload.url,
        platform=payload.platform or cls.platform_name,
        quality=payload.quality,
        name=payload.name,
        enabled=payload.enabled,
        important=payload.important,   # 关键：新建时保留"重要房间"开关（曾漏写）
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.get("/rooms/{room_id}", response_model=RoomOut)
def get_room(room_id: int, db: OrmSession = Depends(get_db)) -> Room:
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "房间不存在")
    return room


@router.put("/rooms/{room_id}", response_model=RoomOut)
def update_room(room_id: int, payload: RoomIn, db: OrmSession = Depends(get_db)) -> Room:
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "房间不存在")
    room.url = payload.url
    room.quality = payload.quality
    room.name = payload.name
    room.enabled = payload.enabled
    room.important = payload.important   # 重要房间开关（曾漏写导致前端切换不持久化）
    if payload.platform:
        room.platform = payload.platform
    db.commit()
    db.refresh(room)
    return room


@router.delete("/rooms/{room_id}", status_code=204)
def delete_room(room_id: int, db: OrmSession = Depends(get_db)) -> None:
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "房间不存在")
    db.delete(room)
    db.commit()


# ---------- 成品库（下载完成的完整 mp4）----------
def _product_status(p: Product) -> str:
    """运行时状态：磁盘文件是否存在"""
    import os
    if not p.file_path or not os.path.exists(p.file_path):
        return "missing"
    return p.status or "ready"


@router.get("/recordings", response_model=list[ProductOut])
def list_recordings(
    room_id: int | None = None,
    limit: int = 500,
    db: OrmSession = Depends(get_db),
) -> list[ProductOut]:
    """成品库列表：只列已合并完成、从缓存转移到成品目录的完整 mp4。
    录制中的 ts 分片属缓存库，不在此列（缓存库可用 /api/cache 查看）。"""
    import os
    q = db.query(Product).order_by(Product.created_at.desc())
    if room_id:
        q = q.filter(Product.room_id == room_id)
    rows = q.limit(limit).all()
    out = []
    for p in rows:
        po = ProductOut.model_validate(p)
        po.exists = bool(p.file_path and os.path.exists(p.file_path))
        if not po.exists:
            # 文件已丢失的记录不在成品列表展示（磁盘文件不存在的无效记录）
            continue
        out.append(po)
    return out


@router.get("/recordings/{pid}/stream")
def stream_product(pid: int, db: OrmSession = Depends(get_db)):
    """页内播放：返回 mp4 文件（支持 Range 拖动/秒播，FileResponse 自动处理）"""
    import os
    p = db.query(Product).filter(Product.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="成品不存在")
    if not p.file_path or not os.path.exists(p.file_path):
        raise HTTPException(status_code=404, detail="磁盘文件丢失")
    return FileResponse(p.file_path, media_type="video/mp4", filename=p.file_name or None)


@router.get("/recordings/{pid}/download")
def download_product(pid: int, db: OrmSession = Depends(get_db)):
    """下载：以附件形式返回成品 mp4。
    文件名可能含中文/emoji → 用 RFC 5987（filename*=UTF-8''URL编码）避免 latin-1 编码崩溃。"""
    import os
    from urllib.parse import quote
    p = db.query(Product).filter(Product.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="成品不存在")
    if not p.file_path or not os.path.exists(p.file_path):
        raise HTTPException(status_code=404, detail="磁盘文件丢失")
    fname = p.file_name or os.path.basename(p.file_path)
    # ASCII 兜底名（去掉非 latin-1 字符）+ UTF-8 编码名
    ascii_name = fname.encode("ascii", "ignore").decode("ascii") or f"product_{p.id}.mp4"
    utf8_name = quote(fname)
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
    return FileResponse(p.file_path, media_type="video/mp4",
                        headers={"Content-Disposition": disposition})


@router.delete("/recordings/{pid}")
def delete_product(pid: int, remove_file: bool = True, db: OrmSession = Depends(get_db)):
    """删除成品：删 DB 记录；remove_file=true 时同时删磁盘 mp4"""
    import os
    p = db.query(Product).filter(Product.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="成品不存在")
    fp = p.file_path
    db.delete(p)
    db.commit()
    if remove_file and fp:
        try:
            os.remove(fp)
        except OSError:
            pass
        # 连同同名字幕文件 .srt 一起删除（生成时间字幕文件功能产出的 .srt）
        srt = os.path.splitext(fp)[0] + ".srt"
        if os.path.exists(srt):
            try:
                os.remove(srt)
            except OSError:
                pass
    return {"ok": True, "deleted_file": bool(remove_file and fp and not os.path.exists(fp))}


# ---------- 缓存库（录制中 ts 分片，可清理）----------
@router.get("/cache")
def list_cache(db: OrmSession = Depends(get_db)):
    """缓存库：录制过程中的 ts 分片等非成品文件（临时、可清理）"""
    import os
    from ..models import CacheRecording
    rows = db.query(CacheRecording).order_by(CacheRecording.start_time.desc()).limit(500).all()
    return [{
        "id": r.id, "room_id": r.room_id, "file_path": r.file_path,
        "file_name": os.path.basename(r.file_path or ""),
        "file_size": r.file_size, "status": r.status, "platform": r.platform,
        "anchor_name": r.anchor_name,
        "exists": bool(r.file_path and os.path.exists(r.file_path)),
        "start_time": r.start_time.isoformat() if r.start_time else None,
    } for r in rows]


# ---------- 实时会话 ----------
@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(db: OrmSession = Depends(get_db)) -> list[Session]:
    return db.query(Session).all()


# ---------- 事件日志 ----------
@router.get("/events", response_model=list[EventOut])
def list_events(
    limit: int = 50,
    type: str | None = None,
    db: OrmSession = Depends(get_db),
) -> list[Event]:
    q = db.query(Event).order_by(Event.id.desc())
    if type:
        q = q.filter(Event.type == type)
    return q.limit(limit).all()


# ---------- 配置 ----------
@router.get("/configs", response_model=list[ConfigOut])
def list_configs(db: OrmSession = Depends(get_db)) -> list[Config]:
    return db.query(Config).order_by(Config.key).all()


@router.put("/configs", response_model=ConfigOut)
def set_config(payload: ConfigSetIn, db: OrmSession = Depends(get_db)) -> Config:
    """配置写入走 body（key/value），避免 key 含 `/`（如 language(zh_cn/en)）时
    路径参数被 URL 解码成路径分隔符导致 405 路由不匹配的坑。"""
    key, value = payload.key, payload.value
    cfg = db.query(Config).filter(Config.key == key).first()
    if cfg:
        cfg.value = value
    else:
        cfg = Config(key=key, value=value)
        db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.put("/configs/{key}", response_model=ConfigOut)
def set_config_by_path(key: str, value: str, db: OrmSession = Depends(get_db)) -> Config:
    """兼容旧路径式调用（key 不含 `/` 时可用）；含 `/` 请走 body 式 PUT /configs。"""
    cfg = db.query(Config).filter(Config.key == key).first()
    if cfg:
        cfg.value = value
    else:
        cfg = Config(key=key, value=value)
        db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg