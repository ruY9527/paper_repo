"""Phase 12：Prompt 模板工作室 REST API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from ...pipeline.prompt_manager import PromptManager
from ..state import get_manager
from ..task_manager import TaskManager

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _pm() -> PromptManager:
    return PromptManager()


@router.get("")
def list_prompts():
    pm = _pm()
    return {"items": pm.list_templates()}


@router.get("/{template_id}")
def get_prompt(template_id: str):
    pm = _pm()
    t = pm.get_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return t


@router.post("")
def create_prompt(body: dict[str, Any] = Body(...)):
    pm = _pm()
    meta = {k: v for k, v in body.items() if k != "body"}
    if "id" not in meta or not meta["id"]:
        raise HTTPException(status_code=422, detail="缺少 id")
    result = pm.create_template(meta, body.get("body", ""))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "创建失败"))
    return result


@router.put("/{template_id}")
def update_prompt(template_id: str, body: dict[str, Any] = Body(...)):
    pm = _pm()
    content = body.get("body", "")
    try:
        result = pm.save_template(template_id, content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="模板不存在")
    return result


@router.post("/{template_id}/reset")
def reset_prompt(template_id: str):
    pm = _pm()
    try:
        result = pm.reset_to_default(template_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "恢复失败"))
    return result


@router.delete("/{template_id}")
def delete_prompt(template_id: str):
    pm = _pm()
    result = pm.delete_template(template_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "删除失败"))
    return result


@router.post("/{template_id}/preview")
def preview_prompt(template_id: str, body: dict[str, Any] = Body(...),
                   manager: TaskManager = Depends(get_manager)):
    """用真实论文数据试渲染，返回最终 Prompt 与预估字符数。"""
    paper_uid = body.get("paper_uid", "")
    paper = manager.repo.get_paper(paper_uid) if paper_uid else None
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    pm = _pm()
    t = pm.get_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")

    import json
    from ...utils.bibtex import to_bibtex

    # 取正文（优先队列 extracted_text）
    content = paper.abstract
    queue_dir = sorted((manager.config.workspace_path / "queue").glob(f"*/{paper_uid}"), reverse=True)
    if queue_dir:
        text_file = queue_dir[0] / "extracted_text.md"
        if text_file.exists():
            content = text_file.read_text(encoding="utf-8", errors="replace")

    context = {
        "paper_uid": paper.paper_uid, "title": paper.title,
        "venue": paper.venue, "year": paper.pub_year,
        "pub_date": paper.pub_date or "", "tier": paper.tier,
        "authors": ", ".join(json.loads(paper.authors_json or "[]")),
        "abstract": paper.abstract, "code_url": paper.code_url or "",
        "paper_url": paper.paper_url, "figures_markdown": "（未抽取到架构图）",
        "bibtex": to_bibtex(paper), "content": content,
    }
    from ...pipeline.prompt_manager import render_prompt
    rendered = render_prompt(t["body"], context)
    return {"template_id": template_id, "prompt": rendered, "chars": len(rendered)}
