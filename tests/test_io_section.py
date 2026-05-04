# -*- coding: utf-8 -*-
"""Tests for 婷姐 IntelligenceSection（IO 課主管）— Phase 3 Step 7."""
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
from trading_system.squads.crypto.intelligence.intelligence_section import IntelligenceSection


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_subreport(
    direction: str = "neutral",
    confidence: float = 0.3,
    staleness: bool = False,
) -> SubReport:
    return SubReport(
        role_name      = "T",
        role_code      = "X",
        direction      = direction,
        sub_confidence = confidence,
        reasoning      = "test",
        data_used      = {},
        timestamp      = datetime.now(),
        staleness_flag = staleness,
    )


def _make_debate(
    direction: str       = "neutral",
    confidence: float    = 0.3,
    consensus_type: str  = "agreed",
    staleness_a: bool    = False,
    staleness_b: bool    = False,
    key_disagreement     = None,
) -> DebateResult:
    return DebateResult(
        debate_id          = "test-id",
        report_a           = _make_subreport(direction, confidence, staleness_a),
        report_b           = _make_subreport(direction, confidence, staleness_b),
        consensus_type     = consensus_type,
        final_direction    = direction,
        final_confidence   = confidence,
        combined_reasoning = "test",
        key_disagreement   = key_disagreement,
        timestamp          = datetime.now(),
    )


def _fresh_section() -> IntelligenceSection:
    get_bus().clear()
    return IntelligenceSection(gateway=MagicMock())


def _mock_debates(section: IntelligenceSection, d01, d02, d03) -> None:
    section.io_01.conduct_debate = MagicMock(return_value=d01)
    section.io_02.conduct_debate = MagicMock(return_value=d02)
    section.io_03.conduct_debate = MagicMock(return_value=d03)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestIntelligenceSection(unittest.TestCase):

    # ── 01: 初始化 ────────────────────────────────────────────────────────────

    def test_01_init_roles_weights_subscriptions(self):
        section = _fresh_section()

        self.assertEqual(section.role_name, "婷姐")
        self.assertEqual(section.role_code, "IO-Manager")
        self.assertIsNotNone(section.io_01)
        self.assertIsNotNone(section.io_02)
        self.assertIsNotNone(section.io_03)
        self.assertAlmostEqual(section.weights["io_01"], 0.50)
        self.assertAlmostEqual(section.weights["io_02"], 0.15)
        self.assertAlmostEqual(section.weights["io_03"], 0.35)
        self.assertEqual(section.reports_produced, 0)
        self.assertIsNone(section.last_report_time)

    # ── 02: 三組全 bullish → 方向一致加成 ────────────────────────────────────
    # composite = 0.6×0.50 + 0.5×0.15 + 0.7×0.35 = 0.620
    # all same direction → +0.1 → 0.720

    def test_02_all_bullish_consensus_bonus(self):
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.6)
        d02 = _make_debate("bullish", 0.5)
        d03 = _make_debate("bullish", 0.7)

        direction, confidence = section._compute_course_score(d01, d02, d03)

        self.assertEqual(direction, "bullish")
        expected = 0.6 * 0.50 + 0.5 * 0.15 + 0.7 * 0.35 + 0.1   # 0.720
        self.assertAlmostEqual(confidence, expected, places=5)

    # ── 03: 方向分歧 → bullish 主導，無加成 ──────────────────────────────────
    # composite = 0.6×0.50 − 0.5×0.15 + 0×0.35 = 0.225

    def test_03_mixed_directions_no_bonus(self):
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.6)
        d02 = _make_debate("bearish", 0.5)
        d03 = _make_debate("neutral", 0.4)

        direction, confidence = section._compute_course_score(d01, d02, d03)

        self.assertEqual(direction, "bullish")
        expected = 0.6 * 0.50 - 0.5 * 0.15 + 0.0   # 0.225
        self.assertAlmostEqual(confidence, expected, places=5)

    # ── 04: staleness 歸零 io_02 → bearish io_02 不影響結果 ──────────────────
    # io_02 stale → weight→0, normalize: io_01=0.50/0.85, io_03=0.35/0.85
    # composite = 0.6×(0.50/0.85) + 0.6×(0.35/0.85) = 0.6

    def test_04_staleness_zeros_io02_weight(self):
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.6, staleness_a=False)
        d02 = _make_debate("bearish", 0.5, staleness_a=True)   # stale!
        d03 = _make_debate("bullish", 0.6, staleness_a=False)

        direction, confidence = section._compute_course_score(d01, d02, d03)

        # bearish io_02 excluded; io_01+io_03 both bullish 0.6
        # directions list = [bullish, bearish, bullish] → NOT all same → no bonus
        self.assertEqual(direction, "bullish")
        expected = 0.6 * (0.50 / 0.85) + 0.6 * (0.35 / 0.85)   # = 0.6
        self.assertAlmostEqual(confidence, expected, places=5)

    # ── 05: dual_track 懲罰 → confidence 打折後再加方向一致加成 ──────────────
    # composite = 0.620; ×(1 − 0.2/3) ≈ 0.5787; all bullish +0.1 → ≈0.6787

    def test_05_dual_track_penalty(self):
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.6, consensus_type="dual_track")
        d02 = _make_debate("bullish", 0.5, consensus_type="agreed")
        d03 = _make_debate("bullish", 0.7, consensus_type="agreed")

        direction, confidence = section._compute_course_score(d01, d02, d03)

        composite   = 0.6 * 0.50 + 0.5 * 0.15 + 0.7 * 0.35          # 0.620
        penalized   = composite * (1 - 0.2 * 1 / 3)
        expected    = penalized + 0.1                                   # all bullish bonus
        self.assertEqual(direction, "bullish")
        self.assertAlmostEqual(confidence, expected, places=4)
        # penalty must be visible vs no-dual-track case (which would be 0.720)
        self.assertLess(confidence, 0.72)

    # ── 06: produce_course_report 產出 CourseReport 並廣播 ──────────────────

    def test_06_produce_course_report(self):
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.6)
        d02 = _make_debate("bullish", 0.5)
        d03 = _make_debate("bullish", 0.7)
        _mock_debates(section, d01, d02, d03)

        received = []
        section.bus.subscribe("report.io", lambda m: received.append(m.payload), role="test")

        report = section.produce_course_report()

        self.assertIsInstance(report, CourseReport)
        self.assertEqual(section.reports_produced, 1)
        self.assertIsNotNone(section.last_report_time)
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], CourseReport)

    # ── 07: CourseReport 欄位完整 ─────────────────────────────────────────────

    def test_07_course_report_fields(self):
        section = _fresh_section()
        _mock_debates(section,
                      _make_debate("bearish", 0.6),
                      _make_debate("bearish", 0.5),
                      _make_debate("bearish", 0.7))

        report = section.produce_course_report()

        self.assertEqual(report.course_name, "市場情報課")
        self.assertEqual(report.course_code, "IO")
        self.assertEqual(report.manager_name, "婷姐")
        self.assertIn(report.course_direction, ("bullish", "bearish", "neutral"))
        self.assertGreaterEqual(report.course_confidence, 0.0)
        self.assertLessEqual(report.course_confidence, 0.95)
        self.assertEqual(len(report.debate_results), 3)
        self.assertIn(report.freshness_grade, ("real_time", "recent", "delayed", "stale"))
        self.assertIn("io_01_funding_data", report.data_health)
        self.assertIn("role", report.self_review)
        self.assertIn("reasoning", report.self_review)

    # ── 08: run_cycle 每 300 秒節流 ───────────────────────────────────────────

    def test_08_run_cycle_throttle(self):
        section = _fresh_section()
        _mock_debates(section,
                      _make_debate(), _make_debate(), _make_debate())

        section.run_cycle()                          # 第一次：last_report_time=None → 觸發
        self.assertEqual(section.reports_produced, 1)

        section.run_cycle()                          # 立即第二次：未到 300s → 節流
        self.assertEqual(section.reports_produced, 1)

        section.last_report_time -= 301              # 手動調舊時間
        section.run_cycle()                          # 第三次：超過 300s → 再次觸發
        self.assertEqual(section.reports_produced, 2)

    # ── 09: bus 主動觸發 io.request_report ────────────────────────────────────

    def test_09_request_report_via_bus(self):
        section = _fresh_section()
        _mock_debates(section,
                      _make_debate(), _make_debate(), _make_debate())

        self.assertEqual(section.reports_produced, 0)
        section.bus.publish("io.request_report", {}, sender="test")
        self.assertEqual(section.reports_produced, 1)

    # ── 10: dual_track 產生 flash_alert ──────────────────────────────────────

    def test_10_flash_alert_on_dual_track(self):
        section = _fresh_section()
        _mock_debates(section,
                      _make_debate("bullish", 0.6,
                                   consensus_type="dual_track",
                                   key_disagreement="方向分歧: 小魏=bullish vs 蓮姐=bearish"),
                      _make_debate("bullish", 0.5),
                      _make_debate("bullish", 0.7))

        report = section.produce_course_report()

        self.assertEqual(len(report.flash_alerts), 1)
        self.assertIn("IO-01 雙人大分歧", report.flash_alerts[0])

    # ── 11: 全部 stale → neutral 0.1 ─────────────────────────────────────────

    def test_11_all_stale_returns_neutral(self):
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.8, staleness_a=True)
        d02 = _make_debate("bullish", 0.8, staleness_a=True)
        d03 = _make_debate("bullish", 0.8, staleness_a=True)

        direction, confidence = section._compute_course_score(d01, d02, d03)

        self.assertEqual(direction, "neutral")
        self.assertAlmostEqual(confidence, 0.1)

    # ── 12: recent_reports 累積 ───────────────────────────────────────────────

    def test_12_recent_reports_accumulate(self):
        section = _fresh_section()
        _mock_debates(section,
                      _make_debate(), _make_debate(), _make_debate())

        section.produce_course_report()
        section.produce_course_report()

        self.assertEqual(len(section.recent_reports), 2)
        self.assertIsInstance(section.recent_reports[-1], CourseReport)

    # ── 13: get_section_status 欄位 ───────────────────────────────────────────

    def test_13_get_section_status_keys(self):
        section = _fresh_section()
        _mock_debates(section,
                      _make_debate(), _make_debate(), _make_debate())
        section.produce_course_report()

        status = section.get_section_status()

        for key in ("manager", "reports_produced", "last_report_time",
                    "weights", "latest_report"):
            self.assertIn(key, status)
        self.assertEqual(status["manager"], "婷姐")
        self.assertEqual(status["reports_produced"], 1)
        self.assertIsNotNone(status["latest_report"])

    # ── 14: data_health 反映 staleness ────────────────────────────────────────

    def test_14_data_health_reflects_staleness(self):
        section = _fresh_section()
        _mock_debates(section,
                      _make_debate("bullish", 0.5),
                      _make_debate("neutral", 0.3, staleness_a=True),   # stale!
                      _make_debate("bullish", 0.5))

        report = section.produce_course_report()

        self.assertTrue(report.data_health["io_01_funding_data"])
        self.assertFalse(report.data_health["io_02_sentiment_data"])   # stale
        self.assertTrue(report.data_health["io_03_onchain_data"])
        self.assertTrue(report.data_health["all_debates_completed"])

    # ── 15: composite 接近零 → neutral ────────────────────────────────────────
    # IO-01 bullish 0.2, IO-02 bearish 0.2, IO-03 neutral 0.1
    # composite = 0.2×0.50 − 0.2×0.15 + 0×0.35 = 0.10 − 0.03 = 0.07 (<0.1 threshold)

    def test_15_near_zero_composite_yields_neutral(self):
        section = _fresh_section()
        d01 = _make_debate("bullish", 0.2)
        d02 = _make_debate("bearish", 0.2)
        d03 = _make_debate("neutral", 0.1)

        direction, confidence = section._compute_course_score(d01, d02, d03)

        # |composite| = |0.10 − 0.03| = 0.07 < threshold 0.1 → neutral
        self.assertEqual(direction, "neutral")


if __name__ == "__main__":
    unittest.main(verbosity=2)
