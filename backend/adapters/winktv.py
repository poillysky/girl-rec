# -*- coding: utf-8 -*-
"""
WinkTV 直播适配器
=================
迁移自原项目逆向资产（legacy/spider.py → get_winktv_stream_data）。
一平台一文件：本文件即 WinkTV 全部接入逻辑。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.winktv")


@register
class WinktvPlatform(BasePlatform):
    platform_name = "WinkTV"
    domains = ['www.winktv.co.kr']
    enable_proxy = True
    support_danmu = False
    only_flv = False
    only_audio = False
    record_headers = {"origin": "https://www.winktv.co.kr"}

    async def extract(self, url: str) -> dict:
        self._last_url = url
        from ..legacy import spider
        try:
            data = await spider.get_winktv_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("WinkTV 数据抓取失败: %s", e)
            raise TransientError(f"WinkTV 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """通用 stream.get_stream_url（spec=True 用顶层 m3u8_url/flv_url）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        port = await stream.get_stream_url(data, quality, spec=True)
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.m3u8_url = port.get("m3u8_url", "")
        info.flv_url = port.get("flv_url", "")
        info.record_url = port.get("record_url", "")
        return info
