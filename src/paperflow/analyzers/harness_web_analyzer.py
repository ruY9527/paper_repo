"""DeepSeek Harness Web 自动解析后端（PDF 作为附件上传 + 提示词原样提交）。

与 headless CLI 的区别：
- 不走 stdin 塞 prompt，而是打开 DSH Web，把 PDF 经 ``input[type=file]`` 作为
  **附件**上传，把用户提示词**原封不动**写入 composer 提交。
- 通过临时启动 ``dsh web --port 0 --no-open`` 并捕获启动时打印的
  ``?token=`` URL 完成认证（DSH Web 要求带 token 的 URL）。

依赖：playwright + 本机 DSH checkout（PAPERFLOW_DSH_CHECKOUT 可覆盖）。
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from .base import AnalysisError, BaseAnalyzer

logger = get_logger()

DEFAULT_DSH_CHECKOUT = Path(r"E:\thesis-code\github_code\deepseek-harness")
DSH_BIN = Path("apps/cli/src/bin.ts")
_ADMIN_BLURB = re.compile(r"我已知晓并继续|用户须知|dsh-purge")


class HarnessWebAnalyzer(BaseAnalyzer):
    """通过 DSH Web 上传 PDF 附件并提交原样提示词。"""

    backend = "harness_web"

    def __init__(self, config: AppConfig, repo: PaperRepository, model: str | None = None,
                 provider: str | None = None):
        super().__init__(config, repo)
        self.cfg = config.analyzer.harness_web
        self.model = model
        self.provider = provider
        raw = os.environ.get("PAPERFLOW_DSH_CHECKOUT", str(DEFAULT_DSH_CHECKOUT))
        self.checkout = Path(raw) if (Path(raw) / DSH_BIN).exists() else None

    def health_check(self, probe: bool = False) -> dict[str, Any]:
        if self.checkout is None:
            return {"ok": False, "backend": self.backend,
                    "message": f"未找到 DSH checkout（{DEFAULT_DSH_CHECKOUT}）"}
        try:
            import playwright  # noqa: F401
            return {"ok": True, "backend": self.backend, "message": "DSH Web 附件模式可用"}
        except ImportError:
            return {"ok": False, "backend": self.backend, "message": "未安装 playwright"}

    # ---- 启动专用 dsh web，捕获带 token 的 URL ----
    def _start_web(self):
        if self.checkout is None:
            raise AnalysisError("DSH checkout 不存在", error_type="dsh_checkout_missing")
        node = os.environ.get("PAPERFLOW_NODE_BIN", "node")
        cmd = [node, "--import", "tsx/esm", str(DSH_BIN), "web",
               "--port", "0", "--no-open", "--host", "127.0.0.1"]
        proc = subprocess.Popen(
            cmd, cwd=str(self.checkout), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, shell=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        box: dict[str, str] = {}
        def reader():
            for line in proc.stdout or []:
                if "dsh web:" in line and "token=" in line:
                    m = re.search(r"(http://[^\s]+)", line)
                    if m:
                        box["url"] = m.group(1)
                        return
        threading.Thread(target=reader, daemon=True).start()
        deadline = time.time() + 40
        while time.time() < deadline and "url" not in box:
            if proc.poll() is not None:
                raise AnalysisError("dsh web 启动失败", error_type="dsh_web_start_failed")
            time.sleep(0.3)
        if "url" not in box:
            proc.terminate()
            raise AnalysisError("等待 dsh web token URL 超时", error_type="dsh_web_token_timeout")
        return proc, box["url"]

    @staticmethod
    def _dismiss_onboarding(pg) -> None:
        """勾选用户须知并继续（首次安装才出现；幂等）。"""
        try:
            cb = pg.locator(".dshpp-welcome-checks input[type=checkbox]")
            if cb.count():
                cb.first.check(timeout=3000)
            btn = pg.get_by_role("button", name="我已知晓并继续")
            if btn.count() and btn.first.is_enabled():
                btn.first.click(timeout=3000)
                pg.wait_for_timeout(300)
        except Exception:
            pass

    def generate(
        self,
        prompt: str,
        *,
        paper_uid: str = "",
        previous_errors: list[str] | None = None,
        attempt: int = 1,
        cancel_event=None,
        progress_cb: Callable[..., None] | None = None,
    ) -> tuple[str, str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise AnalysisError("缺少 playwright，无法使用 Web 附件模式", error_type="playwright_missing")

        # 找 PDF（任务包内或 tmp/pdfs）
        pdf = self._find_pdf(paper_uid)
        if pdf is None:
            raise AnalysisError(f"未找到 {paper_uid} 的 PDF，无法作为附件上传",
                                error_type="pdf_not_found")
        if progress_cb:
            progress_cb(stage="web_attach", message=f"打开 DSH Web 上传 PDF 附件（第 {attempt} 次）")

        proc, url = self._start_web()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 950})
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                self._dismiss_onboarding(page)

                # 附件上传
                file_input = page.locator("input[type=file]")
                if not file_input.count():
                    raise AnalysisError("DSH Web 未找到文件上传控件", error_type="file_input_missing")
                file_input.first.set_input_files(str(pdf), timeout=15000)
                if progress_cb:
                    progress_cb(stage="web_attached", message=f"PDF 附件已上传，等待接收回执")
                page.wait_for_timeout(2500)  # 等上传回执

                # 原样提示词写入 composer（不注入任何路径/正文/约束）
                composer = page.locator("[contenteditable=true]").first
                if not composer.count():
                    raise AnalysisError("DSH Web 未找到输入框", error_type="composer_missing")
                composer.click(timeout=10000)
                composer.fill(prompt)
                page.wait_for_timeout(500)

                # 发送：优先找发送按钮，否则 Enter
                self._submit(page)
                if progress_cb:
                    progress_cb(stage="web_generating", message=f"已提交，等待 DSH Web 输出（第 {attempt} 次）")

                text = self._wait_output(page, cancel_event)
                browser.close()
                # 提示词原样提交、PDF 作附件；仅对返回结果补 frontmatter 以过账本校验
                return self._wrap_output(text, paper_uid), "harness_web"
        finally:
            self._stop_web(proc)

    def build_prompt(self, paper_uid: str, previous_errors: list[str] | None = None) -> str:
        """Web 附件模式：返回逐字原文，绝不注入 PDF 路径/正文/元数据/输出约束。"""
        candidates = [
            Path(__file__).resolve().parents[3] / "config" / "prompts" / "paper_review_verbatim.md",
            self.config.workspace_path.parent / "config" / "prompts" / "paper_review_verbatim.md",
        ]
        for pf in candidates:
            if pf.exists():
                return pf.read_text(encoding="utf-8").strip() + "\n"
        # 兜底：内嵌同一原文（避免部署时缺文件）
        return ("你的任务是：清晰、易懂、深入、详细的总结这篇论文"
                "（读取PDF、搜索arxiv等各种信息源获取论文）。\n\n"
                "你的总结需要条理清晰的包含下面环节：\n" +
                "\n".join(f"{i}. " for i in range(1, 14)))

    def _wrap_output(self, text: str, paper_uid: str) -> str:
        """给 DSH Web 自由文本回复补合法 frontmatter，便于复用既有校验/发布链。"""
        text = (text or "").strip()
        if text.startswith("---"):
            return text
        p = self.repo.get_paper(paper_uid)
        def _esc(v: str) -> str:
            return str(v or "").replace('"', '\\"').replace("\n", " ")
        fm = (
            "---\n"
            f'paper_uid: "{_esc(paper_uid)}"\n'
            f'title: "{_esc(p.title if p else paper_uid)}"\n'
            f'venue: "{_esc(p.venue if p else "arXiv")}"\n'
            f"year: {getattr(p, 'pub_year', 2026) or 2026}\n"
            f'tier: "{getattr(p, "tier", "S") or "S"}"\n'
            f'tldr: "{_esc((p.abstract[:80] if p and p.abstract else paper_uid))}"\n'
            "---\n\n"
        )
        return fm + text + "\n"

    def _find_pdf(self, paper_uid: str) -> Path | None:
        ws = self.config.workspace_path
        cands = [
            ws / "tmp" / "pdfs" / f"{paper_uid}.pdf",
            *(ws / "queue").glob(f"*/{paper_uid}/{paper_uid}.pdf"),
        ]
        for p in cands:
            if p.exists() and p.stat().st_size > 0:
                return p
        return None

    def _submit(self, page) -> None:
        """触发发送：DSH Web 发送按钮 aria-label="发送消息"。"""
        for label in ("发送消息", "发送", "send"):
            btn = page.locator(f"button[aria-label*='{label}']")
            if btn.count() and btn.first.is_enabled():
                btn.first.click(timeout=5000)
                return
        composer = page.locator("[contenteditable=true]").first
        composer.click()
        composer.press("Enter")

    def _wait_output(self, page, cancel_event, timeout_s: int = 1800) -> str:
        """轮询等待 assistant 回复完成，抓取最后一个 markdown 消息容器正文。

        完成判据：会话区出现「已完成」标志（DSH Web 每轮结束会写「已完成，用时 …」）。
        """
        deadline = time.time() + min(timeout_s, self.config.analyzer.timeout_seconds)
        last = ""
        stable = 0
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise AnalysisError("任务已取消", error_type="cancelled")
            try:
                # assistant 回复正文位于 [class*=markdown] 容器；取最后一个（最新一轮）
                blobs = [b.strip() for b in page.locator("[class*=markdown]").all_inner_texts() if b.strip()]
                if blobs:
                    candidate = blobs[-1]
                    if candidate != last:
                        last, stable = candidate, 0
                    else:
                        stable += 1
                body = page.locator("body").inner_text()
                done = ("已完成" in body and "用时" in body) or "已停止" in body
                # 有正文且稳定若干轮，或出现完成标志且正文非空 → 返回
                if last and (done and stable >= 1 or stable >= 3):
                    return last
            except Exception:
                pass
            page.wait_for_timeout(1500)
        if last:
            return last
        raise AnalysisError("等待 DSH Web 回复超时", error_type="web_output_timeout")

    @staticmethod
    def _stop_web(proc) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
