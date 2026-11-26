"""FastAPI 应用入口：路由注册、静态文件挂载、依赖注入与首页。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import AppConfig, load_config
from ..db.repository import PaperRepository
from ..publisher.mkdocs_service import MkDocsService
from .state import get_manager
from .task_manager import TaskManager

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: AppConfig | None = None, repo: PaperRepository | None = None) -> FastAPI:
    """创建应用；可注入 config/repo 便于测试隔离。"""
    from ..utils.http_env import sanitize_no_proxy
    sanitize_no_proxy()  # 进程级清理畸形 NO_PROXY，避免任何 httpx 调用踩坑
    cfg = config or load_config()
    repository = repo or PaperRepository(cfg.db_path)
    # 启动时把遗留的 RUNNING 审计标记为 INTERRUPTED（进程重启/崩溃断点）
    try:
        repository.mark_interrupted_runs()
    except Exception:
        pass
    manager = TaskManager(cfg, repository)
    # Phase 12：MkDocs 预览服务，关闭钩子自动终止子进程
    mkdocs_service = MkDocsService(
        cfg.paper_repo_path, cfg.workspace_path, cfg.publish.preview_port
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        # 关闭时终止 mkdocs serve 预览进程，防止僵尸进程占用端口
        mkdocs_service.stop_preview()

    app = FastAPI(title="PaperFlow Studio", version="1.0.0",
                  docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.state.manager = manager
    manager.app = app
    app.state.config = cfg
    app.state.mkdocs_service = mkdocs_service

    # 依赖覆盖：所有路由的 get_manager 指向本 app 的 manager（支持多实例隔离）
    app.dependency_overrides[get_manager] = lambda: manager

    from .routes import analyzer, blog, blog_preview, dashboard, git_ops, papers, paywall, prompts, settings, sites, staging, system, tasks, topics
    app.include_router(dashboard.router)
    app.include_router(tasks.router)
    app.include_router(papers.router)
    app.include_router(staging.router)
    app.include_router(settings.router)
    app.include_router(git_ops.router)  # Phase 9：Git 发布中心
    app.include_router(topics.router)   # Phase 10：方向精准检索
    app.include_router(analyzer.router) # Phase 11：AI 解析中心
    app.include_router(blog_preview.router)  # Phase 12：构建门禁与预览
    app.include_router(prompts.router)       # Phase 12：Prompt 工作室
    app.include_router(paywall.router)       # Phase 13：受限论文清单
    app.include_router(sites.router)         # Phase 14：网站收录中心
    app.include_router(blog.router)          # Phase 16：博客文章视图
    app.include_router(system.router)        # 系统元信息：代码指纹/旧进程检测

    @app.middleware("http")
    async def no_cache_local(request, call_next):
        """本地控制台禁用浏览器缓存，避免代码更新后仍加载旧 JS/HTML。"""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        index_file = STATIC_DIR / "index.html"
        if not index_file.exists():
            return JSONResponse({"error": "前端页面缺失"}, status_code=500)
        return FileResponse(str(index_file), headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


# 默认 app（uvicorn paperflow.web.app:app）
app = create_app()
