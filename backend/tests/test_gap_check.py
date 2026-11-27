"""缺测核验单业务测试：发酵传感空态 → 补测 → 受理 → 干燥领料全链路。

场景主线：只收到温度没有环境湿度时开核验单；人工补验 80% 与设备补报 98%
同批同时段各保留来源；受理一笔形成转干燥凭据；干燥台领料、等待、
幂等重交、版本快照、一堆茶只交接一次。
"""
from __future__ import annotations

import unittest

from app.store import store
from app.services import service_for


def make_gap_fermentation(batch_no: str, period: str = "2026-11-27 08:00-12:00") -> dict:
    """登记一条只有温度、没有环境湿度的发酵记录。"""
    ferm_svc = service_for("fermentation")
    entry, errors = ferm_svc.create_entry({
        "环境温度": "28",
        "堆高尺寸": "40",
        "翻堆间隔": "4小时",
        "翻堆时段": period,
        "批次号": batch_no,
        "负责人": "发酵员甲",
    })
    assert entry is not None, f"发酵登记应成功: {errors}"
    return entry


class TestGapTicketCreation(unittest.TestCase):
    """空态处置：缺湿度开核验单、标待补、未知不写成 0%。"""

    def test_missing_humidity_marks_pending_and_creates_ticket(self):
        batch_no = "BATCH-GAP-CREATE"
        ferm = make_gap_fermentation(batch_no)

        # 翻堆时段标为待补，未知湿度留空而不是 0%
        self.assertTrue(ferm.get("湿度缺测"))
        self.assertEqual(ferm.get("缺测状态"), "待补")
        self.assertNotEqual(str(ferm.get("环境湿度")), "0")
        self.assertEqual(str(ferm.get("环境湿度") or ""), "")

        # 自动开立缺测核验单，挂在这堆茶（发酵记录）上
        gap_svc = service_for("gap_check")
        ticket = gap_svc.find_ticket_for_fermentation(ferm["id"])
        self.assertIsNotNone(ticket, "缺测应自动开立核验单")
        self.assertEqual(ticket["status"], "待补")
        self.assertEqual(ticket["缺测项目"], "环境湿度")
        self.assertEqual(str(ticket["发酵记录ID"]), str(ferm["id"]))
        self.assertEqual(ticket["翻堆时段"], "2026-11-27 08:00-12:00")
        self.assertEqual(ticket["核验单版本"], 1)
        self.assertEqual(ticket["补测列表"], [])
        self.assertEqual(ferm.get("缺测核验单ID"), ticket["id"])

    def test_valid_humidity_judged_by_workshop_standard(self):
        """录到有效的 80% 时按车间标准判断，不开核验单。"""
        ferm_svc = service_for("fermentation")
        entry, errors = ferm_svc.create_entry({
            "环境温度": "28", "环境湿度": "80", "堆高尺寸": "40",
            "批次号": "BATCH-GAP-H80",
        })
        self.assertIsNotNone(entry, errors)
        self.assertFalse(entry.get("湿度缺测"))
        self.assertIsNone(service_for("gap_check").find_ticket_for_fermentation(entry["id"]))

        entry["status"] = "待确认"
        confirmed, msg = ferm_svc.run_action(int(entry["id"]), "记录发酵")
        self.assertIsNotNone(confirmed, msg)
        # 温度28℃、湿度80% 均在车间标准内，不应有预警
        self.assertNotIn("fermentation_warning", confirmed)

    def test_zero_humidity_rejected_as_unknown(self):
        """不能把未知写成 0%：显式填 0 视为无效读数。"""
        ferm_svc = service_for("fermentation")
        entry, errors = ferm_svc.create_entry({
            "环境温度": "28", "环境湿度": "0", "堆高尺寸": "40",
        })
        self.assertIsNone(entry)
        self.assertTrue(any("0%" in e for e in errors))


class TestSupplementAndAccept(unittest.TestCase):
    """补测提交与受理：来源保留、同时段校验、只受理一笔。"""

    def setUp(self):
        self.gap_svc = service_for("gap_check")
        self.ferm = make_gap_fermentation("BATCH-GAP-SUPP")
        self.ticket = self.gap_svc.find_ticket_for_fermentation(self.ferm["id"])

    def test_manual_and_device_supplements_keep_sources(self):
        """人工签字 80% 与设备补报 98% 同批同时段，各保留来源。"""
        ticket, msg = self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "人工补验", "补测数值": "80", "签字人": "发酵员甲",
            "请求号": "REQ-MANUAL-1", "翻堆时段": "2026-11-27 08:00-12:00",
        })
        self.assertIsNotNone(ticket, msg)
        ticket, msg = self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "设备补报", "补测数值": "98", "设备编号": "HUM-SENSOR-07",
            "请求号": "REQ-DEVICE-1", "翻堆时段": "2026-11-27 08:00-12:00",
        })
        self.assertIsNotNone(ticket, msg)
        self.assertEqual(ticket["status"], "补验中")

        supplements = ticket["补测列表"]
        self.assertEqual(len(supplements), 2)
        by_source = {s["来源"]: s for s in supplements}
        self.assertEqual(by_source["人工补验"]["补测数值"], "80")
        self.assertEqual(by_source["人工补验"]["签字人"], "发酵员甲")
        self.assertEqual(by_source["设备补报"]["补测数值"], "98")
        self.assertEqual(by_source["设备补报"]["设备编号"], "HUM-SENSOR-07")

    def test_supplement_requires_signature_or_device(self):
        ticket, msg = self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "人工补验", "补测数值": "80",
        })
        self.assertIsNone(ticket)
        self.assertIn("签字人", msg)
        ticket, msg = self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "设备补报", "补测数值": "98",
        })
        self.assertIsNone(ticket)
        self.assertIn("设备编号", msg)

    def test_supplement_from_other_period_rejected(self):
        """不属于这堆茶同一时段的补测不能进入凭据候选。"""
        ticket, msg = self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "人工补验", "补测数值": "80", "签字人": "发酵员甲",
            "翻堆时段": "2026-11-26 20:00-24:00",
        })
        self.assertIsNone(ticket)
        self.assertIn("时段", msg)

    def test_accept_one_supplement_forms_credential(self):
        """受理人工 80%：设备 98% 不采用，发酵回写并按车间标准判断。"""
        self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "人工补验", "补测数值": "80", "签字人": "发酵员甲",
            "请求号": "REQ-ACC-M",
        })
        self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "设备补报", "补测数值": "98", "设备编号": "HUM-SENSOR-07",
            "请求号": "REQ-ACC-D",
        })
        ticket, msg = self.gap_svc.accept_supplement(int(self.ticket["id"]), 1)
        self.assertIsNotNone(ticket, msg)
        self.assertEqual(ticket["status"], "已受理")
        self.assertEqual(ticket["受理来源"], "人工补验")
        self.assertEqual(ticket["受理数值"], "80")
        self.assertEqual(ticket["核验单版本"], 2)

        supplements = {s["补测ID"]: s for s in ticket["补测列表"]}
        self.assertEqual(supplements[1]["状态"], "已受理")
        self.assertEqual(supplements[1]["受理结论"], "采纳为转干燥凭据")
        self.assertEqual(supplements[2]["状态"], "不采用")
        self.assertIn("留存备查", supplements[2]["受理结论"])

        # 回写发酵记录：湿度 80%、来源人工、按车间标准判断无预警
        ferm = store.find("fermentation", int(self.ferm["id"]))
        self.assertEqual(ferm["环境湿度"], "80")
        self.assertEqual(ferm["湿度来源"], "人工补验")
        self.assertEqual(ferm["缺测状态"], "已补验")
        self.assertFalse(ferm["湿度缺测"])
        self.assertNotIn("fermentation_warning", ferm)

        # 凭据查询：可转干燥，受理的是人工 80%
        credential = self.gap_svc.get_credential(int(self.ticket["id"]))
        self.assertTrue(credential["可转干燥"])
        self.assertEqual(credential["受理补测"]["来源"], "人工补验")
        self.assertEqual(credential["受理补测"]["补测数值"], "80")

    def test_accept_second_supplement_blocked(self):
        """一堆茶只能交接一次：已受理后不能再受理另一笔。"""
        self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "人工补验", "补测数值": "80", "签字人": "发酵员甲",
        })
        self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "设备补报", "补测数值": "98", "设备编号": "HUM-SENSOR-07",
        })
        ticket, _ = self.gap_svc.accept_supplement(int(self.ticket["id"]), 1)
        self.assertEqual(ticket["status"], "已受理")

        ticket2, msg = self.gap_svc.accept_supplement(int(self.ticket["id"]), 2)
        self.assertIsNone(ticket2)
        self.assertIn("交接一次", msg)

        # 幂等：重复受理同一笔不报错也不改状态
        ticket3, msg3 = self.gap_svc.accept_supplement(int(self.ticket["id"]), 1)
        self.assertIsNotNone(ticket3)
        self.assertIn("幂等", msg3)
        self.assertEqual(ticket3["核验单版本"], 2)


class TestDryingClaim(unittest.TestCase):
    """干燥台领料：等待、凭据领料、版本快照、只交接一次、幂等重交。"""

    def setUp(self):
        self.gap_svc = service_for("gap_check")
        self.drying_svc = service_for("drying")
        self.ferm = make_gap_fermentation("BATCH-GAP-CLAIM")
        self.ticket = self.gap_svc.find_ticket_for_fermentation(self.ferm["id"])

    def _submit_and_accept_manual_80(self):
        self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "人工补验", "补测数值": "80", "签字人": "发酵员甲",
            "请求号": "REQ-CLAIM-M",
        })
        self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "设备补报", "补测数值": "98", "设备编号": "HUM-SENSOR-07",
            "请求号": "REQ-CLAIM-D",
        })
        ticket, msg = self.gap_svc.accept_supplement(int(self.ticket["id"]), 1)
        assert ticket is not None, msg
        return ticket

    def test_claim_waits_until_credential_then_claims(self):
        """核验未受理时干燥放入等待；受理后同一记录转正，不新增。"""
        ferm_id = int(self.ferm["id"])
        # 仍要核对：干燥将这堆放在等待中
        waiting, msg = self.drying_svc.claim_from_fermentation(ferm_id)
        self.assertIsNotNone(waiting, msg)
        self.assertEqual(waiting["status"], "等待中")
        self.assertEqual(waiting["领料状态"], "等待中")
        drying_count = len(store.rows("drying"))

        # 等待中不能确认
        not_ok, reason = self.drying_svc.on_confirm(waiting, "提交确认")
        self.assertFalse(not_ok)
        self.assertIn("等待", reason)

        # 走一次补测并受理，形成凭据
        ticket = self._submit_and_accept_manual_80()

        # 已有可用凭据：继续领，同一记录转正，不增加一条
        claimed, msg = self.drying_svc.claim_from_fermentation(
            ferm_id, {"起始温度": "60", "终止温度": "85", "干燥时长": "3小时", "含水率": "6"})
        self.assertIsNotNone(claimed, msg)
        self.assertEqual(claimed["id"], waiting["id"], "等待记录应转正而不是新增")
        self.assertEqual(len(store.rows("drying")), drying_count)
        self.assertEqual(claimed["status"], "草稿")
        self.assertEqual(claimed["领料状态"], "已领料")

        # 已受理的干燥交接保留当时使用的核验单版本与所用补测
        self.assertEqual(claimed["核验单ID"], ticket["id"])
        self.assertEqual(claimed["核验单版本"], ticket["核验单版本"])
        self.assertEqual(claimed["受理来源"], "人工补验")
        self.assertEqual(claimed["受理数值"], "80")
        self.assertEqual(claimed["受理补测ID"], 1)

    def test_no_double_handover(self):
        """不能让一堆茶交接两次。"""
        ferm_id = int(self.ferm["id"])
        self._submit_and_accept_manual_80()
        claimed, msg = self.drying_svc.claim_from_fermentation(ferm_id)
        self.assertIsNotNone(claimed, msg)
        drying_count = len(store.rows("drying"))

        again, msg = self.drying_svc.claim_from_fermentation(ferm_id)
        self.assertIsNone(again)
        self.assertIn("不能重复领取", msg)
        self.assertEqual(len(store.rows("drying")), drying_count)

    def test_accepted_handover_keeps_ticket_version(self):
        """已受理的干燥交接保留当时使用的核验单版本。"""
        ferm_id = int(self.ferm["id"])
        ticket = self._submit_and_accept_manual_80()
        claimed, _ = self.drying_svc.claim_from_fermentation(ferm_id)
        self.assertEqual(claimed["核验单版本"], 2)

        # 核验单版本后续变化，不动已交接记录上的快照
        ticket["核验单版本"] = 9
        self.assertEqual(store.find("drying", int(claimed["id"]))["核验单版本"], 2)

    def test_resubmit_same_supplement_keeps_furnace_entry(self):
        """重交同一笔补测：不清空已完成的入炉，也不增加一条。"""
        ferm_id = int(self.ferm["id"])
        self._submit_and_accept_manual_80()
        claimed, _ = self.drying_svc.claim_from_fermentation(ferm_id)
        self.assertEqual(claimed["领料状态"], "已领料")
        supp_count = len(self.ticket["补测列表"])
        drying_count = len(store.rows("drying"))

        # 重交同一请求号的补测
        ticket, msg = self.gap_svc.submit_supplement(int(self.ticket["id"]), {
            "来源": "人工补验", "补测数值": "80", "签字人": "发酵员甲",
            "请求号": "REQ-CLAIM-M",
        })
        self.assertIsNotNone(ticket)
        self.assertIn("幂等", msg)
        self.assertEqual(len(ticket["补测列表"]), supp_count, "不能增加一条补测")
        self.assertEqual(ticket["status"], "已受理")

        # 已完成的入炉保持不变
        furnace = store.find("drying", int(claimed["id"]))
        self.assertEqual(furnace["领料状态"], "已领料")
        self.assertEqual(furnace["核验单版本"], 2)
        self.assertEqual(len(store.rows("drying")), drying_count, "不能增加一条干燥记录")

    def test_claim_idempotent_by_request_id(self):
        """领料按请求号幂等：重复请求返回缓存，不新增记录。"""
        ferm_id = int(self.ferm["id"])
        self._submit_and_accept_manual_80()
        first, _ = self.drying_svc.claim_from_fermentation(ferm_id, request_id="CLAIM-REQ-1")
        drying_count = len(store.rows("drying"))
        second, msg = self.drying_svc.claim_from_fermentation(ferm_id, request_id="CLAIM-REQ-1")
        self.assertIsNotNone(second)
        self.assertIn("幂等", msg)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(store.rows("drying")), drying_count)

    def test_other_batch_ticket_not_credential(self):
        """只有属于这堆茶同一时段的核验记录才可形成转干燥的凭据。"""
        # 另一堆茶（另一条发酵记录）的核验单已受理
        other_ferm = make_gap_fermentation("BATCH-GAP-OTHER", "2026-11-27 12:00-16:00")
        other_ticket = self.gap_svc.find_ticket_for_fermentation(other_ferm["id"])
        self.gap_svc.submit_supplement(int(other_ticket["id"]), {
            "来源": "人工补验", "补测数值": "80", "签字人": "发酵员乙",
            "翻堆时段": "2026-11-27 12:00-16:00",
        })
        self.gap_svc.accept_supplement(int(other_ticket["id"]), 1)

        # 本堆茶的核验单仍未受理：别人的凭据不能用，这堆进等待
        waiting, msg = self.drying_svc.claim_from_fermentation(int(self.ferm["id"]))
        self.assertIsNotNone(waiting)
        self.assertEqual(waiting["领料状态"], "等待中")
        self.assertNotIn("核验单ID", waiting)


class TestGapCheckApi(unittest.TestCase):
    """接口层：补测提交、受理、凭据查询、干燥领料（直接调用路由函数）。"""

    def test_api_flow(self):
        from app.routers.gap_check_routes import (
            AcceptPayload, ClaimPayload, SupplementPayload,
            accept_supplement, drying_claim, get_credential, submit_supplement,
        )

        # 登记缺湿度发酵记录，自动开核验单
        ferm = make_gap_fermentation("BATCH-GAP-API")
        ticket_id = int(ferm["缺测核验单ID"])

        # 提交两笔补测：人工签字 80%、设备补报 98%
        resp = submit_supplement(ticket_id, SupplementPayload(
            来源="人工补验", 补测数值="80", 签字人="发酵员甲", 请求号="API-M-1"))
        self.assertTrue(resp["ok"], resp)
        resp = submit_supplement(ticket_id, SupplementPayload(
            来源="设备补报", 补测数值="98", 设备编号="HUM-SENSOR-07", 请求号="API-D-1"))
        self.assertTrue(resp["ok"], resp)

        # 受理人工补验
        resp = accept_supplement(ticket_id, AcceptPayload(补测ID=1))
        self.assertTrue(resp["ok"], resp)

        # 打开核验单确认哪次受理、另一条怎样办理
        cred = get_credential(ticket_id)["credential"]
        self.assertTrue(cred["可转干燥"])
        self.assertEqual(cred["受理补测"]["来源"], "人工补验")
        others = [s for s in cred["补测列表"] if s["状态"] == "不采用"]
        self.assertEqual(len(others), 1)
        self.assertEqual(others[0]["来源"], "设备补报")

        # 干燥台领料：凭已受理核验单领料，可查到所用的补测
        resp = drying_claim(ClaimPayload(
            发酵记录ID=int(ferm["id"]), 请求号="API-CLAIM-1",
            values={"起始温度": "60", "终止温度": "85", "干燥时长": "3小时", "含水率": "6"}))
        self.assertTrue(resp["ok"], resp)
        entry = resp["entry"]
        self.assertEqual(entry["领料状态"], "已领料")
        self.assertEqual(entry["核验单ID"], ticket_id)
        self.assertEqual(entry["受理数值"], "80")


if __name__ == "__main__":
    unittest.main()
