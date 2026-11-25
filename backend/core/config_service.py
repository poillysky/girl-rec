# -*- coding: utf-8 -*-
"""
ConfigService 配置读取服务
==========================
替代原 main.py 每循环 `read_config_value(config.ini, ...)` 的解析，
统一从 configs 表读取，并把 ini 时代的扁平键映射为结构化访问：

    原版键（迁移后保留）           → 本服务方法
    Cookie:抖音cookie             → get_platform_cookie("抖音")
    录制设置:是否使用代理ip(是/否)  → get_proxy_for() 内部总开关
    录制设置:代理地址              → get_proxy_for() 返回 address
    录制设置:使用代理录制的平台(逗号分隔) → get_proxy_for() 白名单
    录制设置:额外使用代理录制的平台(逗号分隔) → get_proxy_for() 附加白名单
    录制设置:循环时间(秒)          → get_int("循环时间(秒)", 120)
    录制设置:原画|超清|...         → get("原画|超清|高清|标清|流畅", "原画")

代理语义与原 main.py:550-574 完全一致：
    if proxy_addr 总开:
        平台白名单中任一子串命中 record_url → 使用代理
    否则查额外白名单，命中 → 使用代理
（原版 enable_proxy_platform_list 默认
 'tiktok, soop, pandalive, winktv, flextv, popkontv, twitch, liveme, showroom, chzzk, shopee, shp, youtu, faceit'）

线程/协程安全：只读查询，每次 new session；数据由 RoomScheduler 8s 热更新驱动。
"""
from __future__ import annotations

import time
from datetime import datetime as dt
from typing import Optional

from ..core.logger import get_logger
from ..models import Config, get_session

logger = get_logger("config_service")

# 原版 enable_proxy_platform 默认值（main.py 默认参数）
DEFAULT_PROXY_PLATFORMS = (
    "tiktok, soop, pandalive, winktv, flextv, popkontv, twitch, "
    "liveme, showroom, chzzk, shopee, shp, youtu, faceit"
)

_YES_NO = {"是": True, "否": False, "true": True, "false": False,
           "1": True, "0": False, "": False}


class ConfigService:
    """configs 表只读门面（每查询短连接，池由 SQLAlchemy sessionmaker 管理）"""

    _CACHE_TTL = 2.0   # 秒：同一配置项 2s 内复用，避免每次 get() 新建一个 DB session

    def __init__(self) -> None:
        self._cache: dict[str, tuple] = {}

    # ---------- 基础 ----------
    def get(self, key: str, default: str = "") -> str:
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and now - hit[1] < self._CACHE_TTL:
            return hit[0] if hit[0] is not None else default
        value = None
        try:
            db = get_session()
            try:
                row = db.query(Config).filter(Config.key == key).first()
                value = row.value if row else None
            finally:
                db.close()
        except Exception:
            return default
        self._cache[key] = (value, now)
        return value if value is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        raw = self.get(key, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key, "是" if default else "否")
        return _YES_NO.get(raw.strip().lower(), default)

    def get_float(self, key: str, default: float = 0.0) -> float:
        raw = self.get(key, str(default))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def set(self, key: str, value: str) -> None:
        """写 configs 表（登录平台 new_cookies/new_token 回写、前端改配置共用）。"""
        try:
            db = get_session()
            try:
                row = db.query(Config).filter(Config.key == key).first()
                if row:
                    row.value = value
                    row.updated_at = dt.utcnow()
                else:
                    db.add(Config(key=key, value=value))
                db.commit()
            finally:
                db.close()
            self._cache.pop(key, None)   # 写后失效，避免读到 2s 前的旧值
        except Exception as exc:
            logger.warning("ConfigService.set(%s) 写入失败: %s", key, exc)

    # ---------- 平台账号密码（登录平台用） ----------
    def get_platform_credential(self, platform_file: str) -> tuple:
        """取登录平台账号密码（用户名, 密码）。
        原版 config.ini 键形如 `账号密码:sooplive账号` / `账号密码:sooplive密码`。
        """
        username = self.get(f"账号密码:{platform_file}账号")
        password = self.get(f"账号密码:{platform_file}密码")
        return username, password

    # ---------- 平台 cookie ----------
    def get_platform_cookie(self, platform_name: str) -> str:
        """取某平台 cookie。
        原版键形如 `Cookie:抖音cookie` / `Cookie:tiktok_cookie`；
        兼容旧迁移形态 `cookie:抖音`。"""
        for key in (f"Cookie:{platform_name}cookie",
                    f"Cookie:{platform_name}_cookie",
                    f"cookie:{platform_name}"):
            value = self.get(key)
            if value:
                return value
        # 原版对部分平台键不带中文后缀：Cookie:快手cookie 等已覆盖；
        # 若平台名本身带下划线（tiktok_cookie）也兼容
        return ""

    # ---------- 平台级参数（平台:{名}:xxx，前端平台设置页写入） ----------
    def get_platform_quality(self, platform_name: str, default: str = "") -> str:
        """平台级默认画质（平台:{名}:默认画质）；未配置返回 default。"""
        value = self.get(f"平台:{platform_name}:默认画质", "").strip()
        return value or default

    def get_platform_enabled(self, platform_name: str, default: bool = True) -> bool:
        """平台级录制开关（平台:{名}:录制启用）；未配置视为启用。"""
        raw = self.get(f"平台:{platform_name}:录制启用", "").strip()
        if not raw:
            return default
        return _YES_NO.get(raw.lower(), default)

    def get_min_file_size_mb(self, default: int = 1) -> int:
        """最小有效文件大小(MB)：小于该值判废删除（stream-rec minPartSize 同款）"""
        return self.get_int("录制设置:最小有效文件大小(mb)", default)

    # ---------- 代理 ----------
    def get_platform_proxy(self, platform_name: str, record_url: str) -> str:
        """平台级代理判定：优先读 平台:{平台名}:启用代理 单平台开关；
        未单独配置则回退到全局 get_proxy_for（按平台名单子串匹配）。
        """
        # 总开关关 → 一律不走
        if not self.get_bool("录制设置:是否使用代理ip(是/否)", True):
            return ""
        proxy_addr = self.get("录制设置:代理地址").strip()
        if not proxy_addr:
            return ""
        per = self.get(f"平台:{platform_name}:启用代理")
        if per in ("是", "否"):
            return proxy_addr if per == "是" else ""
        # 未单独配置 → 回退全局名单逻辑
        return self.get_proxy_for(platform_name, record_url)

    def get_proxy_for(self, platform_name: str, record_url: str) -> str:
        """按原版语义判断该 URL 是否走代理，返回代理地址（不走返回 ""）。

        record_url 传入完整直播间 URL（含域名），白名单用子串匹配：
            平台白名单(使用代理录制的平台(逗号分隔)) 命中 → 使用代理
            未命中再查额外白名单(额外使用代理录制的平台(逗号分隔))
        总开关(是否使用代理ip(是/否)) 为否 → 一律不走。
        """
        if not self.get_bool("录制设置:是否使用代理ip(是/否)", True):
            return ""
        proxy_addr = self.get("录制设置:代理地址").strip()
        if not proxy_addr:
            return ""

        whitelist = self.get("录制设置:使用代理录制的平台(逗号分隔)",
                             DEFAULT_PROXY_PLATFORMS)
        if self._substring_hit(whitelist, record_url):
            return proxy_addr

        extra = self.get("录制设置:额外使用代理录制的平台(逗号分隔)")
        if self._substring_hit(extra, record_url):
            return proxy_addr
        return ""

    @staticmethod
    def _substring_hit(platforms_csv: str, record_url: str) -> bool:
        """逗号分隔平台名单 → 任一子串命中 URL 即 True（原版 `in record_url`）"""
        if not platforms_csv:
            return False
        for platform in platforms_csv.replace("，", ",").split(","):
            item = platform.strip()
            if item and item in record_url:
                return True
        return False

    # ---------- 录制参数（原版主配置读取段） ----------
    def get_quality(self, default: str = "原画") -> str:
        return self.get("录制设置:原画|超清|高清|标清|流畅", default)

    def get_save_type(self, default: str = "ts") -> str:
        return self.get("录制设置:视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频", default)

    def get_stream_format(self, stream_type: str, default: str = "") -> str:
        """按流类型取分片容器：HLS流分片格式 / FLV流分片格式 / Agora流分片格式；
        未配置则回落全局「视频保存格式」（兜底默认）。"""
        key_map = {
            "HLS": "录制设置:HLS流分片格式",
            "FLV": "录制设置:FLV流分片格式",
            "Agora": "录制设置:Agora流分片格式",
        }
        k = key_map.get(stream_type)
        if k:
            v = self.get(k, "")
            if v:
                return v
        return self.get("录制设置:视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频", default or "ts")

    def get_split_enabled(self, default: bool = False) -> bool:
        return self.get_bool("录制设置:分段录制是否开启", default)

    def get_seg_time(self, default: int = 1800) -> int:
        return int(self.get("录制设置:视频分段时间(秒)", str(default)))

    def get_loop_delay(self, default: int = 120) -> int:
        """原版循环时间(秒)，探测轮询基准秒数（随机 ±5，错误多 +60 由调用方做）"""
        return self.get_int("录制设置:循环时间(秒)", default)

    def get_max_duration_seconds(self, default: int = 0) -> int:
        """单次录制最大时长（秒），0=不限（stream-rec maxDownloadTime 同款）"""
        return self.get_int("录制设置:单次录制最大时长(秒)", default)

    def get_max_size_mb(self, default: int = 0) -> int:
        """单次录制最大文件大小（MB），0=不限（stream-rec maxDownloadSize 同款）"""
        return self.get_int("录制设置:单次录制最大大小(mb)", default)

    def get_save_dir(self, default: str = "downloads") -> str:
        return self.get("录制设置:直播保存路径(不填则默认)", default).strip() or default

    def get_disk_space_limit_gb(self, default: float = 1.0) -> float:
        return self.get_float("录制设置:录制空间剩余阈值(gb)", default)

    # ---------- 两库两目录（缓存库/成品库）----------
    def get_cache_dir(self, default: str = "cache") -> str:
        """下载缓存目录：录制过程中的 ts 分片等非成品持续写入这里（可随时清理）"""
        return self.get("录制设置:缓存目录(不填则默认)", "").strip() or default

    def get_product_dir(self, default: str = "downloads") -> str:
        """成品目录：合并完成的完整 mp4 文件转移存放这里（默认 downloads）"""
        return self.get("录制设置:成品目录(不填则默认)", "").strip() or default

    def get_auto_move_product(self, default: bool = True) -> bool:
        """合并出成品 mp4 后是否自动转移到成品目录（默认是）"""
        return self.get_bool("录制设置:成品自动转移至成品库", default)

    # ---------- 命名 / 目录结构（对齐原版）----------
    def get_filename_include_title(self, default: bool = False) -> bool:
        """文件名是否包含直播标题"""
        return self.get_bool("录制设置:保存文件名是否包含标题", default)

    def get_dir_by_author(self, default: bool = True) -> bool:
        """保存文件夹是否以作者区分"""
        return self.get_bool("录制设置:保存文件夹是否以作者区分", default)

    def get_dir_by_time(self, default: bool = False) -> bool:
        """保存文件夹是否以时间区分"""
        return self.get_bool("录制设置:保存文件夹是否以时间区分", default)

    def get_dir_by_title(self, default: bool = False) -> bool:
        """保存文件夹是否以标题区分"""
        return self.get_bool("录制设置:保存文件夹是否以标题区分", default)

    def get_strip_emoji(self, default: bool = False) -> bool:
        """是否去除文件名中的表情符号"""
        return self.get_bool("录制设置:是否去除名称中的表情符号", default)

    # ---------- 转码 / 字幕 ----------
    def get_convert_h264(self, default: bool = False) -> bool:
        """mp4 是否重新编码为 h264（否=直接 copy 封装）"""
        return self.get_bool("录制设置:mp4格式重新编码为h264", default)

    def get_gen_srt(self, default: bool = False) -> bool:
        """是否生成时间字幕文件（.srt）"""
        return self.get_bool("录制设置:生成时间字幕文件", default)

    # ---------- 调试日志 ----------
    def get_show_loop_seconds(self, default: bool = False) -> bool:
        return self.get_bool("录制设置:是否显示循环秒数", default)

    def get_show_stream_url(self, default: bool = False) -> bool:
        return self.get_bool("录制设置:是否显示直播源地址", default)

    def get_skip_proxy_check(self, default: bool = False) -> bool:
        return self.get_bool("录制设置:是否跳过代理检测(是/否)", default)

    # ---------- 推送 ----------
    def get_push_check_interval(self, default: int = 1800) -> int:
        """推送状态检测频率（秒）"""
        return self.get_int("推送配置:直播推送检测频率(秒)", default)

    def get_notify_only(self, default: bool = False) -> bool:
        """只推送通知不录制"""
        return self.get_bool("推送配置:只推送通知不录制(是/否)", default)


# 全局单例（RoomScheduler/RecordingSession 共用）
config_service = ConfigService()

