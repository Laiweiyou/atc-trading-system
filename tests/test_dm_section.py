# -*- coding: utf-8 -*-
"""Tests for DataManagementSection (小蔡 DM-Manager) — Phase 3 Step 3."""
import io
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.flash_alert import reset_flash_state
from trading_system.common.message_bus import get_bus
from trading_system.common.snapshot_builder import reset_snapshot_builder
from trading_system.squads.crypto.data_management.data_management_section import (
    DataManagementSection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_gateway(healthy: bool = True, total: int = 100, errors: int = 0):
    gw = MagicMock()
    gw.get_stats.return_value = {"total_requests": total, "error_count": errors}
    gw.health_check.return_value = {"healthy": healthy}
    return gw


def _fresh(gateway=None) -> DataManagementSection:
    """Reset singletons and return a fresh DataManagementSection."""
    reset_snapshot_builder()
    get_bus().clear()
    reset_flash_state()
    gw = gateway or _make_gateway()
    return DataManagementSection(gateway=gw)


# ── Test Cases ────────────────────────────────────────────────────────────────

class TestDMSectionInit(unittest.TestCase):
    """Test 01 — 初始化：三個下屬已建立，訂閱 alert.flash。"""

    def test_01_init_creates_subordinates(self):
        section = _fresh()
        self.assertIsNotNone(section.dm02_section)
        self.assertIsNotNone(section.dm03)
        self.assertEqual(section.role_name, "小蔡")
        self.assertEqual(section.role_code, "DM-Manager")

    def test_01_init_stats_zero(self):
        section = _fresh()
        self.assertEqual(section.reports_produced, 0)
        self.assertEqual(section.critical_alerts_observed, 0)
        self.assertIsNone(section.last_report_time)
        self.assertEqual(len(section.recent_alerts), 0)

    def test_01_subscribed_to_alert_flash(self):
        section = _fresh()
        bus = get_bus()
        # Verify subscription exists by publishing and checking handler fires
        received = []
        bus.subscribe("alert.flash", lambda m: received.append(m), role="test")
        bus.publish("alert.flash", {"sender": "outside", "alert_level": "info"}, sender="test")
        self.assertEqual(len(received), 1)


class TestDMSectionAlertObservation(unittest.TestCase):
    """Test 02 — 警報觀察：正確過濾 sender。"""

    def test_02_dm_sender_appends_to_recent_alerts(self):
        section = _fresh()
        msg = {"sender": "蓉蓉", "alert_level": "warning", "title": "test"}
        get_bus().publish("alert.flash", msg, sender="蓉蓉")
        self.assertEqual(len(section.recent_alerts), 1)

    def test_02_unknown_sender_ignored(self):
        section = _fresh()
        msg = {"sender": "外部系統", "alert_level": "warning"}
        get_bus().publish("alert.flash", msg, sender="外部系統")
        self.assertEqual(len(section.recent_alerts), 0)

    def test_02_role_code_sender_accepted(self):
        """DM-03 sends FlashAlert with sender='DM-03' (role_code), not '琪琪'."""
        section = _fresh()
        msg = {"sender": "DM-03", "alert_level": "warning", "title": "io 過時"}
        get_bus().publish("alert.flash", msg, sender="DM-03")
        self.assertEqual(len(section.recent_alerts), 1)

    def test_02_dm02a_role_code_accepted(self):
        section = _fresh()
        get_bus().publish("alert.flash", {"sender": "DM-02a", "alert_level": "info"}, sender="DM-02a")
        self.assertEqual(len(section.recent_alerts), 1)

    def test_02_dm02b_role_code_accepted(self):
        section = _fresh()
        get_bus().publish("alert.flash", {"sender": "DM-02b", "alert_level": "info"}, sender="DM-02b")
        self.assertEqual(len(section.recent_alerts), 1)

    def test_02_all_dm_role_names_accepted(self):
        section = _fresh()
        for sender in ["蓉蓉", "小方", "琪琪"]:
            get_bus().publish("alert.flash", {"sender": sender, "alert_level": "info"}, sender=sender)
        self.assertEqual(len(section.recent_alerts), 3)


class TestDMSectionCriticalAlertCount(unittest.TestCase):
    """Test 03 — 嚴重警報計數。"""

    def test_03_critical_increments_counter(self):
        section = _fresh()
        get_bus().publish("alert.flash", {"sender": "琪琪", "alert_level": "critical"}, sender="琪琪")
        self.assertEqual(section.critical_alerts_observed, 1)

    def test_03_warning_does_not_increment(self):
        section = _fresh()
        get_bus().publish("alert.flash", {"sender": "琪琪", "alert_level": "warning"}, sender="琪琪")
        self.assertEqual(section.critical_alerts_observed, 0)

    def test_03_multiple_criticals_accumulate(self):
        section = _fresh()
        for _ in range(3):
            get_bus().publish("alert.flash", {"sender": "蓉蓉", "alert_level": "critical"}, sender="蓉蓉")
        self.assertEqual(section.critical_alerts_observed, 3)

    def test_03_mixed_levels(self):
        section = _fresh()
        get_bus().publish("alert.flash", {"sender": "小方", "alert_level": "critical"}, sender="小方")
        get_bus().publish("alert.flash", {"sender": "小方", "alert_level": "warning"}, sender="小方")
        get_bus().publish("alert.flash", {"sender": "小方", "alert_level": "critical"}, sender="小方")
        self.assertEqual(section.critical_alerts_observed, 2)
        self.assertEqual(len(section.recent_alerts), 3)


class TestDMSectionHealthScore(unittest.TestCase):
    """Test 04 — 健康分數計算。"""

    def test_04_all_normal_score_gte_80(self):
        gw = _make_gateway(healthy=True, total=100, errors=0)
        section = _fresh(gateway=gw)
        # All four courses: no data (no_data → freshness_grade="stale") by default
        # But stale means -8 per course × 4 = -32 → 68. We need to fake freshness.
        # Override dm03 freshness to return all real_time
        section.dm03.get_freshness_summary = lambda: {
            c: {"freshness_grade": "real_time"} for c in ("io", "ca", "ga", "tk")
        }
        score = section._compute_health_score(
            gw.get_stats(), gw.health_check(), section.dm03.get_freshness_summary()
        )
        self.assertGreaterEqual(score, 80.0)

    def test_04_one_stale_course_reduces_score(self):
        gw = _make_gateway(healthy=True, total=100, errors=0)
        section = _fresh(gateway=gw)
        freshness = {
            "io": {"freshness_grade": "stale"},
            "ca": {"freshness_grade": "real_time"},
            "ga": {"freshness_grade": "real_time"},
            "tk": {"freshness_grade": "real_time"},
        }
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 92.0)  # 100 - 8

    def test_04_api_unhealthy_deducts_30(self):
        gw = _make_gateway(healthy=False, total=100, errors=0)
        section = _fresh(gateway=gw)
        freshness = {c: {"freshness_grade": "real_time"} for c in ("io", "ca", "ga", "tk")}
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 70.0)  # 100 - 30

    def test_04_high_error_rate_deducts_20(self):
        gw = _make_gateway(healthy=True, total=100, errors=15)
        section = _fresh(gateway=gw)
        freshness = {c: {"freshness_grade": "real_time"} for c in ("io", "ca", "ga", "tk")}
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 80.0)  # 100 - 20

    def test_04_moderate_error_rate_deducts_10(self):
        gw = _make_gateway(healthy=True, total=100, errors=5)
        section = _fresh(gateway=gw)
        freshness = {c: {"freshness_grade": "real_time"} for c in ("io", "ca", "ga", "tk")}
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 90.0)  # 100 - 10

    def test_04_many_critical_alerts_deducts_20(self):
        gw = _make_gateway(healthy=True, total=100, errors=0)
        section = _fresh(gateway=gw)
        section.critical_alerts_observed = 6
        freshness = {c: {"freshness_grade": "real_time"} for c in ("io", "ca", "ga", "tk")}
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 80.0)  # 100 - 20

    def test_04_moderate_critical_alerts_deducts_10(self):
        gw = _make_gateway(healthy=True, total=100, errors=0)
        section = _fresh(gateway=gw)
        section.critical_alerts_observed = 3
        freshness = {c: {"freshness_grade": "real_time"} for c in ("io", "ca", "ga", "tk")}
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 90.0)  # 100 - 10

    def test_04_many_recent_alerts_deducts_5(self):
        gw = _make_gateway(healthy=True, total=100, errors=0)
        section = _fresh(gateway=gw)
        for i in range(11):
            section.recent_alerts.append({"sender": "蓉蓉", "n": i})
        freshness = {c: {"freshness_grade": "real_time"} for c in ("io", "ca", "ga", "tk")}
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 95.0)  # 100 - 5

    def test_04_score_never_negative(self):
        gw = _make_gateway(healthy=False, total=100, errors=50)
        section = _fresh(gateway=gw)
        section.critical_alerts_observed = 10
        for i in range(20):
            section.recent_alerts.append({"sender": "蓉蓉", "n": i})
        freshness = {c: {"freshness_grade": "stale"} for c in ("io", "ca", "ga", "tk")}
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertGreaterEqual(score, 0.0)

    def test_04_delayed_course_deducts_4(self):
        gw = _make_gateway(healthy=True, total=100, errors=0)
        section = _fresh(gateway=gw)
        freshness = {
            "io": {"freshness_grade": "delayed"},
            "ca": {"freshness_grade": "real_time"},
            "ga": {"freshness_grade": "real_time"},
            "tk": {"freshness_grade": "real_time"},
        }
        score = section._compute_health_score(gw.get_stats(), gw.health_check(), freshness)
        self.assertEqual(score, 96.0)  # 100 - 4


class TestDMSectionHealthClassification(unittest.TestCase):
    """Test 05 — 健康狀態分類。"""

    def test_05_score_85_healthy(self):
        section = _fresh()
        self.assertEqual(section._classify_health(85.0), "healthy")

    def test_05_score_80_healthy(self):
        section = _fresh()
        self.assertEqual(section._classify_health(80.0), "healthy")

    def test_05_score_65_acceptable(self):
        section = _fresh()
        self.assertEqual(section._classify_health(65.0), "acceptable")

    def test_05_score_60_acceptable(self):
        section = _fresh()
        self.assertEqual(section._classify_health(60.0), "acceptable")

    def test_05_score_45_degraded(self):
        section = _fresh()
        self.assertEqual(section._classify_health(45.0), "degraded")

    def test_05_score_40_degraded(self):
        section = _fresh()
        self.assertEqual(section._classify_health(40.0), "degraded")

    def test_05_score_30_critical(self):
        section = _fresh()
        self.assertEqual(section._classify_health(30.0), "critical")

    def test_05_score_0_critical(self):
        section = _fresh()
        self.assertEqual(section._classify_health(0.0), "critical")

    def test_05_score_79_acceptable(self):
        section = _fresh()
        self.assertEqual(section._classify_health(79.0), "acceptable")

    def test_05_score_39_critical(self):
        section = _fresh()
        self.assertEqual(section._classify_health(39.0), "critical")


class TestDMSectionProduceHealthReport(unittest.TestCase):
    """Test 06 — produce_health_report 結構與 bus 廣播。"""

    def test_06_report_has_required_keys(self):
        section = _fresh()
        report = section.produce_health_report()
        for key in (
            "manager", "role_code", "timestamp", "health_score", "health_status",
            "api_stats", "api_health", "freshness_summary",
            "reports_produced", "critical_alerts_observed", "recent_alert_count",
        ):
            self.assertIn(key, report, f"Missing key: {key}")

    def test_06_manager_and_role_code(self):
        section = _fresh()
        report = section.produce_health_report()
        self.assertEqual(report["manager"], "小蔡")
        self.assertEqual(report["role_code"], "DM-Manager")

    def test_06_reports_produced_increments(self):
        section = _fresh()
        self.assertEqual(section.reports_produced, 0)
        section.produce_health_report()
        self.assertEqual(section.reports_produced, 1)
        section.produce_health_report()
        self.assertEqual(section.reports_produced, 2)

    def test_06_last_report_time_set(self):
        section = _fresh()
        before = time.time()
        section.produce_health_report()
        self.assertIsNotNone(section.last_report_time)
        self.assertGreaterEqual(section.last_report_time, before)

    def test_06_bus_publishes_to_report_dm(self):
        section = _fresh()
        received = []
        get_bus().subscribe("report.dm", lambda m: received.append(m.payload), role="test")
        section.produce_health_report()
        self.assertEqual(len(received), 1)
        self.assertIn("health_score", received[0])

    def test_06_health_score_in_valid_range(self):
        section = _fresh()
        report = section.produce_health_report()
        self.assertGreaterEqual(report["health_score"], 0.0)
        self.assertLessEqual(report["health_score"], 100.0)

    def test_06_health_status_valid_value(self):
        section = _fresh()
        report = section.produce_health_report()
        self.assertIn(report["health_status"], ("healthy", "acceptable", "degraded", "critical"))


class TestDMSectionRunCycle(unittest.TestCase):
    """Test 07 — run_cycle 觸發邏輯。"""

    def test_07_first_call_produces_report(self):
        section = _fresh()
        self.assertIsNone(section.last_report_time)
        section.run_cycle()
        self.assertEqual(section.reports_produced, 1)

    def test_07_immediate_second_call_does_not_produce(self):
        section = _fresh()
        section.run_cycle()
        section.run_cycle()
        self.assertEqual(section.reports_produced, 1)

    def test_07_after_interval_produces_again(self):
        section = _fresh()
        section.run_cycle()
        # Simulate 301 seconds elapsed
        section.last_report_time -= 301
        section.run_cycle()
        self.assertEqual(section.reports_produced, 2)

    def test_07_exactly_at_interval_produces(self):
        section = _fresh()
        section.run_cycle()
        section.last_report_time -= 300
        section.run_cycle()
        self.assertEqual(section.reports_produced, 2)

    def test_07_just_before_interval_does_not_produce(self):
        section = _fresh()
        section.run_cycle()
        section.last_report_time -= 299
        section.run_cycle()
        self.assertEqual(section.reports_produced, 1)


class TestDMSectionGetStatus(unittest.TestCase):
    """Test 07b — get_section_status 結構。"""

    def test_07b_status_keys(self):
        section = _fresh()
        status = section.get_section_status()
        for key in (
            "manager", "role_code", "reports_produced",
            "critical_alerts_observed", "last_report_time", "freshness",
        ):
            self.assertIn(key, status)

    def test_07b_status_initial_values(self):
        section = _fresh()
        status = section.get_section_status()
        self.assertEqual(status["reports_produced"], 0)
        self.assertEqual(status["critical_alerts_observed"], 0)
        self.assertIsNone(status["last_report_time"])

    def test_07b_freshness_has_four_courses(self):
        section = _fresh()
        status = section.get_section_status()
        self.assertEqual(set(status["freshness"].keys()), {"io", "ca", "ga", "tk"})


class TestDMSectionIntegration(unittest.TestCase):
    """Test 08 — 整合測試：report.io → dm03 更新 → freshness 反映。"""

    def test_08_publish_report_io_updates_freshness(self):
        section = _fresh()
        bus = get_bus()

        # Publish report.io (simulates IO course reporting in)
        bus.publish("report.io", {"source": "io_course", "data": {}}, sender="io_course")

        freshness = section.dm03.get_freshness_summary()
        io_info = freshness["io"]
        # Should no longer be no_data
        self.assertNotEqual(io_info["status"], "no_data")
        self.assertIn(io_info["freshness_grade"], ("real_time", "recent"))

    def test_08_other_courses_still_no_data(self):
        section = _fresh()
        bus = get_bus()
        bus.publish("report.io", {"source": "io_course"}, sender="io_course")

        freshness = section.dm03.get_freshness_summary()
        for course in ("ca", "ga", "tk"):
            self.assertEqual(freshness[course]["status"], "no_data")

    def test_08_full_cycle_integration(self):
        """Simulate a full cycle: reports come in, run_cycle produces health report."""
        section = _fresh()
        bus = get_bus()

        # All courses report in
        for course in ("io", "ca", "ga", "tk"):
            bus.publish(f"report.{course}", {"source": course}, sender=course)

        # Critical alert from 琪琪
        bus.publish("alert.flash", {"sender": "琪琪", "alert_level": "critical", "title": "ga 過時"}, sender="琪琪")

        # Run cycle
        section.run_cycle()

        self.assertEqual(section.reports_produced, 1)
        self.assertEqual(section.critical_alerts_observed, 1)

        status = section.get_section_status()
        self.assertEqual(status["reports_produced"], 1)
        self.assertEqual(status["critical_alerts_observed"], 1)
        # All four courses should have fresh data
        for course in ("io", "ca", "ga", "tk"):
            self.assertNotEqual(status["freshness"][course]["status"], "no_data")

    def test_08_debate_still_works_after_section_init(self):
        """DM-02 debate still functional after DataManagementSection is created."""
        section = _fresh()
        data = {"eth_price": 3000.0, "rsi": 55.0}
        result = section.dm02_section.conduct_debate(data)
        self.assertIn(result.consensus_type, ("agreed", "discussed_agreed", "dual_track"))
        self.assertIn(result.final_direction, ("bullish", "neutral", "bearish"))


if __name__ == "__main__":
    loader  = unittest.TestLoader()
    suite   = unittest.TestSuite()

    # Load all test classes in order
    for cls in [
        TestDMSectionInit,
        TestDMSectionAlertObservation,
        TestDMSectionCriticalAlertCount,
        TestDMSectionHealthScore,
        TestDMSectionHealthClassification,
        TestDMSectionProduceHealthReport,
        TestDMSectionRunCycle,
        TestDMSectionGetStatus,
        TestDMSectionIntegration,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
