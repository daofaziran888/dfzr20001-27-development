"""缺测核验单领域服务：发酵传感记录空态（只收到温度、没有环境湿度）的业务处置。

业务规则：
1. 发酵记录缺环境湿度时自动开立核验单，对应翻堆时段标为「待补」，未知湿度绝不写成 0%。
2. 补测分「人工补验」（须签字）与「设备补报」（须设备编号）两种来源，各自保留来源。
3. 同一核验单只受理一笔补测作为转干燥凭据，其余补测标「不采用」留存备查，
   一堆茶不能交接两次。
4. 受理后核验单版本号递增；干燥交接记录当时使用的核验单版本快照。
5. 补测提交按「请求号」幂等：重交同一笔补测不新增、不清空已完成的入炉。
"""
from __future__ import annotations

import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class GapCheckService(BaseModuleService):
    MODULE = "gap_check"
    ENTITY = "缺测核验单"
    OPERATION_TERM = "受理核验"
    LIST_FIELDS = ["批次号", "发酵记录ID", "翻堆时段", "缺测项目", "受理来源",
                   "受理数值", "核验单版本", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["发酵记录ID", "缺测项目"]
    STATUS_ORDER = ["待补", "补验中", "已受理", "已关闭"]
    ACTION_RULES = {"关闭核验": "已关闭"}
    NEGATIVE_ACTIONS = []

    SUPPLEMENT_SOURCES = ["人工补验", "设备补报"]

    # ── 登记与自动开立 ──

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        ferm_id = values.get("发酵记录ID")
        if ferm_id not in (None, ""):
            try:
                ferm = store.find("fermentation", int(ferm_id))
            except (TypeError, ValueError):
                ferm = None
            if ferm is None:
                errors.append(f"发酵记录 {ferm_id} 不存在，缺测核验单必须挂在这堆茶上")
        return errors

    def after_create(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        entry.setdefault("补测列表", [])
        entry["核验单版本"] = 1
        entry.setdefault("受理时间", "")

    def create_for_fermentation(self, ferm_entry: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """发酵记录缺环境湿度时自动开立核验单；同一发酵记录只开一张未关闭的核验单。"""
        existing = self.find_ticket_for_fermentation(ferm_entry.get("id"))
        if existing is not None:
            return existing, []
        values = {
            "批次号": ferm_entry.get("批次号", ""),
            "发酵记录ID": ferm_entry.get("id"),
            "翻堆时段": ferm_entry.get("翻堆时段") or "未标注时段",
            "缺测项目": "环境湿度",
            "登记编号": f"GAP-FERM-{ferm_entry.get('id')}",
            "负责人": ferm_entry.get("负责人", ""),
        }
        return self.create_entry(values)

    def find_ticket_for_fermentation(self, fermentation_id: Any) -> dict[str, Any] | None:
        """找到发酵记录对应的未关闭核验单（只有同一堆茶同一时段的核验单才可作凭据）。"""
        if fermentation_id is None:
            return None
        tickets = [
            row for row in store.rows(self.MODULE)
            if str(row.get("发酵记录ID")) == str(fermentation_id)
            and row.get("status") != "已关闭"
        ]
        return tickets[-1] if tickets else None

    # ── 补测提交（幂等）──

    def submit_supplement(self, entry_id: int, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """提交一笔补测。人工补验须签字、设备补报须设备编号；按请求号幂等。"""
        ticket = store.find(self.MODULE, entry_id)
        if ticket is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if ticket.get("status") == "已关闭":
            return None, f"{self.ENTITY} {entry_id} 已关闭，不再接收补测"

        supplements = ticket.setdefault("补测列表", [])

        # 幂等：同一请求号重交，不新增、不改变已受理结果与已完成的入炉
        request_id = str(payload.get("请求号") or "").strip()
        if request_id:
            for sup in supplements:
                if sup.get("请求号") == request_id:
                    return ticket, f"幂等：补测「{request_id}」已登记，不重复受理"

        if ticket.get("status") == "已受理":
            return None, f"{self.ENTITY} {entry_id} 已受理，不再接收新的补测"

        source = str(payload.get("来源") or "").strip()
        if source not in self.SUPPLEMENT_SOURCES:
            return None, f"补测来源须为 {' 或 '.join(self.SUPPLEMENT_SOURCES)}"

        raw_value = str(payload.get("补测数值") or "").strip()
        value = store.parse_weight(raw_value)
        if not raw_value or value <= 0 or value > 100:
            return None, "补测数值无效：未知湿度不能记为 0%，须提交 (0,100] 的有效读数"

        signer = str(payload.get("签字人") or "").strip()
        device_no = str(payload.get("设备编号") or "").strip()
        if source == "人工补验" and not signer:
            return None, "人工补验须填写签字人"
        if source == "设备补报" and not device_no:
            return None, "设备补报须填写设备编号"

        # 只有属于这堆茶同一翻堆时段的补测才可进入凭据候选
        period = str(payload.get("翻堆时段") or "").strip()
        ticket_period = str(ticket.get("翻堆时段") or "").strip()
        if period and ticket_period and ticket_period != "未标注时段" and period != ticket_period:
            return None, "补测时段与核验单翻堆时段不一致，不能作为这堆茶的转干燥凭据"

        supplement = {
            "补测ID": max((int(s.get("补测ID", 0)) for s in supplements), default=0) + 1,
            "来源": source,
            "补测数值": raw_value,
            "签字人": signer,
            "设备编号": device_no,
            "请求号": request_id,
            "翻堆时段": period or ticket_period,
            "状态": "待受理",
            "受理结论": "",
            "提交时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        supplements.append(supplement)
        ticket["status"] = "补验中"
        ticket["pending"] = True

        store.log_event(self.MODULE, entry_id, "submit_supplement", {
            "补测ID": supplement["补测ID"], "来源": source, "补测数值": raw_value,
        })
        return ticket, f"{source} {raw_value}% 已登记为补测 #{supplement['补测ID']}，等待受理"

    # ── 受理补测，形成转干燥凭据 ──

    def accept_supplement(self, entry_id: int, supplement_id: int) -> tuple[dict[str, Any] | None, str]:
        """受理一笔补测：核验单转为「已受理」，其余补测不采用；版本号递增并回写发酵记录。"""
        ticket = store.find(self.MODULE, entry_id)
        if ticket is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if ticket.get("status") == "已关闭":
            return None, f"{self.ENTITY} {entry_id} 已关闭，不能受理"

        supplements = ticket.get("补测列表", [])
        target = next((s for s in supplements if int(s.get("补测ID", 0)) == int(supplement_id)), None)
        if target is None:
            return None, f"补测 #{supplement_id} 不在核验单 {entry_id} 内"

        if ticket.get("status") == "已受理":
            if target.get("状态") == "已受理":
                return ticket, f"幂等：补测 #{supplement_id} 已受理，无需重复操作"
            return None, "核验单已受理其他补测，一堆茶只能交接一次"

        if target.get("状态") != "待受理":
            return None, f"补测 #{supplement_id} 当前状态为「{target.get('状态')}」，不能受理"

        for sup in supplements:
            if sup is target:
                sup["状态"] = "已受理"
                sup["受理结论"] = "采纳为转干燥凭据"
            elif sup.get("状态") == "待受理":
                sup["状态"] = "不采用"
                sup["受理结论"] = "同时段已有受理补测，留存备查不交接"

        ticket["status"] = "已受理"
        ticket["受理来源"] = target["来源"]
        ticket["受理数值"] = target["补测数值"]
        ticket["受理补测ID"] = target["补测ID"]
        ticket["受理时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
        ticket["核验单版本"] = int(ticket.get("核验单版本", 1)) + 1

        self._write_back_fermentation(ticket, target)

        store.log_event(self.MODULE, entry_id, "accept_supplement", {
            "补测ID": target["补测ID"], "来源": target["来源"],
            "补测数值": target["补测数值"], "核验单版本": ticket["核验单版本"],
        })
        return ticket, (f"补测 #{target['补测ID']}（{target['来源']} {target['补测数值']}%）已受理，"
                        f"核验单版本 V{ticket['核验单版本']}，可转干燥")

    def _write_back_fermentation(self, ticket: dict[str, Any], supplement: dict[str, Any]) -> None:
        """把受理的补测结果回写到发酵记录，并按车间标准重新判断。"""
        ferm_id = ticket.get("发酵记录ID")
        if ferm_id in (None, ""):
            return
        ferm = store.find("fermentation", int(ferm_id))
        if ferm is None:
            return
        ferm["环境湿度"] = str(supplement["补测数值"])
        ferm["湿度来源"] = supplement["来源"]
        ferm["湿度缺测"] = False
        ferm["缺测状态"] = "已补验"
        from app.services import service_for
        ferm_svc = service_for("fermentation")
        if ferm_svc is not None:
            temp = store.parse_weight(ferm.get("环境温度", "0"))
            humidity = store.parse_weight(ferm.get("环境湿度", "0"))
            if ferm_svc.is_fermentation_normal(temp, humidity):
                ferm.pop("fermentation_warning", None)
            else:
                ferm["fermentation_warning"] = "补验湿度超出车间标准范围，请注意品质风险"

    # ── 凭据查询 ──

    def get_credential(self, entry_id: int) -> dict[str, Any] | None:
        """返回核验单的转干燥凭据：是否可转干燥、受理的是哪笔补测、其余补测如何办理。"""
        ticket = store.find(self.MODULE, entry_id)
        if ticket is None:
            return None
        accepted = [s for s in ticket.get("补测列表", []) if s.get("状态") == "已受理"]
        return {
            "核验单ID": ticket["id"],
            "批次号": ticket.get("批次号", ""),
            "发酵记录ID": ticket.get("发酵记录ID"),
            "翻堆时段": ticket.get("翻堆时段", ""),
            "缺测项目": ticket.get("缺测项目", ""),
            "状态": ticket.get("status"),
            "可转干燥": ticket.get("status") == "已受理",
            "核验单版本": ticket.get("核验单版本", 1),
            "受理补测": accepted[0] if accepted else None,
            "补测列表": ticket.get("补测列表", []),
        }
