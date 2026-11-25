# -*- coding: utf-8 -*-
"""
平台适配器基类
==============
定义平台接入的统一接口。新平台继承本类即可完成接入。

职责划分（从原项目 main.py 路由逻辑提炼）：
    domains        : URL 匹配域名（原 main.py platform_host 列表）
    extract()      : 拉取直播间数据，判断是否在播（原 spider.get_xx_stream_data）
    resolve()      : 从数据中抽出可录制流（原 stream.get_xx_stream_url）
    record_headers : 录制时 ffmpeg 需要的额外 headers（原 main.py get_record_headers）
    preferred      : 录制偏好（flv/m3u8/audio）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..core.logger import get_logger

logger = get_logger("adapter")


class AdapterError(Exception):
    """平台适配器基础错误"""


class StreamResolveError(AdapterError):
    """流地址解析失败（直播间未开播等）"""


# ---------------------------------------------------------------
# 错误分类（stream-rec analyzeError 同款思路）
# 每个错误自带 retryable 标志：决定主循环是"快速重试"还是"拉长重试/停止"
# ---------------------------------------------------------------
class TransientError(AdapterError):
    """临时性错误（网络抖动/风控限流/接口偶发500）：应快速重试。retryable=True"""
    retryable: bool = True


class PermanentError(AdapterError):
    """永久性错误（房间不存在/主播封禁/账号固有问题）：重试无意义，应拉长重试或停止。retryable=False"""
    retryable: bool = False


class RoomNotFoundError(PermanentError):
    """直播间不存在/已下架（stream-rec StreamerNotFound）：暂停长退避后继续轮询，DB删除才彻底停"""
    retryable: bool = False
    backoff_seconds: int = 300          # 暂停 5 分钟再探


class StreamerBannedError(PermanentError):
    """主播封禁/违规/风控（stream-rec StreamerBanned）：暂停最长退避，避免触发风控"""
    retryable: bool = False
    backoff_seconds: int = 3600         # 暂停 1 小时再探（封禁通常持续）


class CookieInvalidError(PermanentError):
    """平台 Cookie 失效（LyzenX record_cookie_failed 语义）：
    连续多次检测到 cookie 相关失败（系统繁忙/验证/登录失效）后抛出，
    触发 on_cookie_invalid 事件通知用户换 cookie。"""
    retryable: bool = False
    backoff_seconds: int = 600          # 换 cookie 前暂停 10 分钟（用户有操作时间）


@dataclass
class StreamInfo:
    """统一流信息结构（所有平台 resolve 的返回契约）"""
    is_live: bool = False
    title: str = ""
    anchor_name: str = ""
    quality: str = ""
    flv_url: str = ""
    m3u8_url: str = ""
    record_url: str = ""          # 实际录制用地址
    extra: dict[str, Any] = field(default_factory=dict)


class BasePlatform:
    """平台适配器基类"""

    # ---- 平台静态声明 ----
    platform_name: ClassVar[str] = ""       # 中文名（数据库/前端显示）
    domains: ClassVar[list[str]] = []       # URL 域名匹配
    record_headers: ClassVar[dict] = {}     # 录制额外 headers
    enable_proxy: ClassVar[bool] = False    # 是否需要代理
    support_danmu: ClassVar[bool] = False   # 是否支持弹幕扩展
    only_flv: ClassVar[bool] = False        # 强制 flv 录制
    only_audio: ClassVar[bool] = False      # 纯音频平台
    force_http: ClassVar[bool] = False      # 录制流强制 http（原版 http_record_list：shopee/migu）
    enable_https_recording: ClassVar[bool | None] = None  # None=跟随全局配置(默认否)
    stream_type: ClassVar[str] = "HLS"      # 实际流类型：HLS / FLV / Agora（决定取哪个源与分片格式表）

    def __init__(self, cookies: str = "", proxy: str = ""):
        self.cookies = cookies
        self.proxy = proxy
        self._last_url = ""  # extract() 记录，供需要二次请求的 resolve（如虎牙app）使用

    # ---- 子类必须实现 ----
    async def extract(self, url: str) -> dict:
        self._last_url = url
        raise NotImplementedError(f"{self.platform_name} 未实现 extract()")

    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """从 extract() 返回的原始数据中解析出可录制流地址。
        返回 StreamInfo。未开播时 is_live=False。
        注意：生成为 async——需要实测流地址可用性（HEAD 请求）时可以直接 await。"""
        raise NotImplementedError(f"{self.platform_name} 未实现 resolve()")

    # ---- 主播名/ID 解析（可选能力） ----
    async def resolve_identifier(self, identifier: str) -> str | None:
        """把"主播名 / 抖音号 / 房间号"等非 URL 标识解析为直播间 URL。
        返回 URL 字符串；不支持该平台返回 None（表示请用户贴链接）。
        子类可按需覆盖。"""
        return None

    # ---- 通用查询 ----
    @classmethod
    def match(cls, url: str) -> bool:
        return any(domain in url for domain in cls.domains)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Platform:{self.platform_name}>"