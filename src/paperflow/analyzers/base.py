"""Phase 11：解析引擎公共基础（08 文档第 4 节）。

- BaseAnalyzer 抽象基类
- AnalysisResult 结果模型
- sanitize_markdown_output：清洗思考前缀 / 外层 ```markdown 围栏，定位合法 Frontmatter
- smart_truncate：超长正文保留前 75% + 后 25%，中间插入省略标记
"""

from __future__ import annotations

import abc
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..utils.logger import get_logger

logger = get_logger()

_FENCE_RE = re.compile(r"^\s*```(?:markdown|md)?\s*\n", re.IGNORECASE)
# 合法 Frontmatter 起始行：--- 独占一行
_FM_START_RE = re.compile(r"(?m)^\s*---\s*$")


class AnalysisError(Exception):
    """下游解析器错误，携带可诊断的结构化细节。

    runner 捕获后写入 analysis_runs.error_detail，供前端「错误详情」还原现场。
    """

    def __init__(self, message: str, *, error_type: str = "engine_error",
                 stderr: str = "", http_status: int | None = None,
                 response_snippet: str = "", exit_code: int | None = None,
                 extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.stderr = (stderr or "")[:4000]
        self.http_status = http_status
        self.response_snippet = (response_snippet or "")[:2000]
        self.exit_code = exit_code
        self.extra = extra or {}

    def to_detail(self) -> dict:
        d = {
            "error_type": self.error_type,
            "stderr": self.stderr,
            "http_status": self.http_status,
            "response_snippet": self.response_snippet,
            "exit_code": self.exit_code,
        }
        d.update(self.extra)
        return {k: v for k, v in d.items() if v not in (None, "")}


@dataclass
class AnalysisResult:
    """单次解析结果。"""

    paper_uid: str
    backend: str
    ok: bool
    markdown: str = ""
    staging_path: str = ""
    status: str = "SUCCESS"  # SUCCESS | VALIDATION_FAILED | TIMEOUT | ERROR | CANCELLED
    attempt: int = 1
    duration_ms: int = 0
    output_chars: int = 0
    error_message: str | None = None
    error_detail: dict | None = None
    errors: list[str] = field(default_factory=list)
    model_name: str = ""


def sanitize_markdown_output(raw: str) -> str:
    """把模型输出清洗为以 `---` 开头的合法 Markdown。

    处理：外层 ```markdown / ``` 围栏、模型思考前缀、空白与尾部围栏。
    找不到合法 Frontmatter 时返回清洗后的原文（交给 validator 给出精确错误）。
    """
    text = (raw or "").strip()
    # 去外层代码围栏（允许前面有少量废话时，先尝试直接找围栏）
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        inner = text[fence_match.end():]
        # 去掉尾部围栏
        inner = re.sub(r"\n```\s*$", "", inner.strip())
        text = inner.strip()
    else:
        # 无起始围栏时，也可能以 ``` 结束
        text = re.sub(r"\n```\s*$", "", text)

    # 定位第一个独占一行的 ---
    m = _FM_START_RE.search(text)
    if m:
        text = text[m.start():]
    # 去掉尾部可能残留的围栏
    text = re.sub(r"\n```\s*$", "", text.strip())
    return text.strip() + "\n" if text.strip() else ""


def smart_truncate(text: str, max_chars: int) -> str:
    """超长正文智能截断：前 75% + 后 25%，中间插入提示。"""
    text = text or ""
    if len(text) <= max_chars:
        return text
    marker = "\n...[中间部分因长度限制已省略]...\n"
    remain = max(0, max_chars - len(marker))
    head = int(remain * 0.75)
    tail = remain - head
    return text[:head] + marker + (text[-tail:] if tail > 0 else "")


def communicate_once(proc, prompt: str, timeout: int, cancel_event=None) -> tuple[str, str]:
    """向子进程写入 prompt 一次并收集输出（关键：input 只能写一次）。

    旧实现用 `communicate(input=prompt, timeout=0.5)` 循环重试，超时后再次
    communicate 会重复写入 prompt，导致下游 AI 收到拼接乱码。这里改为单次
    communicate + 后台定时/取消线程调用 terminate，保证 prompt 完整且仅一次。
    """
    import threading

    def _terminate():
        # 由取消事件或超时定时器触发
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    timer: threading.Timer | None = None
    cancel_watch: threading.Thread | None = None
    stop_watch = threading.Event()

    if cancel_event is not None:
        def _watch():
            while not stop_watch.is_set():
                if cancel_event.is_set():
                    _terminate()
                    return
                stop_watch.wait(0.05)
        cancel_watch = threading.Thread(target=_watch, daemon=True)
        cancel_watch.start()

    try:
        # 单次 communicate：prompt 只写入一次；超时后由 timer 终止进程使其返回
        timer = threading.Timer(timeout, _terminate)
        timer.daemon = True
        timer.start()
        out, err = proc.communicate(input=prompt)
    finally:
        stop_watch.set()
        if timer is not None:
            timer.cancel()
        if cancel_watch is not None:
            cancel_watch.join(timeout=1)

    if proc.returncode is not None and proc.returncode < 0:
        # 被 terminate/kill：区分取消与超时
        if cancel_event is not None and cancel_event.is_set():
            raise TimeoutError("任务已被用户取消")
        raise TimeoutError(f"子进程超时（{timeout}s）")
    return out or "", err or ""


def atomic_write_text(path: str | Path, content: str) -> None:
    """原子写入 UTF-8 文本：先写 .tmp 再 os.replace。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def ensure_analysis_package(config, repo, paper_uid: str,
                            pdf_bytes: bytes | None = None) -> Path:
    """确保论文有可解析的队列任务包（prompt.md + extracted_text.md）。

    场景：论文已在账本里且 PDF 已下载（DOWNLOADED），但还没 export-queue，
    或用户直接导入了本地 PDF。此函数即时补齐任务包，使 AI 解析无需等待导出。

    返回队列目录 Path。已有完整任务包时直接返回，不重复抽取。
    """
    from ..utils.timeutil import today_date
    from ..pipeline.extractor import extract_clean_text, extract_figures
    from ..pipeline.prompt_manager import PromptManager
    from ..utils.bibtex import to_bibtex

    paper = repo.get_paper(paper_uid)
    if paper is None:
        raise FileNotFoundError(f"论文不存在: {paper_uid}")

    queue_root = config.workspace_path / "queue"
    existing = sorted(queue_root.glob(f"*/{paper_uid}"), reverse=True)
    if existing:
        paper_dir = existing[0]
    else:
        target_date = paper.fetch_date or today_date().isoformat()
        paper_dir = queue_root / target_date / paper_uid
    paper_dir.mkdir(parents=True, exist_ok=True)
    # 已有正文可复用（避免重复解析 PDF），但 prompt 每次都用当前模板重渲染，
    # 保证用户更新提示词（含 PDF 路径）后已入队论文也能拿到最新版。
    cached_text = ""
    cached_text_file = paper_dir / "extracted_text.md"
    if cached_text_file.exists():
        cached_text = cached_text_file.read_text(encoding="utf-8", errors="replace")

    # 定位本地 PDF
    pdf_path = None
    if pdf_bytes is not None:
        pdf_path = paper_dir / f"{paper_uid}.pdf"
        pdf_path.write_bytes(pdf_bytes)
    else:
        candidates = []
        if getattr(paper, "pdf_local_path", ""):
            candidates.append(Path(paper.pdf_local_path))
        candidates.append(config.workspace_path / "tmp" / "pdfs" / f"{paper_uid}.pdf")
        for c in candidates:
            if c.exists():
                pdf_path = c
                break

    # 把 PDF 复制进任务包，供下游 agent 直接读取（这是"上传 PDF 给下游 AI"的落点）
    package_pdf: Path | None = None
    if pdf_path is not None:
        package_pdf = paper_dir / f"{paper_uid}.pdf"
        try:
            if Path(pdf_path).resolve() != package_pdf.resolve():
                shutil_copy = __import__("shutil").copyfile
                shutil_copy(str(pdf_path), str(package_pdf))
        except Exception:
            package_pdf = Path(pdf_path) if Path(pdf_path).exists() else None

    # 抽取正文（PDF 存在则从 PDF 抽；否则优先复用缓存，再用摘要兜底）
    if pdf_path is not None:
        text = extract_clean_text(pdf_path)
    else:
        text = cached_text or paper.abstract or ""
    atomic_write_text(paper_dir / "extracted_text.md", text)

    # 用 PromptManager 按方向路由模板渲染 prompt
    pm = PromptManager()
    from ..utils.figure_links import build_figures_markdown
    assets_dir = config.workspace_path / "staging" / "assets" / paper_uid
    figs = sorted(assets_dir.glob("*.webp"))[:2] if assets_dir.exists() else []
    figures_markdown = build_figures_markdown(
        [f.name for f in figs], paper_uid, empty="（未抽取到架构图）",
    )
    context = {
        "paper_uid": paper.paper_uid, "title": paper.title,
        "venue": paper.venue, "year": paper.pub_year,
        "pub_date": paper.pub_date or "", "tier": paper.tier,
        "authors": ", ".join(json.loads(paper.authors_json or "[]")),
        "abstract": paper.abstract, "code_url": paper.code_url or "",
        "paper_url": paper.paper_url, "figures_markdown": figures_markdown,
        "bibtex": to_bibtex(paper), "content": text,
        "pdf_path": str(package_pdf.resolve()) if package_pdf and package_pdf.exists()
                    else (str(Path(pdf_path).resolve()) if pdf_path else "（未找到本地 PDF）"),
    }
    _, prompt = pm.render_for_paper(paper, context)
    atomic_write_text(paper_dir / "prompt.md", prompt)

    # 如果传了 PDF 字节，同时落到 tmp/pdfs 供后续清理器管理
    if pdf_bytes is not None:
        tmp_pdf = config.workspace_path / "tmp" / "pdfs" / f"{paper_uid}.pdf"
        tmp_pdf.parent.mkdir(parents=True, exist_ok=True)
        tmp_pdf.write_bytes(pdf_bytes)
        repo.update_fields(paper_uid, pdf_local_path=str(tmp_pdf), pdf_deleted=0)

    return paper_dir


class BaseAnalyzer(abc.ABC):
    """解析器抽象基类；子类只需实现 generate()。"""

    backend: str = "base"

    def __init__(self, config: AppConfig, repo: PaperRepository):
        self.config = config
        self.repo = repo

    @abc.abstractmethod
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
        """返回 (raw_markdown, model_name)。"""

    def health_check(self, probe: bool = False) -> dict[str, Any]:
        """连通性自检，默认返回未实现。"""
        return {"ok": False, "backend": self.backend, "message": "health_check 未实现"}

    def build_prompt(self, paper_uid: str, previous_errors: list[str] | None = None) -> str:
        """读取 queue 下的 prompt.md + extracted_text.md，拼接加固指令并智能截断。

        若任务包不存在但本地已有 PDF（DOWNLOADED 状态），会自动即时补齐，
        使"本地已下载论文"无需先 export-queue 也能直接解析。
        """
        cfg = self.config
        ensure_analysis_package(cfg, self.repo, paper_uid)
        queue_root = cfg.workspace_path / "queue"
        candidates = sorted(queue_root.glob(f"*/{paper_uid}"), reverse=True)
        if not candidates:
            raise FileNotFoundError(f"未找到论文任务包: {paper_uid}")
        paper_dir = candidates[0]
        prompt_file = paper_dir / "prompt.md"
        text_file = paper_dir / "extracted_text.md"
        prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
        body = text_file.read_text(encoding="utf-8") if text_file.exists() else ""

        # 关键：提示词本体（13 节要求 + 风格约束）必须完整送达下游 AI，
        # 绝不参与截断；只有论文正文按剩余预算截断。
        body_budget = max(1000, cfg.analyzer.max_input_chars - len(prompt_text))
        body = smart_truncate(body, body_budget)
        combined = f"{prompt_text}\n\n---\n\n{body}"

        suffix = (
            "\n\n---\n"
            "【系统输出约束】请直接输出最终完整的 Markdown 文档内容，"
            "必须以 `---`（YAML Frontmatter）开头；不要输出任何开场白、解释性废话，"
            "也不要用外层 ```markdown 代码块包裹整个文档。\n"
        )
        if previous_errors:
            err_text = "；".join(previous_errors)
            suffix += (
                f"\n【上次输出未通过格式校验，错误原因如下】{err_text}\n"
                "请针对性地修复后重新输出完整 Markdown。\n"
            )
        return combined + suffix
