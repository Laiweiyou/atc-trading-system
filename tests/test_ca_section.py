# -*- coding: utf-8 -*-
"""Tests for 靜姐（CA 課主管）TechnicalSection — Phase 3 Step 11."""
import io
import sys
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import CourseReport, DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.technical.technical_section import TechnicalSection


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_subreport(direction, confidence, stale=False, data_used=None):
    return SubReport(
        role_name      = "test",
        role_code      = "TEST",
        direction      = direction,
        sub_confidence = confidence,
        reasoning      = "test",
        data_used      = data_used or {},
        timestamp      = datetime.now(),
        staleness_flag = stale,
    )


def _make_debate(direction, confidence, consensus_type="agreed",
                 stale_a=False, stale_b=False, data_used_a=None):
    ra = _make_subreport(direction, confidence, stale=stale_a, data_used=data_used_a)
    rb = _make_subreport(direction, confidence, stale=stale_b)
    return DebateResult(
        debate_id          = "test-debate-id",
        report_a           = ra,
        report_b           = rb,
        consensus_type     = consensus_type,
        final_direction    = direction,
        final_confidence   = confidence,
        combined_reasoning = "test",
        key_disagreement   = "test disagreement" if consensus_type == "dual_track" else None,
        timestamp          = datetime.now(),
    )


def _fresh_section():
    get_bus().clear()
    return TechnicalSection(gateway=MagicMock())


def _inject_mocks(section, ca01_report=None, ca02_debate=None, ca03_debate=None):
    if ca01_report is not None:
        section.ca_01.compute_with_review = MagicMock(return_value=ca01_report)
    if ca02_debate is not None:
        section.ca_02.conduct_debate = MagicMock(return_value=ca02_debate)
    if ca03_debate is not None:
        section.ca_03.conduct_debate = MagicMock(return_value=ca03_debate)


def _inject_all_bullish(section, c01=0.7, c02=0.6, c03=0.5):
    """All three sections return bullish agreed results."""
    ca01 = _make_subreport("bullish", c01)
    ca02 = _make_debate("bullish", c02)
    ca03 = _make_debate("bullish", c03)
    _inject_mocks(section, ca01_report=ca01, ca02_debate=ca02, ca03_debate=ca03)
    return ca01, ca02, ca03


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCaSection(unittest.TestCase):

    # ── 01: 初始化三組 + 訂閱 ca.request_report ───────────────────────────────

    def test_01_init_subsections_and_subscription(self):
        section = _fresh_section()

        self.assertTrue(hasattr(section, "ca_01"))
        self.assertTrue(hasattr(section, "ca_02"))
        self.assertTrue(hasattr(section, "ca_03"))
        self.assertEqual(section.weights["ca_01"], 0.35)
        self.assertEqual(section.weights["ca_02"], 0.40)
        self.assertEqual(section.weights["ca_03"], 0.25)
        self.assertIn("靜姐", get_bus().get_subscribers("ca.request_report"))

    # ── 02: 三組全 bullish → +0.1 一致加成 ─────────────────────────────────

    def test_02_all_bullish_consensus_bonus(self):
        # composite = 0.7*0.35 + 0.6*0.40 + 0.5*0.25 = 0.245+0.24+0.125 = 0.61
        # all same direction → +0.1 → 0.71
        section   = _fresh_section()
        ca01      = _make_subreport("bullish", 0.7)
        ca02      = _make_debate("bullish", 0.6)
        ca03      = _make_debate("bullish", 0.5)

        direction, confidence = section._compute_course_score(ca01, ca02, ca03)

        self.assertEqual(direction, "bullish")
        self.assertAlmostEqual(confidence, 0.71, places=5)

    # ── 03: 三組分歧 → neutral 低信心 ────────────────────────────────────────

    def test_03_divergence_yields_neutral(self):
        # 0.8*0.35 - 0.5*0.40 + 0*0.25 = 0.28 - 0.20 = 0.08  → |composite| < 0.1
        section = _fresh_section()
        ca01    = _make_subreport("bullish", 0.8)
        ca02    = _make_debate("bearish",  0.5)
        ca03    = _make_debate("neutral",  0.3)

        direction, confidence = section._compute_course_score(ca01, ca02, ca03)

        self.assertEqual(direction, "neutral")
        self.assertLess(confidence, 0.1)

    # ── 04: staleness 歸零並重正規化 ─────────────────────────────────────────

    def test_04_staleness_zeroes_weight_and_renormalizes(self):
        # ca_01 stale → weight=0; remaining ca_02=0.40, ca_03=0.25, total=0.65
        # composite = 0 + 0.8*(0.40/0.65) + 0.6*(0.25/0.65)
        section = _fresh_section()
        ca01    = _make_subreport("neutral", 0.1, stale=True)
        ca02    = _make_debate("bullish", 0.8)
        ca03    = _make_debate("bullish", 0.6)

        direction, confidence = section._compute_course_score(ca01, ca02, ca03)

        self.assertEqual(direction, "bullish")
        expected = 0.8 * (0.40 / 0.65) + 0.6 * (0.25 / 0.65)
        self.assertAlmostEqual(confidence, expected, places=5)

    # ── 05: dual_track 懲罰（CA-02 or CA-03 分歧時）──────────────────────────

    def test_05_dual_track_penalty(self):
        # ca02 dual_track; ca03 agreed neutral → dual_count=1
        # composite = 0.7*0.35 + 0.6*0.40 + 0 = 0.485
        # penalty factor = 1 - 0.15 = 0.85
        # directions: bullish / bullish / neutral → not all same → no bonus
        section = _fresh_section()
        ca01    = _make_subreport("bullish", 0.7)
        ca02    = _make_debate("bullish", 0.6, consensus_type="dual_track")
        ca03    = _make_debate("neutral", 0.3, consensus_type="agreed")

        direction, confidence = section._compute_course_score(ca01, ca02, ca03)

        self.assertEqual(direction, "bullish")
        expected = (0.7 * 0.35 + 0.6 * 0.40) * 0.85
        self.assertAlmostEqual(confidence, expected, places=5)

    # ── 06: produce_course_report 回傳 CourseReport 並廣播 ───────────────────

    def test_06_produce_course_report_publishes_to_bus(self):
        section = _fresh_section()
        _inject_all_bullish(section)

        received = []
        get_bus().subscribe("report.ca", lambda msg: received.append(msg.payload), role="test")

        report = section.produce_course_report()

        self.assertIsInstance(report, CourseReport)
        self.assertEqual(report.course_code,   "CA")
        self.assertEqual(report.manager_name,  "靜姐")
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], report)
        self.assertEqual(section.reports_produced, 1)
        self.assertIsNotNone(section.last_report_time)

    # ── 07: _wrap_ca01_as_debate 格式驗證 ────────────────────────────────────

    def test_07_wrap_ca01_as_debate(self):
        section = _fresh_section()
        sr      = _make_subreport("bearish", 0.65)

        d = section._wrap_ca01_as_debate(sr)

        self.assertIsInstance(d, DebateResult)
        self.assertTrue(d.debate_id.startswith("CA-01-"))
        self.assertEqual(d.consensus_type,   "agreed")
        self.assertEqual(d.final_direction,  "bearish")
        self.assertAlmostEqual(d.final_confidence, 0.65)
        self.assertIs(d.report_a, sr)
        self.assertIs(d.report_b, sr)
        self.assertIsNone(d.key_disagreement)

    # ── 08: run_cycle 節流（60 秒間隔）────────────────────────────────────────

    def test_08_run_cycle_throttles_at_60s(self):
        section      = _fresh_section()
        mock_produce = MagicMock()
        section.produce_course_report = mock_produce

        # First call: no last_report_time → fires
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 1)

        # Simulate just-produced: too recent → skips
        section.last_report_time = time.time()
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 1)

        # Simulate 61 seconds elapsed → fires again
        section.last_report_time = time.time() - 61
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 2)

    # ── 09: bus "ca.request_report" 主動觸發 ──────────────────────────────────

    def test_09_bus_request_triggers_produce(self):
        section = _fresh_section()
        _inject_all_bullish(section)

        produced = []
        get_bus().subscribe("report.ca", lambda msg: produced.append(msg), role="test")

        get_bus().publish("ca.request_report", {}, sender="test-requester")

        self.assertEqual(len(produced), 1)

    # ── 10: 整合測試（CourseReport 欄位完整）─────────────────────────────────

    def test_10_full_integration_course_report_fields(self):
        section = _fresh_section()
        _inject_all_bullish(section)

        report = section.produce_course_report()

        self.assertEqual(report.course_name, "技術分析課")
        self.assertEqual(len(report.debate_results), 3)
        self.assertEqual(report.freshness_grade, "real_time")
        self.assertIn("ca_01_indicators",    report.data_health)
        self.assertIn("ca_02_structure",     report.data_health)
        self.assertIn("ca_03_volume",        report.data_health)
        self.assertIn("anomaly_events_count",report.data_health)
        self.assertIsInstance(report.flash_alerts, list)
        self.assertIn("reasoning",           report.self_review)
        self.assertIn("anomalies_detected",  report.self_review)
        self.assertIn("指標:",               report.self_review["reasoning"])
        self.assertIn("結構:",               report.self_review["reasoning"])
        self.assertIn("量能:",               report.self_review["reasoning"])

    # ── 11: dual_track flash_alert 列入 flash_alerts ──────────────────────────

    def test_11_dual_track_appears_in_flash_alerts(self):
        section = _fresh_section()
        ca01    = _make_subreport("neutral", 0.3)
        ca02    = _make_debate("bearish", 0.5, consensus_type="dual_track")
        ca03    = _make_debate("neutral", 0.3)
        _inject_mocks(section, ca01_report=ca01, ca02_debate=ca02, ca03_debate=ca03)

        report = section.produce_course_report()

        self.assertTrue(any("CA-02" in a for a in report.flash_alerts))

    # ── 12: anomaly_count 寫入 flash_alerts 和 data_health ───────────────────

    def test_12_anomaly_count_in_flash_alerts(self):
        section = _fresh_section()
        ca01    = _make_subreport("bullish", 0.6)
        ca02    = _make_debate("bullish", 0.5)
        # ca03's report_a.data_used["anomaly_count"] = 2
        ca03    = _make_debate("bullish", 0.4, data_used_a={"anomaly_count": 2})
        _inject_mocks(section, ca01_report=ca01, ca02_debate=ca02, ca03_debate=ca03)

        report = section.produce_course_report()

        self.assertTrue(any("2 個異常事件" in a for a in report.flash_alerts))
        self.assertEqual(report.data_health["anomaly_events_count"], 2)

    # ── 13: all stale → neutral 0.1 ──────────────────────────────────────────

    def test_13_all_stale_returns_neutral_low_confidence(self):
        section = _fresh_section()
        ca01    = _make_subreport("neutral", 0.1, stale=True)
        ca02    = _make_debate("neutral", 0.1, stale_a=True, stale_b=True)
        ca03    = _make_debate("neutral", 0.1, stale_a=True, stale_b=True)

        direction, confidence = section._compute_course_score(ca01, ca02, ca03)

        self.assertEqual(direction, "neutral")
        self.assertAlmostEqual(confidence, 0.1)

    # ── 14: get_section_status 結構完整 ─────────────────────────────────────

    def test_14_get_section_status_structure(self):
        section = _fresh_section()
        status  = section.get_section_status()

        self.assertEqual(status["manager"], "靜姐")
        self.assertIn("reports_produced", status)
        self.assertIn("weights",          status)
        self.assertIsNone(status["latest_report"])

    # ── 15: 兩個 dual_track → 最大懲罰 0.30 ─────────────────────────────────

    def test_15_two_dual_track_max_penalty(self):
        # ca02 dual_track + ca03 dual_track → dual_count=2, penalty=1-0.30=0.70
        # composite = 0.7*0.35 + 0.6*0.40 + 0.5*0.25 = 0.61
        # after penalty: 0.61 * 0.70 = 0.427
        # all bullish → +0.1 → 0.527
        section = _fresh_section()
        ca01    = _make_subreport("bullish", 0.7)
        ca02    = _make_debate("bullish", 0.6, consensus_type="dual_track")
        ca03    = _make_debate("bullish", 0.5, consensus_type="dual_track")

        direction, confidence = section._compute_course_score(ca01, ca02, ca03)

        self.assertEqual(direction, "bullish")
        base     = 0.7 * 0.35 + 0.6 * 0.40 + 0.5 * 0.25   # 0.61
        penalised = base * (1 - 0.15 * 2)                   # 0.61 * 0.70
        expected  = min(penalised + 0.1, 0.95)              # + bonus (all bullish)
        self.assertAlmostEqual(confidence, expected, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
