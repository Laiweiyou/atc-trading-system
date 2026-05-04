# -*- coding: utf-8 -*-
"""Tests for trading_system/common/debate_engine.py — 使用 unittest。"""
import io
import sys
import unittest
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.debate_engine import compare_reports, make_debate_result

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _sub(direction: str, confidence: float, reasoning: str = "test") -> SubReport:
    return SubReport(
        role_name="test",
        role_code="T-00",
        direction=direction,
        sub_confidence=confidence,
        reasoning=reasoning,
        data_used={},
        timestamp=datetime.now(timezone.utc),
    )


def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) < tol


# ─── Case 1: 共識（方向一致 + 信心差 ≤ 0.2）────────────────────────────────

class TestAgreed(unittest.TestCase):

    def test_consensus_type(self):
        r = compare_reports(_sub("bullish", 0.7), _sub("bullish", 0.8))
        self.assertEqual(r["consensus_type"], "agreed")

    def test_final_direction(self):
        r = compare_reports(_sub("bearish", 0.6), _sub("bearish", 0.75))
        self.assertEqual(r["final_direction"], "bearish")

    def test_final_confidence_is_average(self):
        # diff = 0.75 - 0.6 = 0.15 < 0.2，確保進 agreed 分支
        r = compare_reports(_sub("bullish", 0.6), _sub("bullish", 0.75))
        self.assertAlmostEqual(r["final_confidence"], 0.675)

    def test_key_disagreement_is_none(self):
        r = compare_reports(_sub("neutral", 0.5), _sub("neutral", 0.6))
        self.assertIsNone(r["key_disagreement"])

    def test_reasoning_contains_both_labels(self):
        r = compare_reports(
            _sub("bullish", 0.7, "A分析"),
            _sub("bullish", 0.8, "B分析"),
            role_a_label="老徐",
            role_b_label="小曾",
        )
        self.assertIn("老徐", r["reasoning"])
        self.assertIn("小曾", r["reasoning"])
        self.assertIn("A分析", r["reasoning"])
        self.assertIn("B分析", r["reasoning"])

    def test_exactly_0_2_threshold_is_agreed(self):
        # diff = 0.7 - 0.5 = 0.2 → agreed（≤ 閾值）
        r = compare_reports(_sub("bullish", 0.5), _sub("bullish", 0.7))
        self.assertEqual(r["consensus_type"], "agreed")


# ─── Case 2: 小分歧（方向一致 + 信心差 > 0.2）—— 加權平均 ──────────────────

class TestDiscussedAgreed(unittest.TestCase):

    def test_consensus_type(self):
        r = compare_reports(_sub("bullish", 0.3), _sub("bullish", 0.9))
        self.assertEqual(r["consensus_type"], "discussed_agreed")

    def test_final_direction_same_as_both(self):
        r = compare_reports(_sub("bearish", 0.4), _sub("bearish", 0.9))
        self.assertEqual(r["final_direction"], "bearish")

    def test_weighted_confidence_formula(self):
        a, b = 0.3, 0.9
        expected = (a**2 + b**2) / (a + b)
        r = compare_reports(_sub("bullish", a), _sub("bullish", b))
        self.assertAlmostEqual(r["final_confidence"], expected)

    def test_key_disagreement_not_none(self):
        r = compare_reports(_sub("bullish", 0.3), _sub("bullish", 0.9))
        self.assertIsNotNone(r["key_disagreement"])

    def test_key_disagreement_contains_labels(self):
        r = compare_reports(
            _sub("bullish", 0.3),
            _sub("bullish", 0.9),
            role_a_label="阿賴",
            role_b_label="珊珊",
        )
        self.assertIn("阿賴", r["key_disagreement"])
        self.assertIn("珊珊", r["key_disagreement"])

    def test_reasoning_contains_both_confidences(self):
        r = compare_reports(_sub("bullish", 0.30), _sub("bullish", 0.90))
        self.assertIn("0.30", r["reasoning"])
        self.assertIn("0.90", r["reasoning"])

    def test_just_over_threshold(self):
        r = compare_reports(_sub("neutral", 0.5), _sub("neutral", 0.701))
        self.assertEqual(r["consensus_type"], "discussed_agreed")


# ─── Case 3: 大分歧（方向不同）—— 採保守 ────────────────────────────────────

class TestDualTrack(unittest.TestCase):

    def test_consensus_type(self):
        r = compare_reports(_sub("bearish", 0.7), _sub("bullish", 0.8))
        self.assertEqual(r["consensus_type"], "dual_track")

    def test_bearish_wins_over_bullish(self):
        r = compare_reports(_sub("bearish", 0.7), _sub("bullish", 0.8))
        self.assertEqual(r["final_direction"], "bearish")

    def test_bearish_wins_over_neutral(self):
        r = compare_reports(_sub("neutral", 0.6), _sub("bearish", 0.5))
        self.assertEqual(r["final_direction"], "bearish")

    def test_neutral_wins_over_bullish(self):
        r = compare_reports(_sub("bullish", 0.8), _sub("neutral", 0.6))
        self.assertEqual(r["final_direction"], "neutral")

    def test_confidence_gets_penalty(self):
        r = compare_reports(_sub("bearish", 0.7), _sub("bullish", 0.8))
        self.assertAlmostEqual(r["final_confidence"], 0.7 * 0.8)

    def test_custom_penalty(self):
        r = compare_reports(
            _sub("bearish", 0.6), _sub("bullish", 0.9), dual_track_penalty=0.5
        )
        self.assertAlmostEqual(r["final_confidence"], 0.6 * 0.5)

    def test_key_disagreement_not_none(self):
        r = compare_reports(_sub("bearish", 0.7), _sub("bullish", 0.8))
        self.assertIsNotNone(r["key_disagreement"])

    def test_key_disagreement_contains_both_directions(self):
        r = compare_reports(
            _sub("bearish", 0.7),
            _sub("bullish", 0.8),
            role_a_label="君君",
            role_b_label="阿豪",
        )
        self.assertIn("bearish", r["key_disagreement"])
        self.assertIn("bullish", r["key_disagreement"])

    def test_reasoning_mentions_conservative(self):
        r = compare_reports(_sub("bearish", 0.7), _sub("bullish", 0.8))
        self.assertIn("保守", r["reasoning"])


# ─── Case 4: 自訂 severity_order（TK 課用）──────────────────────────────────

class TestCustomSeverity(unittest.TestCase):
    TK_SEVERITY = {"rest": 2, "cautious": 1, "active": 0}

    def _tk(self, direction: str, confidence: float) -> SubReport:
        return SubReport(
            role_name="tk",
            role_code="TK-00",
            direction=direction,
            sub_confidence=confidence,
            reasoning="tk test",
            data_used={},
            timestamp=datetime.now(timezone.utc),
        )

    def test_rest_wins_over_active(self):
        r = compare_reports(
            self._tk("active", 0.8),
            self._tk("rest", 0.6),
            severity_order=self.TK_SEVERITY,
        )
        self.assertEqual(r["final_direction"], "rest")

    def test_rest_wins_over_cautious(self):
        r = compare_reports(
            self._tk("cautious", 0.9),
            self._tk("rest", 0.5),
            severity_order=self.TK_SEVERITY,
        )
        self.assertEqual(r["final_direction"], "rest")

    def test_cautious_wins_over_active(self):
        r = compare_reports(
            self._tk("active", 0.9),
            self._tk("cautious", 0.5),
            severity_order=self.TK_SEVERITY,
        )
        self.assertEqual(r["final_direction"], "cautious")

    def test_same_direction_uses_normal_agreed_logic(self):
        r = compare_reports(
            self._tk("rest", 0.7),
            self._tk("rest", 0.8),
            severity_order=self.TK_SEVERITY,
        )
        self.assertEqual(r["consensus_type"], "agreed")

    def test_penalty_applied_with_custom_severity(self):
        r = compare_reports(
            self._tk("active", 0.8),
            self._tk("rest", 0.6),
            severity_order=self.TK_SEVERITY,
        )
        self.assertAlmostEqual(r["final_confidence"], 0.6 * 0.8)

    def test_does_not_affect_default_severity(self):
        # 確保自訂 severity 不會污染預設值
        r_default = compare_reports(_sub("bullish", 0.7), _sub("bearish", 0.6))
        self.assertEqual(r_default["final_direction"], "bearish")


# ─── Case 5: 邊界情況 ────────────────────────────────────────────────────────

class TestBoundary(unittest.TestCase):

    def test_exactly_threshold_is_agreed(self):
        r = compare_reports(_sub("bullish", 0.5), _sub("bullish", 0.7))
        self.assertEqual(r["consensus_type"], "agreed")

    def test_custom_threshold_smaller(self):
        r = compare_reports(
            _sub("neutral", 0.5), _sub("neutral", 0.65), consensus_threshold=0.1
        )
        self.assertEqual(r["consensus_type"], "discussed_agreed")

    def test_custom_threshold_agreed_within(self):
        r = compare_reports(
            _sub("neutral", 0.5), _sub("neutral", 0.55), consensus_threshold=0.1
        )
        self.assertEqual(r["consensus_type"], "agreed")

    def test_direction_different_regardless_of_confidence_diff(self):
        r = compare_reports(_sub("bullish", 0.7), _sub("bearish", 0.71))
        self.assertEqual(r["consensus_type"], "dual_track")


# ─── Case 6: 兩人都 neutral ──────────────────────────────────────────────────

class TestBothNeutral(unittest.TestCase):

    def test_agreed_when_close(self):
        r = compare_reports(_sub("neutral", 0.5), _sub("neutral", 0.6))
        self.assertEqual(r["consensus_type"], "agreed")
        self.assertEqual(r["final_direction"], "neutral")

    def test_discussed_agreed_when_far(self):
        r = compare_reports(_sub("neutral", 0.3), _sub("neutral", 0.8))
        self.assertEqual(r["consensus_type"], "discussed_agreed")
        self.assertEqual(r["final_direction"], "neutral")

    def test_neutral_vs_bearish_bearish_wins(self):
        r = compare_reports(_sub("neutral", 0.7), _sub("bearish", 0.5))
        self.assertEqual(r["final_direction"], "bearish")

    def test_neutral_vs_bullish_neutral_wins(self):
        r = compare_reports(_sub("neutral", 0.7), _sub("bullish", 0.5))
        self.assertEqual(r["final_direction"], "neutral")


# ─── Case 7: 兩人分數完全相同 ───────────────────────────────────────────────

class TestIdenticalScores(unittest.TestCase):

    def test_same_direction_and_confidence(self):
        r = compare_reports(_sub("bullish", 0.7), _sub("bullish", 0.7))
        self.assertEqual(r["consensus_type"], "agreed")
        self.assertEqual(r["final_direction"], "bullish")
        self.assertAlmostEqual(r["final_confidence"], 0.7)

    def test_dual_track_same_confidence_a_wins_by_severity(self):
        r = compare_reports(_sub("bearish", 0.7), _sub("bullish", 0.7))
        self.assertEqual(r["final_direction"], "bearish")
        self.assertAlmostEqual(r["final_confidence"], 0.7 * 0.8)

    def test_neutral_tie_a_wins_if_higher_severity(self):
        r = compare_reports(_sub("bearish", 0.6), _sub("neutral", 0.6))
        self.assertEqual(r["final_direction"], "bearish")

    def test_same_direction_same_confidence_key_disagreement_none(self):
        r = compare_reports(_sub("neutral", 0.5), _sub("neutral", 0.5))
        self.assertIsNone(r["key_disagreement"])


# ─── make_debate_result ──────────────────────────────────────────────────────

class TestMakeDebateResult(unittest.TestCase):

    def test_returns_debate_result_type(self):
        ra, rb = _sub("bullish", 0.7), _sub("bullish", 0.75)
        result = make_debate_result(ra, rb, "TEST-01")
        self.assertIsInstance(result, DebateResult)

    def test_debate_id_has_prefix(self):
        ra, rb = _sub("bullish", 0.7), _sub("bullish", 0.75)
        result = make_debate_result(ra, rb, "MY-PREFIX")
        self.assertTrue(result.debate_id.startswith("MY-PREFIX-"))

    def test_agreed_key_disagreement_is_none(self):
        ra, rb = _sub("bullish", 0.7), _sub("bullish", 0.75)
        result = make_debate_result(ra, rb, "T")
        self.assertIsNone(result.key_disagreement)

    def test_dual_track_key_disagreement_not_none(self):
        ra, rb = _sub("bearish", 0.7), _sub("bullish", 0.8)
        result = make_debate_result(ra, rb, "T")
        self.assertIsNotNone(result.key_disagreement)

    def test_combined_reasoning_propagated(self):
        ra = _sub("bearish", 0.7, "我看空")
        rb = _sub("bearish", 0.75, "我也看空")
        result = make_debate_result(ra, rb, "T", "角色A", "角色B")
        self.assertIn("我看空", result.combined_reasoning)
        self.assertIn("我也看空", result.combined_reasoning)

    def test_report_a_b_preserved(self):
        ra, rb = _sub("bullish", 0.7), _sub("bearish", 0.8)
        result = make_debate_result(ra, rb, "T")
        self.assertIs(result.report_a, ra)
        self.assertIs(result.report_b, rb)

    def test_custom_severity_order_passed_through(self):
        tk_sev = {"rest": 2, "cautious": 1, "active": 0}
        ra = SubReport("x", "X", "active", 0.9, "快", {}, datetime.now(timezone.utc))
        rb = SubReport("y", "Y", "rest",   0.5, "慢", {}, datetime.now(timezone.utc))
        result = make_debate_result(ra, rb, "TK", severity_order=tk_sev)
        self.assertEqual(result.final_direction, "rest")

    def test_consensus_type_propagated(self):
        ra, rb = _sub("bearish", 0.6), _sub("bullish", 0.8)
        result = make_debate_result(ra, rb, "T")
        self.assertEqual(result.consensus_type, "dual_track")


if __name__ == "__main__":
    unittest.main(verbosity=2)
