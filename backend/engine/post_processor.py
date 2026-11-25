# -*- coding: utf-8 -*-
"""
PostProcessor 后处理池（olive UploaderWorkerPool 同款）
=====================================================
录制完成后不阻塞录制循环的异步后处理：
    1. 转码：TS → MP4（可选 h264 重编码），m4a 音频转换
    2. 自定义脚本执行（原版 script_command / run_script 语义）

设计（吸收 olive recorder.go SubmitUploadTask）：
    - 独立 worker 池（asyncio 协程队列），录制主循环只 submit，不等待
    - 每个任务 = (文件路径, 后处理动作)
    - worker 崩溃不拖垮录制引擎（try/except + 日志）

原版参数语义（main.py:1823-1828 + converts_mp4/main.py:219-270 + run_script:356）：
    录制设置:录制完成后自动转为mp4格式   是/否
    录制设置:追加格式后删除原文件       是/否
    录制设置:转为mp4后转为h264        是/否（converts_to_h264）
    录制设置:是否录制完成后执行自定义脚本 是/否
    录制设置:自定义脚本执行命令          "/path/script.sh"
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from typing import Callable

from ..core.config_service import config_service
from ..core.logger import get_logger

logger = get_logger("post_processor")


def _merge_segments_to_mp4(segments: list[str], out_path: str,
                           to_h264: bool, delete_original: bool) -> bool:
    """把一组 ts 分片按顺序无损拼接成一个完整 mp4（stream-rec 分段交付 + 原版转 mp4 成品）。

    做法：ffmpeg concat demuxer（-f concat -safe 0 -i list.txt），
    -c:v copy（无损）或 libx264 重编码，输出单个 mp4。
    分片必须同为 mpegts 编码（本项目 ts 分段即满足）才能 copy 拼接。
    """
    segments = [s for s in segments if os.path.exists(s) and os.path.getsize(s) > 0]
    if not segments:
        logger.warning("合并中止：无有效分片")
        return False
    segments.sort()   # _000/_001/_002... 字典序即录制顺序
    if os.path.exists(out_path):
        logger.warning("合并目标已存在，跳过: %s", out_path)
        return False

    # concat 清单（绝对路径 + single quotes 转义）
    list_path = out_path + ".concat.txt"
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for seg in segments:
                safe = seg.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
    except OSError as e:
        logger.error("写 concat 清单失败: %s", e)
        return False

    logger.info("合并 %d 个分片 → %s", len(segments), out_path)
    if to_h264:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-vf", "format=yuv420p", "-c:a", "aac",
               "-movflags", "+faststart", "-f", "mp4", out_path]
    else:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
               "-c:v", "copy", "-c:a", "copy",
               "-movflags", "+faststart", "-f", "mp4", out_path]
    ok = False
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        ok = True
    except subprocess.CalledProcessError as e:
        tail = (e.output or b"").decode("utf-8", errors="ignore")[-500:]
        logger.error("合并失败: %s", tail)
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass

    if ok and delete_original:
        for seg in segments:
            try:
                os.remove(seg)
            except OSError as e:
                logger.error("删除分片失败(%s): %s", seg, e)
        logger.info("已删除 %d 个源分片", len(segments))
    elif ok:
        logger.info("合并完成（保留源分片）: %s", out_path)
    return ok


def _convert_mp4(src: str, to_h264: bool, delete_original: bool) -> str | None:
    """原版 converts_mp4 同款：TS/FLV → MP4（默认 copy 流，可选 h264 重编码）"""
    if not (os.path.exists(src) and os.path.getsize(src) > 0):
        return None
    out = src.rsplit(".", maxsplit=1)[0] + ".mp4"
    if os.path.exists(out):
        logger.warning("转码目标已存在，跳过: %s", out)
        return None
    if to_h264:
        logger.info("转码为 MP4 + h264 重编码: %s", src)
        cmd = ["ffmpeg", "-y", "-i", src,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-vf", "format=yuv420p", "-c:a", "copy",
               "-movflags", "+faststart", "-f", "mp4", out]
    else:
        logger.info("转码为 MP4（copy）: %s", src)
        cmd = ["ffmpeg", "-y", "-i", src, "-c:v", "copy", "-c:a", "copy",
               "-movflags", "+faststart", "-f", "mp4", out]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        logger.error("转码失败(%s): %s", src, e)
        return None
    if delete_original:
        time.sleep(1)
        try:
            os.remove(src)
            logger.info("已删除原文件: %s", src)
        except OSError as e:
            logger.error("删除原文件失败: %s", e)
    return out


def _probe_duration(path: str) -> float:
    """ffprobe 读取媒体时长（秒），失败返回 0。"""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            timeout=20, stderr=subprocess.DEVNULL)
        return float(out.strip())
    except Exception:
        return 0.0


def _gen_srt(video_path: str, actions: dict) -> str | None:
    """生成时间字幕文件（.srt），与视频同名同目录（录制设置:生成时间字幕文件）。

    原版「生成时间字幕文件」语义：给成品配一份 srt。这里生成带录制起止时间轴的
    单条字幕（主播 / 标题 / 录制时间），作为可导入播放器的基础字幕骨架。
    """
    try:
        dur = _probe_duration(video_path)
        anchor = actions.get("anchor", "") or "未知主播"
        title = actions.get("title", "") or ""
        start_ts = actions.get("start_ts", "") or time.strftime("%Y-%m-%d %H:%M:%S")
        srt_path = os.path.splitext(video_path)[0] + ".srt"
        # 秒 → hh:mm:ss,mmm
        def _fmt(sec: float) -> str:
            h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
            ms = int((sec - int(sec)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        end = dur if dur > 0 else 1.0
        text = f"{anchor}" + (f" - {title}" if title else "")
        content = f"1\n{_fmt(0)} --> {_fmt(end)}\n{text}\n录制开始：{start_ts}\n\n"
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("已生成字幕: %s", srt_path)
        return srt_path
    except Exception as e:
        logger.error("生成字幕失败(%s): %s", video_path, e)
        return None


def _run_script(script: str, record_name: str, save_file_path: str,
                save_type: str, split: bool, converts_mp4: bool) -> None:
    """原版 run_script + check_subprocess 参数拼接同款：
    - python 脚本：追加 --record_name "--save_file_path --save_type
      --split_video_by_time --converts_to_mp4 参数
    - 其他(可执行/shell)：追加 record_name save_file_path save_type
      split_video_by_time:x converts_to_mp4:x 位置参数
    """
    if "python" in script:
        params = [
            f'--record_name "{record_name}"',
            f'--save_file_path "{save_file_path}"',
            f'--save_type {save_type}',
            f'--split_video_by_time {split}',
            f'--converts_to_mp4 {converts_mp4}',
        ]
    else:
        params = [
            f'"{record_name.split(" ", maxsplit=1)[-1]}"',
            f'"{save_file_path}"',
            save_type,
            f"split_video_by_time:{split}",
            f"converts_to_mp4:{converts_mp4}",
        ]
    command = script.strip() + " " + " ".join(params)
    logger.info("执行自定义脚本: %s", command)
    try:
        proc = subprocess.Popen(command, shell=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        if stdout and stdout.strip():
            logger.info("脚本输出: %s", stdout.decode("utf-8", errors="ignore")[:500])
        if stderr and stderr.strip():
            logger.warning("脚本错误输出: %s", stderr.decode("utf-8", errors="ignore")[:500])
    except PermissionError as e:
        logger.error("脚本无执行权限(%s): %s", command, e)
        logger.error("若是Linux环境请先 chmod +x your_script.sh")
    except OSError as e:
        logger.error("脚本执行失败(%s): %s", command, e)
        logger.error('请确保脚本以 #!/bin/bash 开头或为可执行文件')


class PostProcessor:
    """后处理 worker 池：submit() 即投递，处理在后台协程队列中串行执行"""

    def __init__(self, workers: int = 2) -> None:
        # 有界队列：无上限队列在长时间跑批/磁盘慢时会吃满内存（QueueFull 分支也随之复活）
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.workers = workers
        self._tasks: list[asyncio.Task] = []
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker(i)))

    async def stop(self) -> None:
        """停止 worker（积压任务不强制丢弃：等队列清空后退出）"""
        if not self._started:
            return
        for _ in self._tasks:
            await self.queue.put(None)  # 每个 worker 一个退出哨兵
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        self._started = False

    async def _worker(self, idx: int) -> None:
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            path, actions = item
            try:
                # _handle 内部是 subprocess.check_output / shutil.move 等同步阻塞调用，
                # 直接跑会卡死事件循环（录制协程与 WS 推送一起停摆），必须丢线程池
                await asyncio.to_thread(self._handle, path, actions)
            except Exception as e:
                logger.exception("后处理任务异常(%s): %s", path, e)
            finally:
                self.queue.task_done()

    def _handle(self, path: str, actions: dict) -> None:
        """一次录制的后处理动作序列。
        分段录制：actions["merge_segments"] = [所有分片] → 合并成一个 mp4；
        否则单文件 to_mp4 转码。最后执行自定义脚本。

        两库两目录流水线（缓存库→成品库）：
            合并出成品 mp4 → 若开启「成品自动转移」则把 mp4 从缓存目录 move 到成品目录
            → 调用 on_product 回调把成品路径交给引擎落「成品库」products 表。
        """
        merge_list = actions.get("merge_segments")
        product_path = None
        if merge_list:
            # 分段合并为一个完整 mp4（stream-rec 分段交付 + 原版 mp4 成品）
            ok = _merge_segments_to_mp4(
                merge_list, actions["merge_out"],
                actions.get("to_h264", False),
                actions.get("delete_original", False))
            if ok:
                product_path = actions["merge_out"]
        elif actions.get("to_mp4"):
            out = _convert_mp4(path, actions.get("to_h264", False),
                               actions.get("delete_original", False))
            if out:
                product_path = out
        elif actions.get("as_product"):
            # 单文件录制且不转码：文件本身就是成品，直接进转移/落库流水线
            # （旧代码只有 merge / to_mp4 两条分支，单文件永远拿不到 product_path）
            product_path = path

        # ---- 转移流水线：缓存目录 mp4 → 成品目录 ----
        final_path = product_path
        if product_path and os.path.exists(product_path):
            final_path = self._transfer_to_product(product_path, actions)
            # 回调落成品库（post_processor 不直接碰 DB，交给引擎）
            on_product = actions.get("on_product")
            if on_product:
                try:
                    on_product(final_path, actions)
                except Exception as e:
                    logger.exception("成品落库回调失败(%s): %s", final_path, e)

        # 生成时间字幕文件（可配：录制设置:生成时间字幕文件）
        # 注意：转移后原 product_path 已被 move，须用 final_path
        if final_path and os.path.exists(final_path) and actions.get("gen_srt"):
            _gen_srt(final_path, actions)

        if actions.get("script"):
            _run_script(
                actions["script"],
                actions.get("record_name", ""),
                path,
                actions.get("save_type", "ts"),
                actions.get("split", False),
                actions.get("converts_mp4", False),
            )

    def _transfer_to_product(self, src_mp4: str, actions: dict) -> str:
        """转移流水线（缓存库→成品库）：把合并好的成品 mp4 从缓存目录移动到成品目录。

        - 开启「成品自动转移」：move 到成品目录 downloads/平台/主播/文件名（保留相对结构）
        - 未开启：原地不动（成品留在缓存目录，但仍落成品库记录）
        返回成品最终绝对路径（无论是否移动）。
        """
        if not config_service.get_auto_move_product(True):
            return src_mp4
        product_dir = config_service.get_product_dir("downloads")
        platform = actions.get("platform", "")
        anchor = actions.get("anchor", "") or "未知主播"
        try:
            from pathlib import Path
            base = Path(product_dir)
            if platform:
                base = base / platform
            if anchor:
                base = base / anchor
            base.mkdir(parents=True, exist_ok=True)
            dst = base / os.path.basename(src_mp4)
            if os.path.abspath(src_mp4) == os.path.abspath(str(dst)):
                return str(dst)
            import shutil
            shutil.move(src_mp4, str(dst))
            logger.info("成品转移: %s -> %s", src_mp4, dst)
            return str(dst)
        except Exception as e:
            logger.error("成品转移失败(%s): %s，保留原路径", src_mp4, e)
            return src_mp4

    def submit_merge(self, segments: list[str], merge_out: str, actions: dict) -> None:
        """投递分段合并任务（多个 ts 分片 → 单个 mp4）"""
        if not segments:
            return
        if not self._started:
            self.start()
        actions = dict(actions)
        actions["merge_segments"] = list(segments)
        actions["merge_out"] = merge_out
        try:
            self.queue.put_nowait((merge_out, actions))
            logger.info("已投递分段合并任务: %d 片 → %s", len(segments), merge_out)
        except asyncio.QueueFull:
            logger.warning("后处理队列已满，跳过合并任务: %s", merge_out)

    def submit(self, file_path: str, actions: dict) -> None:
        """投递后处理任务（fire-and-forget；队列满不报错，记日志）"""
        if not file_path:
            return
        if not self._started:
            self.start()
        try:
            self.queue.put_nowait((file_path, actions))
            logger.info("已投递后处理任务: %s", file_path)
        except asyncio.QueueFull:
            logger.warning("后处理队列已满，跳过任务: %s", file_path)


# 全局单例（app startup 时 start，shutdown 时 stop）
post_processor = PostProcessor()