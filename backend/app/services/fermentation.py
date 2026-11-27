"""发酵工序领域服务：监控发酵环境参数，控制堆高与翻堆周期，校验上游揉捻。

传感记录空态处置：只收到温度、没有环境湿度时，记录仍可登记，
对应翻堆时段标为「待补」并自动开立缺测核验单；未知湿度绝不写成 0%。
补验受理后由核验单回写湿度，再按车间标准（75%~95%）判断。
"""
from __future__ import annotations
from typing import Any
from app.services.base import BaseModuleService
from app.store import store

class FermentationService(BaseModuleService):
    MODULE = "fermentation"
    ENTITY = "发酵记录"
    OPERATION_TERM = "记录发酵"
    LIST_FIELDS = ["环境温度", "环境湿度", "堆高尺寸", "翻堆间隔", "翻堆时段", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["环境温度", "堆高尺寸"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"记录发酵": "已确认", "提交确认": "待确认", "撤回记录": "已撤回"}
    NEGATIVE_ACTIONS = []

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        temp = store.parse_weight(values.get("环境温度", "0"))
        if temp < 15:
            errors.append("发酵环境温度不宜低于15℃")
        elif temp > 45:
            errors.append("发酵环境温度不宜高于45℃")
        # 环境湿度允许空态（传感缺测）：留空走缺测核验，不能把未知写成 0%
        humidity_raw = str(values.get("环境湿度") or "").strip()
        if humidity_raw:
            humidity = store.parse_weight(humidity_raw)
            if humidity <= 0:
                errors.append("环境湿度未知时请留空走缺测核验，不能记为 0%")
            elif humidity < 60:
                errors.append("发酵环境湿度不宜低于60%")
            elif humidity > 98:
                errors.append("发酵环境湿度不宜高于98%")
        heap = store.parse_weight(values.get("堆高尺寸", "0"))
        if heap <= 0:
            errors.append("堆高尺寸必须大于0")
        # 上游工序校验
        upstream_module = values.get("上游工序")
        upstream_id = values.get("上游记录ID")
        if upstream_module and upstream_id is not None:
            upstream = store.find(upstream_module, int(upstream_id))
            if upstream is None:
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 不存在")
            elif upstream.get("status") != "已确认":
                errors.append(f"上游记录 {upstream_module}/{upstream_id} 未确认，不能进行发酵")
        return errors

    def after_create(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        """缺环境湿度时标记「待补」并自动开立缺测核验单。"""
        humidity_raw = str(entry.get("环境湿度") or "").strip()
        if not humidity_raw:
            entry["环境湿度"] = ""  # 未知留空，绝不写 0%
            entry["湿度缺测"] = True
            entry["缺测状态"] = "待补"
            entry["湿度来源"] = ""
            from app.services import service_for
            gap_svc = service_for("gap_check")
            if gap_svc is not None:
                ticket, _ = gap_svc.create_for_fermentation(entry)
                if ticket is not None:
                    entry["缺测核验单ID"] = ticket["id"]
        else:
            entry["湿度缺测"] = False
            entry["缺测状态"] = "已记录"
            entry["湿度来源"] = "传感记录"

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        if action == "记录发酵":
            if entry.get("湿度缺测"):
                entry["fermentation_warning"] = "环境湿度缺测待补，转干燥前须完成缺测核验"
            else:
                temp = store.parse_weight(entry.get("环境温度", "0"))
                humidity = store.parse_weight(entry.get("环境湿度", "0"))
                if not self.is_fermentation_normal(temp, humidity):
                    entry["fermentation_warning"] = "发酵条件超出正常范围，请注意品质风险"
        return True, None

    def is_fermentation_normal(self, temp: float, humidity: float) -> bool:
        """判断发酵条件是否正常（车间标准：温度22~35℃、湿度75%~95%）。"""
        return 22 <= temp <= 35 and 75 <= humidity <= 95

    def get_fermentation_by_roll(self, roll_entry_id: int) -> list[dict[str, Any]]:
        """获取指定揉捻记录之后的发酵记录。"""
        rows = store.rows(self.MODULE)
        return [r for r in rows if store.parse_weight(str(r.get("上游记录ID", "-1"))) == roll_entry_id
                and r.get("上游工序") == "rolling"]
