"""运营概览统计口径：今日新增、待处理、异常量只有这一份实现。

首页卡片、模块明细页、汇总重算都从这里取数；口径要调整时只改这个文件，
并把 METRICS_VERSION 加一。历史看板快照按当时那一版口径保留，互不影响。
"""
from __future__ import annotations

from datetime import date
from typing import Any

# v1 旧口径：今日新增按模块总量计；v2 当前口径：今日新增只计当日创建的记录。
LEGACY_METRICS_VERSION = 1
METRICS_VERSION = 2

CREATED_AT_FIELD = "created_at"

# 首页卡片字段名固定，调整口径时不得改名。
CARD_LABELS = ("业务模块", "今日新增", "待处理", "异常量")


def stamp_created(entry: dict[str, Any], today: date | None = None) -> None:
    """给新记录打上创建日期；「今日新增」只认这个字段。"""
    entry[CREATED_AT_FIELD] = (today or date.today()).isoformat()


def is_created_today(row: dict[str, Any], today: date) -> bool:
    return str(row.get(CREATED_AT_FIELD) or "") == today.isoformat()


def is_pending(row: dict[str, Any]) -> bool:
    return bool(row.get("pending"))


def is_abnormal(row: dict[str, Any]) -> bool:
    return bool(row.get("abnormal"))


def compute_module_metrics(
    name: str,
    rows: list[dict[str, Any]],
    today: date | None = None,
) -> dict[str, Any]:
    """单个模块的三项指标：今日新增、待处理、异常量。"""
    day = today or date.today()
    return {
        "name": name,
        "created": sum(1 for row in rows if is_created_today(row, day)),
        "pending": sum(1 for row in rows if is_pending(row)),
        "abnormal": sum(1 for row in rows if is_abnormal(row)),
    }


def compute_module_metrics_legacy(
    name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """v1 旧口径：今日新增按模块总量计。只为留档历史看板保留，新代码不要调用。"""
    return {
        "name": name,
        "created": len(rows),
        "pending": sum(1 for row in rows if is_pending(row)),
        "abnormal": sum(1 for row in rows if is_abnormal(row)),
    }


def build_cards(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """首页卡片：由各模块汇总行向上加总，字段名保持 业务模块/今日新增/待处理/异常量。"""
    return [
        {"label": CARD_LABELS[0], "value": len(modules)},
        {"label": CARD_LABELS[1], "value": sum(int(item["created"]) for item in modules)},
        {"label": CARD_LABELS[2], "value": sum(int(item["pending"]) for item in modules)},
        {"label": CARD_LABELS[3], "value": sum(int(item["abnormal"]) for item in modules)},
    ]


def compute_overview(
    tables: dict[str, list[dict[str, Any]]],
    today: date | None = None,
) -> dict[str, Any]:
    """各模块明细按同一套口径往上汇，得到首页卡片与汇总表。"""
    day = today or date.today()
    modules = [
        compute_module_metrics(name, tables.get(name, []), day)
        for name in sorted(tables)
    ]
    return {"cards": build_cards(modules), "modules": modules}
