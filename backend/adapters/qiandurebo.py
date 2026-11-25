# -*- coding: utf-8 -*-
"""
千度热播 直播适配器
=================
迁移自原项目逆向资产（legacy/spider.py → get_qiandurebo_stream_data）。
一平台一文件：本文件即 千度热播 全部接入逻辑。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.qiandurebo")


@register
class QiandureboPlatform(BasePlatform):
    platform_name = "千度热播"
    domains = ['qiandurebo.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False
    record_headers = {"referer": "https://qiandurebo.com"}

    async def extract(self, url: str) -> dict:
        self._last_url = url
        from ..legacy import spider
        try:
            data = await spider.get_qiandurebo_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("千度热播 数据抓取失败: %s", e)
            raise TransientError(f"千度热播 接口临时失败: {e}") from e

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
