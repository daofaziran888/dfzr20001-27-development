"""缺测核验路由：补测提交、受理、凭据查询与干燥台领料。

通用资源路由（/api/gap_check）负责核验单的查询/登记/关闭；
这里的专用接口承载带载荷的补测与领料动作。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import service_for

router = APIRouter(prefix="/api/gap_check", tags=["缺测核验"])


class SupplementPayload(BaseModel):
    来源: str
    补测数值: str
    签字人: str = ""
    设备编号: str = ""
    请求号: str = ""
    翻堆时段: str = ""


class AcceptPayload(BaseModel):
    补测ID: int


class ClaimPayload(BaseModel):
    发酵记录ID: int
    请求号: str = ""
    values: dict[str, Any] = Field(default_factory=dict)


def require_gap_service():
    service = service_for("gap_check")
    if service is None:
        raise HTTPException(status_code=404, detail="缺测核验模块未注册")
    return service


@router.post("/{entry_id}/supplements")
def submit_supplement(entry_id: int, payload: SupplementPayload) -> dict[str, Any]:
    """提交一笔补测（人工补验须签字、设备补报须设备编号），按请求号幂等。"""
    service = require_gap_service()
    ticket, message = service.submit_supplement(entry_id, payload.model_dump())
    if ticket is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "entry": ticket}


@router.post("/{entry_id}/accept")
def accept_supplement(entry_id: int, payload: AcceptPayload) -> dict[str, Any]:
    """受理一笔补测作为转干燥凭据，其余补测不采用。"""
    service = require_gap_service()
    ticket, message = service.accept_supplement(entry_id, payload.补测ID)
    if ticket is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "entry": ticket}


@router.get("/{entry_id}/credential")
def get_credential(entry_id: int) -> dict[str, Any]:
    """查看核验单凭据：哪次数据受理、另一条怎样办理、是否可转干燥。"""
    service = require_gap_service()
    credential = service.get_credential(entry_id)
    if credential is None:
        raise HTTPException(status_code=404, detail=f"缺测核验单 {entry_id} 不存在或已归档")
    return {"ok": True, "credential": credential}


@router.post("/drying-claim")
def drying_claim(payload: ClaimPayload) -> dict[str, Any]:
    """干燥台领料：凭已受理的核验单领料，否则把这堆茶放入等待。"""
    service = service_for("drying")
    if service is None:
        raise HTTPException(status_code=404, detail="干燥模块未注册")
    entry, message = service.claim_from_fermentation(
        payload.发酵记录ID, payload.values, payload.请求号)
    if entry is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "entry": entry}
