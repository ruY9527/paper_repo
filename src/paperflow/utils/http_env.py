"""HTTP 环境兼容性工具。

Windows 上部分环境把 NO_PROXY 设为 `localhost,127.0.0.1,::1,[::1]`，
httpx 解析带方括号的 IPv6 项时会报 `InvalidURL: Invalid port: ':1]'`，
导致所有走系统代理的 HTTP 客户端失效。这里在进程内规范化 NO_PROXY，
去掉畸形 IPv6 项，保留其余（含有效代理配置），避免影响其它库。
"""

from __future__ import annotations

import os


def sanitize_no_proxy() -> None:
    """幂等清理 NO_PROXY/no_proxy 中 httpx 无法解析的 [::1] 项。"""
    for key in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(key)
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(",")]
        cleaned = [p for p in parts if p and p not in ("[::1]",)]
        # ::1 裸写也可能触发，统一去掉；保留 :: 之外的正常项
        cleaned = [p for p in cleaned if p != "[::1]"]
        new = ",".join(cleaned)
        if new != raw:
            os.environ[key] = new
