"""运营指标的唯一口径来源。

今日新增、待处理、异常量三项指标在这里只实现一遍：
- 首页运营概览（/api/overview）与各模块明细页都调用本模块的函数；
- 存量数据重算（store.recalculate_stock）也走同一套判定；
- 历史看板按冻结快照保留，不随口径变化而改动（见 store.py）。

判定口径（v2，当前版本）：
- 待处理：状态不在该模块「终态集合」里（业务还没闭环）；
- 异常量：状态命中该模块「异常状态集合」；
- 今日新增：created_at 是本机当天日期。

行上仍保留 pending/abnormal 两个布尔位，仅作为统一口径的投影缓存，
任何写入点（状态流转、存量重算）都必须经 classify_row 重新计算，
不再允许各模块各写一遍。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

# 当前统计口径版本。调整口径时升版本号：老版本快照仍可按当时版本查看。
METRIC_VERSION = "v2"
# 历史看板保留的旧版本：v1 直接读行上手工维护的布尔位（即收拢前的口径）。
LEGACY_VERSION = "v1"
VERSION_LABELS = {
    "v1": "初版口径（按行上标记位）",
    "v2": "统一口径（按状态语义判定）",
}


@dataclass(frozen=True)
class MetricSpec:
    """单个业务模块的指标口径。"""

    module: str
    label: str
    keyword_field: str
    entity: str
    required_fields: tuple[str, ...]
    status_order: tuple[str, ...]
    action_rules: dict[str, str]
    # 终态：到达这些状态即视为闭环，不再计入待处理。
    terminal_statuses: frozenset[str]
    # 异常状态：命中这些状态计入异常量。
    abnormal_statuses: frozenset[str]

    def is_pending(self, status: str | None) -> bool:
        return bool(status) and status not in self.terminal_statuses

    def is_abnormal(self, status: str | None) -> bool:
        return status in self.abnormal_statuses


def _spec(
    module: str,
    label: str,
    keyword_field: str,
    entity: str,
    required: tuple[str, ...],
    order: tuple[str, ...],
    rules: dict[str, str],
    terminal: Iterable[str],
    abnormal: Iterable[str],
) -> MetricSpec:
    return MetricSpec(
        module=module,
        label=label,
        keyword_field=keyword_field,
        entity=entity,
        required_fields=required,
        status_order=order,
        action_rules=dict(rules),
        terminal_statuses=frozenset(terminal),
        abnormal_statuses=frozenset(abnormal),
    )


# 20 个业务模块的统一登记表。状态序列、动作映射与旧版各服务保持一致，
# 终态/异常集合按状态语义显式声明，作为唯一判定依据。
MODULE_SPECS: dict[str, MetricSpec] = {
    s.module: s
    for s in (
        _spec("register", "使用登记", "设备编号", "设备登记",
              ("设备编号", "设备名称", "设备种类"),
              ("待登记", "已登记", "停用中", "已注销"),
              {"办理登记": "已登记", "申请停用": "停用中", "申请注销": "已注销"},
              terminal=("已注销",), abnormal=("停用中",)),
        _spec("boiler", "锅炉管理", "锅炉编号", "锅炉",
              ("锅炉编号", "锅炉型号", "额定蒸发量"),
              ("正常运行", "低负荷", "检修中", "已停炉"),
              {"降负荷运行": "低负荷", "停炉检修": "检修中", "恢复运行": "正常运行"},
              terminal=("已停炉",), abnormal=("低负荷", "检修中")),
        _spec("pressurevessel", "压力容器", "容器编号", "压力容器",
              ("容器编号", "容器类别", "设计压力"),
              ("正常", "超压运行", "检验中", "已停用"),
              {"降压运行": "超压运行", "安排检验": "检验中", "办理停用": "已停用"},
              terminal=("已停用",), abnormal=("超压运行", "检验中")),
        _spec("pipeline", "压力管道", "管道编号", "压力管道",
              ("管道编号", "管道级别", "设计压力"),
              ("正常", "壁厚减薄", "待检验", "已报废"),
              {"记录减薄": "壁厚减薄", "安排检验": "待检验", "申请报废": "已报废"},
              terminal=("已报废",), abnormal=("壁厚减薄", "待检验")),
        _spec("elevator", "电梯管理", "电梯编号", "电梯",
              ("电梯编号", "电梯类型", "额定载重"),
              ("正常运行", "维保中", "困人", "检修中"),
              {"安排维保": "维保中", "困人救援": "检修中", "故障检修": "正常运行"},
              terminal=("检修中",), abnormal=("维保中", "困人")),
        _spec("crane", "起重机械", "起重机编号", "起重机",
              ("起重机编号", "起重机类型", "额定起重量"),
              ("正常", "超载运行", "检验中", "已停用"),
              {"降载运行": "超载运行", "安排检验": "检验中", "办理停用": "已停用"},
              terminal=("已停用",), abnormal=("超载运行", "检验中")),
        _spec("forklift", "场车管理", "车辆编号", "场内车辆",
              ("车辆编号", "车辆类型", "动力类型"),
              ("正常", "维修中", "待年检", "已报废"),
              {"安排维修": "维修中", "安排年检": "待年检", "申请报废": "已报废"},
              terminal=("已报废",), abnormal=("维修中", "待年检")),
        _spec("inspection", "定期检验", "检验编号", "检验任务",
              ("检验编号", "被检设备", "检验类别"),
              ("待检验", "检验中", "合格", "不合格"),
              {"安排检验": "检验中", "录入结论": "合格", "下达整改": "不合格"},
              terminal=("合格", "不合格"), abnormal=("检验中",)),
        _spec("maintenance", "维保记录", "维保编号", "维保记录",
              ("维保编号", "维保设备", "维保单位"),
              ("待维保", "维保中", "已完成", "需返工"),
              {"安排维保": "维保中", "开始维保": "已完成", "返工登记": "需返工"},
              terminal=("已完成",), abnormal=("需返工",)),
        _spec("hazard", "隐患排查", "隐患编号", "隐患记录",
              ("隐患编号", "所在设备", "隐患类别"),
              ("待整改", "整改中", "待验收", "已消除"),
              {"安排整改": "整改中", "开始整改": "待验收", "验收消除": "已消除"},
              terminal=("已消除",), abnormal=("整改中", "待验收")),
        _spec("accident", "事故管理", "事故编号", "事故记录",
              ("事故编号", "事故设备", "事故类型"),
              ("待上报", "已上报", "调查中", "已结案"),
              {"上报事故": "已上报", "开展调查": "调查中", "结案归档": "已结案"},
              terminal=("已结案",), abnormal=("已上报", "调查中")),
        _spec("operator", "作业人员", "人员编号", "作业人员",
              ("人员编号", "姓名", "证书类别"),
              ("持证有效", "即将到期", "已过期", "已注销"),
              {"安排复审": "持证有效", "登记过期": "已过期", "注销证书": "已注销"},
              terminal=("已注销",), abnormal=("即将到期", "已过期")),
        _spec("training", "培训考核", "培训编号", "培训记录",
              ("培训编号", "培训内容", "培训对象"),
              ("待培训", "培训中", "已考核", "已归档"),
              {"组织培训": "培训中", "组织考核": "已考核", "归档": "已归档"},
              terminal=("已归档",), abnormal=("培训中",)),
        _spec("safetyvalve", "安全阀校验", "安全阀编号", "安全阀",
              ("安全阀编号", "所属设备", "公称通径"),
              ("校验合格", "即将到期", "待校验", "已报废"),
              {"安排校验": "待校验", "登记合格": "校验合格", "申请报废": "已报废"},
              terminal=("已报废",), abnormal=("即将到期", "待校验")),
        _spec("gauge", "压力表检定", "压力表编号", "压力表",
              ("压力表编号", "所属设备", "量程范围"),
              ("检定合格", "即将到期", "待检定", "已停用"),
              {"安排检定": "待检定", "登记合格": "检定合格", "办理停用": "已停用"},
              terminal=("已停用",), abnormal=("即将到期", "待检定")),
        _spec("sparepart", "备件管理", "备件编号", "备件",
              ("备件编号", "备件名称", "规格型号"),
              ("充足", "不足", "待采购", "已停用"),
              {"办理领用": "不足", "采购入仓": "充足", "停用备件": "已停用"},
              terminal=("已停用",), abnormal=("不足", "待采购")),
        _spec("emergency", "应急演练", "演练编号", "演练记录",
              ("演练编号", "演练主题", "演练类型"),
              ("待组织", "已组织", "已完成", "已复盘"),
              {"组织演练": "已组织", "完成演练": "已完成", "复盘总结": "已复盘"},
              terminal=("已复盘",), abnormal=("已组织",)),
        _spec("energyeff", "能效监测", "记录编号", "能效记录",
              ("记录编号", "设备类型", "耗能量"),
              ("达标", "轻微偏差", "显著偏差", "已调整"),
              {"记录偏差": "轻微偏差", "分析原因": "显著偏差", "调整优化": "已调整"},
              terminal=("已调整",), abnormal=("轻微偏差", "显著偏差")),
        _spec("archive", "档案管理", "档案编号", "设备档案",
              ("档案编号", "所属设备", "档案类别"),
              ("在库", "借出中", "已归还", "已销毁"),
              {"办理借阅": "借出中", "登记归还": "在库", "申请销毁": "已销毁"},
              terminal=("已销毁",), abnormal=("借出中",)),
        _spec("contract", "维保合同", "合同编号", "维保合同",
              ("合同编号", "签约单位", "维保范围"),
              ("待签约", "执行中", "即将到期", "已终止"),
              {"签订合同": "执行中", "到期续签": "执行中", "终止合同": "已终止"},
              terminal=("已终止",), abnormal=("执行中", "即将到期")),
    )
}

MODULE_ORDER: tuple[str, ...] = (
    "register", "boiler", "pressurevessel", "pipeline", "elevator",
    "crane", "forklift", "inspection", "maintenance", "hazard",
    "accident", "operator", "training", "safetyvalve", "gauge",
    "sparepart", "emergency", "energyeff", "archive", "contract",
)

# 明细行里可能承载业务日期的字段，迁移存量数据时用来补 created_at。
_DATE_FIELDS = (
    "投用日期", "检验日期", "年检日期", "维保日期", "发现日期", "发生时间",
    "发证日期", "培训日期", "校验日期", "检定日期", "演练日期", "记录月份",
    "归档日期", "签约日期",
)
_FALLBACK_DATES = {1: "2026-09-01", 2: "2026-09-02", 3: "2026-09-03"}


def spec(module: str) -> MetricSpec:
    """取模块口径；未登记模块直接报错，避免静默漏算。"""
    try:
        return MODULE_SPECS[module]
    except KeyError as exc:
        raise KeyError(f"模块「{module}」没有登记统一统计口径") from exc


def has_spec(module: str) -> bool:
    return module in MODULE_SPECS


def created_at_of(row: dict[str, Any]) -> str | None:
    raw = row.get("created_at")
    if raw:
        return str(raw)[:10]
    for field_name in _DATE_FIELDS:
        value = row.get(field_name)
        if value and _looks_like_date(str(value)):
            return str(value)[:10]
    return _FALLBACK_DATES.get(int(row.get("id", 0) or 0))


def _looks_like_date(value: str) -> bool:
    if len(value) < 10 or value[4] != "-" or value[7] != "-":
        return False
    return value[:4].isdigit() and value[5:7].isdigit() and value[8:10].isdigit()


def classify_row(spec_: MetricSpec, row: dict[str, Any], *, today: date | None = None) -> dict[str, bool]:
    """统一口径的单行判定，返回三个布尔位；created 由创建日期决定。

    今日新增只看 created_at 是否当天，绝不像旧口径那样把整表行数当新增。
    """
    day = (today or date.today()).isoformat()
    return {
        "created": created_at_of(row) == day,
        "pending": spec_.is_pending(row.get("status")),
        "abnormal": spec_.is_abnormal(row.get("status")),
    }


def apply_flags(spec_: MetricSpec, row: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """把统一口径写回行上的投影缓存位，供存量重算和状态流转共用。"""
    flags = classify_row(spec_, row, today=today)
    row["pending"] = flags["pending"]
    row["abnormal"] = flags["abnormal"]
    return row


def module_metrics(module: str, rows: Iterable[dict[str, Any]], *, today: date | None = None) -> dict[str, int]:
    """单个模块的三项指标。明细页与首页都调它，保证两边是同一个数。"""
    spec_ = spec(module)
    created = pending = abnormal = 0
    for row in rows:
        flags = classify_row(spec_, row, today=today)
        created += int(flags["created"])
        pending += int(flags["pending"])
        abnormal += int(flags["abnormal"])
    return {"created": created, "pending": pending, "abnormal": abnormal}


def overview_from(tables: dict[str, list[dict[str, Any]]], *, today: date | None = None) -> dict[str, object]:
    """按统一口径从各模块明细向上汇总成首页卡片与汇总表。

    字段名保持历史不动：cards[*].label/value、modules[*].name/created/pending/abnormal。
    """
    modules: list[dict[str, object]] = []
    for name in MODULE_ORDER:
        if name not in tables:
            continue
        metrics = module_metrics(name, tables[name], today=today)
        modules.append({"name": name, **metrics})
    cards = [
        {"label": "业务模块", "value": len(modules)},
        {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
        {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
        {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
    ]
    return {"cards": cards, "modules": modules}


def legacy_overview_from(tables: dict[str, list[dict[str, Any]]]) -> dict[str, object]:
    """v1 旧口径：直接数行上手工维护的布尔位，新增=整表行数。

    仅供启动时冻结 v1 历史快照使用，不要在新功能里调用。
    """
    modules: list[dict[str, object]] = []
    for name in MODULE_ORDER:
        if name not in tables:
            continue
        rows = tables[name]
        modules.append({
            "name": name,
            "created": len(rows),
            "pending": sum(1 for row in rows if row.get("pending")),
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
        })
    cards = [
        {"label": "业务模块", "value": len(modules)},
        {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
        {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
        {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
    ]
    return {"cards": cards, "modules": modules}
