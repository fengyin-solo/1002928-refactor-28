"""业务模块路由的共享实现。

20 个模块的接口形态完全一致（列表、单条、登记、动作、导出、指标），
这里只实现一遍；各模块路由文件只声明模块名，不再复制粘贴一套接口。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import metrics
from app.schemas import ActionResult, EntryPayload, ModuleMetrics, PageResult
from app.services.base import ModuleService


def build_module_router(module: str, service: ModuleService) -> APIRouter:
    spec_ = metrics.spec(module)
    label = spec_.label
    entity = spec_.entity
    status_desc = "、".join(spec_.status_order)
    router = APIRouter(prefix=f"/api/{module}", tags=[label])

    @router.get("", response_model=PageResult[dict])
    def list_entries(
        keyword: str | None = Query(default=None, description=f"按{spec_.keyword_field}检索"),
        status: str | None = Query(default=None, description=status_desc),
        page: int = 1,
        size: int = 20,
    ) -> PageResult[dict]:
        """按编号与状态过滤列表；没有数据时返回空页，不报错。"""
        if size > 200:
            raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
        items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
        return PageResult(items=items, total=total, page=page, size=size)

    @router.get("/metrics", response_model=ModuleMetrics)
    def module_metrics() -> ModuleMetrics:
        """单模块今日新增/待处理/异常量，与首页概览同源，保证两边同数。"""
        values = service.metrics()
        return ModuleMetrics(
            module=module,
            label=label,
            version=metrics.METRIC_VERSION,
            created=values["created"],
            pending=values["pending"],
            abnormal=values["abnormal"],
        )

    @router.get("/export")
    def export_entries() -> dict[str, Any]:
        """导出当前模块清单：返回全量数据。"""
        items, total = service.list_entries(page=1, size=10000)
        return {"module": module, "total": total, "items": items}

    @router.get("/{entry_id}", response_model=dict)
    def get_entry(entry_id: int) -> dict:
        """读取单条明细；不存在时给出可读的错误说明。"""
        entry = service.get_entry(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"{entity} {entry_id} 不存在或已归档")
        return entry

    @router.post("", response_model=ActionResult)
    def create_entry(payload: EntryPayload) -> ActionResult:
        """登记一条记录，缺字段时说明原因而不是静默丢弃。"""
        entry, missing = service.create_entry(payload.values)
        if missing:
            return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
        return ActionResult(ok=True, message=f"{entity}已登记", entry=entry)

    @router.post("/{entry_id}/actions", response_model=ActionResult)
    def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
        """对单条记录执行状态流转；不允许的动作会被拦下并说明原因。"""
        action = str(payload.values.get("action") or "").strip()
        entry, message = service.run_action(entry_id, action)
        if entry is None:
            return ActionResult(ok=False, message=message)
        return ActionResult(ok=True, message=message, entry=entry)

    return router
