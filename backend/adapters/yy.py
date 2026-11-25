# -*- coding: utf-8 -*-
"""
YY直播 适配器
=============
迁移自原项目逆向资产（legacy/spider.get_yy_stream_data + stream.get_yy_stream_url）。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.yy")


@register
class YyPlatform(BasePlatform):
    platform_name = "YY直播"
    domains = ['www.yy.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_yy_stream_data）"""
        from ..legacy import spider
        self._last_url = url
        try:
            data = await spider.get_yy_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("YY直播 数据抓取失败: %s", e)
            raise TransientError(f"YY直播 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """YY专属：avp_info_res 结构（原版 stream.get_yy_stream_url）"""
        from ..legacy import stream as stream
        port = await stream.get_yy_stream_url(data)
        info = StreamInfo(anchor_name=port.get("anchor_name", ""))
        if not port.get("is_live"):
            return info
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.flv_url = port.get("flv_url", "")
        info.record_url = port.get("record_url", "") or info.flv_url
        return info