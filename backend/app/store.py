"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

统计相关的能力全部委托给 app.metrics（唯一口径），本模块只负责：
- 持有明细表，并在加载时按当前口径重算存量数据；
- 冻结历史看板快照（v1 旧口径永久保留）；
- 批次汇总的幂等去重：同一 batch_id 重复提交只生效一次。
"""
from __future__ import annotations

import copy
import threading
from datetime import date
from typing import Any

from app import metrics
from app.seed import SEED_ROWS


def _deep_copy(data: dict[str, Any]) -> dict[str, Any]:
    """快照对外只给深拷贝，调用方改不到冻结的历史数字。"""
    return copy.deepcopy(data)


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._lock = threading.RLock()
        # 批次汇总的幂等台账：batch_id -> 已落账结果。
        self._batches: dict[str, dict[str, Any]] = {}
        # 历史看板快照：version -> {"as_of": 日期, "overview": {...}}。
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._bootstrap()

    # ------------------------------------------------------------------ 基础访问
    def module_names(self) -> list[str]:
        return [name for name in metrics.MODULE_ORDER if name in self._tables]

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    # ------------------------------------------------------------------ 口径归一
    def _bootstrap(self) -> None:
        """加载即迁移：先冻结旧口径快照，再按新口径重算全部存量。"""
        with self._lock:
            # v1 快照必须在重算前冻结：此时行上还是 seed 自带的旧标记位。
            self._snapshots[metrics.LEGACY_VERSION] = {
                "version": metrics.LEGACY_VERSION,
                "label": metrics.VERSION_LABELS[metrics.LEGACY_VERSION],
                "as_of": date.today().isoformat(),
                "overview": metrics.legacy_overview_from(self._tables),
            }
            self.recalculate_stock()

    def recalculate_stock(self, *, today: date | None = None) -> dict[str, object]:
        """按当前统一口径把存量明细重算一遍（幂等：反复执行结果不变）。

        - 补齐 created_at（缺失时按业务日期/序号回填）；
        - 用 metrics.classify_row 重新投影 pending/abnormal 标记位；
        - 冻结当前版本快照；历史版本快照原样保留。
        """
        with self._lock:
            for module, rows in self._tables.items():
                spec_ = metrics.spec(module)
                for row in rows:
                    created_at = metrics.created_at_of(row)
                    if created_at:
                        row["created_at"] = created_at
                    metrics.apply_flags(spec_, row, today=today)
            return self._freeze_current(today=today)

    def overview(self, *, today: date | None = None) -> dict[str, object]:
        """当前口径的运营概览：首页卡片与明细共用同一份实现。

        查询只按当前明细现算，不改动已冻结的历史看板快照；
        快照在启动迁移与重算时落定（见 _freeze_current）。
        """
        with self._lock:
            return metrics.overview_from(self._tables, today=today)

    def _freeze_current(self, *, today: date | None = None) -> dict[str, object]:
        """把当前口径与当前存量冻结为该版本的历史看板（重算时刷新一次）。"""
        overview = metrics.overview_from(self._tables, today=today)
        self._snapshots[metrics.METRIC_VERSION] = {
            "version": metrics.METRIC_VERSION,
            "label": metrics.VERSION_LABELS[metrics.METRIC_VERSION],
            "as_of": (today or date.today()).isoformat(),
            "overview": overview,
        }
        return overview

    def module_overview(self, module: str, *, today: date | None = None) -> dict[str, int]:
        """单模块三指标：明细页直接取这里，与首页汇总必然一致。"""
        with self._lock:
            return metrics.module_metrics(module, self.rows(module), today=today)

    # ------------------------------------------------------------------ 历史看板
    def snapshots(self) -> list[dict[str, Any]]:
        """返回全部版本的冻结看板；查询不触发重新冻结。"""
        with self._lock:
            ordered = [metrics.LEGACY_VERSION, metrics.METRIC_VERSION]
            return [_deep_copy(self._snapshots[v]) for v in ordered if v in self._snapshots]

    def snapshot(self, version: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._snapshots.get(version)
            return _deep_copy(data) if data else None

    # ------------------------------------------------------------------ 批次汇总
    def submit_batch(
        self,
        batch_id: str,
        entries: list[dict[str, Any]],
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        """把一批明细提交汇总，按 batch_id 幂等去重。

        - 同一 batch_id 第二次提交：直接回放上一次结果，不重复计数；
        - 指标只按统一口径从明细状态现算，客户端自报的 pending/abnormal/created
          一律不采信，避免重复提交把台数叠成两份；
        - 明细里给了 module+id 且能在表里找到时，以库存明细为准。
        """
        with self._lock:
            cached = self._batches.get(batch_id)
            if cached is not None:
                result = dict(cached)
                result["deduplicated"] = True
                return result

            by_module: dict[str, list[dict[str, Any]]] = {}
            # 同一批里同一条库存明细被列多次时只算一台；台数按物理设备去重。
            seen_keys: set[tuple[str, int]] = set()
            seen_free: set[tuple[str, str | None, str | None]] = set()
            for item in entries or []:
                module = str(item.get("module") or "").strip()
                if not metrics.has_spec(module):
                    continue
                row = None
                entry_id = item.get("id")
                if entry_id is not None:
                    try:
                        numeric_id = int(entry_id)
                    except (TypeError, ValueError):
                        numeric_id = None
                    if numeric_id is not None:
                        key = (module, numeric_id)
                        if key in seen_keys:
                            continue
                        row = self.find(module, numeric_id)
                        if row is not None:
                            seen_keys.add(key)
                if row is None and item.get("status"):
                    status = item.get("status")
                    created_at = item.get("created_at")
                    free_key = (module, status, created_at)
                    if free_key in seen_free:
                        continue
                    seen_free.add(free_key)
                    row = {"status": status, "created_at": created_at}
                if row is not None:
                    by_module.setdefault(module, []).append(row)

            modules: list[dict[str, Any]] = []
            for module in metrics.MODULE_ORDER:
                rows = by_module.get(module)
                if not rows:
                    continue
                modules.append({
                    "name": module,
                    **metrics.module_metrics(module, rows, today=today),
                    "units": len(rows),
                })
            totals = {
                key: sum(int(item[key]) for item in modules)
                for key in ("created", "pending", "abnormal", "units")
            }
            result = {
                "batch_id": batch_id,
                "version": metrics.METRIC_VERSION,
                "as_of": (today or date.today()).isoformat(),
                "deduplicated": False,
                "modules": modules,
                "totals": totals,
            }
            self._batches[batch_id] = {k: v for k, v in result.items() if k != "deduplicated"}
            return result


store = Store()
