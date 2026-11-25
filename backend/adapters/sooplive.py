# -*- coding: utf-8 -*-
"""
SOOP 直播适配器
=============
迁移自原项目逆向资产（legacy/spider.get_sooplive_stream_data + stream.get_stream_url(spec=True)）。
登录平台：sooplive.com 域名直连海外接口；sooplive.co.kr 走 tk/bj_id 逻辑。
new_cookies 自动回写 configs 表（Cookie:sooplive_cookie）。
"""
from __future__ import annotations

from ..core.config_service import config_service
from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.sooplive")


@register
class SooplivePlatform(BasePlatform):
    platform_name = "SOOP"
    domains = ['sooplive.co.kr', 'sooplive.com']
    enable_proxy = True
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_sooplive_stream_data，带登录参数）"""
        from ..legacy import spider
        self._last_url = url
        username, password = config_service.get_platform_credential("sooplive")
        try:
            data = await spider.get_sooplive_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None,
                username=username or None, password=password or None)
            data = data or {}
            if data.get("new_cookies"):
                config_service.set("Cookie:sooplive_cookie", data["new_cookies"])
            return data
        except Exception as e:
            logger.warning("SOOP 数据抓取失败: %s", e)
            raise TransientError(f"SOOP 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """SOOP 专属：spec=True 用顶层 m3u8_url/flv_url（原版 stream.get_stream_url）"""
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
        info.record_url = port.get("record_url", "") or info.m3u8_url or info.flv_url
        return info