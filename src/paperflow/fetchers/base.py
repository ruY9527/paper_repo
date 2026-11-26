"""统一采集器接口：RawPaper 标准对象 + BaseFetcher 抽象基类 + 限流重试。"""

from __future__ import annotations

import abc
import time
from datetime import date

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..utils.logger import get_logger

logger = get_logger()


class RawPaper(BaseModel):
    """数据源无关的标准论文元数据对象。"""

    title: str
    authors: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    venue: str  # 标准化简称（大写）：CVPR/NEURIPS/TPAMI/...
    pub_year: int
    pub_date: str | None = None
    source: str  # arxiv | openalex | openreview | manual
    doi: str | None = None
    arxiv_id: str | None = None
    openreview_id: str | None = None
    abstract: str = ""
    comment: str = ""
    paper_url: str = ""
    pdf_url: str = ""
    code_url: str = ""
    project_url: str = ""


class RateLimiter:
    """按最小间隔节流，线程内串行调用。"""

    def __init__(self, min_interval_seconds: float):
        self.min_interval = max(0.0, min_interval_seconds)
        self._last_call: float | None = None

    def wait(self) -> None:
        if self._last_call is not None:
            elapsed = time.monotonic() - self._last_call
            remaining = self.min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_call = time.monotonic()


class FetchRetryableError(Exception):
    """可被 tenacity 重试的网络类错误（429 / 5xx / 超时）。"""


class BaseFetcher(abc.ABC):
    """所有采集器的基类：内置 httpx 客户端、限流、指数退避重试。"""

    source_name: str = "base"
    DEFAULT_USER_AGENT = "PaperFlow2026/1.0 (mailto:your_email@example.com)"

    def __init__(
        self,
        rate_limit_seconds: float = 1.0,
        user_agent: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ):
        self.rate_limiter = RateLimiter(rate_limit_seconds)
        from ..utils.http_env import sanitize_no_proxy
        sanitize_no_proxy()  # 规避 Windows NO_PROXY=[::1] 导致 httpx InvalidURL
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": user_agent or self.DEFAULT_USER_AGENT},
        )

    @property
    def client(self) -> httpx.Client:
        return self._client

    @retry(
        retry=retry_if_exception_type(FetchRetryableError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),  # 2s -> 4s -> 8s
        reraise=True,
    )
    def _get(self, url: str, **kwargs) -> httpx.Response:
        """带节流与指数退避重试的 GET。"""
        self.rate_limiter.wait()
        try:
            response = self._client.get(url, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(f"[{self.source_name}] 网络异常，将重试: {exc}")
            raise FetchRetryableError(str(exc)) from exc
        if response.status_code == 429 or 500 <= response.status_code < 600:
            logger.warning(f"[{self.source_name}] HTTP {response.status_code}，将重试: {url}")
            raise FetchRetryableError(f"HTTP {response.status_code}")
        return response

    @abc.abstractmethod
    def fetch_by_date_range(
        self, start_date: date, end_date: date, venues: list[str] | None = None
    ) -> list[RawPaper]:
        """按日期区间拉取论文，子类必须实现。"""
        raise NotImplementedError

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BaseFetcher":
        return self

    def __exit__(self, *args) -> None:
        self.close()
