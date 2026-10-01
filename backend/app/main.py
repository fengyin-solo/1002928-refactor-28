"""特种设备安全管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import metrics
from app.config import settings
from app.routers import ROUTERS
from app.schemas import BatchResult, BatchSubmit, SnapshotResult
from app.store import store

app = FastAPI(title="特种设备安全管理平台", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：首页卡片与汇总表。

    全部数字由 app.metrics 统一口径从各模块明细向上汇总，
    明细页 /api/<module>/metrics 取的是同一套实现，两边必然相等。
    字段名（cards/modules、created/pending/abnormal）保持不动。
    """
    overview = store.overview()
    return {"version": metrics.METRIC_VERSION, **overview}


@app.get("/api/overview/snapshots")
def list_snapshots() -> dict[str, object]:
    """历史看板版本列表：每个版本保留当时那一版口径的数字。"""
    return {"current": metrics.METRIC_VERSION, "snapshots": store.snapshots()}


@app.get("/api/overview/snapshots/{version}", response_model=SnapshotResult)
def get_snapshot(version: str) -> SnapshotResult:
    """查看某一历史版本的看板；老口径数字冻结不变。"""
    data = store.snapshot(version)
    if data is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"历史看板版本 {version} 不存在")
    return SnapshotResult(**data)


@app.post("/api/batches", response_model=BatchResult)
def submit_batch(payload: BatchSubmit) -> BatchResult:
    """提交一批明细做汇总。

    以 batch_id 为幂等键：网络重试或人工重复提交同一批时只落一次账，
    台数不会叠成两份；指标统一按明细状态现算，不采信客户端自报的计数。
    """
    batch_id = payload.batch_id.strip()
    if not batch_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="batch_id 不能为空")
    return BatchResult(**store.submit_batch(batch_id, [item.model_dump() for item in payload.entries]))


@app.post("/api/admin/recalculate")
def recalculate_stock() -> dict[str, object]:
    """统计口径调整后，按当前算法把存量数据整体重算一遍（幂等）。"""
    return {"version": metrics.METRIC_VERSION, "overview": store.recalculate_stock()}
