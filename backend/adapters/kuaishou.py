# -*- coding: utf-8 -*-
"""
快手直播 适配器
=============
迁移自原项目逆向资产（legacy/spider.get_kuaishou_stream_data + stream.get_kuaishou_stream_url）。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.kuaishou")


@register
class KuaishouPlatform(BasePlatform):
    platform_name = "快手直播"
    domains = ['live.kuaishou.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        self._last_url = url
        from ..legacy import spider
        try:
            data = await spider.get_kuaishou_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("快手直播 数据抓取失败: %s", e)
            raise TransientError(f"快手直播 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """快手专属：m3u8_url_list 倒序 / flv_url_list 按 bitrate 排序（原版 get_kuaishou_stream_url）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        # type==1 且未直播（原版直接透传）
        if data.get("type") == 1 and not data.get("is_live"):
            return info
        if not data.get("is_live"):
            return info
        port = await stream.get_kuaishou_stream_url(data, quality)
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