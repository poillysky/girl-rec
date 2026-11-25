# -*- coding: utf-8 -*-
"""
RoomScheduler 房间调度器
========================
替代原 main.py 的 `while True: 每3秒扫ini` + 线程模型。

职责：
    1. 从数据库加载房间，每房间启动一个 RecordingSession 协程任务
    2. 周期轮询数据库（5-10s），热更新：新增房间/停用/删除/改配置
    3. 崩溃恢复：启动时清理遗留 sessions 会话
    4. 维护  房间id -> (task, session)  映射

协程模型（asyncio）：
    一万个房间的探测循环都是协程，单进程无压力；
    ffmpeg 是独立子进程，由 session 内部管理。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

from ..adapters import BasePlatform, match_platform, get_platform
from ..core.config_service import config_service
from ..core.event_bus import event_center
from ..core.logger import get_logger
from ..engine.session import RecordingSession

if TYPE_CHECKING:  # pragma: no cover
    from ..models import Room

logger = get_logger("scheduler")

RELOAD_INTERVAL = 8          # 数据库轮询秒数（热更新频率）
STARTUP_STAGGER = 1.2        # 启动错峰：避免所有房间同时探测（防封）


class RoomScheduler:
    def __init__(self, db_session_factory, save_dir: str = "downloads",
                 default_quality: str = "原画", default_save_type: str = "TS",
                 seg_time: int = 1800, split: bool = False) -> None:
        self.db = db_session_factory
        # 同一时间访问网络的线程数（可配，默认 5）：限制并发探测/取流的网络协程数（原版线程池上限语义）
        max_net = config_service.get_int("录制设置:同一时间访问网络的线程数", 5)
        self._net_sem = asyncio.Semaphore(max(max_net, 1))
        self.save_dir = save_dir
        self.default_quality = default_quality
        self.default_save_type = default_save_type
        self.seg_time = seg_time
        self.split = split
        self.tasks: dict[int, asyncio.Task] = {}
        self.sessions: dict[int, RecordingSession] = {}
        self._stop = asyncio.Event()

    # ---------- 生命周期 ----------
    async def start(self) -> None:
        # 热更新循环必须在代理检测之前建：_proxy_check_once 在「跳过代理检测=是」时提前
        # return，旧代码把 create_task 放在它尾部 -> 8s 热更新整个不启动（改房间/停用不生效）
        asyncio.create_task(self._reload_loop())
        await self._proxy_check_once()
        await self._cleanup_stale_sessions()
        logger.info("调度器启动，加载房间...")
        await self.reload()

    async def _proxy_check_once(self) -> None:
        """启动时代理检测（原版 main.py 全局代理检测语义）。

        录制设置:是否跳过代理检测(是/否)=是 → 跳过，直接认为有代理能力；
        =否 → 做一次外网连通性探测，仅日志提示，失败不阻塞启动。
        """
        if config_service.get_skip_proxy_check(False):
            logger.info("已跳过代理连通检测（配置）")
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8) as client:
                await client.head("https://www.google.com/")
            logger.info("外网连通检测通过（代理/直连可用）")
        except Exception as e:
            logger.warning("未检测到可用外网代理/直连（录制海外直播需配置代理，国内平台可忽略）: %s", e)

    async def stop(self) -> None:
        self._stop.set()
        for sid, session in list(self.sessions.items()):
            await session.stop()
        for task in list(self.tasks.values()):
            task.cancel()
        for task in list(self.tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.tasks.clear()
        self.sessions.clear()
        logger.info("调度器已停止")

    async def _reload_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.sleep(RELOAD_INTERVAL)
                await self.reload()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("热更新失败")

    # ---------- 热更新 ----------
    async def reload(self) -> None:
        """DB → 任务差异同步（新增/停用/删除/平台变更）"""
        from ..models import Room
        db = self.db()
        try:
            rooms = db.query(Room).all()
        finally:
            db.close()

        room_by_id = {r.id: r for r in rooms}
        db_ids = set(room_by_id)

        # 1. 删除不在库中的任务
        for sid in list(self.tasks):
            if sid not in db_ids:
                await self._remove_task(sid, reason="房间已删除")

        # 2. 处理每个房间
        for rid, room in room_by_id.items():
            existing = self.tasks.get(rid)
            if existing and not existing.done():
                self._apply_runtime_change(room, rid)
                continue
            if existing and existing.done():
                # 上个任务意外结束，重启
                logger.warning("房间 %s 协程已结束，重启", rid)
                self.tasks.pop(rid, None)
            # 在线状态始终准确：所有房间都启动探测协程（enabled 只控制 session 内部是否录制）
            await self._spawn_task(rid, room)

    def _apply_runtime_change(self, room, rid: int) -> None:
        """运行时变更（停用/品质/保存类型）即时生效"""
        session = self.sessions.get(rid)
        if session is None:
            return
        if not room.enabled:
            # 停用 = 不录制，但仍需持续探测在线状态（老大要求：在线状态始终准确）
            # 已处于「只停录制」状态时不再重复投递，避免每轮 reload 空转
            if not session.stop_recording_only:
                asyncio.create_task(session.stop_recording())
            return
        # 重新启用：复位「只停当前录制」标记，否则该房间永久不再开新录制
        if session.stop_recording_only:
            session.stop_recording_only = False
            logger.info("房间 %s 已重新启用，恢复录制", rid)
        session.quality = config_service.get_platform_quality(
            session.platform_name, room.quality or self.default_quality)

    async def _spawn_task(self, rid: int, room) -> None:
        platform_cls = match_platform(room.url)
        if platform_cls is None:
            logger.warning("无法匹配平台: %s", room.url)
            return
        adapter = platform_cls(
            cookies=config_service.get_platform_cookie(platform_cls.platform_name),
            proxy=config_service.get_platform_proxy(platform_cls.platform_name, room.url),
        )
        session = RecordingSession(
            room_id=rid, url=room.url, platform_cls=platform_cls,
            adapter=adapter,
            # 平台级默认画质优先（平台:{名}:默认画质）；Room 无 save_type 列，别再 hasattr 试探
            quality=config_service.get_platform_quality(
                platform_cls.platform_name, room.quality or self.default_quality),
            save_type=self.default_save_type,
            save_dir=self.save_dir, seg_time=self.seg_time, split=self.split,
            important=getattr(room, "important", False),
            db_session_factory=self.db,
            net_sem=self._net_sem,
        )
        self.sessions[rid] = session
        task = asyncio.create_task(session.run())
        self.tasks[rid] = task
        task.add_done_callback(lambda t, _rid=rid: self._task_done(_rid, t))
        # 启动错峰，防集中探测（可配：录制设置:排队读取网址时间(秒)，默认 1.2s）
        stagger = config_service.get_int("录制设置:排队读取网址时间(秒)", int(STARTUP_STAGGER))
        await asyncio.sleep(stagger if stagger >= 0 else STARTUP_STAGGER)
        logger.info("已启动监听 [%s] %s", platform_cls.platform_name, room.url)

    def _task_done(self, rid: int, task: asyncio.Task) -> None:
        self.tasks.pop(rid, None)
        self.sessions.pop(rid, None)
        if not task.cancelled() and task.exception():
            logger.error("房间 %s 监听协程异常退出: %s", rid, task.exception())

    async def _remove_task(self, rid: int, reason: str) -> None:
        logger.info("移除房间 %s（%s）", rid, reason)
        session = self.sessions.pop(rid, None)
        if session:
            await session.stop()
        task = self.tasks.pop(rid, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # ---------- 崩溃恢复 ----------
    async def _cleanup_stale_sessions(self) -> None:
        """启动时清理数据库遗留的 sessions（上次异常退出残留）"""
        try:
            from ..models import Session, Product, CacheRecording, Room
            from ..core.config_service import config_service
            db = self.db()
            try:
                stale = db.query(Session).all()
                for s in stale:
                    # 异常中断的会话：把磁盘上遗留的分片合并成成品 mp4，转移到成品目录并入库
                    if s.save_file_path:
                        import os, glob as _glob
                        base, ext = os.path.splitext(s.save_file_path)
                        parts = sorted(_glob.glob(f"{base}_*{ext}")) if ext else []
                        src_mp4 = None
                        if parts:
                            try:
                                from ..engine.post_processor import _merge_segments_to_mp4
                                merge_out = base + ".mp4"
                                _merge_segments_to_mp4(parts, merge_out,
                                                       to_h264=False, delete_original=True)
                                if os.path.exists(merge_out):
                                    src_mp4 = merge_out
                                logger.info("遗留分片已合并为 mp4: %s (%d 片)", merge_out, len(parts))
                            except Exception as e:
                                logger.error("遗留分片合并失败: %s", e)
                        elif os.path.exists(s.save_file_path) and s.save_file_path.endswith(".mp4"):
                            src_mp4 = s.save_file_path

                        # 转移到成品目录 downloads/平台/主播/
                        if src_mp4 and os.path.exists(src_mp4):
                            final_path = src_mp4
                            try:
                                import shutil
                                from pathlib import Path
                                pdir = Path(config_service.get_product_dir("downloads"))
                                if s.platform:
                                    pdir = pdir / s.platform
                                if s.anchor_name:
                                    pdir = pdir / s.anchor_name
                                pdir.mkdir(parents=True, exist_ok=True)
                                dst = pdir / os.path.basename(src_mp4)
                                if os.path.abspath(src_mp4) != os.path.abspath(str(dst)):
                                    shutil.move(src_mp4, str(dst))
                                final_path = str(dst)
                            except Exception as e:
                                logger.error("遗留成品转移失败: %s", e)
                            db.add(Product(
                                room_id=s.room_id, file_path=final_path,
                                file_name=os.path.basename(final_path),
                                file_size=os.path.getsize(final_path),
                                start_time=s.start_time, end_time=dt.now(),
                                status="ready", save_type="mp4",
                                platform=s.platform, anchor_name=s.anchor_name))
                db.query(Session).delete()
                db.commit()
                logger.info("清理 %d 条遗留会话", len(stale))
            finally:
                db.close()
        except Exception as e:
            logger.error("清理遗留会话失败: %s", e)