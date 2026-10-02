"""运营概览接口：首页汇总、模块明细指标、口径重算与历史看板。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas import ActionResult
from app.services.overview import OverviewService

router = APIRouter(prefix="/api/overview", tags=["运营概览"])

service = OverviewService()


class RecomputePayload(BaseModel):
    """触发一次汇总重算；batch_id 相同的重复提交会被去重，不会重复计数。"""

    batch_id: str | None = None


@router.get("")
def get_overview() -> dict[str, Any]:
    """首页卡片与汇总表：与模块明细同一套口径，两边给出同一个数。"""
    return service.current_overview()


@router.get("/modules/{module}")
def get_module_metrics(module: str) -> dict[str, Any]:
    """单个模块的今日新增、待处理、异常量，与首页汇总表里的同一行是同一个数。"""
    result = service.module_metrics(module)
    if result is None:
        raise HTTPException(status_code=404, detail=f"业务模块 {module} 不存在")
    return result


@router.post("/recompute", response_model=ActionResult)
def recompute(payload: RecomputePayload | None = None) -> ActionResult:
    """按当前口径把存量明细重算一遍；取数失败可安全重试，同一批次重复提交不重复计数。"""
    batch_id = payload.batch_id if payload else None
    summary, duplicated = service.recompute(batch_id=batch_id)
    if duplicated:
        return ActionResult(ok=True, message="该批次已汇总过，台数未重复计算", entry=summary)
    return ActionResult(ok=True, message=f"已按口径 v{summary['version']} 重算汇总", entry=summary)


@router.get("/snapshots")
def list_snapshots() -> dict[str, Any]:
    """历史看板：每次重算留一档，各档按当时那一版口径保留。"""
    items = service.snapshots()
    return {"items": items, "total": len(items), "page": 1, "size": len(items)}
