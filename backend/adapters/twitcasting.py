# -*- coding: utf-8 -*-
"""
TwitCasting 直播适配器
=============
迁移自原项目逆向资产（legacy/spider.get_twitcasting_stream_url + stream.get_stream_url(spec=False)）。
登录平台：account_type（normal/other）+ username/password；new_cookies 自动回写 configs 表（Cookie:twitcasting_cookie）。
"""
from __future__ import annotations

from ..core.config_service import config_service
from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.twitcasting")


@register
class TwitcastingPlatform(BasePlatform):
    platform_name = "TwitCasting"
    domains = ['twitcasting.tv']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_twitcasting_stream_url，带登录参数）"""
        from ..legacy import spider
        self._last_url = url
        username, password = config_service.get_platform_credential("twitcasting")
        account_type = config_service.get("账号密码:twitcasting账号类型", "normal")
        try:
            data = await spider.get_twitcasting_stream_url(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None,
                account_type=account_type or "normal",
                username=username or None, password=password or None)
            data = data or {}
            if data.get("new_cookies"):
                config_service.set("Cookie:twitcasting_cookie", data["new_cookies"])
            return data
        except Exception as e:
            logger.warning("TwitCasting 数据抓取失败: %s", e)
            raise TransientError(f"TwitCasting 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """TwitCasting 专属：play_url_list 结构（原版 stream.get_stream_url spec=False）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        port = await stream.get_stream_url(data, quality, spec=False)
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.m3u8_url = port.get("m3u8_url", "")
        info.record_url = port.get("record_url", "") or info.m3u8_url
        return info