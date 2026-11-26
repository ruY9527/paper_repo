"""Phase 15：解析引擎能力注册表（单一真相源）。

新增解析引擎只需：
1. 在 ENGINES 注册一条 EngineSpec；
2. 在 runner.create_analyzer 增加创建分支。
前端引擎下拉由 /api/analyzer/engines 数据驱动，新增引擎前端零改动；
论文队列、操作、进度、结果查看与引擎解耦，保持稳定。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EngineSpec:
    id: str                 # 后端标识，传给 /api/analyzer/run 的 backend
    name: str               # 显示名
    icon: str               # Emoji
    mode: str               # auto（全自动批量）| manual（手动协作）
    description: str        # 一句话说明
    supports_model: bool    # 是否使用上方模型下拉（DSH 模型目录）
    supports_check: bool    # 是否支持连通性检测
    available: bool = True  # 是否可用（配置缺失时置 False 并给 reason）
    reason: str = ""


# 引擎注册表：顺序即前端下拉顺序
ENGINES: tuple[EngineSpec, ...] = (
    EngineSpec(
        id="claude_cli", name="Claude CLI", icon="🤖", mode="auto",
        description="本地 Claude CLI 全自动批量解析（Kimi K3）",
        supports_model=True, supports_check=True,
    ),
    EngineSpec(
        id="harness_cli", name="DeepSeek Harness", icon="⚡", mode="auto",
        description="DeepSeek Harness headless 全自动批量解析，按选中模型执行",
        supports_model=True, supports_check=True,
    ),
    EngineSpec(
        id="harness_web", name="Harness Web（附件模式）", icon="📎", mode="auto",
        description="自动打开 DSH Web，把 PDF 作为附件上传、提示词原样提交（Karpathy/Kaiming 13 节），结果自动回填",
        supports_model=False, supports_check=True,
    ),
)


def list_engines(config: Any | None = None) -> list[dict[str, Any]]:
    """返回引擎能力清单；按当前配置标记可用性。"""
    out: list[dict[str, Any]] = []
    for e in ENGINES:
        d = asdict(e)
        if config is not None:
            analyzer = getattr(config, "analyzer", None)
            if analyzer is not None:
                if e.id == "claude_cli" and not getattr(analyzer.claude_cli, "enabled", True):
                    d.update(available=False, reason="claude_cli 未在配置中启用")
                elif e.id == "harness_web" and not getattr(analyzer.harness_web, "enabled", True):
                    d.update(available=False, reason="harness_web 未在配置中启用")
        out.append(d)
    return out
