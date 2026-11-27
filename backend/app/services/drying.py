"""干燥工序领域服务：控制干燥温度曲线，监控含水率达标，校验上游发酵。

干燥台领料（入炉）规则：
1. 上游发酵记录缺环境湿度时，须凭「已受理」的缺测核验单才能领料；
   核验未受理的，这堆茶放入「等待中」。
2. 一堆茶只能交接一次：已领料的发酵记录不能重复领取。
3. 已受理的干燥交接保留当时使用的核验单版本快照，后续核验单变更不影响它。
"""
from __future__ import annotations
from typing import Any
from app.services.base import BaseModuleService
from app.store import store

class DryingService(BaseModuleService):
    MODULE = "drying"
    ENTITY = "干燥记录"
    OPERATION_TERM = "记录干燥"
    LIST_FIELDS = ["起始温度", "终止温度", "干燥时长", "含水率", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["起始温度", "终止温度", "干燥时长", "含水率"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"记录干燥": "已确认", "提交确认": "待确认", "撤回记录": "已撤回"}
    NEGATIVE_ACTIONS = []

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        start_temp = store.parse_weight(values.get("起始温度", "0"))
        end_temp = store.parse_weight(values.get("终止温度", "0"))
        if start_temp <= 0 or end_temp <= 0:
            errors.append("干燥温度必须大于0")
        if start_temp > end_temp:
            errors.append("起始温度不应高于终止温度")
        moisture = store.parse_weight(values.get("含水率", "0"))
        if moisture <= 0:
            errors.append("必须记录含水率")
        elif moisture > 7:
            pass  # 记录但放行，不同茶类要求不同
        # 上游工序校验
        upstream_module = values.get("上游工序")
        upstream_id = values.get("上游记录ID")
        if upstream_module and upstream_id is not None:
            upstream = store.find(upstream_module, int(upstream_id))
            if upstream is None:
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 不存在")
            elif upstream.get("status") != "已确认":
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 未确认，不能进行干燥")
        return errors

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        if entry.get("status") == "等待中" or entry.get("领料状态") == "等待中":
            return False, "干燥记录仍在等待缺测核验凭据，不能确认"
        if action == "记录干燥":
            moisture = store.parse_weight(entry.get("含水率", "0"))
            if not self.is_moisture_standard(moisture):
                entry["moisture_warning"] = "含水率超标，建议复烘"
            upstream_weight = store.parse_weight(entry.get("上游重量", "0"))
            if upstream_weight > 0:
                entry["产出重量"] = round(upstream_weight * (1.0 - moisture / 100.0 * 0.5), 3)
        return True, None

    def is_moisture_standard(self, moisture: float, tea_type: str = "绿茶") -> bool:
        """检查含水率是否达标（绿茶标准≤7%，红茶≤6%，乌龙茶≤5%）。"""
        standards = {"绿茶": 7.0, "红茶": 6.0, "乌龙茶": 5.0}
        return moisture <= standards.get(tea_type, 7.0)

    def get_drying_by_fermentation(self, ferm_entry_id: int) -> list[dict[str, Any]]:
        """获取指定发酵记录之后的干燥记录。"""
        rows = store.rows(self.MODULE)
        return [r for r in rows
                if r.get("上游记录ID") is not None
                and int(r.get("上游记录ID", -1)) == ferm_entry_id
                and r.get("上游工序") == "fermentation"]

    # ── 干燥台领料（入炉）──

    def claim_from_fermentation(self, fermentation_id: int,
                                values: dict[str, Any] | None = None,
                                request_id: str = "") -> tuple[dict[str, Any] | None, str]:
        """从干燥台尝试领料：凭缺测核验单决定直接领料还是放入等待。"""
        if request_id:
            cached = store.check_idempotent(request_id)
            if cached:
                return cached.get("entry"), f"幂等: {cached.get('message', '已执行')}"

        ferm = store.find("fermentation", int(fermentation_id))
        if ferm is None:
            return None, f"发酵记录 {fermentation_id} 不存在"

        # 一堆茶只能交接一次：查是否已有这堆茶的干燥交接
        existing = None
        for row in store.rows(self.MODULE):
            if (row.get("上游工序") == "fermentation"
                    and str(row.get("上游记录ID")) == str(fermentation_id)
                    and row.get("status") != "已撤回"):
                existing = row
                break
        if existing is not None and existing.get("领料状态") == "已领料":
            return None, f"该堆茶已完成干燥交接（干燥记录 {existing['id']}），不能重复领取"

        cred_ok, ticket, cred_msg = self._resolve_gap_credential(ferm)

        if existing is not None:
            # 等待中的记录：凭据到位则转正领料，否则继续等待，不新增记录
            if cred_ok:
                self._attach_credential(existing, ticket)
                existing["status"] = "草稿"
                existing["领料状态"] = "已领料"
                for field in self.LIST_FIELDS:
                    if values and values.get(field) not in (None, ""):
                        existing[field] = values[field]
                store.log_event(self.MODULE, existing["id"], "claim", {
                    "fermentation_id": fermentation_id,
                    "核验单ID": ticket["id"] if ticket else None,
                })
                message = (f"缺测核验单 {ticket['id']} 已受理，"
                           f"等待中的干燥记录 {existing['id']} 转为已领料")
                if request_id:
                    store.record_idempotent(request_id, {"entry": dict(existing), "message": message})
                return existing, message
            return existing, f"缺测核验单仍未受理（{cred_msg}），该堆茶继续等待"

        # 新建干燥交接记录
        rows = store.rows(self.MODULE)
        new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry: dict[str, Any] = {"id": new_id}
        entry.update({field: (values or {}).get(field, "") for field in self.LIST_FIELDS})
        if not entry.get("登记编号"):
            entry["登记编号"] = f"DRY-CLAIM-{new_id:04d}"
        entry["批次号"] = ferm.get("批次号", "")
        entry["上游工序"] = "fermentation"
        entry["上游记录ID"] = fermentation_id
        entry["上游重量"] = ferm.get("产出重量", ferm.get("上游重量", ""))
        entry["pending"] = True
        entry["abnormal"] = False
        entry["frozen"] = False
        if cred_ok:
            entry["status"] = "草稿"
            entry["领料状态"] = "已领料"
            self._attach_credential(entry, ticket)
            if ticket is not None:
                message = (f"凭缺测核验单 {ticket['id']}（V{ticket.get('核验单版本', 1)}）领料，"
                           f"干燥记录 {new_id} 已建立")
            else:
                message = f"发酵记录 {fermentation_id} 湿度齐全，干燥记录 {new_id} 已建立"
        else:
            entry["status"] = "等待中"
            entry["领料状态"] = "等待中"
            message = f"发酵记录 {fermentation_id} 环境湿度缺测且{cred_msg}，该堆茶放入等待"
        rows.append(entry)

        store.log_event(self.MODULE, new_id, "claim", {
            "fermentation_id": fermentation_id,
            "领料状态": entry["领料状态"],
            "核验单ID": ticket["id"] if ticket else None,
        })
        if request_id:
            store.record_idempotent(request_id, {"entry": dict(entry), "message": message})
        return entry, message

    def _resolve_gap_credential(self, ferm: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str]:
        """判定这堆茶是否具备转干燥凭据。返回 (可否领料, 核验单, 说明)。

        以核验单为准：这堆茶开过核验单，就必须等它受理；
        受理后即使发酵记录已回写湿度，交接仍引用该核验单版本。
        """
        from app.services import service_for
        gap_svc = service_for("gap_check")
        ticket = gap_svc.find_ticket_for_fermentation(ferm.get("id")) if gap_svc else None
        if ticket is None:
            if ferm.get("湿度缺测"):
                return False, None, "缺测核验单未开立"
            return True, None, "湿度齐全"
        if ticket.get("status") == "已受理":
            return True, ticket, "凭据可用"
        return False, ticket, f"核验单状态为「{ticket.get('status')}」"

    def _attach_credential(self, entry: dict[str, Any], ticket: dict[str, Any] | None) -> None:
        """把受理的核验单快照写到干燥记录上，保留当时使用的核验单版本。"""
        if ticket is None:
            return
        entry["核验单ID"] = ticket["id"]
        entry["核验单版本"] = ticket.get("核验单版本", 1)
        entry["受理来源"] = ticket.get("受理来源", "")
        entry["受理数值"] = ticket.get("受理数值", "")
        entry["受理补测ID"] = ticket.get("受理补测ID", "")
