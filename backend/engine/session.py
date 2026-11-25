# -*- coding: utf-8 -*-
"""
RecordingSession 录制会话
=========================
一次直播 = 一个 Session 对象（吸收 olive 的 bout 设计 + stream-rec 状态机）。

状态流转：
    idle -> checking(探测中) -> preparing(取流) -> recording(录制中)
              └--> 未开播 -> idle（回到探测）
    recording -> stopping(优雅停止) -> finished/failed/stopped
                 │                                    
                 ├--> 断流/卡死 -> 自愈重连 -> preparing -> recording
                 └--> 停止请求 -> stopped

核心能力（录制最强）：
    1. 状态机驱动 + DB 持久化（崩溃可恢复）
    2. 断流自愈：ffmpeg 异常退出自动重连（指数退避，最大 N 次）
    3. 死流检测：卡顿超过阈值自动重启录制
    4. 事件广播：开播/关播/出错实时推给订阅者（推送/前端）
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ..adapters import (
    BasePlatform, StreamInfo, PermanentError, TransientError,
    RoomNotFoundError, StreamerBannedError, CookieInvalidError,
)
from ..core.config_service import config_service
from ..core.event_bus import event_center
from ..core.logger import get_logger
from ..legacy import utils as legacy_utils  # get_query_params（flv codec 判断）
from .ffmpeg import FFmpegRecorder, build_command, _is_overseas_url
from .post_processor import post_processor

if TYPE_CHECKING:  # pragma: no cover
    from ..models import Session

logger = get_logger("session")

STATE_IDLE = "idle"
STATE_CHECKING = "checking"
STATE_PREPARING = "preparing"
STATE_RECORDING = "recording"
STATE_STOPPING = "stopping"
STATE_FINISHED = "finished"
STATE_FAILED = "failed"
STATE_STOPPED = "stopped"

# 自愈参数
MAX_RECONNECT = 5          # 单次直播最大重连次数
RECONNECT_BASE_DELAY = 3   # 重连基础等待秒
DEAD_STREAM_TIMEOUT = 300  # 卡死检测：300s 无数据认为死流（可配）
PROGRESS_REPORT_INTERVAL = 3  # 录制进度上报去抖间隔（秒）

# 录制完成后快速复检窗口（原项目逻辑：录完马上再探测，防主播卡顿）
POST_FINISH_RECHECK = 30

# 续录保护：连续 N 段时长都不到 M 秒 -> 判定空流/风控，停止续录（防无限续录空转）
MIN_VALID_SEGMENT_SECONDS = 10
MAX_EMPTY_SEGMENTS = 3


class RecordingSession:
    """单个直播间的录制会话"""

    def __init__(self, room_id: int, url: str, platform_cls: type[BasePlatform],
                 adapter: BasePlatform, quality: str = "原画",
                 save_type: str = "ts", save_dir: str = "downloads",
                 seg_time: int = 1800, split: bool = False,
                 important: bool = False, db_session_factory=None,
                 net_sem=None) -> None:
        self.room_id = room_id
        self.url = url
        self.platform_cls = platform_cls
        self.platform_name = platform_cls.platform_name
        self.adapter = adapter
        self.quality = quality
        self.save_type = save_type.upper()
        self.save_dir = save_dir
        self.seg_time = seg_time
        self.split = split
        self.important = important
        self.db_session_factory = db_session_factory
        self._net_sem = net_sem   # 同一时间访问网络的并发信号量（可空）
        self._stream_type = "HLS"  # 实际流类型（HLS/FLV/Agora），每次录制前按配置重算

        self.state = STATE_IDLE
        self.stream_info: StreamInfo | None = None
        self.recorder: FFmpegRecorder | None = None
        self.anchor_name = ""
        self.live_title = ""
        self.save_file_path = ""
        self.start_time: dt.datetime | None = None
        self.stop_requested = False
        self.stop_recording_only = False   # 只停当前录制、保留探测循环（房间停用但需继续监控在线状态）
        self.no_data_since = 0.0        # 死流检测时间戳
        self.reconnect_count = 0
        self.record_finished_at: float = 0.0
        self._paused_until: float = 0.0
        self._last_check_had_error = False   # 上一轮探测/录制出过错 → delay +60（原版 error_count>20）
        self._last_progress_at: float = 0.0  # 录制进度上报去抖时间戳
        # stream-rec maxDownload 同款：单次录制上限（0=不限），录制前由 _refresh_runtime_config 热刷
        self._max_duration_seconds: int = 0
        self._max_size_bytes: int = 0
        # 达到大小上限封顶切段标记（本批 mp4 合并后继续录下一批）
        self._size_capped: bool = False
        self._empty_segments: int = 0   # 连续无效段计数（续录保护）

    # ---------- 状态管理 ----------
    def _set_state(self, state: str, error: str = "") -> None:
        self.state = state
        if error:
            logger.error("[%s] %s | %s", self.platform_name, self.anchor_name or self.url, error)
        logger.info("[%s] %s -> %s", self.platform_name, self.anchor_name or self.url, state)
        asyncio.ensure_future(self._emit_state(error=error))

    async def _emit_state(self, error: str = "") -> None:
        await event_center.emit_session(
            self.room_id, self.state,
            dict(url=self.url, platform=self.platform_name, anchor=self.anchor_name,
                 title=self.live_title, error=error or ""),
        )

    async def _net(self, coro):
        """限制并发网络访问（同一时间访问网络的线程数）：有信号量则取，否则直跑。"""
        if self._net_sem is None:
            return await coro
        async with self._net_sem:
            return await coro

    # ---------- 主循环 ----------
    async def run(self) -> None:
        """会话主循环：探测 -> 取流 -> 录制 -> 自愈 -> 回到探测"""
        logger.info("开始监听 [%s] %s", self.platform_name, self.url)
        if self.stop_requested:
            return
        self._persist_start()
        while not self.stop_requested:
            try:
                await self._check_and_record()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("会话异常: %s", e)
                await event_center.emit_rec_error(self.room_id, self.url, str(e))
                self._last_check_had_error = True
            # 探测间隔: 正常 delay + 随机抖动（防封）, 录完快速复检
            delay = self._next_check_delay()
            if self._paused_until > time.time():
                # 永久性错误暂停期：睡到暂停结束（不空转快速轮询）
                delay = int(self._paused_until - time.time()) + 1
            # 调试日志：是否显示循环秒数（可配：录制设置:是否显示循环秒数）
            if config_service.get_show_loop_seconds(False):
                logger.info("[%s] 循环等待 %ds 后再次探测", self.anchor_name or self.platform_name, delay)
            await self._sleep_interruptible(delay)
        self._persist_end()

    def _next_check_delay(self) -> int:
        """探测间隔：从 DB 配置循环时间(秒) 取基准，加随机抖动 ±5，录完 30s 快速复检。
        瞬时错误计数（原版 error_count>20）再加 60s——由 _last_check_had_error 传递。"""
        base = config_service.get_loop_delay()
        if self.record_finished_at and time.time() - self.record_finished_at < 60:
            return POST_FINISH_RECHECK
        delay = base + random.randint(-5, 5)
        if delay < 0:
            delay = 0
        # 重要房间：探测节奏加倍（LyzenX 分级语义：重要房间更快捕捉开播）
        if self.important:
            delay = max(delay // 2, 3)
        if self._last_check_had_error:
            self._last_check_had_error = False
            delay += 60
        return delay

    async def _sleep_interruptible(self, seconds: int) -> None:
        """可中断的等待（收到停止请求立即结束）"""
        for _ in range(seconds):
            if self.stop_requested:
                return
            await asyncio.sleep(1)

    # ---------- 探测+录制 ----------
    async def _check_and_record(self) -> None:
        self._set_state(STATE_CHECKING)
        try:
            data = await self._net(self.adapter.extract(self.url))
            if not data:
                # 解析失败 -> 记录错误但继续循环（原项目行为）
                await event_center.emit_rec_error(self.room_id, self.url, "直播间数据解析失败")
                return
            stream_info = await self._net(self.adapter.resolve(data, self.quality))
        except StreamerBannedError as e:
            # 主播封禁/违规：暂停最长退避（1h），避免触发风控；不终止协程（等DB删除才会停）
            logger.warning("主播封禁 %s: %s", self.url, e)
            await event_center.emit_rec_error(self.room_id, self.url, f"[封禁] {e}")
            self._pause_long(e.backoff_seconds)
            return
        except RoomNotFoundError as e:
            # 房间不存在/下架：暂停长退避（5min）后继续轮询；DB删除会停
            logger.warning("房间不存在 %s: %s", self.url, e)
            await event_center.emit_rec_error(self.room_id, self.url, f"[房间不存在] {e}")
            self._pause_long(e.backoff_seconds)
            return
        except CookieInvalidError as e:
            # 平台 Cookie 失效（LyzenX record_cookie_failed 语义）：
            # 连续多次提取失败后触发，通知用户换 cookie，暂停 10 分钟等操作
            logger.warning("平台 Cookie 失效 %s: %s", self.url, e)
            await event_center.emit_cookie_invalid(self.platform_name)
            await event_center.emit_rec_error(self.room_id, self.url, f"[cookie失效] {e}")
            self._pause_long(e.backoff_seconds)
            return
        except PermanentError as e:
            # 其他永久性错误兜底：长退避
            logger.warning("永久性错误 %s: %s", self.url, e)
            await event_center.emit_rec_error(self.room_id, self.url, f"[永久] {e}")
            self._pause_long()
            return
        except TransientError as e:
            # 临时性错误：快速重试即可，但要记事件
            logger.warning("临时性错误 %s: %s", self.url, e)
            await event_center.emit_rec_error(self.room_id, self.url, f"[临时] {e}")
            return

        if not stream_info.is_live:
            self.record_finished_at = 0
            self._persist_room_meta(is_live=False)   # 未开播：在线状态置 False（列表实时刷新）
            return  # 未开播，回到探测循环

        # 主播在播：先回写在线状态（在线状态始终准确，与是否录制无关）
        self._persist_room_meta(is_live=True)

        # 启用只控制是否录制：房间停用（enabled=False）时仍持续探测在线状态，但不录制
        if await self._is_paused_room():
            logger.info("[%s] 主播在播，但房间已停用 —— 仅更新在线状态，不录制", self.anchor_name or self.platform_name)
            await event_center.emit_live_start(
                self.room_id, self.url, self.platform_name,
                stream_info.anchor_name or self.anchor_name, stream_info.title,
            )
            return  # 不录制，回到探测循环继续监控

        # 房间「停用 -> 重新启用」时复位标记：stop_recording_only 一旦置 True 旧代码永不复位，
        # 该房间此后永久不再开新录制（只能重启进程恢复）
        if self.stop_recording_only:
            self.stop_recording_only = False
            logger.info("[%s] 房间已重新启用，恢复录制", self.anchor_name or self.platform_name)

        await self._record(stream_info)

    def _pause_long(self, seconds: int = 300) -> None:
        """永久性错误后拉长暂停（默认5分钟；封禁1小时），防封禁频率检测"""
        self._paused_at = time.time()
        self._paused_until = self._paused_at + seconds
        logger.info("永久性错误暂停 %ds（至 %s）", seconds,
                    dt.datetime.fromtimestamp(self._paused_until))

    async def _record(self, stream_info: StreamInfo) -> None:
        """录制一次直播（含断流自愈 + 录完续录）。

        对齐原版 while True 语义：**每一轮（含重连/续录）都重新探测取流**，
        流地址（尤其中间跳转的 m3u8/flv）有时效性，缓存旧地址在断流后只会无限重连失败。
        """
        # 首轮直接用调用方传来的探测结果
        self.stream_info = stream_info
        self.anchor_name = stream_info.anchor_name or self.anchor_name
        self.live_title = stream_info.title
        self._persist_room_meta(is_live=True)   # 回写主播名/标题/在线状态到 Room 列表
        self.reconnect_count = 0
        self._set_state(STATE_PREPARING)

        await event_center.emit_live_start(
            self.room_id, self.url, self.platform_name,
            self.anchor_name, self.live_title,
        )

        # 只推送通知不录制（可配：推送配置:只推送通知不录制）：发出开播事件后不录制，回到探测循环
        if config_service.get_notify_only(False):
            logger.info("[%s] 已推送开播通知（只推送不录制），跳过录制", self.anchor_name or self.platform_name)
            self._persist_room_meta(is_live=True)
            # 等待一个循环周期再探测，避免高频空转
            await self._sleep_interruptible(config_service.get_push_check_interval(1800))
            return

        while not self.stop_requested:
            try:
                # 每轮录制前热刷配置（画质/格式/分段时间等 DB 改动即刻生效）
                self._refresh_runtime_config()
                # 重连/续录轮：重新探测取流，拿最新流地址（原版每轮 spider+stream 全跑）
                if self.stream_info is None or self.reconnect_count > 0:
                    fresh = await self._refresh_stream()
                    if fresh is None:
                        # 重连探测发现主播已下播 → 本次直播结束（不判失败）
                        if self.reconnect_count > 0:
                            logger.info("断流重连探测：主播已下播，结束本次直播")
                        return
                    self.stream_info = fresh
                    self.anchor_name = fresh.anchor_name or self.anchor_name
                    self.live_title = fresh.title

                # 上一轮录制期间房间被停用 -> 收工回探测循环（等重新启用再录）
                if self.stop_recording_only:
                    if await self._is_paused_room():
                        return
                    self.stop_recording_only = False

                ok = await self._start_recording_once()
                if not ok:
                    return  # 停止或出错不重连
                # 正常录完：先持久化本段文件
                self.record_finished_at = time.time()
                self._set_state(STATE_FINISHED)
                await event_center.emit_live_end(
                    self.room_id, self.url, self.platform_name,
                    self.anchor_name, self.save_file_path,
                    self._duration(),
                )
                # only_flv 平台（shopee/花椒）httpx 直录无进度统计 —— 用文件大小近似
                self._persist_recording("finished")
                # olive 同款：录完投递后处理（转码/脚本）到独立 worker 池，不阻塞录制循环
                # 分段录制：此处把本批分片合并成一个完整 mp4（大小封顶切段时即每批一个 mp4）
                self._submit_post_process()
                capped = self._size_capped
                self._size_capped = False   # 重置封顶标记，下一批重新计
                # LyzenX refresh_video_recorder 同款：主播仍在播 → 直接续录下一段。
                # 续录轮会走到 while 顶部重新探测取流（拿最新流地址），此处不再重复探测。
                # 续录保护：主播还在播但每段都录不出东西（空流/风控/死链）时，
                # 无上限续录会无限建文件、无限投后处理，连续 N 段无效就退回探测循环
                if not capped and self._duration() < MIN_VALID_SEGMENT_SECONDS:
                    self._empty_segments += 1
                else:
                    self._empty_segments = 0
                if self._empty_segments >= MAX_EMPTY_SEGMENTS:
                    logger.warning("连续 %d 段录制时长不足 %ds（疑似空流/风控），停止续录，回到探测循环",
                                   self._empty_segments, MIN_VALID_SEGMENT_SECONDS)
                    self._empty_segments = 0
                    return

                if await self._is_still_live() and not await self._is_paused_room():
                    if capped:
                        logger.info("文件大小已封顶并合并本批 mp4，主播仍在直播，开始录制下一批")
                    else:
                        logger.info("主播仍在直播，续录下一段（下轮重新取流）")
                    continue
                return
            except Exception as e:
                # 断流是常态（抖音流网络抖动/平台风控），记录摘要即可，不打印全栈噪音
                logger.warning("录制异常(断流): %s", e)
                await event_center.emit_rec_error(self.room_id, self.url, str(e))
                self.reconnect_count += 1
                if self.reconnect_count > MAX_RECONNECT:
                    logger.error("重连超过 %d 次，放弃本次直播", MAX_RECONNECT)
                    self._set_state(STATE_FAILED, f"重连失败: {e}")
                    self._persist_recording("failed")
                    return
                delay = RECONNECT_BASE_DELAY * self.reconnect_count + random.uniform(0, 2)
                logger.warning("断流自愈: 第 %d 次重连，%ds 后重试", self.reconnect_count, int(delay))
                await self._sleep_interruptible(int(delay))

    async def _refresh_stream(self) -> StreamInfo | None:
        """重连/续录前重新探测取流。返回 None=已下播（结束本次直播）。"""
        try:
            data = await self._net(self.adapter.extract(self.url))
            if not data:
                return None
            info = await self._net(self.adapter.resolve(data, self.quality))
            if not info.is_live:
                return None
            return info
        except Exception as e:
            logger.warning("重连取流失败: %s", e)
            raise

    async def _is_still_live(self) -> bool:
        """录完复查：主播是否仍在直播（LyzenX refresh_video_recorder）。
        总是返回实际值；pause 只在 '仍直播但 pause 检测到' 时不触发续录（见 _record 判断）。"""
        try:
            data = await self._net(self.adapter.extract(self.url))
            if not data:
                return False
            info = await self._net(self.adapter.resolve(data, self.quality))
            return bool(info.is_live)
        except Exception as e:
            logger.warning("续录复查失败: %s", e)
            return False

    async def _is_paused_room(self) -> bool:
        """查 DB 该房间 enabled 状态（录完续录前判断，避免对已停用房间继续开新文件）"""
        try:
            from ..models import Room, get_session
            db = get_session()
            try:
                room = db.query(Room).filter(Room.id == self.room_id).first()
                if room is not None and not room.enabled:
                    return True
                # 平台级「录制启用」为否 -> 同样只监控在线状态、不录制
                return not config_service.get_platform_enabled(self.platform_name, True)
            finally:
                db.close()
        except Exception:
            return False

    async def _start_recording_once(self) -> bool:
        """启动一次 ffmpeg 录制，返回 True=正常结束，False=被停止"""
        # 原版每循环重读 config.ini 实现热更新 —— 这里每轮录制前实时刷新录制参数
        self._refresh_runtime_config()
        record_url = self.stream_info.record_url or self.stream_info.flv_url or self.stream_info.m3u8_url
        if not record_url:
            raise RuntimeError("解析不到可录制的流地址")

        # ---- only_audio 平台强制音频格式（原版 only_audio_record 语义）----
        # 猫耳FM/Look直播：不论全局保存格式，强制 MP3/M4A 音频
        if self.platform_cls.only_audio:
            forced = "MP3" if "m4a" not in self.save_type.lower() else "M4A"
            if self.save_type != forced:
                logger.info("平台 %s 仅音频，强制保存格式 %s", self.platform_name, forced)
                self.save_type = forced
                self.quality = self.quality  # 音频不涉及画质

        # ---- 按实际流类型选源（_refresh_runtime_config 已按配置算好 self._stream_type）----
        # HLS→m3u8 源；FLV→flv 源（h265 编码时 FLV 不支持 → 回退缺省源）；Agora/其余→resolve 给的 record_url
        if self._stream_type == "HLS":
            hls = self.stream_info.m3u8_url or self.stream_info.record_url
            if hls:
                record_url = hls
                logger.info("[%s] 流类型=HLS，使用 m3u8 源录制", self.anchor_name or self.platform_name)
        elif self._stream_type == "FLV":
            flv = self.stream_info.flv_url
            if flv:
                codec_params = legacy_utils.get_query_params(flv, "codec")
                if codec_params and codec_params[0] == "h265":
                    logger.warning("[%s] 流类型=FLV 但源为 h265，改用缺省源: %s",
                                   self.anchor_name or self.platform_name, record_url)
                else:
                    record_url = flv
                    logger.info("[%s] 流类型=FLV，使用 flv 源录制", self.anchor_name or self.platform_name)
            else:
                logger.warning("[%s] 流类型=FLV 但无 flv 源，回退缺省源", self.anchor_name or self.platform_name)
        # Agora / 其他：保持 resolve 返回的 record_url

        # 原版语义：默认启用 https 提升；shopee/migu 例外强制 http 直连
        from ..core.config_service import config_service
        https_upgrade = self.platform_cls.enable_https_recording
        if https_upgrade is None:
            https_upgrade = config_service.get_bool("录制设置:是否强制启用https录制", False)
        if https_upgrade and record_url.startswith("http://"):
            record_url = record_url.replace("http://", "https://")
        if self.platform_cls.force_http and record_url.startswith("https://"):
            record_url = record_url.replace("https://", "http://")

        save_path = self._build_save_path()
        self.save_file_path = save_path
        self.start_time = dt.datetime.now()
        self.no_data_since = time.time()

        # stream-rec 同款：录制前磁盘空间预检（低于阈值直接失败，不空转）
        if not self._check_disk_space(save_path):
            raise RuntimeError("磁盘空间不足，拒绝开始录制")

        # ---- only_flv 平台（shopee/花椒）：httpx 直录 flv，不经过 ffmpeg（原版 direct_download_stream）----
        if self.platform_cls.only_flv:
            return await self._direct_download_flv(record_url, save_path)

        # shopee 动态 origin:{live_domain}（原版 get_record_headers 语义：live_url 前 3 段）
        record_headers = dict(self.platform_cls.record_headers or {})
        if any("{live_domain}" in v for v in record_headers.values()):
            live_domain = "/".join(record_url.split("/")[0:3])
            record_headers = {k: v.replace("{live_domain}", live_domain)
                              for k, v in record_headers.items()}

        # 调试日志：是否显示直播源地址（可配：录制设置:是否显示直播源地址）
        if config_service.get_show_stream_url(False):
            logger.info("[%s] 直播源: %s", self.anchor_name or self.platform_name, record_url)

        command = build_command(
            record_url, save_path, self.save_type, self.quality,
            seg_time=self.seg_time, split=self.split,
            overseas=_is_overseas_url(record_url),   # 按域名判断海外参数（原版 overseas_platform_host）
            http_headers=record_headers or None,
            proxy=self.adapter.proxy,
        )
        self.recorder = FFmpegRecorder(command)
        self._set_state(STATE_RECORDING)
        await event_center.emit_session(self.room_id, "recording_started",
                                        dict(url=record_url, path=save_path))
        self._persist_session("recording", save_path)

        await self.recorder.start()
        rc = await self.recorder.wait(stop_callback=self._dead_stream_check)
        self.save_file_path = save_path

        if self.stop_requested:
            # 用户/系统停止录制（非正常录完）：保留已录内容并同样走后处理（转码/脚本），
            # 保证"停止"也能产出成品文件（不止 finished 路径转码）。
            self._set_state(STATE_STOPPED)
            self._persist_recording("stopped")
            self._submit_post_process()   # 主动停止也转码成品（补全链路）
            await event_center.emit_live_end(
                self.room_id, self.url, self.platform_name,
                self.anchor_name, save_path, self._duration(),
            )
            return False

        # 404 内容检测（LyzenX 同款：录到 404 页面判废）。分段模式下检查首个实际分片
        _chk = save_path
        if self.split:
            _b, _e = os.path.splitext(save_path)
            import glob as _glob
            _first = sorted(_glob.glob(f"{_b}_*{_e}"))
            _chk = _first[0] if _first else save_path
        if self._is_404_file(_chk):
            logger.warning("录制内容为 404 页面，删除文件: %s", _chk)
            try:
                os.remove(_chk)
            except OSError:
                pass
            self.save_file_path = ""
            raise RuntimeError("流地址返回 404 页面")

        if rc != 0:
            if rc == -9 and (self._size_capped or self.stop_requested or self.stop_recording_only):
                # graceful_stop 10s 超时被 SIGKILL（rc=-9）不是断流，按正常结束处理，
                # 否则会走重连退避、把本批分片重复投后处理
                logger.warning("ffmpeg 被强杀(rc=-9)，属主动停止/封顶切段，按正常结束处理")
            else:
                # ffmpeg 异常退出：断流（打印真实 stderr 尾部诊断）
                logger.warning("ffmpeg 退出码 %s（断流）\n命令: %s\nstderr尾:\n%s", rc,
                               " ".join(self.recorder.command), self.recorder.last_stderr(15))
                raise RuntimeError(f"ffmpeg 退出码 {rc}")

        return True

    async def _direct_download_flv(self, flv_url: str, save_path: str) -> bool:
        """only_flv 平台（shopee/花椒）httpx 直录 flv 流，不经过 ffmpeg。

        原版 direct_download_stream（main.py:385-424）语义：异步 stream GET，
        平台 headers（get_record_headers），16KB chunk 写文件，停止中断返回 False。
        返回 True=正常录完，False=被停止（调用方不重连）。
        """
        headers = {}
        record_headers = self.platform_cls.record_headers or {}
        # 原版 header 是 "key:value" 字符串 → 这里已是 dict
        for key, value in record_headers.items():
            headers[key] = value
        if headers and "{live_domain}" in str(headers):
            live_domain = "/".join(flv_url.split("/")[0:3])
            headers = {k: v.replace("{live_domain}", live_domain)
                       for k, v in headers.items()}

        self._set_state(STATE_RECORDING)
        await event_center.emit_session(self.room_id, "recording_started",
                                        dict(url=flv_url, path=save_path))
        self._persist_session("recording", save_path)

        written = 0
        start = time.time()
        last_progress = 0.0
        try:
            async with httpx.AsyncClient(timeout=None, headers=headers or None,
                                         follow_redirects=True) as client:
                async with client.stream("GET", flv_url) as response:
                    if response.status_code != 200:
                        logger.error("请求直播流失败，状态码: %s", response.status_code)
                        raise RuntimeError(f"FLV 直录 HTTP {response.status_code}")
                    with open(save_path, "wb") as f:
                        async for chunk in response.aiter_bytes(1024 * 16):
                            if self.stop_requested:
                                logger.warning("录制被停止，下载中断: %s", save_path)
                                self.save_file_path = save_path
                                return False
                            if chunk:
                                f.write(chunk)
                                written += len(chunk)
                                # 直录不经过 ffmpeg wait 回调，循环内周期补进度上报
                                now = time.time()
                                if now - last_progress >= PROGRESS_REPORT_INTERVAL:
                                    last_progress = now
                                    await event_center.emit_session(
                                        self.room_id, "session_update",
                                        dict(state=STATE_RECORDING,
                                             duration_seconds=int(now - start),
                                             file_size=written))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("FLV 直录错误: %s", e)
            raise RuntimeError(f"FLV 直录失败: {e}")
        finally:
            self.save_file_path = save_path
            # 404/空文件判废
            try:
                if os.path.exists(save_path) and os.path.getsize(save_path) == 0:
                    os.remove(save_path)
            except OSError:
                pass

        self.start_time = dt.datetime.fromtimestamp(start)
        return True

    # ---------- 运行时配置热刷新 ----------
    def _refresh_runtime_config(self) -> None:
        """录制前从 configs 表实时刷新录制参数（原版每循环重读 config.ini 的等价物）。
        启动快照（scheduler 传入）作兜底默认，configs 表有值则覆盖——DB 改配置立即生效，无需重启。"""
        # 平台级「默认画质」优先（平台:{名}:默认画质），未配置回落房间/全局画质
        quality = config_service.get_platform_quality(
            self.platform_name, config_service.get_quality(self.quality))
        # 分片格式按"实际流类型"决定：平台内置语义（抖音/TikTok 用 FLV，其余默认 HLS），
        # 容器=全局「流类型分片」映射（HLS→HLS流分片格式 / FLV→FLV流分片格式 / Agora→…，兜底全局视频保存格式）
        # 平台自己声明 stream_type（BasePlatform.stream_type，默认 HLS），不再按平台名硬编码
        st = getattr(self.platform_cls, "stream_type", "") or "HLS"
        self._stream_type = st
        save_type = config_service.get_stream_format(st, config_service.get_save_type(self.save_type)).upper()
        seg_time = config_service.get_seg_time(self.seg_time)
        split = config_service.get_split_enabled(self.split)
        save_dir = config_service.get_cache_dir(self.save_dir)   # 录制过程 ts 分片写缓存目录；成品转移至 downloads
        self._max_duration_seconds = config_service.get_max_duration_seconds(0)
        self._max_size_bytes = config_service.get_max_size_mb(0) * 1024 * 1024

        if quality != self.quality:
            logger.info("配置热更新: quality %s -> %s", self.quality, quality)
            self.quality = quality
        if save_type != self.save_type:
            logger.info("配置热更新: save_type %s -> %s", self.save_type, save_type)
            self.save_type = save_type
        if seg_time != self.seg_time:
            logger.info("配置热更新: seg_time %s -> %s", self.seg_time, seg_time)
            self.seg_time = seg_time
        if split != self.split:
            logger.info("配置热更新: split %s -> %s", self.split, split)
            self.split = split
        if save_dir != self.save_dir:
            logger.info("配置热更新: save_dir %s -> %s", self.save_dir, save_dir)
            self.save_dir = save_dir

    # ---------- 死流/异常检测（参考 stream-rec maxDownload* + LyzenX 404） ----------
    def _dead_stream_check(self) -> bool:
        """wait() 的 stop_callback（每1s回调）：
        1. 周期性上报录制进度（3s去抖 → WS 实时进度条数据）
        2. 死流检测：超 DEAD_STREAM_TIMEOUT 无新数据 → 返回 True 触发优雅停止（走断流重连）"""
        if self.recorder is None:
            return False
        try:
            # 死流进度探测目标：
            #  - 不分段：主路径自身
            #  - 分段：实际输出是 base_%03d.ext 分片，主路径不存在；
            #         取目录下最新分片（分片切换后仍能反映"还在写入"）
            probe_path = self.save_file_path
            if self.split and self.save_file_path:
                _base, _ext = os.path.splitext(self.save_file_path)
                import glob as _glob
                _parts = _glob.glob(f"{_base}_*{_ext}")
                if _parts:
                    probe_path = max(_parts, key=lambda p: os.path.getmtime(p))
                else:
                    probe_path = ""   # 尚无分片
            if probe_path and os.path.exists(probe_path):
                size = os.path.getsize(probe_path)
                if size > 0:
                    self.no_data_since = time.time()   # 有数据，重置计时
        except OSError:
            pass

        # ---- 进度上报（3s 去抖） ----
        now = time.time()
        if now - self._last_progress_at >= PROGRESS_REPORT_INTERVAL:
            self._last_progress_at = now
            prog = self.recorder.get_progress()
            if prog:
                # 异步上报（fire-and-forget，不对录制阻塞）
                asyncio.ensure_future(event_center.emit_session(
                    self.room_id, STATE_RECORDING,
                    dict(url=self.url, platform=self.platform_name,
                         anchor=self.anchor_name, title=self.live_title,
                         **prog),
                ))

        # ---- 单次录制上限（stream-rec maxDownloadSize/maxDownloadTime 同款）----
        # 达到上限 → 优雅停止（发 q 正常退出），按"正常录完"处理（rc==0 路径）
        if self._max_duration_seconds > 0 and self.start_time is not None:
            elapsed = time.time() - self.start_time.timestamp()
            if elapsed >= self._max_duration_seconds:
                # 达到时长上限 → 优雅停止当前 ffmpeg（rc=0），本批分片合并成一个完整 mp4 后继续录下一批
                self._size_capped = True
                logger.info("达到单次时长上限 %ds（%.1f 小时），封顶切段：合并本批 mp4 后继续录制",
                            self._max_duration_seconds, self._max_duration_seconds / 3600)
                return True
        if self._max_size_bytes > 0 and probe_path and os.path.exists(probe_path):
            try:
                # 分段模式：所有分片大小累加（单看最新分片会低估）
                if self.split and self.save_file_path:
                    _b, _e = os.path.splitext(self.save_file_path)
                    import glob as _glob
                    total = sum(os.path.getsize(p) for p in _glob.glob(f"{_b}_*{_e}"))
                else:
                    total = os.path.getsize(probe_path)
                if total >= self._max_size_bytes:
                    # 达到大小上限 → 优雅停止当前 ffmpeg（rc=0 正常退出），
                    # _record 主循环会把这批分片合并成一个完整 mp4 并立即续录下一批。
                    self._size_capped = True
                    logger.info("达到单次文件大小上限 %.1fMB，封顶切段：合并本批 mp4 后继续录制",
                                self._max_size_bytes / 1024 / 1024)
                    return True
            except OSError:
                pass

        # ---- 死流检测 ----
        if time.time() - self.no_data_since > DEAD_STREAM_TIMEOUT:
            stderr_tail = self.recorder.last_stderr(5)
            logger.warning("死流检测：%ss 无数据，重启录制\nstderr 尾部:\n%s",
                           DEAD_STREAM_TIMEOUT, stderr_tail)
            return True
        return False

    def _check_disk_space(self, save_path: str, min_free_mb: int | None = None) -> bool:
        """stream-rec checkSpaceAvailable 同款：目标盘剩余空间预检。
        min_free_mb 缺省时读配置 录制空间剩余阈值(gb) 换算（默认 1GB）。"""
        if min_free_mb is None:
            # 原版：录制空间剩余阈值(gb)，默认 1.0
            limit_gb = config_service.get_disk_space_limit_gb(1.0)
            min_free_mb = int(limit_gb * 1024)
        try:
            import shutil
            disk = shutil.disk_usage(os.path.dirname(save_path) or ".")
            return disk.free > min_free_mb * 1024 * 1024
        except Exception:
            return True  # 拿不到信息时不阻塞

    def _is_404_file(self, path: str) -> bool:
        """LyzenX 同款：文件内容为 404 Not Found 则判废"""
        try:
            if os.path.getsize(path) < 1024:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(512)
                return "<head><title>404 Not Found</title></head>" in content
        except OSError:
            pass
        return False

    def _submit_post_process(self) -> None:
        """录完按配置投递后处理任务到独立 worker 池。

        分段录制（老大要求最终成品=单个完整 mp4）：
            收集所有 ts 分片 → ffmpeg concat 拼接 → 一个完整 mp4（可选 h264/H264、删源分片）
        不分段录制：
            单文件 ts → mp4（原版 converts_mp4 语义）
        自定义脚本：单文件时按原版参数执行；分段合并后对成品 mp4 执行。
        """
        files = self._collect_output_files()
        if not files:
            return
        # 成品落库回调（post_processor 合并+转移完成后回调，把成品路径交给本引擎入成品库）
        def _on_product(final_path: str, actions: dict) -> None:
            # 把本批分片清单一起传下去：只清本批缓存账本，别误删并发/后续批次
            self._persist_product(final_path, actions.get("merge_segments"))
        _env = {"platform": self.platform_name, "anchor": self.anchor_name or "未知主播",
                "on_product": _on_product,
                "title": self.live_title or "",
                "start_ts": self.start_time.strftime("%Y-%m-%d %H:%M:%S") if getattr(self, "start_time", None) else "",
                "gen_srt": config_service.get_gen_srt(False)}
        to_mp4 = config_service.get_bool("录制设置:录制完成后自动转为mp4格式", False)
        delete_original = config_service.get_bool("录制设置:追加格式后删除原文件", False)
        # h264：真实键为 "录制设置:mp4格式重新编码为h264"（旧代码误读 "转为mp4后转为h264" 导致开关失效，已修）
        to_h264 = config_service.get_convert_h264(False)
        run_script_flag = config_service.get_bool("录制设置:是否录制完成后执行自定义脚本", False)
        script = config_service.get("录制设置:自定义脚本执行命令", "").strip()

        # 分段录制：_multipart_format 本身就产出多个分片文件，必须合并成单个成品（与是否 TS 无关）。
        # 原版 converts_to_mp4 的 TS 判断只适用于"单文件 ts → mp4"转码，不适用于分段合并。
        ext_lower = self.save_type.lower()
        is_video = ext_lower not in ("mp3", "mp3音频", "m4a", "m4a音频")
        # 分段合并：只要分段录制 + 视频格式 + (自动转mp4 或 已就是mp4/需成品)，都要合并
        need_merge = self.split and len(files) >= 1 and is_video and \
            (to_mp4 or ext_lower in ("mp4", "mkv", "flv", "ts"))
        # 单文件转码：仅 TS（原版 converts_to_mp4 语义）
        convert = (not self.split) and to_mp4 and self.save_type.upper() == "TS"
        # 单文件不转码也要入成品库：旧逻辑在「录制完成后自动转为mp4=否」时直接 return，
        # 单文件录制永远只有缓存库记录、成品库永远空（审阅缺陷 #1 的另一半）
        as_product = (not self.split) and not convert
        run_script = run_script_flag and bool(script)
        if not (need_merge or convert or as_product or run_script):
            return

        if self.split and len(files) >= 1:
            # 分段：合并成一个完整 mp4（文件名基于主路径，去掉 _%03d 后缀）
            merge_out = self.save_file_path.rsplit(".", maxsplit=1)[0] + ".mp4"
            if need_merge or convert:
                post_processor.submit_merge(files, merge_out, {
                    "to_h264": to_h264,
                    "delete_original": delete_original,
                    "script": script if run_script else "",
                    "record_name": self.anchor_name,
                    "save_type": self.save_type.lower(),
                    "split": self.split,
                    "converts_mp4": convert,
                    **_env,
                })
            elif run_script:
                # 只跑脚本不合并：逐片投递（原版分段脚本语义）
                for path in files:
                    post_processor.submit(path, {
                        "to_mp4": False, "to_h264": to_h264,
                        "delete_original": delete_original,
                        "script": script, "record_name": self.anchor_name,
                        "save_type": self.save_type.lower(), "split": self.split,
                        "converts_mp4": False,
                    })
            return

        # 不分段：单文件
        for path in files:
            post_processor.submit(path, {
                "to_mp4": convert,
                "as_product": as_product,
                "to_h264": to_h264,
                "delete_original": delete_original,
                "script": script if run_script else "",
                "record_name": self.anchor_name,
                "save_type": self.save_type.lower(),
                "split": self.split,
                "converts_mp4": convert,
                **_env,
            })

    # ---------- 辅助 ----------
    def _build_save_path(self) -> str:
        """构造保存路径。stream-rec 同款防碰撞：目标已存在则追加 _1/_2 序号，
        避免同一秒续录（主播断流重连/录完续录）撞名被 ffmpeg -y 覆盖。"""
        now = time.strftime("%Y-%m-%d_%H-%M")   # 文件名时间精度到分钟（同分钟续录靠 _1/_2 序号防撞名）
        anchor = self._safe(self.anchor_name or "未知主播")
        title = ""
        # 文件名含标题（可配：录制设置 保存文件名是否包含标题）
        if self.live_title and config_service.get_filename_include_title(False):
            title = self._safe(self.live_title) + "_"
        ext = self.save_type.lower()
        if self.platform_cls.only_flv:
            # only_flv 平台 httpx 直录 flv 流 → 扩展名强制 .flv（原版直录分支 filename=...flv）
            ext = "flv"
        elif ext in ("mp3音频", "mp3"):
            ext = "mp3"
        elif ext in ("m4a音频", "m4a"):
            ext = "m4a"
        # 目录结构：平台 / [作者] / [时间] / [标题]（各自可配，对齐原版）
        base_dir = Path(self.save_dir) / self.platform_name
        if config_service.get_dir_by_author(True):
            base_dir = base_dir / anchor
        if config_service.get_dir_by_time(False):
            base_dir = base_dir / time.strftime("%Y-%m-%d")
        if config_service.get_dir_by_title(False) and self.live_title:
            base_dir = base_dir / self._safe(self.live_title)
        base_dir.mkdir(parents=True, exist_ok=True)

        candidate = base_dir / f"{anchor}_{title}{now}.{ext}"
        seq = 1
        while candidate.exists():
            candidate = base_dir / f"{anchor}_{title}{now}_{seq}.{ext}"
            seq += 1
        return str(candidate)

    @staticmethod
    def _safe(name: str) -> str:
        import re
        name = re.sub(r'[\\/:*?"<>|&#.,~!]', "_", name)
        # 去表情符号（可配）：过滤常见 emoji 区段
        if config_service.get_strip_emoji(False):
            name = re.sub(r'[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u200d\ufe0f]', '', name)
        return name.strip("_") or "未命名"

    def _duration(self) -> int:
        """本次录制时长（秒）；未开始返回 0"""
        if not self.start_time:
            return 0
        return int((dt.datetime.now() - self.start_time).total_seconds())

    # ---------- DB 持久化 ----------
    def _persist(self, fn):
        if not self.db_session_factory:
            return
        try:
            db = self.db_session_factory()
            try:
                fn(db)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error("DB 持久化失败: %s", e)

    def _persist_start(self) -> None:
        def _fn(db):
            from ..models import Session
            db.query(Session).filter(Session.room_id == self.room_id).delete()
            db.add(Session(room_id=self.room_id, url=self.url, platform=self.platform_name,
                           anchor_name=self.anchor_name, state=STATE_CHECKING))
        self._persist(_fn)

    def _persist_room_meta(self, is_live: bool | None = None) -> None:
        """探测到直播后回写主播名/标题/is_live 到 Room，让前端列表实时展示。

        is_live：显式设置在线状态（True=直播中，False=未开播）；None=不改动。
        """
        if not (self.anchor_name or self.live_title or is_live is not None):
            return

        def _fn(db):
            from ..models import Room
            upd = {"last_check_at": dt.datetime.now()}
            if self.anchor_name:
                upd["anchor_name"] = self.anchor_name
            if self.live_title:
                upd["title"] = self.live_title
            if is_live is not None:
                upd["is_live"] = is_live
            db.query(Room).filter(Room.id == self.room_id).update(upd)
        self._persist(_fn)

    def _persist_session(self, state: str, save_path: str = "") -> None:
        def _fn(db):
            from ..models import Session
            db.query(Session).filter(Session.room_id == self.room_id).delete()
            db.add(Session(room_id=self.room_id, url=self.url, platform=self.platform_name,
                           anchor_name=self.anchor_name, state=state,
                           record_url=self.stream_info.record_url if self.stream_info else "",
                           save_file_path=save_path or self.save_file_path,
                           start_time=self.start_time))
        self._persist(_fn)

    def _persist_recording(self, status: str) -> None:
        """录制落库 —— 两库分流（缓存库/成品库）：
        - 本次产出是 ts 分片（缓存文件）→ 记入「缓存库」recordings 表（CacheRecording）
        - 已合并出成品 mp4（成品文件）→ 记入「成品库」products 表（Product），
          并删除对应缓存库记录（缓存已转成品，不再占缓存账本）。
        过小文件（<1MB）判废删除，不入任何库。
        """
        files = self._collect_output_files()
        if not files:
            if self.save_file_path and os.path.exists(self.save_file_path):
                files = [self.save_file_path]

        def _fn(db):
            from ..models import CacheRecording, Room, Session
            end = dt.datetime.now()
            duration = int((end - self.start_time).total_seconds()) if self.start_time else 0

            for path in files:
                size = 0
                if path and os.path.exists(path):
                    size = os.path.getsize(path)
                if self._is_too_small(size):
                    self._rm_small_file(path, status)
                    continue
                db.add(CacheRecording(
                    room_id=self.room_id, file_path=path, file_size=size,
                    start_time=self.start_time, end_time=end, duration_seconds=duration,
                    status=status, save_type=self.save_type, platform=self.platform_name,
                    anchor_name=self.anchor_name,
                ))
            # 不在此处置 is_live=False：本方法每段录完（含封顶切段/断流重连）都会跑，
            # 主播仍在播时把它打成 False 会让前端列表整场直播反复闪「未开播」。
            # 在线状态统一由探测循环 _persist_room_meta 维护。
            db.query(Room).filter(Room.id == self.room_id).update(
                {"anchor_name": self.anchor_name})
            db.query(Session).filter(Session.room_id == self.room_id).delete()
        self._persist(_fn)

    def _persist_product(self, mp4_path: str, source_files: list[str] | None = None) -> None:
        """成品落库 —— 合并出完整 mp4 后调用（post_processor 回调）。
        记入成品库 products 表；删除本批对应的缓存库 recordings 记录（ts 分片已删/已转成品）。

        参数 mp4_path：成品 mp4 在成品目录下的最终路径。
        """
        if not mp4_path or not os.path.exists(mp4_path):
            return
        size = os.path.getsize(mp4_path)
        if self._is_too_small(size):
            return

        # 时长优先 ffprobe 实测（精准），回退本批时间差
        duration = self._probe_duration(mp4_path)
        if not duration:
            end_now = dt.datetime.now()
            duration = int((end_now - self.start_time).total_seconds()) if self.start_time else 0

        def _fn(db):
            from ..models import Product, CacheRecording
            end = dt.datetime.now()
            db.add(Product(
                room_id=self.room_id, file_path=mp4_path,
                file_name=os.path.basename(mp4_path), file_size=size,
                duration_seconds=duration, start_time=self.start_time, end_time=end,
                # 不再硬编码 "mp4"：不转码的单文件成品保留真实容器（ts/mkv/flv/mp3…）
                save_type=os.path.splitext(mp4_path)[1].lstrip(".").lower() or "mp4",
                platform=self.platform_name,
                anchor_name=self.anchor_name, title=self.live_title, status="ready",
            ))
            # 本批缓存分片已合并转出 → 只清掉本批分片对应的缓存库记录。
            # 旧实现按 status in (...) 全量删该房间记录，会把并发批次/下一批正在录的
            # recording 账本一起删掉（缓存库凭空少文件、前端看不到正在录的段）。
            q = db.query(CacheRecording).filter(CacheRecording.room_id == self.room_id)
            if source_files:
                q = q.filter(CacheRecording.file_path.in_(list(source_files)))
            else:
                q = q.filter(CacheRecording.status.in_(("finished", "stopped", "merged")))
            q.delete(synchronize_session=False)
        self._persist(_fn)
        logger.info("成品入库: %s (%.1fMB)", os.path.basename(mp4_path), size / 1024 / 1024)

    def _collect_output_files(self) -> list[str]:
        """收集本次录制实际产出文件：
        - 不分段：主路径自身
        - 分段：主路径同目录下所有 `basename_NNN.ext` 分片
        （ffmpeg segment 输出 base_%03d.ext，主路径本身不会生成）"""
        if not self.save_file_path:
            return []
        if not self.split:
            return [self.save_file_path] if os.path.exists(self.save_file_path) else []
        base, ext = os.path.splitext(self.save_file_path)
        base_dir = os.path.dirname(self.save_file_path)
        import glob
        pattern = os.path.join(base_dir, f"{os.path.basename(base)}_*{ext}")
        found = sorted(glob.glob(pattern))
        return found if found else ([self.save_file_path] if os.path.exists(self.save_file_path) else [])

    @staticmethod
    def _probe_duration(path: str) -> int:
        """ffprobe 读视频时长（秒）；失败返回 0。"""
        import subprocess as _sp, json as _json
        try:
            out = _sp.check_output([
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", path], timeout=15)
            return int(float(_json.loads(out).get("format", {}).get("duration", 0)))
        except Exception:
            return 0

    def _is_too_small(self, size: int) -> bool:
        """分片/文件过小判废（stream-rec minPartSize 同款，阈值可配：录制设置:最小有效文件大小(mb)）"""
        min_mb = config_service.get_min_file_size_mb(1)
        return size < int(max(min_mb, 0) * 1024 * 1024)

    def _rm_small_file(self, path: str, status: str) -> None:
        """olive 同款：过小录制文件判废删除（除非异常状态）"""
        if status == "finished" and path and os.path.exists(path):
            size = os.path.getsize(path)
            logger.warning("录制文件过小(%.1fKB)删除: %s", size / 1024, path)
            try:
                os.remove(path)
                if path == self.save_file_path:
                    self.save_file_path = ""
            except OSError:
                pass

    def _persist_end(self) -> None:
        def _fn(db):
            from ..models import Session, Room
            db.query(Session).filter(Session.room_id == self.room_id).delete()
            db.query(Room).filter(Room.id == self.room_id).update({"is_live": False})
        self._persist(_fn)

    async def stop(self) -> None:
        """请求彻底停止（外部调用/删除房间）。olive atomic CAS 同款幂等。"""
        if self.stop_requested:
            return
        logger.info("停止请求 [%s] %s", self.platform_name, self.url)
        self.stop_requested = True
        if self.recorder and self.recorder.running:
            await self.recorder.graceful_stop()

    async def stop_recording(self) -> None:
        """只停止当前录制，保留探测循环（房间停用但需继续监控在线状态）。
        优雅停止当前 ffmpeg，录制循环会因 _is_paused_room() 不再开始新录制，
        但 run() 主探测循环继续，持续刷新 is_live。"""
        # 幂等：调度器每轮 reload 都会调用，已在「只停录制」状态时直接返回，避免日志刷屏
        if self.stop_requested or self.stop_recording_only:
            return
        logger.info("停止录制（保留在线监控）[%s] %s", self.platform_name, self.url)
        self.stop_recording_only = True
        if self.recorder and self.recorder.running:
            await self.recorder.graceful_stop()