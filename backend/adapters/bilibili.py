# -*- coding: utf-8 -*-
"""
B站直播 适配器
=============
迁移自原项目逆向资产（legacy/spider.get_bilibili_room_info + stream.get_bilibili_stream_url）。
原版语义：room_info 拿 live_status/anchor → 直播时 get_bilibili_stream_data(qn) 二次取流。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.bilibili")


@register
class BilibiliPlatform(BasePlatform):
    platform_name = "B站直播"
    domains = ['live.bilibili.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_bilibili_room_info）"""
        from ..legacy import spider
        self._last_url = url
        try:
            data = await spider.get_bilibili_room_info(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("B站直播 数据抓取失败: %s", e)
            raise TransientError(f"B站直播 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """B站专属：live_status → qn 二次取流（原版 stream.get_bilibili_stream_url）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("live_status"):
            return info
        port = await stream.get_bilibili_stream_url(
            data, quality, proxy_addr=self.proxy or None, cookies=self.cookies or None)
        if not port.get("is_live"):
            return info
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.record_url = port.get("record_url", "")
        return info