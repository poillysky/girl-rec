# -*- coding: utf-8 -*-
"""
抖音直播适配器
==============
迁移自原项目逆向资产（backend/legacy/spider.py + stream.py）：
    extract : spider.get_douyin_stream_data / get_douyin_app_stream_data / get_douyin_web_stream_data
              三通道自动切换（web 正则 HTML → app 接口 → 短链解析）
    resolve : stream.get_douyin_stream_url（含画质映射 OD/UHD/HD/SD/LD + m3u8 状态兜底）

原逻辑特性（全部保留）：
    1. 首通道 HTML 解析，失败/触发风控自动切 app 接口通道
    2. live.douyin.com/xxx 直连 web 通道；短链(v.douyin.com)先解析 sec_user_id 再走 app 通道
    3. a_bogus = SM3+RC4 纯 Python 签名（ab_sign.py）；X-Bogus 走 node（仅部分场景）
    4. flv/hls URL 列表按画质索引取值，m3u8 失效自动降级下一个
"""
from __future__ import annotations

from ..core.logger import get_logger
from ..legacy import spider
from ..legacy.http_clients.async_http import get_response_status
from .base import (
    BasePlatform, StreamInfo, AdapterError, StreamResolveError,
    TransientError, PermanentError, RoomNotFoundError, StreamerBannedError,
    CookieInvalidError,
)
from .registry import register

logger = get_logger("adapter.douyin")

# 原 stream.py QUALITY_MAPPING（键=画质名, 值=flv/hls列表索引）
QUALITY_MAPPING = {"OD": 0, "BD": 0, "UHD": 1, "HD": 2, "SD": 3, "LD": 4}


def _get_quality_index(quality: str) -> tuple:
    """画质名/数字 → (画质名, 索引)。原 legacy_stream.get_quality_index"""
    if not quality:
        return "原画", 0
    q = str(quality).upper()
    if q.isdigit():
        q = list(QUALITY_MAPPING.keys())[int(q[0])]
    return q, QUALITY_MAPPING.get(q, 0)


@register
class DouyinPlatform(BasePlatform):
    platform_name = "抖音"
    domains = ["live.douyin.com", "v.douyin.com", "douyin.com"]
    # 录制时需要 referer/UA 头（ffmpeg -headers）
    record_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Referer": "https://live.douyin.com/",
    }
    enable_proxy = False
    support_danmu = True          # LyzenX doyley + webmssdk.js 弹幕可挂
    only_flv = False
    stream_type = "FLV"           # 抖音主推 flv 源（HLS 多为低画质兜底）

    # cookie 失效计数（LyzenX record_cookie_failed 语义）：
    # 连续 max_cookie_failed 次"风控/验证"类失败判定 cookie 失效 → CookieInvalidError
    _cookie_failed = 0
    _max_cookie_failed = 5

    @classmethod
    def _record_cookie_failed(cls) -> None:
        cls._cookie_failed += 1
        logger.warning("抖音 cookie/风控失败计数 %d/%d", cls._cookie_failed, cls._max_cookie_failed)

    @classmethod
    def _cookie_ok(cls) -> None:
        """任意成功探测清零计数（同 LyzenX：成功→0）"""
        cls._cookie_failed = 0

    async def extract(self, url: str) -> dict:
        self._last_url = url
        try:
            data = await spider.get_douyin_stream_data(
                url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
        except Exception as e:
            logger.warning("抖音数据抓取失败: %s", e)
            msg = str(e)
            if self._is_banned(msg):
                raise StreamerBannedError(f"主播账号异常(封禁/违规): {msg}") from e
            if self._is_room_not_found(msg):
                raise RoomNotFoundError(f"直播间不存在/已下架: {msg}") from e
            # cookie 风控语义（LyzenX record_cookie_failed）：风险控制/系统繁忙/验证类失败累计计数
            if self._is_cookie_risk(msg):
                self._record_cookie_failed()
                if self._cookie_failed >= self._max_cookie_failed:
                    self._cookie_failed = 0
                    raise CookieInvalidError(
                        f"抖音 cookie 疑似失效（连续 {self._max_cookie_failed} 次风控/验证失败），请更新配置中的 cookie") from e
                raise TransientError(f"抖音接口临时失败(风控计数{self._cookie_failed}/{self._max_cookie_failed}): {e}") from e
            raise TransientError(f"抖音接口临时失败: {e}") from e
        if not data:
            self._cookie_ok()
            raise TransientError("抖音直播间数据为空")
        self._cookie_ok()
        return data

    @staticmethod
    def _is_banned(msg: str) -> bool:
        """主播封禁/违规关键词"""
        keywords = ("已封禁", "违规", "被限制", "banned", "blocked", "风控")
        return any(k in msg.lower() for k in keywords)

    @staticmethod
    def _is_room_not_found(msg: str) -> bool:
        """房间不存在关键词"""
        keywords = ("不存在", "已下架", "not found", "404", "removed")
        return any(k in msg.lower() for k in keywords)

    @staticmethod
    def _is_cookie_risk(msg: str) -> bool:
        """cookie 失效/风控前置关键词（LyzenX record_cookie_failed 判定源）：
        'it triggered risk control' 是原 spider 瀑布流接口的风控文案。"""
        keywords = (
            "risk control", "triggered", "繁忙", "验证", "captcha",
            "滑块", "login", "登录失效", "verify", "风控",
        )
        return any(k in msg.lower() for k in keywords)

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """
        从 extract() 原始数据解析流地址。
        status==2 表示直播中；画质按 QUALITY_MAPPING 索引取值，
        m3u8 实测失效自动降级画质。
        """
        anchor = data.get("anchor_name", "")
        info = StreamInfo(is_live=False, anchor_name=anchor)

        if data.get("status") != 2:
            # 明确未开播（status==4 平台封禁 / status==2 直播中）
            if str(data.get("status")) == "4":
                raise StreamerBannedError(f"直播间状态异常(status=4)，可能违规封禁: {anchor}")
            return info

        stream_url = data.get("stream_url")
        if not stream_url:
            raise StreamResolveError("直播间数据缺少 stream_url（可能是不支持的类型）")

        flv_list = list(stream_url.get("flv_pull_url", {}).values())
        m3u8_list = list(stream_url.get("hls_pull_url_map", {}).values())
        if not flv_list and not m3u8_list:
            return info

        # 补足 5 档画质（原逻辑：不足重复最后一个）。
        # 坑：flv/m3u8 可能只有其一为空，`flv_list[-1]` 会 IndexError ——
        # 补足源为空列表时用空串占位（resolve 择优时自然回退到另一通道）。
        while len(flv_list) < 5:
            flv_list.append(flv_list[-1] if flv_list else "")
        while len(m3u8_list) < 5:
            m3u8_list.append(m3u8_list[-1] if m3u8_list else "")

        q_name, q_idx = _get_quality_index(quality)
        m3u8_url = m3u8_list[q_idx]
        flv_url = flv_list[q_idx]

        # 原逻辑强化：m3u8 实测不可用（HEAD 失败）→ 降级下一档（q_idx+1，到头则回退 q_idx-1）
        # 注：m3u8 通道可能整体缺失（hls_pull_url_map 为空），此时跳过探测直接走 flv
        if m3u8_url:
            try:
                ok = await get_response_status(url=m3u8_url, proxy_addr=self.proxy or None)
            except Exception as e:
                logger.debug("m3u8 状态探测异常: %s", e)
                ok = False
            if not ok:
                idx = q_idx + 1 if q_idx < 4 else q_idx - 1
                m3u8_url = m3u8_list[idx]
                flv_url = flv_list[idx]

        # 择优录制地址：m3u8 优先（原项目 record_url = m3u8_url or flv_url）
        record_url = m3u8_url or flv_url

        info.is_live = True
        info.title = data.get("title", "")
        info.anchor_name = anchor
        info.quality = q_name
        info.m3u8_url = m3u8_url
        info.flv_url = flv_url
        info.record_url = record_url
        return info

    async def resolve_identifier(self, identifier: str) -> str | None:
        """把"房间号 / 抖音号(unique_id) / 直播间链接"解析为直播间 URL。
        规则：
          1. 纯数字(5-20位) → 房间号：live.douyin.com/{id}
          2. 已是 douyin.com / v.douyin.com 链接 → 原样返回
          3. 其他（抖音号 unique_id，如 ssuou）→ 反查链路：
             unique_id --(iesdouyin user/info)--> sec_uid
             sec_uid   --(douyin web profile/other)--> room_data.owner.web_rid
             得到直播间 ID 后拼 URL；不在直播则回退到用户主页 URL。
          4. 反查失败 → 返回 None，提示用户改用 ID 或链接。"""
        import re as _re
        _id = (identifier or "").strip()
        if not _id:
            return None
        if "douyin.com" in _id or "v.douyin.com" in _id:
            return _id
        if _re.fullmatch(r"\d{5,20}", _id):
            return f"https://live.douyin.com/{_id}"
        # 抖音号(unique_id) 反查
        return await self._resolve_unique_id(_id)

    async def _resolve_unique_id(self, unique_id: str) -> str | None:
        """抖音号 → sec_uid → 当前直播间 web_rid。反查失败返回 None。"""
        import httpx
        _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
        _ck = self.cookies.strip() if self.cookies else (
            "ttwid=1%7C4ejCkU2bKY76IySQENJwvGhg1IQZrgGEupSyTKKfuyk%7C1740470403"
            "%7Cbc9ad2ee341f1a162f9e27f4641778030d1ae91e31f9df6553a8f2efa3bdb7b4")
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                # 1) unique_id → sec_uid（iesdouyin 用户信息接口，免签名）
                r1 = await c.get(
                    f"https://www.iesdouyin.com/web/api/v2/user/info/?unique_id={unique_id}",
                    headers={"User-Agent": _UA})
                ui = (r1.json() or {}).get("user_info") or {}
                sec_uid = ui.get("sec_uid")
                if not sec_uid:
                    logger.info("抖音号反查 sec_uid 失败: %s", unique_id)
                    return None
                # 2) sec_uid → 当前直播间 web_rid（douyin web profile 接口，room_data）
                r2 = await c.get(
                    "https://www.douyin.com/aweme/v1/web/user/profile/other/"
                    f"?sec_user_id={sec_uid}&device_platform=webapp&aid=6383&channel=channel_pc_web",
                    headers={"User-Agent": _UA, "Referer": "https://www.douyin.com/", "Cookie": _ck})
                _u = (r2.json() or {}).get("user") or {}
                _rd = _u.get("room_data") or {}
                if isinstance(_rd, str):   # room_data 是 JSON 字符串
                    import json as _json
                    try:
                        _rd = _json.loads(_rd)
                    except Exception:
                        _rd = {}
                web_rid = ((_rd.get("owner") or {}).get("web_rid") if isinstance(_rd, dict) else None)
                if web_rid:
                    logger.info("抖音号 %s 反查到直播间 web_rid=%s", unique_id, web_rid)
                    return f"https://live.douyin.com/{web_rid}"
                # 不在直播：回退到用户主页（前端仍可提示"未开播"，用 sec_uid 定位主播）
                logger.info("抖音号 %s 当前未开播（无 room_data），回退用户主页", unique_id)
                return f"https://www.douyin.com/user/{sec_uid}"
        except Exception as e:  # noqa: BLE001
            logger.warning("抖音号反查失败 %s: %s", unique_id, e)
            return None