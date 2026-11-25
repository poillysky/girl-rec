# -*- coding: utf-8 -*-
"""
虎牙直播 适配器
=============
迁移自原项目逆向资产（legacy/spider.get_huya_stream_data / get_huya_app_stream_url + stream.get_huya_stream_url）。
原版语义：普通画质走 get_huya_stream_data → stream.get_huya_stream_url；原画/蓝光/超清 走 get_huya_app_stream_url（小程序接口）。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.huya")


@register
class HuyaPlatform(BasePlatform):
    platform_name = "虎牙直播"
    domains = ['www.huya.com']
    enable_proxy = False
    support_danmu = False
    only_flv = False
    only_audio = False

    async def extract(self, url: str) -> dict:
        self._last_url = url
        from ..legacy import spider
        try:
            data = await spider.get_huya_stream_data(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {}
        except Exception as e:
            logger.warning("虎牙直播 数据抓取失败: %s", e)
            raise TransientError(f"虎牙直播 接口临时失败: {e}") from e

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """虎牙专属：原画/蓝光/超清走 app 接口，其余走 web 取流"""
        from ..legacy import stream as stream
        from ..legacy import spider
        if quality in ("OD", "BD", "UHD"):
            # app 接口返回已含 all 格式（原版直接 port_info）
            port = await spider.get_huya_app_stream_url(
                url=self._last_url or "", proxy_addr=self.proxy or None, cookies=self.cookies or None)
            if port and port.get("is_live"):
                return StreamInfo(
                    is_live=True,
                    title=port.get("title", ""),
                    anchor_name=port.get("anchor_name", ""),
                    quality=quality,
                    flv_url=port.get("flv_url", ""),
                    m3u8_url=port.get("m3u8_url", ""),
                    record_url=port.get("record_url", "") or port.get("flv_url", "") or port.get("m3u8_url", ""),
                )
            return StreamInfo(anchor_name=(port or {}).get("anchor_name", ""))
        port = await stream.get_huya_stream_url(data, quality)
        info = StreamInfo(anchor_name=port.get("anchor_name", ""))
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

    # resolve 需要 url（app 分支重新请求），由 scheduler/session 传入 extra
    def set_url_context(self, url: str) -> None:
        self._last_url = url