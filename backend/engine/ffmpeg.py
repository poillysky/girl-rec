# -*- coding: utf-8 -*-
"""
FFmpeg 录制执行器
=================
封装 ffmpeg 子进程生命周期：启动、优雅停止（发 'q'）、强杀、状态读取。
吸收原 main.py check_subprocess + ffmpeg 命令构造，重构为异步协程版。

录制健壮性参数（继承原项目并增强）：
    -rw_timeout 15s（海外 50s）网络卡顿自动重连
    -reconnect_streamed -reconnect_at_eof 断流重连
    -fflags +discardcorrupt 容错
    -max_muxing_queue_size 1024+ 防爆队
    分片录制、纯音频、mp4转码等由调用方决定命令尾部
"""
from __future__ import annotations

import asyncio
import atexit
import os
import signal
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..core.logger import get_logger

# 全局活跃 ffmpeg 子进程登记表：进程异常退出/被强杀时兜底清理，避免留下孤儿占配额带宽
_ACTIVE_PROCS: set = set()


def _cleanup_all_procs() -> None:
    """atexit / 信号兜底：强杀所有仍在运行的 ffmpeg 进程组。"""
    for proc in list(_ACTIVE_PROCS):
        try:
            if proc.returncode is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except Exception:
                pass
        except Exception:
            pass
    _ACTIVE_PROCS.clear()


atexit.register(_cleanup_all_procs)

logger = get_logger("ffmpeg")

OVERSEAS_FFMPEG_ARGS = [
    "-rw_timeout", "50000000",          # 海外 50s
    "-analyzeduration", "40s",
    "-probesize", "20M",
    "-max_muxing_queue_size", "2048",
]
# 海外参数按域名判断（原版 main.py:2050-2073 overseas_platform_host 20 个）
OVERSEAS_HOSTS = [
    "www.tiktok.com",
    "play.sooplive.co.kr", "m.sooplive.co.kr",
    "www.sooplive.com", "m.sooplive.com",
    "www.pandalive.co.kr",
    "www.winktv.co.kr",
    "www.flextv.co.kr",
    "www.ttinglive.com",
    "www.popkontv.com",
    "www.twitch.tv",
    "www.liveme.com",
    "www.showroom-live.com",
    "chzzk.naver.com", "m.chzzk.naver.com",
    "live.shopee.", ".shp.ee",
    "www.youtube.com", "youtu.be",
    "www.faceit.com",
]
# 原版固定录制 UA（主线程写死 Android UA，main.py:1166）
DEFAULT_UA = ("Mozilla/5.0 (Linux; Android 11; SAMSUNG SM-G973U) AppleWebKit/537.36 ("
              "KHTML, like Gecko) SamsungBrowser/14.2 Chrome/87.0.4280.141 Mobile "
              "Safari/537.36")


def _is_overseas_url(record_url: str) -> bool:
    """原版海外语义：record_url 命中海外域名列表才用海外参数（rw_timeout 50s 等）"""
    return any(host in record_url for host in OVERSEAS_HOSTS)


def _apply_overseas(base: list[str]) -> list[str]:
    """海外参数覆盖 base 同名项（rw_timeout/analyzeduration/probesize/max_muxing_queue_size）。

    保持被替换项在原位（rw_timeout 始终是 index 3,4），未出现在 base 中的海外项
    追加到结尾。返回新列表，不改动传入的 base。
    """
    out = list(base)
    for i in range(0, len(OVERSEAS_FFMPEG_ARGS), 2):
        flag = OVERSEAS_FFMPEG_ARGS[i]
        val = OVERSEAS_FFMPEG_ARGS[i + 1]
        if flag in out:
            idx = out.index(flag)
            out[idx:idx + 2] = [flag, val]
        else:
            out += [flag, val]
    return out

# 分片/结尾常用参数（由调用方拼接到命令尾部）
# 原版语义：视频全程 -c:v copy -c:a copy -map 0（不重编码；缺了会默认重编码 mpeg2video 报错）
SEGMENT_TAIL = {
    "ts": ["-c:v", "copy", "-c:a", "copy", "-map", "0",
           "-f", "segment", "-segment_time", "{seg_time}", "-segment_format", "mpegts",
           "-reset_timestamps", "1", "{output}"],
    "flv": ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
            "-f", "segment", "-segment_time", "{seg_time}", "-segment_format", "flv",
            "-reset_timestamps", "1", "{output}"],
    "mp4": ["-c:v", "copy", "-c:a", "aac", "-map", "0",
            "-f", "segment", "-segment_time", "{seg_time}", "-segment_format", "mp4",
            "-reset_timestamps", "1", "-movflags", "+frag_keyframe+empty_moov", "{output}"],
    "mkv": ["-flags", "global_header", "-c:v", "copy", "-c:a", "copy", "-map", "0",
            "-f", "segment", "-segment_time", "{seg_time}", "-segment_format", "matroska",
            "-reset_timestamps", "1", "{output}"],
}

WHOLE_TAIL = {
    "ts": ["-c:v", "copy", "-c:a", "copy", "-map", "0", "-f", "mpegts", "{output}"],
    "flv": ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
            "-f", "flv", "{output}"],
    "mp4": ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-f", "mp4", "{output}"],
    "mkv": ["-flags", "global_header", "-map", "0", "-c:v", "copy", "-c:a", "copy",
            "-f", "matroska", "{output}"],
}

AUDIO_TAIL = {
    "mp3": ["-map", "0:a", "-c:a", "libmp3lame", "-ab", "320k", "{output}"],
    "m4a": ["-map", "0:a", "-c:a", "aac", "-bsf:a", "aac_adtstoasc", "-ab", "320k",
            "-movflags", "+faststart", "{output}"],
}

# 音频分片（原版 main.py:1241-1265）：MP3 f segment 直出；M4A 用 mpegts 容器（原版原样）
SEGMENT_AUDIO_TAIL = {
    "mp3": ["-map", "0:a", "-c:a", "libmp3lame", "-ab", "320k",
            "-f", "segment", "-segment_time", "{seg_time}", "-reset_timestamps", "1",
            "{output}"],
    "m4a": ["-map", "0:a", "-c:a", "aac", "-bsf:a", "aac_adtstoasc", "-ab", "320k",
            "-f", "segment", "-segment_time", "{seg_time}", "-segment_format", "mpegts",
            "-reset_timestamps", "1", "{output}"],
}


def build_command(record_url: str, save_path: str, save_type: str,
                  quality: str = "原画", seg_time: int = 1800,
                  split: bool = False, overseas: bool = False,
                  http_headers: dict | None = None,
                  proxy: str = "", user_agent: str = "") -> list[str]:
    """构造 ffmpeg 命令（逐项对齐原版 main.py:1155-1205 的 ffmpeg_command 构建）。

    原版参数顺序（不可随意调换——ffmpeg 对 -reconnect_* / -max_muxing_queue_size
    等选项有"需在 -i 之后"的约束，放错位置报 Invalid argument/234）：
        ffmpeg -y -v verbose -rw_timeout{R} -loglevel error -hide_banner
               -user_agent{UA} -protocol_whitelist ... -thread_queue_size 1024
               -analyzeduration{AN} -probesize{PR} -fflags +discardcorrupt
               -re -i {url} -bufsize{BS} -sn -dn
               -reconnect_delay_max 60 -reconnect_streamed -reconnect_at_eof
               -max_muxing_queue_size{MMQS} -correct_ts_overflow 1 -avoid_negative_ts 1
    海外命中：rw_timeout=50000000/analyzeduration=40000000/probesize=20000000/
              bufsize=15000k/max_muxing_queue_size=2048（未命中：15000000/20000000/
              10000000/8000k/1024）
    headers：insert(11) 位（-user_agent 之后、-protocol_whitelist 之前）
    proxy：insert(1)/insert(2)（原版同款，紧跟 ffmpeg 之后）
    输出侧（分片/格式）由调用方追加 tail。
    """
    overseas = overseas or _is_overseas_url(record_url)
    ua = user_agent or DEFAULT_UA

    # 海外参数（原版每项独立赋值，命中才换值）
    rw_timeout = "50000000" if overseas else "15000000"
    analyzeduration = "40000000" if overseas else "20000000"
    probesize = "20000000" if overseas else "10000000"
    bufsize = "15000k" if overseas else "8000k"
    max_muxing_queue_size = "2048" if overseas else "1024"

    # ---- 顺序拼装（全部是输入侧全局选项，必须位于 -i 之前；不再用 insert 魔术下标）----
    cmd: list[str] = ["ffmpeg", "-y"]
    if proxy:
        cmd += ["-http_proxy", proxy]
    # 只保留一个日志级别：旧代码 -v verbose 与 -loglevel error 互相覆盖（后者生效），
    # 留着只会让维护者以为在打 verbose 日志
    cmd += ["-loglevel", "error", "-hide_banner"]
    if http_headers:
        header_str = " ".join(f"{k}: {v}" for k, v in http_headers.items())
        cmd += ["-headers", header_str]
    cmd += [
        "-user_agent", ua,
        "-rw_timeout", rw_timeout,
        "-protocol_whitelist", "rtmp,crypto,file,http,https,tcp,tls,udp,rtp,httpproxy",
        "-thread_queue_size", "1024",
        "-analyzeduration", analyzeduration,
        "-probesize", probesize,
        "-fflags", "+discardcorrupt",
        "-re", "-i", record_url,
        "-bufsize", bufsize,
        "-sn", "-dn",
        "-reconnect_delay_max", "60",
        "-reconnect_streamed", "-reconnect_at_eof",
        "-max_muxing_queue_size", max_muxing_queue_size,
        "-correct_ts_overflow", "1",
        "-avoid_negative_ts", "1",
    ]

    # ---- 输出侧（格式/分片） ----
    if save_type.upper() in ("MP3", "M4A"):
        fmt = save_type.lower()
        # 原版音频分片语义（main.py:1241-1265）：MP3 直接 f segment；
        # M4A 分片用 mpegts 容器（原版原样，扩展名仍是 .m4a）
        tail_cmd = (SEGMENT_AUDIO_TAIL[fmt] if split else AUDIO_TAIL[fmt]).copy()
    else:
        fmt = save_type.lower()
        tail_cmd = ((SEGMENT_TAIL if split else WHOLE_TAIL)
                    .get(fmt, (WHOLE_TAIL if not split else SEGMENT_TAIL)["ts"]).copy())
    out = save_path.replace("{", "").replace("}", "")
    if split:
        # 分片输出带 %03d 占位
        base, ext = os.path.splitext(save_path)
        out = f"{base}_%03d{ext}"
    tail_cmd = [t.replace("{output}", out).replace("{seg_time}", str(seg_time)) for t in tail_cmd]
    cmd += tail_cmd
    return cmd


class FFmpegRecorder:
    """单个 ffmpeg 子进程封装。

    进度：启动时自动注入 `-nostats -progress pipe:1`，stdout 逐行解析
    key=value 进度（out_time_us/size/bitrate/fps），wait() 期间通过
    get_progress() 读取。
    stderr：后台读取到环形缓冲（供断流/异常诊断），同时避免管道写满
    阻塞 ffmpeg（原版未读 stderr 的隐患）。
    """

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.process: asyncio.subprocess.Process | None = None
        self.started_at: float = 0.0
        self._stop_evt = asyncio.Event()
        self._readers: list[asyncio.Task] = []
        self._progress: dict[str, float | int | str] = {}
        self._progress_end = False
        self.stderr_lines: deque[str] = deque(maxlen=200)   # 断流诊断用
        self._progress_ts: float = 0.0

    async def start(self) -> None:
        self.started_at = time.time()
        self._stop_evt.clear()
        self._progress = {}
        self._progress_end = False
        self.stderr_lines.clear()
        # 注入进度输出（全局选项放可执行文件之后、其余参数之前）
        cmd = list(self.command[:1]) + ["-nostats", "-progress", "pipe:1"] + list(self.command[1:])
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,   # 独立进程组：父进程被强杀时不会留成孤儿占带宽
        )
        _ACTIVE_PROCS.add(self.process)
        logger.debug("ffmpeg 启动 pid=%s", self.process.pid)
        if self.process.stdout:
            self._readers.append(asyncio.create_task(self._read_progress()))
        if self.process.stderr:
            self._readers.append(asyncio.create_task(self._read_stderr()))

    async def _read_progress(self) -> None:
        """stdout 逐行解析 -progress key=value"""
        try:
            assert self.process and self.process.stdout
            async for raw in self.process.stdout:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    if k == "progress":
                        self._progress_end = (v == "end")
                    else:
                        try:
                            self._progress[k] = float(v)
                        except ValueError:
                            self._progress[k] = v
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("进度读取结束", exc_info=True)

    async def _read_stderr(self) -> None:
        """stderr 写环形缓冲（避免管道写满阻塞 ffmpeg，保留最近 200 行）"""
        try:
            assert self.process and self.process.stderr
            async for raw in self.process.stderr:
                line = raw.decode("utf-8", errors="ignore").rstrip("\n")
                if line:
                    self.stderr_lines.append(line)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _cancel_readers(self) -> None:
        for t in self._readers:
            t.cancel()
        for t in self._readers:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._readers.clear()

    def get_progress(self) -> dict:
        """当前录制进度（秒/字节/kbps），失败返回空 dict"""
        if self.process is None or self.process.returncode is not None:
            return {}

        def _num(v):
            """ffmpeg -progress 常出现 'N/A'，统一转 float 失败返回 None"""
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            if not s or s.upper() == "N/A":
                return None
            try:
                return float(s)
            except ValueError:
                import re
                m = re.search(r"-?[\d.]+", s)
                return float(m.group(0)) if m else None

        out_time_us = _num(self._progress.get("out_time_us"))
        size = _num(self._progress.get("total_size"))
        bitrate_raw = self._progress.get("bitrate")     # ffmpeg: " 123.4kbits/s"
        elapsed = time.time() - self.started_at
        duration = (out_time_us / 1_000_000.0) if out_time_us is not None else elapsed
        if size is None:
            size = _num(self._progress.get("size"))

        bitrate_kbps: float | None = None
        if bitrate_raw is not None:
            bitrate_kbps = _num(bitrate_raw)
            if bitrate_kbps is not None:
                bitrate_kbps = round(bitrate_kbps, 1)

        return {
            "duration_seconds": round(duration, 1),
            "file_size": int(size or 0),
            "bitrate_kbps": bitrate_kbps,
            "fps": self._progress.get("fps"),
            "paused": self._progress.get("speed") == "0x",
            "progress_end": self._progress_end,
        }

    def last_stderr(self, n: int = 10) -> str:
        """最近 n 行 stderr（断流/异常原因诊断）"""
        return "\n".join(list(self.stderr_lines)[-n:])

    async def wait(self, stop_callback=None) -> int:
        """等待进程退出。stop_callback 每 1s 回调一次，返回 True 表示发起优雅停止。"""
        while True:
            if self.process is None:
                return -1
            rc = self.process.returncode
            if rc is not None:
                break
            if stop_callback and stop_callback():
                await self.graceful_stop()
                stop_callback = None  # 只触发一次
            try:
                await asyncio.wait_for(self.process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
        await self._cancel_readers()
        if self.process is not None:
            _ACTIVE_PROCS.discard(self.process)
        return self.process.returncode if self.process else -1

    async def graceful_stop(self) -> None:
        """向 ffmpeg 发 'q'（正常收尾写索引），超时强杀"""
        if self.process is None or self.process.returncode is not None:
            return
        logger.info("ffmpeg 优雅停止...")
        try:
            if self.process.stdin and not self.process.stdin.is_closing():
                self.process.stdin.write(b"q")
                await self.process.stdin.drain()
        except Exception:
            pass
        try:
            await asyncio.wait_for(self.process.wait(), timeout=10)
            await self._cancel_readers()
            return
        except asyncio.TimeoutError:
            pass
        # 超时强杀（杀整个进程组，含可能的子进程）
        logger.warning("ffmpeg 10s 未退出，强杀进程组 pid=%s", self.process.pid)
        self._kill_group()
        await self.process.wait()
        await self._cancel_readers()
        _ACTIVE_PROCS.discard(self.process)

    def _kill_group(self) -> None:
        """杀死 ffmpeg 所在进程组（start_new_session=True 使 pgid==pid）。"""
        if self.process is None:
            return
        import os as _os, signal as _signal
        try:
            _os.killpg(_os.getpgid(self.process.pid), _signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

    async def stop(self) -> None:
        """强制停止（杀进程组，确保不留孤儿 ffmpeg）"""
        if self.process and self.process.returncode is None:
            self._kill_group()
            try:
                await self.process.wait()
            except ProcessLookupError:
                pass
            await self._cancel_readers()
            _ACTIVE_PROCS.discard(self.process)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FFmpegRecorder pid={self.process.pid if self.process else None}>"