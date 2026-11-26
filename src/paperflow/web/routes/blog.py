"""博客文章视图 REST API（Phase 16）：以博客仓库文件为主的发布记录查看。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from ..state import get_manager
from ..task_manager import TaskManager

router = APIRouter(prefix="/api/blog", tags=["blog"])


@router.get("/articles")
def blog_articles(q: str | None = None, limit: int = 20, offset: int = 0,
                  manager: TaskManager = Depends(get_manager)):
    from ...publisher.blog_articles import list_blog_articles
    return list_blog_articles(manager.config, manager.repo, q=q, limit=limit, offset=offset)


@router.get("/articles/{paper_uid}/content")
def blog_article_content(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    from ...publisher.blog_articles import list_blog_articles, read_blog_article
    # 按 paper_uid 找到仓库内相对路径
    data = list_blog_articles(manager.config, manager.repo)
    hit = next((x for x in data["items"] if x["paper_uid"] == paper_uid), None)
    if hit is None:
        raise HTTPException(status_code=404, detail="该论文尚未发布到博客")
    content = read_blog_article(manager.config, hit["path"])
    if content is None:
        raise HTTPException(status_code=404, detail="博客文章文件不存在")
    return {"paper_uid": paper_uid, "path": hit["path"], "content": content}


@router.get("/article-by-path")
def blog_article_by_path(path: str, manager: TaskManager = Depends(get_manager)):
    from ...publisher.blog_articles import read_blog_article
    content = read_blog_article(manager.config, path)
    if content is None:
        raise HTTPException(status_code=404, detail="博客文章不存在或路径越界")
    return PlainTextResponse(content)
