"""事故管理业务服务：仅声明模块身份。

状态序列、必填字段、动作映射、终态与异常状态统一登记在 app.metrics.MODULE_SPECS；
列表/创建/流转/今日新增/待处理/异常量的实现全部在 app.services.base.ModuleService。
"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "accident"


class AccidentService(ModuleService):
    def __init__(self) -> None:
        super().__init__(MODULE)
