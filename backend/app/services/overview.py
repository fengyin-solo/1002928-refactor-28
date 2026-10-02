"""运营概览汇总：明细按统一口径往上汇，重算幂等，历史看板按版本留档。

首页与明细页都走 current_overview / module_metrics，两个入口调的是
metrics 里的同一个函数，所以两边必然给出同一个数。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services import metrics
from app.store import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OverviewService:
    def current_overview(self) -> dict[str, Any]:
        """首页取数：对当前明细实时套用统一口径。"""
        self._ensure_initialized()
        return metrics.compute_overview(store.tables())

    def module_metrics(self, module: str) -> dict[str, Any] | None:
        """明细页取数：与首页同一个函数，只是只取一个模块；模块不存在时返回 None。"""
        self._ensure_initialized()
        if module not in store.module_names():
            return None
        return metrics.compute_module_metrics(module, store.rows(module))

    def recompute(self, batch_id: str | None = None) -> tuple[dict[str, Any], bool]:
        """按当前口径把存量明细重算一遍，整体替换汇总结果。

        返回 (汇总结果, 是否重复提交)。重算是整体替换而不是累加，失败后可以
        安全重试；带相同 batch_id 的重复提交直接返回已落库的汇总，不会把
        台数叠成两份。
        """
        self._ensure_initialized()
        if batch_id and batch_id in store.processed_batches():
            summary = store.summary()
            assert summary is not None  # 初始化后必有汇总
            return summary, True
        return self._recompute_once(batch_id), False

    def snapshots(self) -> list[dict[str, Any]]:
        """历史看板：每次重算留一档，各档按当时那一版口径保留。"""
        self._ensure_initialized()
        return store.snapshots()

    def _ensure_initialized(self) -> None:
        """首次访问：先按旧口径给存量数据留一档历史看板，再按当前口径重算存量。"""
        if store.summary() is not None:
            return
        legacy_modules = [
            metrics.compute_module_metrics_legacy(name, store.rows(name))
            for name in store.module_names()
        ]
        store.append_snapshot({
            "version": metrics.LEGACY_METRICS_VERSION,
            "generated_at": _now(),
            "batch_id": None,
            "cards": metrics.build_cards(legacy_modules),
            "modules": legacy_modules,
        })
        self._recompute_once(batch_id=None)

    def _recompute_once(self, batch_id: str | None) -> dict[str, Any]:
        overview = metrics.compute_overview(store.tables())
        summary: dict[str, Any] = {
            "version": metrics.METRICS_VERSION,
            "generated_at": _now(),
            **overview,
        }
        store.save_summary(summary)
        store.append_snapshot({**summary, "batch_id": batch_id})
        if batch_id:
            store.mark_batch_processed(batch_id)
        return summary
