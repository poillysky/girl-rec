# -*- coding: utf-8 -*-
"""
平台适配器层
============
每平台一个文件 = 一个适配器类，注册进 PLATFORM_REGISTRY 即可被调度器识别。
核心约定：
    extract(url)  -> 直播间原始数据（迁移自 legacy/spider.py 的 get_xxx_stream_data）
    resolve(data) -> 从数据中抽出可录制流地址（迁移自 legacy/stream.py 的 get_xxx_stream_url）

持续扩展协议：
    新增平台 = 新建一个文件继承 BasePlatform，@register 装饰，实现 extract/resolve。
    主程序、调度器、数据库、前端零改动。
"""
from .base import (
    BasePlatform,
    StreamInfo,
    AdapterError,
    StreamResolveError,
    TransientError,
    PermanentError,
    RoomNotFoundError,
    StreamerBannedError,
    CookieInvalidError,
)
from .registry import (
    PLATFORM_REGISTRY,
    registry,
    match_platform,
    get_platform,
    list_platforms,
    register,
)
# 平台适配器模块（导入即触发 @register 注册）
from . import (  # noqa: F401
    acfun,
    baidu,
    bigo,
    bilibili,
    blued,
    changliao,
    chzzk,
    douyin,
    douyu,
    faceit,
    flextv,
    haixiu,
    huajiao,
    huamao,
    huya,
    jd,
    kuaishou,
    kugou,
    laixiu,
    langlive,
    lehaitv,
    lianjie,
    liuxing,
    live17,
    liveme,
    looklive,
    maoerfm,
    migu,
    netease,
    pandatv,
    picarto,
    popkontv,
    pplive,
    qiandurebo,
    room6,
    shopee,
    showroom,
    sooplive,
    taobao,
    tiktok,
    twitcasting,
    twitchtv,
    vvxqiu,
    weibo,
    winktv,
    xhs,
    yinbo,
    yingke,
    youtube,
    yy,
    zhihu,
    custom_stream,  # 兜底：裸 .m3u8/.flv 直录流（须最后注册——match 是 URL 子串而非域名）
)

__all__ = [
    "BasePlatform",
    "StreamInfo",
    "AdapterError",
    "StreamResolveError",
    "TransientError",
    "PermanentError",
    "RoomNotFoundError",
    "StreamerBannedError",
    "CookieInvalidError",
    "register",
    "registry",
    "PLATFORM_REGISTRY",
    "match_platform",
    "get_platform",
    "list_platforms",
]