# -*- coding: utf-8 -*-
"""
FlexTV 直播适配器
=============
迁移自原项目逆向资产（legacy/spider.get_flextv_stream_data + stream.get_stream_url(spec=True)）。
登录平台：19+ 直播需登录（aker_id 获取）；new_cookies 自动回写 configs 表（Cookie:flextv_cookie）。
"""
from __future__ import annotations

from ..core.config_service import config_service
from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.flextv")


@register
class FlextvPlatform(BasePlatform):
    platform_name = "FlexTV"
    domains = ['www.flextv.co.kr', 'www.ttinglive.com']
    enable_proxy = True
    support_danmu = False
    only_flv = False
    only_audio = False
    record_headers = {"origin": "https://www.flextv.co.kr"}

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_flextv_stream_data，带登录参数）"""
        from ..legacy import spider
        self._last_url = url
        username, password = config_service.get_platform_credential("flextv")
        try:
            data = await spider.get_flextv_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None,
                username=username or None, password=password or None)
            data = data or {}
            if data.get("new_cookies"):
                config_service.set("Cookie:flextv_cookie", data["new_cookies"])
            return data
        except Exception as e:
            logger.warning("FlexTV 数据抓取失败: %s", e)
            raise TransientError(f"FlexTV 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """FlexTV 专属：play_url_list 存在走 spec=True，否则原样返回（原版语义）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        if "play_url_list" in data:
            port = await stream.get_stream_url(data, quality, spec=True)
        else:
            port = data
        info.is_live = True
        info.title = port.get("title", "") if isinstance(port, dict) else data.get("title", "")
        info.anchor_name = port.get("anchor_name", "") if isinstance(port, dict) else data.get("anchor_name", "")
        info.quality = port.get("quality", quality) if isinstance(port, dict) else quality
        info.m3u8_url = port.get("m3u8_url", "") if isinstance(port, dict) else data.get("m3u8_url", "")
        info.flv_url = port.get("flv_url", "") if isinstance(port, dict) else data.get("flv_url", "")
        info.record_url = (port.get("record_url", "") if isinstance(port, dict) else "") \
            or info.m3u8_url or info.flv_url
        return info