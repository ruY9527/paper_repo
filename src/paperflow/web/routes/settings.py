"""可视化配置中心 API：读取/校验保存 config.yaml、备份、重新打分。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import ValidationError

from ...config import AppConfig, PROJECT_ROOT
from ..state import get_manager
from ..task_manager import TaskManager, reload_config

router = APIRouter(prefix="/api/settings", tags=["settings"])

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@router.get("")
def get_settings(manager: TaskManager = Depends(get_manager)):
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.yaml 不存在")
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return {"config": data, "path": str(CONFIG_PATH)}


@router.put("")
def put_settings(body: dict[str, Any] = Body(...), manager: TaskManager = Depends(get_manager)):
    """Pydantic 校验 -> 备份 -> 原子覆盖写入。校验失败返回 422 且不写盘。

    安全策略：以磁盘现有 config 为基底做浅合并，仅更新前端传入的顶层键，
    避免旧前端/旧进程回传不完整 config 时静默删除 topic_search/analyzer 等新节点。
    """
    config_data = body.get("config", body)
    if not isinstance(config_data, dict):
        raise HTTPException(status_code=422, detail="config 必须是对象")

    # 语义校验：tier_s 必须 >= tier_a
    try:
        thresholds = config_data.get("interest_profile", {}).get("thresholds", {})
        if thresholds:
            ts = int(thresholds.get("tier_s", 50))
            ta = int(thresholds.get("tier_a", 25))
            if ts < ta:
                raise HTTPException(status_code=422, detail="tier_s 必须大于或等于 tier_a")
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"阈值非法: {exc}")

    # 以磁盘现有配置为基底，合并前端修改（不丢失磁盘上已有的新节点）
    merged = {}
    if CONFIG_PATH.exists():
        merged = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    merged.update(config_data)

    # Pydantic 严格校验（先验证，验证通过才写盘）
    try:
        AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"配置校验失败: {exc.errors()}")

    # 备份原文件
    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_suffix(".yaml.bak"))

    # 原子写入
    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, CONFIG_PATH)

    # 统一刷新 manager/app 与 MkDocs 服务配置
    reload_config(manager, CONFIG_PATH)

    return {"saved": True, "path": str(CONFIG_PATH), "backup": str(CONFIG_PATH) + ".bak"}


@router.post("/rescore")
def rescore(manager: TaskManager = Depends(get_manager)):
    """用最新兴趣画像重新给未发布（FETCHED/SCORED/SKIPPED）论文打分。"""
    from ...db.models import PaperRecord
    from ...pipeline.scorer import score_and_persist

    # 重新加载配置（Web 可能刚改过 config.yaml）
    cfg = reload_config(manager, CONFIG_PATH)

    targets = manager.repo.get_papers_by_status("FETCHED", "SCORED", "SKIPPED")
    s = a = b = 0
    for p in targets:
        result = score_and_persist(
            p, cfg, manager.repo,
            exempt_exclude_keywords=(p.discovery_mode == "topic" or p.source == "manual"),
        )
        if result.tier == "S":
            s += 1
        elif result.tier == "A":
            a += 1
        else:
            b += 1
    return {"rescored": len(targets), "tier_s": s, "tier_a": a, "tier_b": b}
