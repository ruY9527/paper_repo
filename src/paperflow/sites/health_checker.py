"""Phase 14：轻量并发死链巡检（HEAD 优先，405 回退 GET 流式读头）。

状态判定：2xx/3xx 且耗时 <=3s -> OK；2xx/3xx 且 >3s -> SLOW；
>=400 或异常/超时 -> DEAD。通过 progress_cb 推送进度。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from ..utils.timeutil import now_iso

import httpx

from ..utils.logger import get_logger

logger = get_logger()

SLOW_THRESHOLD_SECONDS = 3.0


def check_one(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """探测单个 URL，返回 {status, http_status, elapsed_ms}。"""
    import time
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; PaperFlowSiteHub/1.0)"}) as client:
            try:
                resp = client.head(url)
                code = resp.status_code
                if code == 405:
                    with client.stream("GET", url) as g:
                        code = g.status_code
            except httpx.HTTPError:
                # HEAD 失败（部分站点禁 HEAD）回退 GET
                with client.stream("GET", url) as g:
                    code = g.status_code
        elapsed = time.monotonic() - t0
        if 200 <= code < 400:
            status = "SLOW" if elapsed > SLOW_THRESHOLD_SECONDS else "OK"
        else:
            status = "DEAD"
        return {"status": status, "http_status": code,
                "elapsed_ms": int(elapsed * 1000)}
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.debug(f"[sites] health check {url}: {exc}")
        return {"status": "DEAD", "http_status": None,
                "elapsed_ms": int(elapsed * 1000), "error": type(exc).__name__}


def check_many(sites: list[dict[str, Any]], *, timeout: float = 8.0,
               concurrency: int = 5,
               progress_cb: Callable[..., None] | None = None) -> list[dict[str, Any]]:
    """并发巡检多个站点（每项需含 id / url），结果带 id 与状态。"""
    total = len(sites)
    results: list[dict[str, Any]] = []
    if not total:
        return results
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(check_one, s["url"], timeout): s for s in sites}
        for i, fut in enumerate(as_completed(futures), 1):
            site = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:
                r = {"status": "DEAD", "http_status": None, "error": str(exc)}
            r.update({"id": site["id"], "url": site["url"],
                      "checked_at": now_iso()})
            results.append(r)
            if progress_cb:
                progress_cb(stage="health_check", current=i, total=total,
                            message=f"巡检 {i}/{total}: {site['url']} -> {r['status']}")
    return results
