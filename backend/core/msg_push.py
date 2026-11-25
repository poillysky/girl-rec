# -*- coding: utf-8 -*-
"""
消息推送（迁移自原项目 msg_push.py，295 行原样保留全部 7 通道）
================================================================
通道：钉钉 / 微信(xizhi) / 邮箱(SMTP) / TG / BARK / NTFY / PUSHPLUS

触发：订阅 event_center 的 live_start / live_end 事件（原版 main.py:1070-1115
开播/关播推送语义）：
    - 开播：live_status_push 非空 且 开播推送开启(是/否)=是
    - 关播：start 后 transform 到 over（原版 start_pushed 翻转语义）

配置（configs 表『推送配置:』前缀，迁移自 config.ini 原键）：
    直播状态推送渠道(大写逗号分隔：微信,钉钉,邮箱,TG,BARK,NTFY,PUSHPLUS)
    开播推送开启(是/否) / 关播推送开启(是/否)
    自定义推送标题 / 自定义开播推送内容 / 自定义关播推送内容
    (替换占位 [直播间名称] [时间])
    各通道参数：钉钉推送接口链接/钉钉通知@对象(填手机号)/钉钉通知@全体(是/否)
    微信推送接口链接/smtp邮件服务器/...（见 _load_config）

PushLog 落库：每次推送结果写 push_logs 表（channel/status/message），
与 WS 事件解耦，推送失败不阻塞录制主循环（异常整体吞掉只记日志）。
"""
from __future__ import annotations

import base64
import json
import time
import smtplib
import urllib.error
import urllib.request
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from ..core.logger import get_logger
from ..core.config_service import config_service
from ..core.event_bus import event_center

logger = get_logger("msg_push")

# 原版同款：禁用系统代理直连推送接口（推送通道不走业务代理）
no_proxy_handler = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(no_proxy_handler)
_req_headers: dict[str, str] = {"Content-Type": "application/json"}

# 推送渠道 -> 配置键前缀（原版 push_functions 对应）
CHANNEL_DINGTALK = "钉钉"
CHANNEL_XIZHI = "微信"
CHANNEL_EMAIL = "邮箱"
CHANNEL_TG = "TG"
CHANNEL_BARK = "BARK"
CHANNEL_NTFY = "NTFY"
CHANNEL_PUSHPLUS = "PUSHPLUS"


# ---------------------------------------------------------------
# 7 通道原版实现（函数签名与语义 1:1 迁移）
# ---------------------------------------------------------------
def dingtalk(url: str, content: str, number: str = None, is_atall: bool = False) -> dict[str, Any]:
    success, error = [], []
    api_list = url.replace("，", ",").split(",") if url.strip() else []
    for api in api_list:
        json_data = {'msgtype': 'text', 'text': {'content': content},
                     "at": {"atMobiles": [number], "isAtAll": is_atall}}
        try:
            req = urllib.request.Request(api, data=json.dumps(json_data).encode("utf-8"),
                                         headers=_req_headers)
            resp = json.loads(opener.open(req, timeout=10).read().decode("utf-8"))
            if resp.get("errcode") == 0:
                success.append(api)
            else:
                error.append(api)
                logger.warning("钉钉推送失败, 推送地址：%s, %s", api, resp.get("errmsg"))
        except Exception as e:
            error.append(api)
            logger.warning("钉钉推送失败, 推送地址：%s, 错误信息:%s", api, e)
    return {"success": success, "error": error}


def xizhi(url: str, title: str, content: str) -> dict[str, Any]:
    success, error = [], []
    api_list = url.replace("，", ",").split(",") if url.strip() else []
    for api in api_list:
        json_data = {'title': title, 'content': content}
        try:
            req = urllib.request.Request(api, data=json.dumps(json_data).encode("utf-8"),
                                         headers=_req_headers)
            resp = json.loads(opener.open(req, timeout=10).read().decode("utf-8"))
            if resp.get("code") == 200:
                success.append(api)
            else:
                error.append(api)
                logger.warning("微信推送失败, 推送地址：%s, 失败信息：%s", api, resp.get("msg"))
        except Exception as e:
            error.append(api)
            logger.warning("微信推送失败, 推送地址：%s, 错误信息:%s", api, e)
    return {"success": success, "error": error}


def send_email(email_host: str, login_email: str, email_pass: str, sender_email: str,
               sender_name: str, to_email: str, title: str, content: str,
               smtp_port: str = None, open_ssl: bool = True) -> dict[str, Any]:
    receivers = to_email.replace("，", ",").split(",") if to_email.strip() else []
    try:
        message = MIMEMultipart()
        send_name = base64.b64encode(sender_name.encode("utf-8")).decode()
        message['From'] = f"=?UTF-8?B?{send_name}?= <{sender_email}>"
        message['Subject'] = Header(title, 'utf-8')
        if len(receivers) == 1:
            message['To'] = receivers[0]
        message.attach(MIMEText(content, 'plain', 'utf-8'))

        if open_ssl:
            smtp_obj = smtplib.SMTP_SSL(email_host, int(smtp_port) or 465)
        else:
            smtp_obj = smtplib.SMTP(email_host, int(smtp_port) or 25)
        smtp_obj.login(login_email, email_pass)
        smtp_obj.sendmail(sender_email, receivers, message.as_string())
        return {"success": receivers, "error": []}
    except smtplib.SMTPException as e:
        logger.warning("邮件推送失败, 推送邮箱：%s, 错误信息:%s", to_email, e)
        return {"success": [], "error": receivers}


def tg_bot(chat_id: int, token: str, content: str) -> dict[str, Any]:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        req = urllib.request.Request(url, data=json.dumps(
            {"chat_id": chat_id, 'text': content}).encode("utf-8"), headers=_req_headers)
        urllib.request.urlopen(req, timeout=15)
        return {"success": [1], "error": []}
    except Exception as e:
        logger.warning("tg推送失败, 聊天ID：%s, 错误信息:%s", chat_id, e)
        return {"success": [], "error": [1]}


def bark(api: str, title: str = "message", content: str = 'test', level: str = "active",
         badge: int = 1, auto_copy: int = 1, sound: str = "", icon: str = "",
         group: str = "", is_archive: int = 1, url: str = "") -> dict[str, Any]:
    success, error = [], []
    api_list = api.replace("，", ",").split(",") if api.strip() else []
    for _api in api_list:
        json_data = {"title": title, "body": content, "level": level, "badge": badge,
                     "autoCopy": auto_copy, "sound": sound, "icon": icon, "group": group,
                     "isArchive": is_archive, "url": url}
        try:
            req = urllib.request.Request(_api, data=json.dumps(json_data).encode("utf-8"),
                                         headers=_req_headers)
            resp = json.loads(opener.open(req, timeout=10).read().decode("utf-8"))
            if resp.get("code") == 200:
                success.append(_api)
            else:
                error.append(_api)
                logger.warning("Bark推送失败, 推送地址：%s, 失败信息：%s", _api, resp.get("message"))
        except Exception as e:
            error.append(_api)
            logger.warning("Bark推送失败, 推送地址：%s, 错误信息:%s", _api, e)
    return {"success": success, "error": error}


def ntfy(api: str, title: str = "message", content: str = 'test', tags: str = 'tada',
         priority: int = 3, action_url: str = "", attach: str = "", filename: str = "",
         click: str = "", icon: str = "", delay: str = "", email: str = "",
         call: str = "") -> dict[str, Any]:
    success, error = [], []
    api_list = api.replace("，", ",").split(",") if api.strip() else []
    tags = tags.replace("，", ",").split(",") if tags else ['partying_face']
    actions = [{"action": "view", "label": "view live", "url": action_url}] if action_url else []
    for _api in api_list:
        server, topic = _api.rsplit('/', maxsplit=1)
        json_data = {"topic": topic, "title": title, "message": content, "tags": tags,
                     "priority": priority, "attach": attach, "filename": filename,
                     "click": click, "actions": actions, "markdown": False,
                     "icon": icon, "delay": delay, "email": email, "call": call}
        try:
            req = urllib.request.Request(server, data=json.dumps(
                json_data, ensure_ascii=False).encode("utf-8"), headers=_req_headers)
            resp = json.loads(opener.open(req, timeout=10).read().decode("utf-8"))
            if "error" not in resp:
                success.append(_api)
            else:
                error.append(_api)
                logger.warning("ntfy推送失败, 推送地址：%s, 失败信息：%s", _api, resp["error"])
        except urllib.error.HTTPError as e:
            error.append(_api)
            logger.warning("ntfy推送失败, 推送地址：%s, 失败信息:%s",
                           _api, json.loads(e.read().decode("utf-8")).get("error"))
        except Exception as e:
            error.append(_api)
            logger.warning("ntfy推送失败, 推送地址：%s, 错误信息:%s", _api, e)
    return {"success": success, "error": error}


def pushplus(token: str, title: str, content: str) -> dict[str, Any]:
    success, error = [], []
    token_list = token.replace("，", ",").split(",") if token.strip() else []
    for _token in token_list:
        json_data = {'token': _token, 'title': title, 'content': content}
        try:
            req = urllib.request.Request("https://www.pushplus.plus/send",
                                         data=json.dumps(json_data).encode("utf-8"),
                                         headers=_req_headers)
            resp = json.loads(opener.open(req, timeout=10).read().decode("utf-8"))
            if resp.get("code") == 200:
                success.append(_token)
            else:
                error.append(_token)
                logger.warning("PushPlus推送失败, Token：%s, 失败信息：%s", _token, resp.get("msg"))
        except Exception as e:
            error.append(_token)
            logger.warning("PushPlus推送失败, Token：%s, 错误信息:%s", _token, e)
    return {"success": success, "error": error}


# ---------------------------------------------------------------
# 配置加载 + 事件桥接（原版 main.py:1856-1880 的 18 个推送键）
# ---------------------------------------------------------------
def _load_config() -> dict:
    """一次性读全部推送配置（configs 表『推送配置:』前缀）"""
    c = config_service
    return {
        "live_status_push": c.get("推送配置:直播状态推送渠道", ""),
        "begin_show_push": c.get_bool("推送配置:开播推送开启(是/否)", True),
        "over_show_push": c.get_bool("推送配置:关播推送开启(是/否)", False),
        "push_message_title": c.get("推送配置:自定义推送标题", "直播间状态更新通知"),
        "begin_push_message_text": c.get("推送配置:自定义开播推送内容", ""),
        "over_push_message_text": c.get("推送配置:自定义关播推送内容", ""),
        "dingtalk_api_url": c.get("推送配置:钉钉推送接口链接", ""),
        "dingtalk_phone_num": c.get("推送配置:钉钉通知@对象(填手机号)", ""),
        "dingtalk_is_atall": c.get_bool("推送配置:钉钉通知@全体(是/否)", False),
        "xizhi_api_url": c.get("推送配置:微信推送接口链接", ""),
        "bark_msg_api": c.get("推送配置:bark推送接口链接", ""),
        "bark_msg_level": c.get("推送配置:bark推送中断级别", "active"),
        "bark_msg_ring": c.get("推送配置:bark推送铃声", "bell"),
        "tg_token": c.get("推送配置:tgapi令牌", ""),
        "tg_chat_id": c.get("推送配置:tg聊天id(个人或者群组id)", ""),
        "email_host": c.get("推送配置:smtp邮件服务器", ""),
        "open_smtp_ssl": c.get_bool("推送配置:是否使用smtp服务ssl加密(是/否)", True),
        "smtp_port": c.get("推送配置:smtp邮件服务器端口", ""),
        "login_email": c.get("推送配置:邮箱登录账号", ""),
        "email_password": c.get("推送配置:发件人密码(授权码)", ""),
        "sender_email": c.get("推送配置:发件人邮箱", ""),
        "sender_name": c.get("推送配置:发件人显示昵称", ""),
        "to_email": c.get("推送配置:收件人邮箱", ""),
        "ntfy_api": c.get("推送配置:ntfy推送地址", ""),
        "ntfy_tags": c.get("推送配置:ntfy推送标签", "tada"),
        "ntfy_email": c.get("推送配置:ntfy推送邮箱", ""),
        "pushplus_token": c.get("推送配置:pushplus推送token", ""),
    }


def _do_push(record_name: str, live_url: str, content: str, cfg: dict) -> dict[str, Any]:
    """按渠道分发（原版 push_message + push_functions 语义）。逐渠道 try 收集结果。"""
    msg_title = cfg["push_message_title"].strip() or "直播间状态更新通知"
    results: dict[str, Any] = {}
    channels = {
        CHANNEL_XIZHI: lambda: xizhi(cfg["xizhi_api_url"], msg_title, content),
        CHANNEL_DINGTALK: lambda: dingtalk(cfg["dingtalk_api_url"], content,
                                           cfg["dingtalk_phone_num"], cfg["dingtalk_is_atall"]),
        CHANNEL_EMAIL: lambda: send_email(cfg["email_host"], cfg["login_email"],
                                          cfg["email_password"], cfg["sender_email"],
                                          cfg["sender_name"], cfg["to_email"], msg_title,
                                          content, cfg["smtp_port"], cfg["open_smtp_ssl"]),
        CHANNEL_TG: lambda: tg_bot(int(cfg["tg_chat_id"] or 0), cfg["tg_token"], content),
        CHANNEL_BARK: lambda: bark(cfg["bark_msg_api"], title=msg_title, content=content,
                                   level=cfg["bark_msg_level"], sound=cfg["bark_msg_ring"]),
        CHANNEL_NTFY: lambda: ntfy(cfg["ntfy_api"], title=msg_title, content=content,
                                   tags=cfg["ntfy_tags"], action_url=live_url,
                                   email=cfg["ntfy_email"]),
        CHANNEL_PUSHPLUS: lambda: pushplus(cfg["pushplus_token"], msg_title, content),
    }
    enabled = set(ch.strip() for ch in cfg["live_status_push"].replace("，", ",").split(",")
                  if ch.strip())
    for name, fn in channels.items():
        if name not in enabled:
            continue
        try:
            res = fn()
            results[name] = res
            ok = not res.get("error")
            logger.info("推送[%s] %s %s: %s", record_name, name,
                        "成功" if ok else "失败", content[:60])
            _log_push(name, "sent" if ok else "failed",
                      json.dumps(res, ensure_ascii=False)[:500])
        except Exception as e:
            logger.warning("推送[%s] %s 异常: %s", record_name, name, e)
            _log_push(name, "failed", str(e)[:500])
    return results


def _log_push(channel: str, status: str, message: str) -> None:
    """推送结果落 push_logs 表（独立连接，失败不影响主流程）"""
    try:
        from ..models import get_session
        db = get_session()
        from ..models import PushLog
        db.add(PushLog(channel=channel, status=status, message=message))
        db.commit()
        db.close()
    except Exception:
        logger.exception("PushLog 落库失败")


# 推送节流去重：{(方向, room_id): 上次推送时间戳}
_push_last: dict = {}


def _throttle_ok(direction: str, room_id) -> bool:
    """直播推送检测频率(秒) 语义：同一房间同方向推送在间隔内只推一次，防断流重连重复通知。"""
    interval = config_service.get_push_check_interval(1800)
    if interval <= 0:
        return True
    key = (direction, room_id)
    now = time.time()
    last = _push_last.get(key, 0)
    if now - last < interval:
        return False
    _push_last[key] = now
    return True


async def _on_live(event) -> None:
    """live_start 事件 → 开播推送（原版 start_pushed 翻转语义）"""
    try:
        cfg = _load_config()
        if not cfg["live_status_push"] or not cfg["begin_show_push"]:
            return
        if not _throttle_ok("start", event.payload.get("room_id")):
            return
        record_name = str(event.payload.get("anchor") or event.payload.get("record_name")
                          or event.payload.get("room_id") or "")
        push_at = _now_str()
        content = cfg["begin_push_message_text"].strip() or \
            "直播间状态更新：[直播间名称] 正在直播中，时间：[时间]"
        content = content.replace("[直播间名称]", record_name).replace("[时间]", push_at)
        _do_push(record_name, event.payload.get("url", ""), content, cfg)
    except Exception:
        logger.exception("开播推送处理异常")


async def _on_live_end(event) -> None:
    """live_end 事件 → 关播推送"""
    try:
        cfg = _load_config()
        if not cfg["live_status_push"] or not cfg["over_show_push"]:
            return
        if not _throttle_ok("end", event.payload.get("room_id")):
            return
        record_name = str(event.payload.get("anchor") or event.payload.get("record_name")
                          or event.payload.get("room_id") or "")
        push_at = _now_str()
        content = cfg["over_push_message_text"].strip() or \
            "直播间状态更新：[直播间名称] 直播已结束！时间：[时间]"
        content = content.replace("[直播间名称]", record_name).replace("[时间]", push_at)
        _do_push(record_name, event.payload.get("url", ""), content, cfg)
    except Exception:
        logger.exception("关播推送处理异常")


def _now_str() -> str:
    import datetime
    return datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S')


def start() -> None:
    """模块级启动：订阅开播/关播事件（幂等，重复调用不重复订阅）"""
    seen = getattr(_on_live, "_subscribed", False)
    if seen:
        return
    event_center.subscribe("live_start", _on_live)
    event_center.subscribe("live_end", _on_live_end)
    _on_live._subscribed = True
    logger.info("消息推送已启动：订阅 live_start / live_end")


__all__ = [f.__name__ for f in (dingtalk, xizhi, send_email, tg_bot, bark, ntfy, pushplus)] + ["start"]