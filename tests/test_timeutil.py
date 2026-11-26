"""全项目统一时间工具验收（GMT+8 / Asia-Shanghai）。"""

from __future__ import annotations

from datetime import datetime, timezone

from paperflow.utils.timeutil import LOCAL_TZ, fmt_display, now_dt, now_iso, today_date, today_str
from paperflow.db.models import utc_now_iso


def test_now_iso_gmt8_offset():
    ts = now_iso()
    assert ts.endswith("+08:00"), ts
    # 秒精度无毫秒
    assert "." not in ts.split("+")[0]


def test_utc_now_iso_alias_is_gmt8():
    # 历史函数名保留，但语义已统一为 GMT+8
    assert utc_now_iso().endswith("+08:00")


def test_today_date_and_str():
    assert today_str() == today_date().isoformat()
    assert len(today_str()) == 10


def test_fmt_display_handles_z_and_offset():
    z = "2026-11-22T06:38:32.660Z"
    plus8 = "2026-11-22T14:38:32+08:00"
    assert fmt_display(z) == "2026-11-22 14:38:32"
    assert fmt_display(plus8) == "2026-11-22 14:38:32"
    assert fmt_display(z) == fmt_display(plus8)


def test_fmt_display_with_datetime():
    d = datetime(2026, 11, 22, 6, 38, 32, tzinfo=timezone.utc)
    assert fmt_display(d) == "2026-11-22 14:38:32"


def test_local_tz_offset():
    assert LOCAL_TZ.utcoffset(None).total_seconds() == 8 * 3600
