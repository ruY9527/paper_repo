"""Phase 11：批量解析调度器（队列遍历、超时重试、校验自修复、进度回调）。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from ..config import AppConfig
from ..db.models import PaperStatus
from ..db.repository import PaperRepository
from ..pipeline.md_validator import validate_md_file
from ..publisher.digest import generate_digest
from ..utils.logger import get_logger
from ..utils.timeutil import now_iso, today_date
from .base import AnalysisError, AnalysisResult, BaseAnalyzer, atomic_write_text, sanitize_markdown_output
from .claude_cli_analyzer import ClaudeCliAnalyzer
from .harness_cli_analyzer import HarnessCliAnalyzer
from .openai_api_analyzer import OpenAIApiAnalyzer

logger = get_logger()


def create_analyzer(backend: str, config: AppConfig, repo: PaperRepository,
                    model: str | None = None, provider: str | None = None) -> BaseAnalyzer:
    """按后端名创建解析器实例；model 非空时覆盖配置里的默认模型。"""
    if backend == "harness_cli":
        return HarnessCliAnalyzer(config, repo, model=model, provider=provider)
    if backend == "harness_web":
        from .harness_web_analyzer import HarnessWebAnalyzer
        return HarnessWebAnalyzer(config, repo, model=model, provider=provider)
    if backend in ("claude_cli", "openai_api"):
        cfg = config
        if model:
            # 复制配置避免污染全局；只改对应后端的 model
            cfg = config.model_copy(deep=True)
            if backend == "claude_cli":
                cfg.analyzer.claude_cli.model = model
            else:
                cfg.analyzer.openai_api.model = model
        if backend == "claude_cli":
            return ClaudeCliAnalyzer(cfg, repo)
        return OpenAIApiAnalyzer(cfg, repo)
    raise ValueError(
        f"不支持的解析后端: {backend}。支持的后端: claude_cli / harness_cli / harness_web / openai_api。"
        "若你刚更新过代码仍报此错，说明 paperflow ui 是旧进程，请关闭后重新运行 "
        "python -m paperflow ui --open 并刷新页面。"
    )


class AnalyzerRunner:
    """批量解析调度器。"""

    def __init__(self, config: AppConfig, repo: PaperRepository,
                 analyzer: BaseAnalyzer | None = None,
                 backend: str | None = None,
                 model: str | None = None,
                 provider: str | None = None):
        self.config = config
        self.repo = repo
        self.backend = backend or (analyzer.backend if analyzer else config.analyzer.default_backend)
        self.analyzer = analyzer or create_analyzer(self.backend, config, repo, model=model, provider=provider)

    # ---- 单篇 ----

    # 单篇解析内部的阶段进度锚点（0~1），用于把「正在生成」这种长阶段也映射到进度条
    _STAGE_FRACTION = {
        "starting": 0.02, "building_prompt": 0.10, "generating": 0.45,
        "validating": 0.85, "validated": 0.95, "self_heal": 0.55,
    }

    def analyze_one(
        self,
        paper_uid: str,
        *,
        task_id: str | None = None,
        cancel_event=None,
        progress_cb: Callable[..., None] | None = None,
        base_percent: float = 0.0,
        percent_span: float = 100.0,
    ) -> AnalysisResult:
        cfg = self.config.analyzer
        started = time.monotonic()
        result = AnalysisResult(paper_uid=paper_uid, backend=self.backend, ok=False)
        previous_errors: list[str] = []
        max_attempts = cfg.max_retries + 1

        # 解析开始即落库一条 RUNNING 记录：提供"解析中"的持久痕迹与断点依据。
        # 每次终态时删除该 RUNNING 记录，再按既有语义插一条终态审计（每次尝试一条），
        # 因此审计表的历史条数与旧版一致，只是额外多了实时阶段追踪。
        run_id = self.repo.start_analysis_run(
            paper_uid=paper_uid, backend=self.backend, task_id=task_id,
            model_name=self.analyzer.model if hasattr(self.analyzer, "model") else "",
        )

        def audit_now(stage: str | None = None):
            result.duration_ms = int((time.monotonic() - started) * 1000)
            # 清掉实时 RUNNING 痕迹，写终态审计（兼容旧的每次尝试一条）
            self.repo.delete_analysis_run(run_id)
            self._audit(result, task_id, stage=stage)

        def emit(stage: str, message: str, level: str = "INFO", **kw):
            # 阶段驱动进度：单篇内部 building_prompt→generating→validating 逐步推进，
            # 避免「进度条瞬间 100% 但任务仍在跑」的问题；批量时按 percent_span 缩放。
            frac = self._STAGE_FRACTION.get(stage, 0.2)
            kw.setdefault("percent", round(base_percent + frac * percent_span, 1))
            if progress_cb:
                progress_cb(stage=stage, message=message, level=level, **kw)
            self.repo.update_analysis_run(run_id, stage=stage)

        # 找到论文与日期（用该论文的 fetch_date 或最新队列日期）
        paper = self.repo.get_paper(paper_uid)
        if paper is None:
            result.status = "ERROR"
            result.error_message = f"论文不存在: {paper_uid}"
            audit_now("paper_not_found")
            return result
        target_date = paper.fetch_date or today_date().isoformat()
        staging_path = self.config.workspace_path / "staging" / target_date / f"{paper_uid}.md"

        for attempt in range(1, max_attempts + 1):
            result.attempt = attempt
            if cancel_event is not None and cancel_event.is_set():
                result.status = "CANCELLED"
                result.error_message = "任务已取消"
                audit_now("cancelled")
                return result
            emit("building_prompt", f"{paper_uid} 构建 Prompt（第 {attempt} 次）")
            try:
                prompt = self.analyzer.build_prompt(paper_uid, previous_errors)
                raw, model_name = self.analyzer.generate(
                    prompt, paper_uid=paper_uid, previous_errors=previous_errors,
                    attempt=attempt, cancel_event=cancel_event,
                    progress_cb=progress_cb,
                )
                result.model_name = model_name
                emit("generating", f"{paper_uid} 模型生成中（第 {attempt} 次）")
            except TimeoutError as exc:
                result.status = "TIMEOUT"
                result.error_message = str(exc)
                result.error_detail = {"error_type": "timeout", "message": str(exc)}
                emit("timeout", f"✗ {paper_uid} 超时（第 {attempt} 次）: {str(exc)[:200]}", level="ERROR")
                audit_now()
                if attempt >= max_attempts:
                    return result
                continue
            except AnalysisError as exc:
                result.status = "ERROR"
                result.error_message = str(exc)
                result.error_detail = exc.to_detail()
                emit("error", f"✗ {paper_uid} 调用失败（第 {attempt} 次）: {str(exc)[:300]}", level="ERROR")
                audit_now()
                return result
            except Exception as exc:
                result.status = "ERROR"
                result.error_message = str(exc)
                result.error_detail = {"error_type": type(exc).__name__, "message": str(exc)[:2000]}
                emit("error", f"✗ {paper_uid} 异常（第 {attempt} 次）: {type(exc).__name__}: {str(exc)[:300]}", level="ERROR")
                audit_now()
                return result

            cleaned = sanitize_markdown_output(raw)
            result.output_chars = len(cleaned)
            if not cleaned:
                result.status = "VALIDATION_FAILED"
                result.errors = ["模型输出为空"]
                result.error_detail = {"error_type": "empty_output", "raw_chars": len(raw)}
                previous_errors = list(result.errors)
                emit("empty_output", f"✗ {paper_uid} 模型输出为空（第 {attempt} 次）", level="WARNING")
                audit_now()
                continue

            # 原子写入 staging
            # 兜底修复 AI 输出的裸公式（无 $ 定界符的方程），保证博客可渲染
            from ..pipeline.math_fix import fix_bare_math
            cleaned = fix_bare_math(cleaned)
            atomic_write_text(staging_path, cleaned)
            result.staging_path = str(staging_path)

            # 校验（自动入库 metrics、更新 STAGED）
            emit("validating", f"{paper_uid} 校验中")
            validation = validate_md_file(staging_path, self.repo, self.config, persist=True)
            if validation.ok:
                emit("validated", f"{paper_uid} 校验通过")
                result.ok = True
                result.status = "SUCCESS"
                result.error_message = None
                self.repo.update_status(paper_uid, PaperStatus.STAGED,
                                        md_staging_path=str(staging_path))
                try:
                    generate_digest(self.config, self.repo, target_date)
                except Exception:
                    pass
                audit_now()
                return result

            # 校验失败：把具体错误拼入下一次 prompt（自修复）
            result.status = "VALIDATION_FAILED"
            result.errors = validation.errors
            result.error_message = "；".join(validation.errors)
            result.error_detail = {"error_type": "validation_failed",
                                   "output_chars": len(cleaned),
                                   "staging_path": str(staging_path)}
            previous_errors = list(validation.errors)
            audit_now("validation_failed")
            emit("self_heal", f"{paper_uid} 校验失败，自修复重试: {result.error_message}", level="WARNING")

            # 校验失败时删除半成品，避免污染 staging
            staging_path.unlink(missing_ok=True)

        # 所有重试耗尽仍未成功
        emit("exhausted", f"✗ {paper_uid} 重试 {max_attempts} 次仍失败: {result.error_message or '未知原因'}", level="ERROR")
        audit_now("exhausted")
        return result

    def _audit(self, result: AnalysisResult, task_id: str | None, stage: str | None = None) -> None:
        try:
            import json
            detail = None
            if result.error_detail:
                detail = json.dumps(result.error_detail, ensure_ascii=False)
            errors = None
            if result.errors:
                errors = json.dumps(result.errors, ensure_ascii=False)
            self.repo.add_analysis_run(
                paper_uid=result.paper_uid, backend=result.backend,
                status=result.status, task_id=task_id,
                model_name=result.model_name, attempt=result.attempt,
                duration_ms=result.duration_ms, output_chars=result.output_chars,
                error_message=result.error_message,
                error_detail=detail, errors_json=errors,
                stage=stage or result.status,
                finished_at=now_iso(),
            )
        except Exception as exc:
            logger.warning(f"[analyzer] 审计落库失败: {exc}")

    # ---- 批量 ----

    def run_batch(
        self,
        paper_uids: list[str],
        *,
        task_id: str | None = None,
        cancel_event=None,
        progress_cb: Callable[..., None] | None = None,
    ) -> list[AnalysisResult]:
        results: list[AnalysisResult] = []
        total = len(paper_uids)
        span = 100.0 / total if total else 100.0
        for i, uid in enumerate(paper_uids):
            if cancel_event is not None and cancel_event.is_set():
                break
            base = i * span
            if progress_cb:
                progress_cb(stage="analyzing", current=i, total=total,
                            percent=round(base, 1),
                            message=f"正在解析第 {i + 1}/{total} 篇: {uid}")
            t0 = time.monotonic()
            result = self.analyze_one(uid, task_id=task_id,
                                      cancel_event=cancel_event, progress_cb=progress_cb,
                                      base_percent=base, percent_span=span)
            result.duration_ms = int((time.monotonic() - t0) * 1000)
            results.append(result)
            # 每篇给出明确终态日志：成功/失败都可见，失败带原因
            if progress_cb:
                ok = getattr(result, "ok", False) or result.status == "SUCCESS"
                progress_cb(
                    stage="paper_result",
                    status=result.status,
                    level="INFO" if ok else "ERROR",
                    percent=round(base + span, 1),
                    message=(f"✓ {uid} 解析完成" if ok
                             else f"✗ {uid} 解析失败（{result.status}）: {(result.error_message or '未知原因')[:200]}"),
                )
            # cooldown（可被取消打断）
            if i < total - 1 and self.config.analyzer.cooldown_seconds > 0:
                deadline = time.monotonic() + self.config.analyzer.cooldown_seconds
                while time.monotonic() < deadline:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    time.sleep(0.1)
        return results
