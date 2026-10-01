"""业务服务共享实现：状态流转、字段校验、筛选与指标全部只在这里实现一遍。

各模块服务只声明自己用哪一份 MetricSpec（见 app.metrics），
今日新增/待处理/异常量的判定一律走统一口径，明细与首页必然同数。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app import metrics
from app.store import store


class ModuleService:
    """所有业务模块共用的服务基类。"""

    def __init__(self, module: str) -> None:
        self.module = module
        self.spec = metrics.spec(module)

    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(self.module)
        if keyword:
            field_name = self.spec.keyword_field
            rows = [row for row in rows if keyword in str(row.get(field_name, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(self.module, entry_id)

    def metrics(self) -> dict[str, int]:
        """明细页卡片的数据源，与首页 overview 同源同口径。"""
        return store.module_overview(self.module)

    # ------------------------------------------------------------------ 写入
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in self.spec.required_fields
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        entry: dict[str, Any] = {"id": store.next_id(self.module)}
        entry.update({field: values.get(field) for field in self.spec.required_fields})
        entry["status"] = self.spec.status_order[0]
        entry["created_at"] = date.today().isoformat()  # 新建一律计为今日新增
        # 标记位由统一口径投影，不再手工硬编码 True/False。
        metrics.apply_flags(self.spec, entry)
        store.rows(self.module).append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.module, entry_id)
        entity = self.spec.entity
        if entry is None:
            return None, f"{entity} {entry_id} 不存在或已归档"
        if action not in self.spec.action_rules:
            return None, f"动作「{action}」不属于{self.spec.label}可执行范围"
        target = self.spec.action_rules[action]
        if target not in self.spec.status_order:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        # 唯一口径：状态一变，待处理/异常位统一重算，不各写一份。
        metrics.apply_flags(self.spec, entry)
        return entry, f"{entity}已{action}"
