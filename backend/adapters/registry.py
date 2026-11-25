# -*- coding: utf-8 -*-
"""
平台注册表
==========
模块导入即注册（@register 装饰器）；match_platform(url) 按域名自动路由。

加平台流程：
    1. server/adapters/ 下新建 xxx.py
    2. 继承 BasePlatform，@register，实现 extract/resolve
    3. 在 __init__.py 的 import 区加一行导入
    完成。
"""
from __future__ import annotations

from typing import Type

from .base import BasePlatform

# 平台名 -> 适配器类
PLATFORM_REGISTRY: dict[str, Type[BasePlatform]] = {}
# 兼容别名（__init__.py 及外部引用 registry）
registry = PLATFORM_REGISTRY


def register(cls: Type[BasePlatform]) -> Type[BasePlatform]:
    """类装饰器：注册平台"""
    if not cls.platform_name:
        raise ValueError(f"{cls.__name__} 缺少 platform_name")
    if cls.platform_name in PLATFORM_REGISTRY:
        raise ValueError(f"平台 {cls.platform_name} 重复注册")
    PLATFORM_REGISTRY[cls.platform_name] = cls
    return cls


def match_platform(url: str) -> Type[BasePlatform] | None:
    """按 URL 匹配平台类"""
    for cls in PLATFORM_REGISTRY.values():
        if cls.match(url):
            return cls
    return None


def get_platform(name: str) -> Type[BasePlatform] | None:
    """按平台名获取类"""
    return PLATFORM_REGISTRY.get(name)


def list_platforms() -> list[dict]:
    """平台列表（供前端 /api/platforms 动态展示）"""
    return [
        {
            "name": cls.platform_name,
            "domains": cls.domains,
            "enable_proxy": cls.enable_proxy,
            "support_danmu": cls.support_danmu,
            "only_audio": cls.only_audio,
            "only_flv": cls.only_flv,
        }
        for cls in PLATFORM_REGISTRY.values()
    ]