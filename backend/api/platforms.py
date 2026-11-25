# -*- coding: utf-8 -*-
"""平台配置 API：每个平台独立参数（走不走代理 / 默认画质 / 是否启用 / Cookie 概览等）。

配置存储沿用 configs 表，用 `平台:{平台名}:{参数}` 作为 key，无需新增表结构。
参数定义集中在 PLATFORM_PARAM_DEFS，前端据此动态渲染表单。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from ..adapters import list_platforms, get_platform
from ..core.config_service import config_service
from ..models import Config, get_session

router = APIRouter(prefix="/api", tags=["platforms"])


# 每平台可配参数定义（key 后缀, 中文名, 类型, 默认值, 说明）
PLATFORM_PARAM_DEFS = [
    {"key": "启用代理", "label": "走代理", "type": "bool", "default": None,
     "hint": "该平台录制时是否走代理（留空=跟随适配器默认）"},
    {"key": "默认画质", "label": "默认画质", "type": "select",
     "options": ["原画", "超清", "高清", "标清", "流畅"], "default": "原画",
     "hint": "添加该平台直播间时的默认画质"},
    {"key": "录制启用", "label": "启用录制", "type": "bool", "default": "是",
     "hint": "关闭后该平台所有直播间只探测在线状态、不录制"},
    {"key": "Cookie", "label": "Cookie", "type": "text", "default": "",
     "hint": "该平台登录 Cookie（敏感，留空用内置）", "secret": True},
]


class PlatformConfigIn(BaseModel):
    key: str
    value: str


def _cfg_key(platform: str, param: str) -> str:
    return f"平台:{platform}:{param}"


def _get_value(db: OrmSession, platform: str, param: str, default):
    row = db.query(Config).filter(Config.key == _cfg_key(platform, param)).first()
    if row is not None:
        return row.value
    return default


# 平台管理页不展示的适配器（自定义流是裸 m3u8/flv 兜底，无画质/Cookie 可配，
# 仅在添加房间时作为可选平台使用）
HIDDEN_PLATFORMS = {"自定义录制直播"}


@router.get("/platforms")
def api_list_platforms(db: OrmSession = Depends(get_session)):
    """平台列表 + 每平台当前配置值（供前端平台配置页渲染）。"""
    out = []
    for p in list_platforms():
        name = p["name"]
        if name in HIDDEN_PLATFORMS:
            continue
        params = []
        for d in PLATFORM_PARAM_DEFS:
            val = _get_value(db, name, d["key"], d["default"])
            if d["key"] == "启用代理" and val is None:
                # 未单独配置 → 显示适配器默认（enable_proxy）
                val = "是" if p.get("enable_proxy") else "否"
            params.append({**d, "value": val})
        out.append({
            "name": name,
            "domains": p.get("domains", []),
            "enable_proxy": p.get("enable_proxy", False),
            "support_danmu": p.get("support_danmu", False),
            "only_audio": p.get("only_audio", False),
            "only_flv": p.get("only_flv", False),
            "params": params,
        })
    # 热门平台优先（老大要求：抖音等最火的排最前面），未上榜按名称兜底
    HOT_ORDER = ["抖音", "TikTok直播", "快手直播", "B站直播", "虎牙直播", "斗鱼直播", "YY直播",
                 "微信视频号", "小红书直播", "微博直播", "TwitchTV", "Youtube", "SOOP", "网易CC直播",
                 "花椒直播", "百度直播", "映客直播", "Acfun", "17Live", "TwitCasting"]
    out.sort(key=lambda x: (HOT_ORDER.index(x["name"]) if x["name"] in HOT_ORDER else 999,
                            x["name"]))
    return out


@router.put("/platforms/{platform}")
def api_set_platform_config(platform: str, payload: PlatformConfigIn,
                            db: OrmSession = Depends(get_session)):
    """设置某平台的单项配置（key 为参数短名，如 启用代理/默认画质/Cookie）。"""
    cls = get_platform(platform)
    if not cls:
        raise HTTPException(status_code=404, detail=f"未知平台: {platform}")
    if payload.key not in {d["key"] for d in PLATFORM_PARAM_DEFS}:
        raise HTTPException(status_code=400, detail=f"不支持的参数: {payload.key}")
    full = _cfg_key(platform, payload.key)
    row = db.query(Config).filter(Config.key == full).first()
    import datetime as dt
    if row:
        row.value = payload.value
        row.updated_at = dt.datetime.utcnow()
    else:
        db.add(Config(key=full, value=payload.value, updated_at=dt.datetime.utcnow()))
    db.commit()
    return {"ok": True, "key": full, "value": payload.value}
