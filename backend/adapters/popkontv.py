# -*- coding: utf-8 -*-
"""
PopkonTV 直播适配器
=============
迁移自原项目逆向资产（legacy/spider.get_popkontv_stream_url + get_popkontv_stream_data）。
登录平台：access_token（Authorization Bearer）+ username/password + partner_code；
new_token 自动回写 configs 表（Authorization:popkontv_token）。
"""
from __future__ import annotations

from ..core.config_service import config_service
from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.popkontv")


@register
class PopkontvPlatform(BasePlatform):
    platform_name = "PopkonTV"
    domains = ['www.popkontv.com']
    enable_proxy = True
    support_danmu = False
    only_flv = False
    only_audio = False
    record_headers = {"origin": "https://www.popkontv.com"}

    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.get_popkontv_stream_url，带 token + 登录参数）"""
        from ..legacy import spider
        self._last_url = url
        username, password = config_service.get_platform_credential("popkontv")
        access_token = config_service.get("Authorization:popkontv_token")
        partner_code = config_service.get("账号密码:partner_code", "P-00001")
        try:
            data = await spider.get_popkontv_stream_url(
                url=url,
                proxy_addr=self.proxy or None,
                access_token=access_token or None,
                username=username or None,
                password=password or None,
                partner_code=partner_code or "P-00001")
            data = data or {}
            if data.get("new_token"):
                config_service.set("Authorization:popkontv_token", data["new_token"])
            return data
        except Exception as e:
            logger.warning("PopkonTV 数据抓取失败: %s", e)
            raise TransientError(f"PopkonTV 接口临时失败: {e}") from e

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