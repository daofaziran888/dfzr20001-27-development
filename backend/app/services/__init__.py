"""领域服务注册表：通用资源路由按模块 key 分派到独立业务服务。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.services.tea_garden import TeaGardenService
from app.services.picking import PickingService
from app.services.withering import WitheringService
from app.services.fixing import FixingService
from app.services.rolling import RollingService
from app.services.fermentation import FermentationService
from app.services.drying import DryingService
from app.services.gap_check import GapCheckService
from app.services.grading import GradingService
from app.services.blending import BlendingService
from app.services.packing import PackingService
from app.services.storage import StorageService
from app.services.testing import TestingService
from app.services.certification import CertificationService
from app.services.trace_code import TraceCodeService
from app.services.shipment import ShipmentService
from app.services.sample import SampleService
from app.services.defect import DefectService
from app.services.audit import AuditService

SERVICES: dict[str, BaseModuleService] = {
    "tea_garden": TeaGardenService(),
    "picking": PickingService(),
    "withering": WitheringService(),
    "fixing": FixingService(),
    "rolling": RollingService(),
    "fermentation": FermentationService(),
    "drying": DryingService(),
    "gap_check": GapCheckService(),
    "grading": GradingService(),
    "blending": BlendingService(),
    "packing": PackingService(),
    "storage": StorageService(),
    "testing": TestingService(),
    "certification": CertificationService(),
    "trace_code": TraceCodeService(),
    "shipment": ShipmentService(),
    "sample": SampleService(),
    "defect": DefectService(),
    "audit": AuditService(),
}


def service_for(module: str) -> BaseModuleService | None:
    return SERVICES.get(module)
