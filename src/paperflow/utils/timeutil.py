"""全项目统一时间工具（时区：Asia/Shanghai，GMT+8）。

所有时间戳、日期、显示格式都从这里取，杜绝 UTC(Z) 与 GMT+8(+08:00) 混用。
- now_iso()    : 带 +08:00 的 ISO 时间戳，与前端 now_iso 同格式
- today_str()  : GMT+8 当天日期 YYYY-MM-DD
- fmt_display(): 中文显示格式 YYYY-MM-DD HH:MM:SS
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def now_dt() -> datetime:
    """当前 GMT+8 的 datetime（带时区）。"""
    return datetime.now(LOCAL_TZ)


def now_iso() -> str:
    """ISO 8601 时间戳（GMT+8，+08:00），秒精度。"""
    return now_dt().isoformat(timespec="seconds")


def today_str() -> str:
    """GMT+8 当天日期 YYYY-MM-DD。"""
    return now_dt().date().isoformat()


def today_date() -> date:
    """GMT+8 当天的 date 对象（需要日期运算时用）。"""
    return now_dt().date()


def fmt_display(ts: str | datetime | None) -> str:
    """把任意 ISO 时间戳（Z 或 +08:00）转成 GMT+8 显示格式。"""
    if not ts:
        return ""
    try:
        if isinstance(ts, datetime):
            d = ts
        else:
            d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=LOCAL_TZ)
        return d.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(ts)
