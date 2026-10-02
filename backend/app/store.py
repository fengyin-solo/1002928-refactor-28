"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
统计口径不在这一层：今日新增、待处理、异常量的算法统一在 app.services.metrics，
这里只负责存取明细、汇总结果与历史看板快照。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._summary: dict[str, Any] | None = None
        self._snapshots: list[dict[str, Any]] = []
        self._processed_batches: set[str] = set()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def tables(self) -> dict[str, list[dict[str, Any]]]:
        return self._tables

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def summary(self) -> dict[str, Any] | None:
        return self._summary

    def save_summary(self, summary: dict[str, Any]) -> None:
        """汇总结果整体替换，不做累加，重复重算不会把台数叠成两份。"""
        self._summary = summary

    def snapshots(self) -> list[dict[str, Any]]:
        return list(self._snapshots)

    def append_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshots.append(snapshot)

    def processed_batches(self) -> set[str]:
        return set(self._processed_batches)

    def mark_batch_processed(self, batch_id: str) -> None:
        self._processed_batches.add(batch_id)


store = Store()
