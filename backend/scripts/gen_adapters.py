# -*- coding: utf-8 -*-
"""
平台适配器批量生成器（一次性工具）
==================================
依据原版 main.py 路由 + spider.py/stream.py 函数签名，
为每个平台生成独立的 adapters/xx.py 适配器文件（保真迁移，同构模板）。

生成的每个文件都是独立可维护单元：
    加平台 = 复制模板改 extract/resolve 或直接在元数据表加行再生成。

本脚本只负责"拆"，不负责"改"——后续优化逐文件手工做。

用法：.venv/bin/python backend/scripts/gen_adapters.py
"""
import os
import re
from typing import Optional

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "adapters")
OUT_DIR = os.path.abspath(OUT_DIR)

HEADER = '''# -*- coding: utf-8 -*-
"""抖音直播适配器（自动生成模板）"""
'''


# 平台元数据表：(文件名, 平台名, 域名列表, spider函数名, stream处理说明, 特殊标记)
# stream处理说明取值：
#   direct  = spider 函数直接返回 {is_live, flv_url/m3u8_url, record_url}（无需二次处理）
#   stream_m3u8 = 用 stream.get_stream_url(json_data, quality)（is_live/play_url_list 结构）
#   stream_spec = 同上但 spec=True（用顶层 m3u8_url/flv_url 字段）
#   custom   = 需自定义 resolve（特殊函数/参数）
PLATFORMS = [
    # (file, name, domains, spider_fn, stream_mode, extra)
    ("tiktok",   "TikTok直播",  ["www.tiktok.com"],       "get_tiktok_stream_data",   "stream_spec", {"proxy": True}),
    ("kuaishou", "快手直播",    ["live.kuaishou.com"],     "get_kuaishou_stream_data", "custom", {}),
    ("huya",     "虎牙直播",    ["www.huya.com"],          "get_huya_stream_data",     "custom", {}),
    ("douyu",    "斗鱼直播",    ["www.douyu.com"],         "get_douyu_info_data",      "custom", {}),
    ("yy",       "YY直播",      ["www.yy.com"],            "get_yy_stream_data",       "custom", {}),
    ("bilibili", "B站直播",    ["live.bilibili.com"],     "get_bilibili_room_info",   "custom", {}),
    ("xhs",      "小红书直播",  ["xhslink.com", "xiaohongshu.com"], "get_xhs_stream_url", "direct", {}),
    ("bigo",     "Bigo直播",    ["www.bigo.tv", "slink.bigovideo.tv"], "get_bigo_stream_url", "direct", {}),
    ("blued",    "Blued直播",   ["app.blued.cn"],          "get_blued_stream_url",     "direct", {}),
    ("sooplive", "SOOP",       ["sooplive.co.kr", "sooplive.com"], "get_sooplive_stream_data", "stream_spec", {"proxy": True, "login": True}),
    ("netease",  "网易CC直播",  ["cc.163.com"],            "get_netease_stream_data",  "custom", {}),
    ("qiandurebo","千度热播",   ["qiandurebo.com"],        "get_qiandurebo_stream_data", "direct", {}),
    ("pandatv",  "PandaTV",     ["www.pandalive.co.kr"],   "get_pandatv_stream_data",  "stream_spec", {"proxy": True}),
    ("maoerfm",  "猫耳FM直播",  ["fm.missevan.com"],       "get_maoerfm_stream_url",   "direct", {"audio": True}),
    ("winktv",   "WinkTV",      ["www.winktv.co.kr"],      "get_winktv_stream_data",   "stream_spec", {"proxy": True}),
    ("flextv",   "FlexTV",      ["www.flextv.co.kr", "www.ttinglive.com"], "get_flextv_stream_data", "custom", {"proxy": True, "login": True}),
    ("looklive", "Look直播",    ["look.163.com"],          "get_looklive_stream_url",  "direct", {"audio": True}),
    ("popkontv", "PopkonTV",    ["www.popkontv.com"],      "get_popkontv_stream_url",  "direct", {"proxy": True, "login": True}),
    ("twitcasting","TwitCasting",["twitcasting.tv"],        "get_twitcasting_stream_url", "custom", {"login": True}),
    ("baidu",    "百度直播",    ["live.baidu.com"],        "get_baidu_stream_data",    "stream_m3u8", {}),
    ("weibo",    "微博直播",    ["weibo.com"],             "get_weibo_stream_data",    "custom", {}),
    ("kugou",    "酷狗直播",    ["kugou.com"],             "get_kugou_stream_url",     "direct", {}),
    ("twitchtv", "TwitchTV",    ["www.twitch.tv"],         "get_twitchtv_stream_data", "stream_spec", {"proxy": True}),
    ("liveme",   "LiveMe",      ["www.liveme.com"],        "get_liveme_stream_url",    "direct", {"proxy": True}),
    ("huajiao",  "花椒直播",    ["www.huajiao.com"],       "get_huajiao_stream_url",   "direct", {"flv": True}),
    ("liuxing",  "流星直播",    ["7u66.com"],              "get_liuxing_stream_url",   "direct", {}),
    ("showroom", "ShowRoom",    ["showroom-live.com"],     "get_showroom_stream_data", "stream_spec", {"proxy": True}),
    ("acfun",    "Acfun",       ["live.acfun.cn", "m.acfun.cn"], "get_acfun_stream_data", "custom", {}),
    ("changliao","畅聊直播",    ["live.tlclw.com"],        "get_changliao_stream_url", "direct", {}),
    ("yinbo",    "音播直播",    ["ybw1666.com"],           "get_yinbo_stream_url",     "direct", {}),
    ("yingke",   "映客直播",    ["www.inke.cn"],           "get_yingke_stream_url",    "direct", {}),
    ("zhihu",    "知乎直播",    ["www.zhihu.com"],         "get_zhihu_stream_url",     "direct", {}),
    ("chzzk",    "CHZZK",       ["chzzk.naver.com"],       "get_chzzk_stream_data",    "stream_spec", {"proxy": True}),
    ("haixiu",   "嗨秀直播",    ["www.haixiutv.com"],      "get_haixiu_stream_url",    "direct", {}),
    ("vvxqiu",   "VV星球",      ["vvxqiu.com"],            "get_vvxqiu_stream_url",    "direct", {}),
    ("live17",   "17Live",      ["17.live"],               "get_17live_stream_url",    "direct", {}),
    ("langlive", "浪Live",      ["www.lang.live"],         "get_langlive_stream_url",  "direct", {}),
    ("pplive",   "漂漂直播",    ["m.pp.weimipopo.com"],    "get_pplive_stream_url",    "direct", {}),
    ("room6",    "六间房直播",  [".6.cn"],                 "get_6room_stream_url",     "direct", {}),
    ("lehaitv",  "乐嗨直播",    ["lehaitv.com"],           "get_haixiu_stream_url",    "direct", {}),
    ("huamao",   "花猫直播",    ["h.catshow168.com"],      "get_pplive_stream_url",    "direct", {}),
    ("shopee",   "shopee",      ["live.shopee", "shp.ee"], "get_shopee_stream_url",    "direct", {"flv": True}),
    ("youtube",  "Youtube",     ["www.youtube.com", "youtu.be"], "get_youtube_stream_url", "stream_spec", {"proxy": True}),
    ("taobao",   "淘宝直播",    ["tb.cn"],                 "get_taobao_stream_url",    "custom", {}),
    ("jd",       "京东直播",    ["3.cn", "m.jd.com"],      "get_jd_stream_url",        "direct", {}),
    ("faceit",   "faceit",      ["faceit.com"],            "get_faceit_stream_data",   "stream_spec", {"proxy": True}),
    ("migu",     "咪咕直播",    ["miguvideo.com"],         "get_migu_stream_url",      "direct", {"http": True}),
    ("lianjie",  "连接直播",    ["show.lailianjie.com"],   "get_lianjie_stream_url",   "direct", {}),
    ("laixiu",   "来秀直播",    ["www.imkktv.com"],        "get_laixiu_stream_url",    "direct", {}),
    ("picarto",  "Picarto",     ["www.picarto.tv"],        "get_picarto_stream_url",   "direct", {}),
]


def snake(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '_', name)


def gen_resolve(mode: str, spider_fn: str) -> str:
    if mode == "direct":
        return f'''    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """spider 已直接给出可录制地址（原版 direct 返回）"""
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        info.is_live = True
        info.title = data.get("title", "")
        info.anchor_name = data.get("anchor_name", "")
        info.quality = quality
        info.flv_url = data.get("flv_url", "")
        info.m3u8_url = data.get("m3u8_url", "")
        info.record_url = data.get("record_url") or info.m3u8_url or info.flv_url
        return info'''
    if mode == "stream_m3u8":
        return f'''    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """通用 stream.get_stream_url（m3u8 通道）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        port = await stream.get_stream_url(data, quality)
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.m3u8_url = port.get("m3u8_url", "")
        info.flv_url = port.get("flv_url", "")
        info.record_url = port.get("record_url", "")
        return info'''
    if mode == "stream_spec":
        return f'''    async def resolve(self, data: dict, quality: str = "原画") -> StreamInfo:
        """通用 stream.get_stream_url（spec=True 用顶层 m3u8_url/flv_url）"""
        from ..legacy import stream as stream
        info = StreamInfo(anchor_name=data.get("anchor_name", ""))
        if not data.get("is_live"):
            return info
        port = await stream.get_stream_url(data, quality, spec=True)
        info.is_live = True
        info.title = port.get("title", "")
        info.anchor_name = port.get("anchor_name", "")
        info.quality = port.get("quality", quality)
        info.m3u8_url = port.get("m3u8_url", "")
        info.flv_url = port.get("flv_url", "")
        info.record_url = port.get("record_url", "")
        return info'''
    return ""


def gen_extract(spider_fn: str, mode: str, platform_name: str) -> str:
    # 带登录参数的平台需要额外配置读取
    return f'''    async def extract(self, url: str) -> dict:
        """拉取直播间数据（迁移自 legacy/spider.{spider_fn}）"""
        from ..legacy import spider
        try:
            data = await spider.{spider_fn}(
                url=url, proxy_addr=self.proxy or None, cookies=self.cookies or None)
            return data or {{}}
        except Exception as e:
            logger.warning("{platform_name} 数据抓取失败: %s", e)
            raise TransientError(f"{platform_name} 接口临时失败: {{e}}") from e'''


def gen_file(name, pname, domains, spider_fn, mode, extra):
    lines = []
    lines.append(f'''# -*- coding: utf-8 -*-
"""
{pname} 直播适配器
=================
迁移自原项目逆向资产（legacy/spider.py → {spider_fn}）。
一平台一文件：本文件即 {pname} 全部接入逻辑。
"""
from __future__ import annotations

from ..core.logger import get_logger
from .base import BasePlatform, StreamInfo, TransientError
from .registry import register

logger = get_logger("adapter.{name}")


@register
class {''.join(w.capitalize() for w in name.split('_'))}Platform(BasePlatform):
    platform_name = "{pname}"
    domains = {domains!r}
    enable_proxy = {str(bool(extra.get("proxy"))).lower()}
    support_danmu = False
    only_flv = {str(bool(extra.get("flv"))).lower()}
    only_audio = {str(bool(extra.get("audio"))).lower()}
''')
    # record_headers（原版 get_record_headers 平台子集）
    headers_map = {
        "PandaTV": "origin:https://www.pandalive.co.kr",
        "WinkTV": "origin:https://www.winktv.co.kr",
        "PopkonTV": "origin:https://www.popkontv.com",
        "FlexTV": "origin:https://www.flextv.co.kr",
        "千度热播": "referer:https://qiandurebo.com",
        "17Live": "referer:https://17.live/en/live/6302408",
        "浪Live": "referer:https://www.lang.live",
        "shopee": "origin:{live_domain}",
        "Blued直播": "referer:https://app.blued.cn",
    }
    if pname in headers_map:
        # 保真：原版是 'origin:https://...' 字符串（ffmpeg -headers 单行）
        lines.append(f'    record_headers = {{"{pname}": "{headers_map[pname]}"}}\n')

    lines.append('\n')
    lines.append(gen_extract(spider_fn, mode, pname))
    lines.append('\n\n')
    lines.append(gen_resolve(mode, spider_fn))
    lines.append('\n')
    return ''.join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, pname, domains, spider_fn, mode, extra in PLATFORMS:
        path = os.path.join(OUT_DIR, f"{name}.py")
        content = gen_file(name, pname, domains, spider_fn, mode, extra)
        # 已存在不覆盖（手工优化优先）
        if os.path.exists(path):
            print(f"[skip] {path} 已存在")
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[ok] {path}")


if __name__ == "__main__":
    main()