# -*- coding: utf-8 -*-
"""Tests for AU-02 英姐 SystemHealthMonitor."""
import io
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── 隔離 bus 單例 ────────────────────────────────────────────────────────────
from trading_system.common.message_bus import get_bus
from trading_system.common.flash_alert import reset_flash_state


def _fresh():
    get_bus().clear()
    reset_flash_state()


def _make_monitor(
    roles=None,
    channels=None,
    gateway=None,
):
    """建立 SystemHealthMonitor，預設合理參數。"""
    from trading_system.squads.crypto.monitoring.au_02_system_health import SystemHealthMonitor
    _fresh()
    if roles is None:
        roles = ["EX-01", "EX-02", "EX-03", "AU-01"]
    if channels is None:
        channels = ["execution.result", "alert.flash"]
    if gateway is None:
        gw = MagicMock()
        gw.get_stats.return_value = {"total_requests": 0, "requests_last_min": 0}
    else:
        gw = gateway
    return SystemHealthMonitor(tracked_roles=roles, tracked_channels=channels, gateway=gw)


# ─────────────────────────────────────────────────────────────────────────────
# Test 01 — 初始化與訂閱
# ─────────────────────────────────────────────────────────────────────────────
class Test01_Init(unittest.TestCase):
    def test_initial_state(self):
        mon = _make_monitor()
        self.assertEqual(mon.current_health, "healthy")
        self.assertEqual(mon.total_messages, 0)
        self.assertEqual(mon.last_cpu_pct, 0.0)
        self.assertIsNone(mon.health_changed_at)

    def test_subscribes_to_tracked_channels(self):
        channels = ["execution.result", "alert.flash"]
        mon = _make_monitor(channels=channels)
        bus = get_bus()
        self.assertIn(_("AU-02"), bus.get_subscribers("execution.result"))
        self.assertIn(_("AU-02"), bus.get_subscribers("alert.flash"))
        self.assertIn(_("AU-02"), bus.get_subscribers("system.warning"))

    def test_subscribes_to_system_warning(self):
        mon = _make_monitor()
        self.assertIn(_("AU-02"), get_bus().get_subscribers("system.warning"))


def _(role_code):
    """Helper: role code string passthrough."""
    return role_code


# ─────────────────────────────────────────────────────────────────────────────
# Test 02 — update_role_activity & check_role_liveness
# ─────────────────────────────────────────────────────────────────────────────
class Test02_RoleLiveness(unittest.TestCase):
    def test_never_reported_is_missing(self):
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        result = mon.check_role_liveness()
        self.assertIn("EX-01", result["missing"])
        self.assertIn("EX-02", result["missing"])
        self.assertEqual(result["active"], [])
        self.assertEqual(result["stale"], [])

    def test_just_updated_is_active(self):
        mon = _make_monitor(roles=["EX-01"])
        mon.update_role_activity("EX-01")
        result = mon.check_role_liveness()
        self.assertIn("EX-01", result["active"])
        self.assertNotIn("EX-01", result["stale"])
        self.assertNotIn("EX-01", result["missing"])

    def test_stale_boundary(self):
        mon = _make_monitor(roles=["EX-01"])
        # 人工設定時間為 61 秒前
        mon.role_activity["EX-01"] = time.time() - 61
        result = mon.check_role_liveness()
        self.assertIn("EX-01", result["stale"])

    def test_missing_boundary(self):
        mon = _make_monitor(roles=["EX-01"])
        # 人工設定時間為 301 秒前
        mon.role_activity["EX-01"] = time.time() - 301
        result = mon.check_role_liveness()
        self.assertIn("EX-01", result["missing"])

    def test_update_multiple_roles(self):
        mon = _make_monitor(roles=["EX-01", "EX-02", "EX-03"])
        mon.update_role_activity("EX-01")
        mon.update_role_activity("EX-02")
        result = mon.check_role_liveness()
        self.assertIn("EX-01", result["active"])
        self.assertIn("EX-02", result["active"])
        self.assertIn("EX-03", result["missing"])


# ─────────────────────────────────────────────────────────────────────────────
# Test 03 — _track_message & check_message_flow
# ─────────────────────────────────────────────────────────────────────────────
class Test03_MessageFlow(unittest.TestCase):
    def test_track_message_via_bus(self):
        mon = _make_monitor(channels=["execution.result"])
        bus = get_bus()
        bus.publish("execution.result", {"status": "FILLED"}, sender="EX-01")
        flow = mon.check_message_flow()
        self.assertEqual(flow["total_messages"], 1)
        self.assertEqual(flow["by_channel"].get("execution.result", 0), 1)

    def test_multiple_channels_counted_separately(self):
        mon = _make_monitor(channels=["execution.result", "alert.flash"])
        bus = get_bus()
        bus.publish("execution.result", {}, sender="EX-01")
        bus.publish("execution.result", {}, sender="EX-01")
        bus.publish("alert.flash", {}, sender="AU-01")
        flow = mon.check_message_flow()
        self.assertEqual(flow["by_channel"].get("execution.result", 0), 2)
        self.assertEqual(flow["by_channel"].get("alert.flash", 0), 1)
        self.assertEqual(flow["total_messages"], 3)

    def test_track_message_updates_sender_activity(self):
        mon = _make_monitor(
            roles=["EX-01"],
            channels=["execution.result"],
        )
        bus = get_bus()
        bus.publish("execution.result", {}, sender="EX-01")
        result = mon.check_role_liveness()
        self.assertIn("EX-01", result["active"])

    def test_system_warning_channel_tracked(self):
        mon = _make_monitor()
        bus = get_bus()
        bus.publish("system.warning", {"msg": "test"}, sender="EX-03")
        flow = mon.check_message_flow()
        self.assertGreaterEqual(flow["total_messages"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# Test 04 — check_system_resources
# ─────────────────────────────────────────────────────────────────────────────
class Test04_SystemResources(unittest.TestCase):
    def test_returns_expected_keys(self):
        mon = _make_monitor()
        res = mon.check_system_resources()
        self.assertIn("cpu_pct", res)
        self.assertIn("memory_mb", res)
        self.assertIn("psutil_available", res)

    def test_without_psutil_returns_zeros(self):
        import trading_system.squads.crypto.monitoring.au_02_system_health as mod
        original = mod._HAS_PSUTIL
        mod._HAS_PSUTIL = False
        try:
            mon = _make_monitor()
            res = mon.check_system_resources()
            self.assertEqual(res["cpu_pct"], 0.0)
            self.assertEqual(res["memory_mb"], 0.0)
            self.assertFalse(res["psutil_available"])
        finally:
            mod._HAS_PSUTIL = original

    def test_updates_cached_values(self):
        mon = _make_monitor()
        mon.check_system_resources()
        self.assertIsNotNone(mon.last_resource_check)

    def test_with_psutil_returns_non_negative(self):
        import trading_system.squads.crypto.monitoring.au_02_system_health as mod
        if not mod._HAS_PSUTIL:
            self.skipTest("psutil 未安裝")
        mon = _make_monitor()
        res = mon.check_system_resources()
        self.assertGreaterEqual(res["cpu_pct"], 0.0)
        self.assertGreater(res["memory_mb"], 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 05 — evaluate_health: healthy
# ─────────────────────────────────────────────────────────────────────────────
class Test05_EvaluateHealthy(unittest.TestCase):
    def test_all_active_is_healthy(self):
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        mon.update_role_activity("EX-01")
        mon.update_role_activity("EX-02")
        health = mon.evaluate_health()
        self.assertEqual(health, "healthy")
        self.assertEqual(mon.current_health, "healthy")

    def test_one_stale_still_healthy(self):
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        mon.update_role_activity("EX-01")
        mon.role_activity["EX-02"] = time.time() - 61  # stale
        health = mon.evaluate_health()
        self.assertEqual(health, "healthy")

    def test_no_flash_on_healthy(self):
        from trading_system.common.flash_alert import _sent_alerts
        mon = _make_monitor(roles=["EX-01"])
        mon.update_role_activity("EX-01")
        before = len(_sent_alerts)
        mon.evaluate_health()
        self.assertEqual(len(_sent_alerts), before)


# ─────────────────────────────────────────────────────────────────────────────
# Test 06 — evaluate_health: degraded
# ─────────────────────────────────────────────────────────────────────────────
class Test06_EvaluateDegraded(unittest.TestCase):
    def test_two_stale_is_degraded(self):
        mon = _make_monitor(roles=["EX-01", "EX-02", "EX-03"])
        mon.update_role_activity("EX-03")
        mon.role_activity["EX-01"] = time.time() - 61
        mon.role_activity["EX-02"] = time.time() - 61
        health = mon.evaluate_health()
        self.assertEqual(health, "degraded")

    def test_degraded_sends_flash_alert(self):
        from trading_system.common.flash_alert import _sent_alerts
        mon = _make_monitor(roles=["EX-01", "EX-02", "EX-03"])
        mon.update_role_activity("EX-03")
        mon.role_activity["EX-01"] = time.time() - 61
        mon.role_activity["EX-02"] = time.time() - 61
        before = len(_sent_alerts)
        mon.evaluate_health()
        self.assertGreater(len(_sent_alerts), before)

    def test_degraded_flash_is_anomaly_type(self):
        flashes = []
        mon = _make_monitor(roles=["EX-01", "EX-02", "EX-03"])
        get_bus().subscribe("alert.flash", lambda m: flashes.append(m.payload), role="TEST")
        mon.update_role_activity("EX-03")
        mon.role_activity["EX-01"] = time.time() - 61
        mon.role_activity["EX-02"] = time.time() - 61
        mon.evaluate_health()
        self.assertTrue(any(f.get("alert_type") == "ANOMALY_FLASH" for f in flashes))

    def test_health_changed_at_updated(self):
        mon = _make_monitor(roles=["EX-01", "EX-02", "EX-03"])
        mon.update_role_activity("EX-03")
        mon.role_activity["EX-01"] = time.time() - 61
        mon.role_activity["EX-02"] = time.time() - 61
        self.assertIsNone(mon.health_changed_at)
        mon.evaluate_health()
        self.assertIsNotNone(mon.health_changed_at)


# ─────────────────────────────────────────────────────────────────────────────
# Test 07 — evaluate_health: critical
# ─────────────────────────────────────────────────────────────────────────────
class Test07_EvaluateCritical(unittest.TestCase):
    def test_missing_role_is_critical(self):
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        mon.update_role_activity("EX-01")
        # EX-02 從未回報 → missing
        health = mon.evaluate_health()
        self.assertEqual(health, "critical")

    def test_critical_sends_data_offline_flash(self):
        flashes = []
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        get_bus().subscribe("alert.flash", lambda m: flashes.append(m.payload), role="TEST")
        mon.update_role_activity("EX-01")
        mon.evaluate_health()
        self.assertTrue(any(f.get("alert_type") == "DATA_OFFLINE" for f in flashes))

    def test_critical_requires_acknowledgment(self):
        flashes = []
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        get_bus().subscribe("alert.flash", lambda m: flashes.append(m.payload), role="TEST")
        mon.update_role_activity("EX-01")
        mon.evaluate_health()
        critical = [f for f in flashes if f.get("alert_type") == "DATA_OFFLINE"]
        self.assertTrue(all(f.get("requires_acknowledgment") for f in critical))

    def test_critical_targets_all(self):
        flashes = []
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        get_bus().subscribe("alert.flash", lambda m: flashes.append(m.payload), role="TEST")
        mon.update_role_activity("EX-01")
        mon.evaluate_health()
        offline = [f for f in flashes if f.get("alert_type") == "DATA_OFFLINE"]
        self.assertTrue(any("全員" in f.get("target_recipients", []) for f in offline))


# ─────────────────────────────────────────────────────────────────────────────
# Test 08 — evaluate_health 等級不重複發 Flash
# ─────────────────────────────────────────────────────────────────────────────
class Test08_NoRepeatFlash(unittest.TestCase):
    def test_same_health_no_repeated_flash(self):
        from trading_system.common.flash_alert import _sent_alerts
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        mon.update_role_activity("EX-01")
        # 第一次 → critical (EX-02 missing)
        mon.evaluate_health()
        count_after_first = len(_sent_alerts)
        # 第二次仍是 critical → 不重複發
        mon.evaluate_health()
        self.assertEqual(len(_sent_alerts), count_after_first)

    def test_health_change_triggers_new_flash(self):
        from trading_system.common.flash_alert import _sent_alerts
        mon = _make_monitor(roles=["EX-01", "EX-02"])
        mon.update_role_activity("EX-01")
        mon.evaluate_health()   # healthy → critical (EX-02 missing)
        count1 = len(_sent_alerts)
        # 修復 EX-02
        mon.update_role_activity("EX-02")
        # 回到 healthy → 不發 flash（只有惡化才發）
        mon.evaluate_health()
        # 再讓 EX-02 消失 → critical 再發一次
        del mon.role_activity["EX-02"]
        mon.current_health = "healthy"  # 手動重置以模擬狀態變化
        mon.evaluate_health()
        self.assertGreater(len(_sent_alerts), count1)


# ─────────────────────────────────────────────────────────────────────────────
# Test 09 — get_system_health_report
# ─────────────────────────────────────────────────────────────────────────────
class Test09_HealthReport(unittest.TestCase):
    def test_report_structure(self):
        mon = _make_monitor()
        report = mon.get_system_health_report()
        self.assertIn("role_liveness", report)
        self.assertIn("message_flow", report)
        self.assertIn("system_resources", report)
        self.assertIn("bus_subscribers", report)
        self.assertIn("gateway_stats", report)
        self.assertIn("health_summary", report)

    def test_report_includes_liveness_categories(self):
        mon = _make_monitor(roles=["EX-01"])
        mon.update_role_activity("EX-01")
        report = mon.get_system_health_report()
        liveness = report["role_liveness"]
        self.assertIn("active", liveness)
        self.assertIn("stale", liveness)
        self.assertIn("missing", liveness)

    def test_report_bus_subscribers_per_channel(self):
        mon = _make_monitor(channels=["execution.result"])
        report = mon.get_system_health_report()
        self.assertIn("execution.result", report["bus_subscribers"])

    def test_report_calls_gateway_stats(self):
        gw = MagicMock()
        gw.get_stats.return_value = {"total_requests": 42}
        mon = _make_monitor(gateway=gw)
        report = mon.get_system_health_report()
        self.assertEqual(report["gateway_stats"]["total_requests"], 42)
        gw.get_stats.assert_called_once()

    def test_report_health_summary_fields(self):
        mon = _make_monitor(roles=["EX-01"])
        mon.update_role_activity("EX-01")
        mon.evaluate_health()
        report = mon.get_system_health_report()
        hs = report["health_summary"]
        self.assertIn("current_health", hs)
        self.assertIn("health_reason", hs)
        self.assertIn("health_changed_at", hs)


# ─────────────────────────────────────────────────────────────────────────────
# Test 10 — run_cycle
# ─────────────────────────────────────────────────────────────────────────────
class Test10_RunCycle(unittest.TestCase):
    def test_run_cycle_checks_resources_first_time(self):
        mon = _make_monitor()
        self.assertIsNone(mon.last_resource_check)
        mon.run_cycle()
        self.assertIsNotNone(mon.last_resource_check)

    def test_run_cycle_skips_resource_within_interval(self):
        mon = _make_monitor()
        mon.run_cycle()
        t1 = mon.last_resource_check
        mon.run_cycle()
        t2 = mon.last_resource_check
        # 因為間隔未到 30 秒，last_resource_check 不應更新
        self.assertEqual(t1, t2)

    def test_run_cycle_triggers_resource_after_interval(self):
        mon = _make_monitor()
        mon.run_cycle()
        t1 = mon.last_resource_check
        # 人工推遲 30 秒
        mon.last_resource_check = time.time() - 31
        mon.run_cycle()
        t2 = mon.last_resource_check
        self.assertGreater(t2, t1)

    def test_run_cycle_evaluates_health(self):
        mon = _make_monitor(roles=["EX-01"])
        # EX-01 未回報 → 應為 critical
        mon.run_cycle()
        self.assertEqual(mon.current_health, "critical")

    def test_run_cycle_healthy_when_all_active(self):
        mon = _make_monitor(roles=["EX-01"])
        mon.update_role_activity("EX-01")
        mon.run_cycle()
        self.assertEqual(mon.current_health, "healthy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
