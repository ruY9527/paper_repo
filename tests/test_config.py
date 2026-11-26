"""Phase 1 验收：配置系统严格校验（01 文档第 5 节第 1 项）。"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from paperflow.config import (
    ALL_VENUES,
    PROJECT_ROOT,
    AppConfig,
    load_config,
    load_example_config,
)


def test_example_config_parses_and_has_nine_venues():
    """config.example.yaml 能通过 Pydantic 严格校验并解析全部 9 个 Venue。"""
    cfg = load_example_config()
    assert isinstance(cfg, AppConfig)
    assert set(cfg.venues.names()) == set(ALL_VENUES)
    assert len(cfg.venues.names()) == 9
    # 期刊 3 + 会议 6
    assert set(cfg.venues.journals.keys()) == {"TPAMI", "TIP", "IJCV"}
    assert set(cfg.venues.conferences.keys()) == {
        "CVPR", "ECCV", "ICCV", "NEURIPS", "ICLR", "AAAI"
    }


def test_example_config_key_values():
    cfg = load_example_config()
    assert cfg.target_year == 2026
    assert cfg.project.timezone == "Asia/Shanghai"
    assert cfg.sources.arxiv.rate_limit_seconds == 3.1
    assert cfg.sources.openalex.rate_limit_seconds == 0.5
    assert cfg.sources.openreview.rate_limit_seconds == 1.0
    assert cfg.interest_profile.thresholds.tier_s == 50
    assert cfg.interest_profile.thresholds.tier_a == 25
    assert cfg.storage.min_valid_md_chars == 300
    assert cfg.backfill.max_slice_days == 5
    # 期刊 ISSN 与会议 OpenReview venue id 正确解析
    assert "0162-8828" in cfg.venues.journals["TPAMI"].issns
    assert cfg.venues.conferences["ICLR"].openreview_venue_id == "ICLR.cc/2026/Conference"
    assert cfg.venues.conferences["NEURIPS"].openreview_venue_id == "NeurIPS.cc/2026/Conference"


def test_paths_resolve_to_project_root():
    cfg = load_example_config()
    assert cfg.workspace_path == PROJECT_ROOT / "workspace"
    assert cfg.paper_repo_path == PROJECT_ROOT / "paper_repo"
    assert cfg.db_path == PROJECT_ROOT / "workspace" / "state.db"


def test_strict_mode_rejects_unknown_field():
    """extra=forbid：未知字段必须被拒绝。"""
    raw = yaml.safe_load(
        (PROJECT_ROOT / "config" / "config.example.yaml").read_text(encoding="utf-8")
    )
    raw["project"]["typo_field"] = "oops"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_missing_venue_rejected():
    raw = yaml.safe_load(
        (PROJECT_ROOT / "config" / "config.example.yaml").read_text(encoding="utf-8")
    )
    del raw["venues"]["conferences"]["AAAI"]
    with pytest.raises(ValidationError, match="缺少目标 Venue"):
        AppConfig.model_validate(raw)


def test_load_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="config.example.yaml"):
        load_config(tmp_path / "nope.yaml")
