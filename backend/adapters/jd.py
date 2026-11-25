# -*- coding: utf-8 -*-
"""
京东直播 直播适配器
=================
迁移自原项目逆向资产（legacy/spider.py → get_jd_stream_url）。
一平台一文件：本文件即 京东直播 全部接入逻辑。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.jd")


@register
class JdPlatform(BasePlatform):
    platform_name = "京东直播"
    domains = ['3.cn', 'm.jd.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        self._last_url = url
        from ..legacy import spider
        try:
            data = await spider.get_jd_stream_url(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("京东直播 数据抓取失败: %s", e)
            raise TransientError(f"京东直播 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """spider 已直接给出可录制地址（原版 direct 返回）"""
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
