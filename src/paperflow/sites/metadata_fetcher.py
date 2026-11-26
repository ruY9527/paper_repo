"""Phase 14：URL 标准化去重 + 轻量 HTML 元信息抓取（零重依赖）。

- normalize_url：补全协议、仅允许 http/https、主机名小写、去除 utm_* 等追踪参数、
  去末尾斜杠（根路径除外）与 fragment，返回 (normalized_url, domain)。
- fetch_metadata：httpx + 标准库 html.parser 提取 title/description/favicon，
  超时/403/反爬一律优雅降级，绝不抛异常。
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from ..utils.logger import get_logger

logger = get_logger()

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from",
}
_ALLOWED_SCHEMES = {"http", "https"}


def normalize_url(raw_url: str) -> tuple[str, str]:
    """标准化 URL 用于去重；非法协议抛 ValueError。"""
    raw = (raw_url or "").strip()
    if not raw:
        raise ValueError("URL 不能为空")
    # 补全协议（仅当无 scheme）
    parsed = urlparse(raw)
    if not parsed.scheme:
        parsed = urlparse("https://" + raw)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"不支持的 URL 协议: {scheme}")
    if not parsed.netloc:
        raise ValueError(f"URL 缺少主机名: {raw_url}")
    host = parsed.netloc.lower()
    # 去默认端口
    if scheme == "https" and host.endswith(":443"):
        host = host[:-4]
    elif scheme == "http" and host.endswith(":80"):
        host = host[:-3]
    # 去追踪参数
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                       if k.lower() not in _TRACKING_PARAMS])
    # 去末尾斜杠（含根路径，确保 https://x.com/ 与 https://x.com 归一化一致）
    path = parsed.path.rstrip("/")
    normalized = urlunparse((scheme, host, path, "", query, ""))
    return normalized, urlparse(normalized).netloc.split(":")[0]


class _MetaParser(HTMLParser):
    """提取 title / meta description / icon。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.og_title = ""
        self.og_description = ""
        self.icon = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key == "description" and not self.description:
                self.description = a.get("content", "").strip()
            elif key == "og:title":
                self.og_title = a.get("content", "").strip()
            elif key == "og:description" and not self.description:
                self.description = a.get("content", "").strip()
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if ("icon" in rel or "shortcut" in rel) and not self.icon and a.get("href"):
                self.icon = a["href"].strip()

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str):
        if self._in_title and not self.title:
            self.title = data.strip()


def fetch_metadata(raw_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """抓取网页元信息；任何异常都降级返回，不抛出。"""
    try:
        normalized, domain = normalize_url(raw_url)
    except ValueError as exc:
        return {"ok": False, "normalized_url": "", "domain": "", "title": "",
                "description": "", "favicon_url": "", "warning": str(exc)}
    fallback_favicon = f"https://{domain}/favicon.ico"
    base = {"ok": False, "normalized_url": normalized, "domain": domain,
            "title": domain, "description": "", "favicon_url": fallback_favicon,
            "warning": ""}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; PaperFlowSiteHub/1.0)"}) as client:
            with client.stream("GET", normalized) as resp:
                if resp.status_code >= 400:
                    base["warning"] = f"HTTP {resp.status_code}，无法自动抓取，请手动补全标题"
                    return base
                # 只读前 256KB
                buf = b""
                for chunk in resp.iter_bytes(65536):
                    buf += chunk
                    if len(buf) >= 262144:
                        break
                ctype = resp.headers.get("content-type", "")
        if "html" not in ctype.lower():
            base["warning"] = "非 HTML 页面，无法自动抓取，请手动补全标题"
            return base
        parser = _MetaParser()
        parser.feed(buf.decode("utf-8", errors="replace"))
        title = (parser.og_title or parser.title or domain).strip()
        desc = parser.description.strip()
        favicon = urljoin(normalized, parser.icon) if parser.icon else fallback_favicon
        return {"ok": True, "normalized_url": normalized, "domain": domain,
                "title": title, "description": desc, "favicon_url": favicon, "warning": ""}
    except Exception as exc:
        base["warning"] = f"无法自动抓取（{type(exc).__name__}），请手动补全标题"
        logger.debug(f"[sites] fetch_metadata {normalized}: {exc}")
        return base
