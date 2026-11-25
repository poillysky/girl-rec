# -*- coding: utf-8 -*-
"""
斗鱼直播 适配器
=============
迁移自原项目逆向资产（legacy/spider.get_douyu_info_data + stream.get_douyu_stream_url）。
原版语义：get_douyu_info_data 返回 room_id → stream.get_douyu_stream_url 用 rid+rate 二次取流（sign 10分钟有效）。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.douyu")


@register
class DouyuPlatform(BasePlatform):
    platform_name = "斗鱼直播"
    domains = ['www.douyu.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_douyu_info_data）"""
        from ..legacy import spider
        self._last_url = url
        try:
            data = await spider.get_douyu_info_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("斗鱼直播 数据抓取失败: %s", e)
            raise TransientError(f"斗鱼直播 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """斗鱼专属：rid + rate 二次取流（原版 stream.get_douyu_stream_url）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        port = await stream.get_douyu_stream_url(
            data, quality, cookies=self.cookies or "", proxy_addr=self.proxy or None)
        if not port.get("is_live"):
            return info
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.flv_url = port.get("flv_url", "")
        info.m3u8_url = port.get("m3u8_url", "")
        info.record_url = port.get("record_url", "") or info.flv_url or info.m3u8_url
        return info