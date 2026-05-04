# -*- coding: utf-8 -*-
"""Tests for GA 琳姐（GA 課主管）GlobalAffairsSection — Phase 3 Step 14."""
import io
import sys
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import AnomalyEvent, CourseReport, DebateResult, SubReport
from trading_system.common.flash_alert import reset_flash_state
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.global_affairs.global_affairs_section import GlobalAffairsSection


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_subreport(direction, confidence, stale=False):
    return SubReport(
        role_name="test", role_code="TEST",
        direction=direction, sub_confidence=confidence,
        reasoning="test", data_used={},
        timestamp=datetime.now(), staleness_flag=stale,
    )


def _make_debate(direction, confidence, consensus_type="agreed",
                 stale_a=False, stale_b=False):
    ra = _make_subreport(direction, confidence, stale=stale_a)
    rb = _make_subreport(direction, confidence, stale=stale_b)
    return DebateResult(
        debate_id          = f"test-{direction}",
        report_a           = ra,
        report_b           = rb,
        consensus_type     = consensus_type,
        final_direction    = direction,
        final_confidence   = confidence,
        combined_reasoning = "test",
        key_disagreement   = "disagreement" if consensus_type == "dual_track" else None,
        timestamp          = datetime.now(),
    )


def _fresh_section():
    get_bus().clear()
    reset_flash_state()
    return GlobalAffairsSection(gateway=MagicMock())


def _inject_debates(section, d01=None, d02=None):
    if d01 is not None:
        section.ga_01.conduct_debate = MagicMock(return_value=d01)
    if d02 is not None:
        section.ga_02.conduct_debate = MagicMock(return_value=d02)


def _inject_all_bullish(section, c01=0.6, c02=0.5):
    d01 = _make_debate("bullish", c01)
    d02 = _make_debate("bullish", c02)
    _inject_debates(section, d01=d01, d02=d02)
    return d01, d02


def _make_anomaly(severity, event_id="evt-001"):
    return AnomalyEvent(
        event_id      = event_id,
        event_type    = "FLASH_MOVE",
        symbol        = "ETHUSDT",
        magnitude     = 0.12,
        severity      = severity,
        timestamp     = datetime.now(),
        triggered_alert = True,
        direction     = "down",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGaSection(unittest.TestCase):

    # ── 01: 初始化 + 訂閱 ───────────────────────────────────────────────────

    def test_01_init_and_subscriptions(self):
        section = _fresh_section()

        self.assertTrue(hasattr(section, "ga_01"))
        self.assertTrue(hasattr(section, "ga_02"))
        self.assertEqual(section.weights["ga_01"], 0.65)
        self.assertEqual(section.weights["ga_02"], 0.35)
        self.assertEqual(section.report_interval, 1080)
        self.assertIn("琳姐", get_bus().get_subscribers("ga.request_report"))
        self.assertIn("琳姐", get_bus().get_subscribers("anomaly.detected"))

    # ── 02: 兩組 bullish → 一致加成 ─────────────────────────────────────────

    def test_02_both_bullish_consensus_bonus(self):
        # composite = 1*0.6*0.65 + 1*0.5*0.35 = 0.39+0.175 = 0.565
        # both bullish → +0.1 → 0.665
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.6)
        d02 = _make_debate("bullish", 0.5)

        direction, confidence = section._compute_course_score(d01, d02)

        self.assertEqual(direction, "bullish")
        self.assertAlmostEqual(confidence, 0.665, places=5)

    # ── 03: staleness 歸零並重正規化 ────────────────────────────────────────

    def test_03_staleness_zeroes_weight_renormalizes(self):
        # ga_01 stale → weight=0; only ga_02=0.35 remains → renorm to 1.0
        # composite = 1*0.8*1.0 = 0.8 → bullish, conf=0.8
        # bonus: d01.direction="neutral" ≠ d02.direction="bullish" → no bonus
        section = _fresh_section()
        d01 = _make_debate("neutral", 0.1, stale_a=True, stale_b=True)
        d02 = _make_debate("bullish", 0.8)

        direction, confidence = section._compute_course_score(d01, d02)

        self.assertEqual(direction, "bullish")
        self.assertAlmostEqual(confidence, 0.8, places=5)

    # ── 04: dual_track 懲罰（兩組都 dual_track）──────────────────────────────

    def test_04_two_dual_track_penalty_with_bonus(self):
        # composite = 1*0.7*0.65 + 1*0.6*0.35 = 0.455+0.21 = 0.665
        # dual_count=2 → 0.665*(1-0.30) = 0.665*0.70 = 0.4655
        # both bullish → +0.1 → 0.5655
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.7, consensus_type="dual_track")
        d02 = _make_debate("bullish", 0.6, consensus_type="dual_track")

        direction, confidence = section._compute_course_score(d01, d02)

        self.assertEqual(direction, "bullish")
        base      = 0.7 * 0.65 + 0.6 * 0.35
        penalised = base * (1 - 0.15 * 2)
        expected  = min(penalised + 0.1, 0.95)
        self.assertAlmostEqual(confidence, expected, places=5)

    # ── 05: 高嚴重度異常事件 → 加急報告 + FlashAlert ─────────────────────────

    def test_05_high_severity_anomaly_triggers_report_and_flash(self):
        section = _fresh_section()
        _inject_all_bullish(section)

        flash_received = []
        get_bus().subscribe(
            "alert.flash",
            lambda m: flash_received.append(m.payload),
            role="test-flash",
        )

        anomaly = _make_anomaly(severity=0.8)
        get_bus().publish("anomaly.detected", anomaly, sender="test")

        self.assertEqual(len(section.anomaly_responses), 1)
        self.assertEqual(section.anomaly_responses[0]["severity"],     0.8)
        self.assertEqual(section.anomaly_responses[0]["anomaly_type"], "FLASH_MOVE")

        # Urgent report should have been produced
        self.assertEqual(section.reports_produced, 1)

        # FlashAlert must have been sent to alert.flash
        self.assertGreater(len(flash_received), 0)
        alert = flash_received[0]
        self.assertEqual(alert["alert_type"], "GA_CRITICAL")
        self.assertEqual(alert["sender"],     "琳姐")

    # ── 06: 低嚴重度異常（< 0.7）→ 不觸發 ───────────────────────────────────

    def test_06_low_severity_anomaly_no_trigger(self):
        section = _fresh_section()
        produce_mock = MagicMock()
        section.produce_course_report = produce_mock

        anomaly = _make_anomaly(severity=0.5)
        get_bus().publish("anomaly.detected", anomaly, sender="test")

        produce_mock.assert_not_called()
        self.assertEqual(len(section.anomaly_responses), 0)

    # ── 07: produce_course_report 廣播 report.ga ─────────────────────────────

    def test_07_produce_course_report_publishes_to_bus(self):
        section = _fresh_section()
        _inject_all_bullish(section)

        received = []
        get_bus().subscribe("report.ga", lambda m: received.append(m.payload), role="test")

        report = section.produce_course_report()

        self.assertIsInstance(report, CourseReport)
        self.assertEqual(report.course_code,  "GA")
        self.assertEqual(report.manager_name, "琳姐")
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], report)
        self.assertEqual(section.reports_produced, 1)
        self.assertIsNotNone(section.last_report_time)

    # ── 08: produce_daily_brief 格式完整 ────────────────────────────────────

    def test_08_produce_daily_brief_format(self):
        section = _fresh_section()
        _inject_all_bullish(section)
        section.produce_course_report()

        brief = section.produce_daily_brief()

        self.assertIn("date",                  brief)
        self.assertIn("current_market_view",   brief)
        self.assertIn("anomaly_responses_24h", brief)
        self.assertIn("reports_produced_today",brief)
        self.assertIn("consensus_rate",        brief)

        view = brief["current_market_view"]
        self.assertIn("direction",  view)
        self.assertIn("confidence", view)
        self.assertIn("reasoning",  view)
        self.assertEqual(view["direction"], "bullish")
        self.assertGreater(view["confidence"], 0)
        self.assertEqual(brief["reports_produced_today"], 1)

    # ── 09: consensus_rate 計算 ──────────────────────────────────────────────

    def test_09_consensus_rate_calculation(self):
        section = _fresh_section()
        # d01 agreed, d02 discussed_agreed → 1 agreed / 2 debates = 0.5
        d01 = _make_debate("bearish", 0.6, consensus_type="agreed")
        d02 = _make_debate("bearish", 0.4, consensus_type="discussed_agreed")
        _inject_debates(section, d01=d01, d02=d02)

        section.produce_course_report()

        rate = section._calculate_consensus_rate()
        self.assertAlmostEqual(rate, 0.5, places=5)

    # ── 10: run_cycle 節流（1080 秒）────────────────────────────────────────

    def test_10_run_cycle_throttles_at_1080s(self):
        section      = _fresh_section()
        mock_produce = MagicMock()
        section.produce_course_report = mock_produce

        # First call: no last_report_time → fires
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 1)

        # Just produced → too recent → skips
        section.last_report_time = time.time()
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 1)

        # 1081 seconds elapsed → fires again
        section.last_report_time = time.time() - 1081
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
