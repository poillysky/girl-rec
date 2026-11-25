# -*- coding: utf-8 -*-
"""
引擎层：录制会话 + ffmpeg 执行器
"""
from .ffmpeg import FFmpegRecorder, build_command
from .session import (RecordingSession, STATE_IDLE, STATE_CHECKING, STATE_PREPARING,
                      STATE_RECORDING, STATE_STOPPING, STATE_FINISHED, STATE_FAILED,
                      STATE_STOPPED, MAX_RECONNECT, DEAD_STREAM_TIMEOUT)

__all__ = [
    "FFmpegRecorder", "build_command",
    "RecordingSession",
    "STATE_IDLE", "STATE_CHECKING", "STATE_PREPARING", "STATE_RECORDING",
    "STATE_STOPPING", "STATE_FINISHED", "STATE_FAILED", "STATE_STOPPED",
    "MAX_RECONNECT", "DEAD_STREAM_TIMEOUT",
]