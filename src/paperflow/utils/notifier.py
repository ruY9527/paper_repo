"""Windows 桌面通知 + 飞书/钉钉 Webhook（04 文档第 5 节）。

桌面通知失败静默降级到日志；Webhook 仅在环境变量存在时触发。
"""

from __future__ import annotations

import json
import os
import subprocess

import httpx

from ..config import AppConfig
from .logger import get_logger

logger = get_logger()


def windows_toast(title: str, message: str) -> bool:
    """用 PowerShell 原生 Toast；失败返回 False（静默降级）。"""
    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName('text')
$texts.Item(0).AppendChild($template.CreateTextNode({json.dumps(title)})) | Out-Null
$texts.Item(1).AppendChild($template.CreateTextNode({json.dumps(message)})) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PaperFlow').Show($toast)
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=15,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.debug(f"[notifier] 桌面通知降级: {exc}")
        return False


def send_webhook(config: AppConfig, title: str, message: str) -> bool:
    """飞书/钉钉/generic Webhook；从环境变量读取 URL，不存在则跳过。"""
    notif = config.notifications
    if notif.webhook_type == "none":
        return False
    url = os.environ.get(notif.webhook_url_env, "")
    if not url:
        logger.info(f"[notifier] 环境变量 {notif.webhook_url_env} 未设置，跳过 Webhook")
        return False

    if notif.webhook_type == "feishu":
        payload = {
            "msg_type": "interactive",
            "card": {"header": {"title": {"tag": "plain_text", "content": title}},
                     "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": message}}]},
        }
    elif notif.webhook_type == "dingtalk":
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": f"## {title}\n\n{message}"}}
    else:
        payload = {"title": title, "text": message}

    try:
        resp = httpx.post(url, json=payload, timeout=10.0, trust_env=False)
        return resp.status_code == 200
    except Exception as exc:
        logger.debug(f"[notifier] Webhook 发送失败（静默）: {exc}")
        return False


def notify_daily(config: AppConfig, message: str, title: str = "PaperFlow 日报") -> dict:
    """发送每日播报，返回各通道结果。"""
    result = {"toast": False, "webhook": False}
    if config.notifications.windows_toast:
        result["toast"] = windows_toast(title, message)
    result["webhook"] = send_webhook(config, title, message)
    logger.info(f"[notifier] {title}: {message}")
    return result
