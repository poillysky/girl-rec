# -*- coding: utf-8 -*-
"""
自定义录制直播适配器
===================
迁移自原项目 main.py "自定义录制直播" 分支（main.py:1025-1036）。

用户直接粘贴一条 .m3u8 / .flv 流地址时的兜底路由：
    - 不归属任何域名的直播间页面，而是裸流地址本身
    - 原版语义：anchor_name = "自定义录制直播_" + uuid4 前8位，is_live=True，record_url 原样直录
    - 录制走 ffmpeg（原版该分支不进 direct_download_stream，仍走 ffmpeg 命令）

match 规则：URL 含 ".m3u8" 或 ".flv" 子串（注册在 __init__ import 链末位，
保证前面 51 个域名平台先匹配，此兜底只接住漏网的裸流地址）。
"""
from __future__ import annotations

import uuid

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo
from .registry import register

logger = get_logger("adapter.custom_stream")


@register
class CustomStreamPlatform(BasePlatform):
    platform_name = "自定义录制直播"
    domains: list[str] = []            # 不靠域名匹配，见 match()
    enable_proxy = False
    support_danmu = False
    only_flv = False                   # flv/m3u8 都走 ffmpeg（原版该分支同 ffmpeg）
    only_audio = False
    force_http = False                 # 自定义流不做 https 提升（原版 platform=='自定义录制直播' 例外）

    @classmethod
    def match(cls, url: str) -> bool:
        return ".m3u8" in url or ".flv" in url

    async def extract(self, url: str) -> dict:
        self._last_url = url
        # 原版：anchor_name = platform + '_' + str(uuid.uuid4())[:8]
        anchor = f"{self.platform_name}_{uuid.uuid4().hex[:8]}"
        data = {
            "anchor_name": anchor,
            "is_live": True,
            "record_url": url,
            "flv_url": url if ".flv" in url else "",
            "m3u8_url": url if ".m3u8" in url else "",
        }
        logger.info("自定义直录流: %s", url)
        return data

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        info.is_live = True
        info.title = data.get("title", "")
        info.anchor_name = data.get("anchor_name", "")
        info.quality = quality
        info.flv_url = data.get("flv_url", "")
        info.m3u8_url = data.get("m3u8_url", "")
        info.record_url = data.get("record_url") or info.m3u8_url or info.flv_url
        return info