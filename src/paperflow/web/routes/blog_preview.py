"""Phase 12：构建门禁与本地预览 REST API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...publisher.mkdocs_service import MkDocsService
from ..state import get_manager
from ..task_manager import TaskManager

router = APIRouter(prefix="/api/blog", tags=["blog"])


def _service(request: Request) -> MkDocsService:
    return request.app.state.mkdocs_service


@router.post("/build-check")
def build_check(request: Request):
    svc = _service(request)
    result = svc.build_strict()
    return result.model_dump()


@router.get("/preview/status")
def preview_status(request: Request):
    return _service(request).get_preview_status()


@router.post("/preview/start")
def preview_start(request: Request):
    return _service(request).start_preview()


@router.post("/preview/stop")
def preview_stop(request: Request):
    return _service(request).stop_preview()
