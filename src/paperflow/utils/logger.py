"""Rich 控制台 + 按天轮转日志文件。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from rich.logging import RichHandler
from .timeutil import today_date

_LOGGER_CACHE: dict[str, logging.Logger] = {}


def setup_logger(
    name: str = "paperflow",
    log_dir: str | Path | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """获取（或首次配置）一个同时输出到 Rich 控制台与当日日志文件的 logger。"""
    if name in _LOGGER_CACHE:
        return _LOGGER_CACHE[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    console = RichHandler(rich_tracebacks=True, show_time=True, show_path=False)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    if log_dir is not None:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        log_file = directory / f"paperflow_{today_date().isoformat()}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        logger.addHandler(file_handler)

    _LOGGER_CACHE[name] = logger
    return logger


def get_logger(name: str = "paperflow") -> logging.Logger:
    return setup_logger(name)


def reset_logger_cache() -> None:
    """仅供测试使用：清空缓存以便重新配置。"""
    _LOGGER_CACHE.clear()
