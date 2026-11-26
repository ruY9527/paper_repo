"""Phase 12 模块 B：Prompt 模板管理与安全渲染引擎。

- 渲染用正则仅替换白名单 {{var}}，严禁 str.format（防 LaTeX/JSON 花括号报错）。
- select_template 按 topic_tags -> keywords -> tier 兜底路由。
- 修改保存前备份到 workspace/backups/prompts/。
"""

from __future__ import annotations

import json
import re
import shutil
from ..utils.timeutil import now_dt
from pathlib import Path
from typing import Any

from ..config import AppConfig, PROJECT_ROOT
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from .builtin_templates import _BUILTIN_META, _BUILTIN_TEMPLATES

logger = get_logger()

PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"
META_FILE = PROMPTS_DIR / "templates_meta.json"

# 白名单变量（渲染时只替换这些 {{var}}）
ALLOWED_VARS = {
    "paper_uid", "title", "venue", "year", "pub_date", "tier",
    "authors", "abstract", "code_url", "paper_url", "figures_markdown",
    "bibtex", "content", "date", "pdf_path",
}
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def render_prompt(template_text: str, context: dict[str, Any]) -> str:
    """仅替换白名单 {{var}}，其余花括号原样保留。"""

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in ALLOWED_VARS:
            return str(context.get(key, ""))
        return match.group(0)  # 非白名单变量原样保留

    return _VAR_RE.sub(repl, template_text)


class PromptManager:
    """Prompt 模板管理器。"""

    def __init__(self, prompts_dir: str | Path | None = None):
        self.dir = Path(prompts_dir) if prompts_dir else PROMPTS_DIR
        self.meta_file = self.dir / "templates_meta.json"
        self.backups_dir = PROJECT_ROOT / "workspace" / "backups" / "prompts"

    # ---- 初始化与元数据 ----

    def ensure_builtin_templates(self) -> bool:
        """若 config/prompts/ 不存在则释放内置模板。返回是否新建。"""
        if self.dir.exists() and self.meta_file.exists():
            return False
        self.dir.mkdir(parents=True, exist_ok=True)
        for tid, content in _BUILTIN_TEMPLATES.items():
            (self.dir / f"{tid}.md").write_text(content, encoding="utf-8")
        self.meta_file.write_text(
            json.dumps(_BUILTIN_META, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True

    def load_meta(self) -> list[dict[str, Any]]:
        self.ensure_builtin_templates()
        return json.loads(self.meta_file.read_text(encoding="utf-8"))

    def save_meta(self, meta: list[dict[str, Any]]) -> None:
        self.meta_file.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_templates(self) -> list[dict[str, Any]]:
        meta = self.load_meta()
        for item in meta:
            item["file_path"] = str(self.dir / item["file"])
            item["file_exists"] = (self.dir / item["file"]).exists()
        return meta

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        for item in self.load_meta():
            if item["id"] == template_id:
                body = (self.dir / item["file"]).read_text(encoding="utf-8")
                return {**item, "body": body}
        return None

    # ---- 路由 ----

    def select_template(self, paper, override_id: str | None = None) -> tuple[str, str]:
        """返回 (template_id, template_body)。"""
        if override_id:
            t = self.get_template(override_id)
            if t:
                return override_id, t["body"]
        meta = self.load_meta()
        tier = getattr(paper, "tier", "S")
        # Phase 17：S 级统一使用用户指定的深度分析提示词（含本地 PDF 路径），
        # 不再被方向专属模板覆盖，保证"提示词 + PDF 一起送给下游 AI"。
        if tier == "S":
            t = self.get_template("tier_s_default")
            if t:
                return "tier_s_default", (t["body"] if "body" in t else "")
        # 1) topic_tags 命中
        tags = []
        try:
            tags = json.loads(getattr(paper, "topic_tags_json", "[]") or "[]")
        except json.JSONDecodeError:
            tags = []
        candidates = []
        for item in meta:
            if item.get("tier", "ALL") not in ("ALL", tier):
                continue
            match_topics = item.get("match_topics", [])
            if any(t in match_topics for t in tags):
                candidates.append(item)
        # 2) keywords 命中
        if not candidates:
            text = f"{getattr(paper, 'title', '')} {getattr(paper, 'abstract', '')} {getattr(paper, 'matched_tags_json', '')}".lower()
            for item in meta:
                if item.get("tier", "ALL") not in ("ALL", tier):
                    continue
                if any(k.lower() in text for k in item.get("match_keywords", [])):
                    candidates.append(item)
        if candidates:
            best = max(candidates, key=lambda x: x.get("priority", 0))
            return best["id"], (self.dir / best["file"]).read_text(encoding="utf-8")
        # 3) 兜底
        tid = "tier_s_default" if tier == "S" else "tier_a_default"
        t = self.get_template(tid)
        return tid, (t["body"] if t else "")

    def render_for_paper(self, paper, context: dict[str, Any], override_id: str | None = None) -> tuple[str, str]:
        """返回 (template_id, rendered_prompt)。"""
        tid, body = self.select_template(paper, override_id)
        return tid, render_prompt(body, context)

    # ---- 修改与备份 ----

    def _backup(self, template_id: str, body: str) -> Path:
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        ts = now_dt().strftime("%Y%m%d_%H%M%S")
        backup = self.backups_dir / f"{template_id}_{ts}.md"
        backup.write_text(body, encoding="utf-8")
        return backup

    def save_template(self, template_id: str, body: str) -> dict[str, Any]:
        t = self.get_template(template_id)
        if t is None:
            raise FileNotFoundError(f"模板不存在: {template_id}")
        self._backup(template_id, t["body"])
        (self.dir / t["file"]).write_text(body, encoding="utf-8")
        warnings = self._contract_check(body)
        return {"ok": True, "warnings": warnings, "backed_up": True}

    @staticmethod
    def _contract_check(body: str) -> list[str]:
        warnings = []
        if "---" not in body:
            warnings.append("模板缺少 YAML Frontmatter 分隔符 `---`")
        if "paper_uid" not in body:
            warnings.append("模板未要求输出 paper_uid 字段")
        if "tldr" not in body:
            warnings.append("模板未要求输出 tldr 字段")
        return warnings

    def reset_to_default(self, template_id: str) -> dict[str, Any]:
        t = self.get_template(template_id)
        if t is None:
            raise FileNotFoundError(f"模板不存在: {template_id}")
        if not t.get("is_builtin"):
            return {"ok": False, "message": "仅内置模板可恢复默认"}
        self._backup(template_id, t["body"])
        default = _BUILTIN_TEMPLATES.get(template_id)
        if default is None:
            return {"ok": False, "message": f"无内置内容: {template_id}"}
        (self.dir / t["file"]).write_text(default, encoding="utf-8")
        return {"ok": True}

    def delete_template(self, template_id: str) -> dict[str, Any]:
        t = self.get_template(template_id)
        if t is None:
            return {"ok": False, "message": "模板不存在"}
        if t.get("is_builtin"):
            return {"ok": False, "message": "内置模板禁止删除"}
        (self.dir / t["file"]).unlink(missing_ok=True)
        meta = [m for m in self.load_meta() if m["id"] != template_id]
        self.save_meta(meta)
        return {"ok": True}

    def create_template(self, meta: dict[str, Any], body: str) -> dict[str, Any]:
        tid = meta["id"]
        if self.get_template(tid):
            return {"ok": False, "message": "模板 id 已存在"}
        meta.setdefault("is_builtin", False)
        meta.setdefault("priority", 50)
        meta.setdefault("tier", "S")
        meta.setdefault("match_topics", [])
        meta.setdefault("match_keywords", [])
        meta.setdefault("file", f"{tid}.md")
        (self.dir / meta["file"]).write_text(body, encoding="utf-8")
        all_meta = self.load_meta()
        all_meta.append(meta)
        self.save_meta(all_meta)
        return {"ok": True}
