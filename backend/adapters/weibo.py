# -*- coding: utf-8 -*-
"""
微博直播 适配器
=============
迁移自原项目逆向资产（legacy/spider.get_weibo_stream_data + stream.get_stream_url(hls_extra_key='m3u8_url')）。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.weibo")


@register
class WeiboPlatform(BasePlatform):
    platform_name = "微博直播"
    domains = ['weibo.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_weibo_stream_data）"""
        from ..legacy import spider
        self._last_url = url
        try:
            data = await spider.get_weibo_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("微博直播 数据抓取失败: %s", e)
            raise TransientError(f"微博直播 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """微博专属：play_url_list 中 m3u8_url 键（原版 url_type=m3u8 hls_extra_key='m3u8_url'）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        port = await stream.get_stream_url(data, quality, hls_extra_key="m3u8_url")
        if not port.get("is_live"):
            return info
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.m3u8_url = port.get("m3u8_url", "")
        info.record_url = port.get("record_url", "") or info.m3u8_url
        return info