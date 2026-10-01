"""压力表检定接口：列表/明细/登记/动作/指标由共享工厂统一生成。"""
from __future__ import annotations

from app.routers.base import build_module_router
from app.services.gauge import GaugeService

service = GaugeService()
router = build_module_router("gauge", service)
