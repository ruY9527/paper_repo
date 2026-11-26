"""Phase 3 验收：自动补录按天切片、水位线断点续传、手动不回退。"""

from datetime import date

from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.backfill import (
    BackfillEngine,
    clamp_start_date,
    determine_start_date,
    slice_range,
)
from paperflow.fetchers.base import BaseFetcher, RawPaper


class StubFetcher(BaseFetcher):
    """可注入的假采集器：按调用次数决定是否抛异常。"""

    source_name = "arxiv"

    def __init__(self, fail_on_call: int | None = None):
        # 不创建真实 httpx client
        self.rate_limiter = None
        self.fail_on_call = fail_on_call
        self.calls = []

    def fetch_by_date_range(self, start_date, end_date, venues=None):
        self.calls.append((start_date, end_date))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("模拟网络中断")
        # 返回 1 篇普通论文（无高优先级词 -> B 级）
        return [RawPaper(
            title=f"Paper {start_date}",
            authors=[],
            venue="CVPR", pub_year=2026, pub_date=start_date.isoformat(),
            source="arxiv",
        )]


def _cfg():
    cfg = load_example_config()
    cfg.backfill.max_slice_days = 5
    cfg.backfill.default_lookback_days = 3
    return cfg


def test_slice_range():
    s = slice_range(date(2026, 3, 1), date(2026, 3, 12), 5)
    assert s == [
        (date(2026, 3, 1), date(2026, 3, 5)),
        (date(2026, 3, 6), date(2026, 3, 10)),
        (date(2026, 3, 11), date(2026, 3, 12)),
    ]


def test_determine_start_date(tmp_path):
    cfg = _cfg()
    repo = PaperRepository(tmp_path / "state.db")
    today = date(2026, 3, 20)
    # 无水位线 -> today - lookback
    assert determine_start_date(repo, "arxiv", "ALL", cfg, today) == date(2026, 3, 17)
    repo.set_watermark("arxiv", "ALL", "2026-03-15")
    assert determine_start_date(repo, "arxiv", "ALL", cfg, today) == date(2026, 3, 16)


def test_clamp_start_date():
    cfg = _cfg()
    start, truncated = clamp_start_date(date(2026, 1, 1), date(2026, 3, 20), cfg)
    assert truncated is True
    assert (date(2026, 3, 20) - start).days == 60


def test_auto_backfill_slices_and_watermark(tmp_path):
    """模拟停机 12 天，max_slice_days=5 -> 3 个切片；每片成功后推进水位线。"""
    cfg = _cfg()
    repo = PaperRepository(tmp_path / "state.db")
    today = date(2026, 3, 16)
    repo.set_watermark("arxiv", "ALL", "2026-03-04")  # 上次成功 12 天前
    fetcher = StubFetcher()

    engine = BackfillEngine(cfg, repo, fetchers={"arxiv": fetcher}, today=today)
    result = engine.run_auto()

    assert len(result.slices) == 3  # 3 个批次
    assert result.new_papers == 3
    wm = repo.get_watermark("arxiv", "ALL")
    assert wm.last_success_date == "2026-03-16"  # 推进到最后一天
    assert wm.last_status == "SUCCESS"


def test_auto_backfill_second_slice_failure_stops_watermark(tmp_path):
    """第 2 个切片抛异常：水位线停在第 1 片末尾，第 3 片不执行。"""
    cfg = _cfg()
    repo = PaperRepository(tmp_path / "state.db")
    today = date(2026, 3, 16)
    repo.set_watermark("arxiv", "ALL", "2026-03-04")
    # 从第 5 天起，第 2 次调用失败（第 1 片成功，第 2 片失败）
    fetcher = StubFetcher(fail_on_call=2)

    engine = BackfillEngine(cfg, repo, fetchers={"arxiv": fetcher}, today=today)
    result = engine.run_auto()

    assert result.failed == 1
    assert len(fetcher.calls) == 2  # 第 3 片未执行
    wm = repo.get_watermark("arxiv", "ALL")
    assert wm.last_success_date == "2026-03-09"  # 第 1 片末尾
    assert wm.last_status == "FAILED"
    assert "模拟网络中断" in wm.last_error


def test_manual_backfill_does_not_rewind_watermark(tmp_path):
    cfg = _cfg()
    repo = PaperRepository(tmp_path / "state.db")
    repo.set_watermark("arxiv", "ALL", "2026-03-15")
    engine = BackfillEngine(
        cfg, repo, fetchers={"arxiv": StubFetcher()}, today=date(2026, 3, 20)
    )
    result = engine.run_manual(date(2026, 1, 1), date(2026, 1, 5))
    wm = repo.get_watermark("arxiv", "ALL")
    assert wm.last_success_date == "2026-03-15"  # 未回退
