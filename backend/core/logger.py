# -*- coding: utf-8 -*-
"""统一日志"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_configured = False


def _setup_root() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("recorder")
    if root.handlers:
        _configured = True
        return
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(_LOG_DIR / "recorder.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    root.addHandler(fh)
    root.addHandler(sh)
    _configured = True


def get_logger(name: str = "recorder") -> logging.Logger:
    _setup_root()
    return logging.getLogger(f"recorder.{name}")