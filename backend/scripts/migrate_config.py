# -*- coding: utf-8 -*-
"""
配置迁移脚本：原项目 config.ini + URL_config.ini → SQLite configs/rooms 表
===========================================================================
用法：
    .venv/bin/python backend/scripts/migrate_config.py [--config 原项目config.ini] [--url 原项目URL_config.ini]

流程：
    1. config.ini 的 [节]配置扁平化为 configs 表（key = 节:option，保留中文说明）
    2. URL_config.ini 的每行直播间 → rooms 表（行首 # 注释 = enabled=False）
"""
from __future__ import annotations

import argparse
import configparser
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

from backend.models import Config, Room, init_db  # noqa: E402

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INI = BASE_DIR / "refs" / "DouyinLiveRecorder" / "config" / "config.ini"
DEFAULT_URL_INI = BASE_DIR / "refs" / "DouyinLiveRecorder" / "config" / "URL_config.ini"
DB_PATH = BASE_DIR / "data" / "recorder.db"


def migrate_configs(db, ini_path: Path) -> int:
    """ [节]option = value 扁平化写入 configs 表，返回写入条数 """
    cfg = configparser.RawConfigParser()   # 禁用 % 插值（cookie含大量%7B等URL编码）
    with open(ini_path, "r", encoding="utf-8-sig") as f:   # UTF-8 BOM
        cfg.read_file(f)
    count = 0
    for section in cfg.sections():
        for key, value in cfg.items(section):
            flat = f"{section}:{key}"
            row = db.query(Config).filter(Config.key == flat).first()
            if row:
                row.value = value
            else:
                db.add(Config(key=flat, value=value))
            count += 1
    db.commit()
    return count


def migrate_urls(db, ini_path: Path) -> int:
    """ URL_config.ini 每行 → rooms 表（跳过空行；# 注释 = disabled） """
    count = 0
    with open(ini_path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            enabled = True
            url = line
            if line.startswith("#"):
                enabled = False
                url = line.lstrip("#").strip()
            if not url or "http" not in url:
                continue
            exists = db.query(Room).filter(Room.url == url).first()
            if exists:
                exists.enabled = enabled
            else:
                db.add(Room(url=url, platform="", enabled=enabled))
            count += 1
    db.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移原项目配置到 SQLite")
    parser.add_argument("--config", default=str(DEFAULT_INI), help="原 config.ini 路径")
    parser.add_argument("--url", default=str(DEFAULT_URL_INI), help="原 URL_config.ini 路径")
    parser.add_argument("--db", default=str(DB_PATH), help="目标 SQLite 路径")
    args = parser.parse_args()

    factory = init_db(args.db)
    db = factory()
    try:
        n1 = migrate_configs(db, Path(args.config))
        print(f"[config.ini] 迁移 {n1} 条配置 -> configs 表")
        if Path(args.url).exists():
            n2 = migrate_urls(db, Path(args.url))
            print(f"[URL_config.ini] 迁移 {n2} 条直播间 -> rooms 表")
        else:
            print(f"[URL_config.ini] 跳过（文件不存在: {args.url}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()