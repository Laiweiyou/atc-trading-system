# -*- coding: utf-8 -*-
"""Tests for trading_system.evolution.hindsight_engine — 事後驗證引擎。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from trading_system.common.feedback_models import SelfReview
from trading_system.common.message_bus import get_bus, reset_bus
from trading_system.evolution.hindsight_engine import HindsightEngine


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _review(
    role_code: str = "CA-01",
    my_call:   str = "bullish",
    timestamp: datetime = None,
    role_name: str = "test-role",
) -> SelfReview:
    return SelfReview(
        role_name=role_name,
        role_code=role_code,
        work_type="test",
        timestamp=timestamp or datetime.now(),
        my_call=my_call,
        confidence_at_time=0.7,
        reasoning="test",
        data_used={},
    )


def _fresh() -> HindsightEngine:
    reset_bus()
    gw = MagicMock()
    gw.get_market_kline.return_value = {"success": False}
    return HindsightEngine(gateway=gw)


def _add_pending(engine: HindsightEngine, review: SelfReview,
                 verify_at: datetime, window_hours: int = 4) -> None:
    """直接插入 pending_reviews（跳過 bus）。"""
    engine.pending_reviews[review.review_id] = {
        "review":       review,
        "verify_at":    verify_at,
        "window_hours": window_hours,
        "submitted_at": time.time(),
    }


def _past(seconds: int = 1) -> datetime:
    return datetime.now() - timedelta(seconds=seconds)


def _future(hours: int = 4) -> datetime:
    return datetime.now() + timedelta(hours=hours)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — 初始化
# ═══════════════════════════════════════════════════════════════════════════════

class TestInit(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def test_01_role_name_code(self):
        self.assertEqual(self.engine.role_name, "Hindsight Engine")
        self.assertEqual(self.engine.role_code, "HINDSIGHT")

    def test_02_subscription(self):
        self.assertIn("HINDSIGHT", get_bus().get_subscribers("feedback.submitted"))

    def test_03_defaults(self):
        e = self.engine
        self.assertEqual(e.reviews_received,       0)
        self.assertEqual(e.reviews_verified,        0)
        self.assertEqual(e.correct_count,           0)
        self.assertEqual(e.incorrect_count,         0)
        self.assertEqual(e.partial_count,           0)
        self.assertEqual(e.unverified_due_to_data,  0)
        self.assertEqual(len(e.pending_reviews),    0)

    def test_04_verification_windows_sampled(self):
        w = self.engine.VERIFICATION_WINDOWS
        self.assertEqual(w["CA-01"],  4)
        self.assertEqual(w["GA-01"], 24)
        self.assertEqual(w["TK-01"],  8)
        self.assertEqual(w["IO-01"], 12)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — Review 登記（feedback.submitted）
# ═══════════════════════════════════════════════════════════════════════════════

class TestReviewRegistration(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def test_01_review_stored_in_pending(self):
        r = _review("CA-01")
        get_bus().publish("feedback.submitted", r, sender="test")
        self.assertIn(r.review_id, self.engine.pending_reviews)

    def test_02_verify_at_computed_correctly(self):
        ts = datetime(2026, 1, 1, 10, 0, 0)
        r  = _review("CA-01", timestamp=ts)   # window = 4h
        get_bus().publish("feedback.submitted", r, sender="test")
        entry = self.engine.pending_reviews[r.review_id]
        expected = datetime(2026, 1, 1, 14, 0, 0)
        self.assertEqual(entry["verify_at"], expected)

    def test_03_reviews_received_incremented(self):
        get_bus().publish("feedback.submitted", _review("CA-01"), sender="test")
        get_bus().publish("feedback.submitted", _review("GA-01"), sender="test")
        self.assertEqual(self.engine.reviews_received, 2)

    def test_04_non_selfreview_payload_ignored(self):
        get_bus().publish("feedback.submitted", {"not": "a review"}, sender="test")
        self.assertEqual(len(self.engine.pending_reviews), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — 不同角色不同驗證時間窗口
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerificationWindows(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def _window_hours(self, role_code: str) -> int:
        ts = datetime(2026, 1, 1, 0, 0, 0)
        r  = _review(role_code, timestamp=ts)
        get_bus().publish("feedback.submitted", r, sender="test")
        return self.engine.pending_reviews[r.review_id]["window_hours"]

    def test_01_ca01_short_window(self):
        self.assertEqual(self._window_hours("CA-01"), 4)

    def test_02_ga01_long_window(self):
        self.assertEqual(self._window_hours("GA-01"), 24)

    def test_03_unknown_role_uses_default(self):
        self.assertEqual(self._window_hours("UNKNOWN-ROLE"), 6)

    def test_04_tk_tempo_window(self):
        self.assertEqual(self._window_hours("TK-01"), 8)

    def test_05_io_medium_window(self):
        self.assertEqual(self._window_hours("IO-01"), 12)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — 判定邏輯（_judge）
# ═══════════════════════════════════════════════════════════════════════════════

class TestJudgeLogic(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def _j(self, direction, change_pct):
        result, notes = self.engine._judge(direction, change_pct)
        return result

    # Bullish
    def test_01_bullish_strong_rise_correct(self):
        self.assertEqual(self._j("bullish", 1.0), "correct")

    def test_02_bullish_exact_threshold_correct(self):
        # change > 0.5 → correct
        self.assertEqual(self._j("bullish", 0.51), "correct")

    def test_03_bullish_small_rise_partial(self):
        self.assertEqual(self._j("bullish", 0.3), "partial_correct")

    def test_04_bullish_drop_incorrect(self):
        self.assertEqual(self._j("bullish", -0.5), "incorrect")

    def test_05_bullish_zero_change_incorrect(self):
        self.assertEqual(self._j("bullish", 0.0), "incorrect")

    # Bearish
    def test_06_bearish_strong_drop_correct(self):
        self.assertEqual(self._j("bearish", -1.0), "correct")

    def test_07_bearish_small_drop_partial(self):
        self.assertEqual(self._j("bearish", -0.3), "partial_correct")

    def test_08_bearish_rise_incorrect(self):
        self.assertEqual(self._j("bearish", 0.5), "incorrect")

    # Neutral
    def test_09_neutral_small_change_correct(self):
        self.assertEqual(self._j("neutral", 0.5), "correct")   # abs=0.5 < 1

    def test_10_neutral_flat_correct(self):
        self.assertEqual(self._j("neutral", 0.0), "correct")

    def test_11_neutral_large_move_incorrect(self):
        self.assertEqual(self._j("neutral", 2.0), "incorrect")

    def test_12_neutral_negative_large_incorrect(self):
        self.assertEqual(self._j("neutral", -1.5), "incorrect")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — 時間還沒到不驗證
# ═══════════════════════════════════════════════════════════════════════════════

class TestCycleNotYet(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def test_01_future_verify_at_stays_pending(self):
        r = _review()
        _add_pending(self.engine, r, verify_at=_future(4))
        self.engine.run_verification_cycle()
        self.assertIn(r.review_id, self.engine.pending_reviews)

    def test_02_no_verification_attempted(self):
        r = _review()
        _add_pending(self.engine, r, verify_at=_future(4))
        self.engine.run_verification_cycle()
        self.assertEqual(self.engine.reviews_verified, 0)

    def test_03_cycle_returns_zero_verified(self):
        r = _review()
        _add_pending(self.engine, r, verify_at=_future(4))
        count = self.engine.run_verification_cycle()
        self.assertEqual(count, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6 — 時間到了會驗證
# ═══════════════════════════════════════════════════════════════════════════════

class TestCycleVerifies(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()
        self.engine._fetch_price_range = MagicMock(return_value=(3000.0, 3030.0))

    def test_01_past_verify_at_removed_from_pending(self):
        r = _review("CA-01", my_call="bullish")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertNotIn(r.review_id, self.engine.pending_reviews)

    def test_02_hindsight_correct_filled(self):
        r = _review("CA-01", my_call="bullish")   # +1% → correct
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(r.hindsight_correct, "correct")

    def test_03_reviews_verified_incremented(self):
        r = _review("CA-01", my_call="bullish")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(self.engine.reviews_verified, 1)

    def test_04_cycle_returns_verified_count(self):
        for _ in range(3):
            r = _review("CA-01", my_call="bullish")
            _add_pending(self.engine, r, verify_at=_past())
        count = self.engine.run_verification_cycle()
        self.assertEqual(count, 3)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 7 — 統計累積
# ═══════════════════════════════════════════════════════════════════════════════

class TestStats(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def _run(self, my_call: str, start: float, end: float) -> None:
        r = _review(my_call=my_call)
        _add_pending(self.engine, r, verify_at=_past())
        self.engine._fetch_price_range = MagicMock(return_value=(start, end))
        self.engine.run_verification_cycle()

    def test_01_correct_count_increments(self):
        self._run("bullish", 3000, 3030)  # +1% → correct
        self.assertEqual(self.engine.correct_count, 1)

    def test_02_partial_count_increments(self):
        self._run("bullish", 3000, 3009)  # +0.3% → partial
        self.assertEqual(self.engine.partial_count, 1)

    def test_03_incorrect_count_increments(self):
        self._run("bullish", 3000, 2985)  # -0.5% → incorrect
        self.assertEqual(self.engine.incorrect_count, 1)

    def test_04_mixed_stats_accumulate(self):
        self._run("bullish", 3000, 3030)  # correct
        self._run("bullish", 3000, 3009)  # partial
        self._run("bullish", 3000, 2985)  # incorrect
        self.assertEqual(self.engine.correct_count,   1)
        self.assertEqual(self.engine.partial_count,   1)
        self.assertEqual(self.engine.incorrect_count, 1)
        self.assertEqual(self.engine.reviews_verified, 3)

    def test_05_overall_accuracy_calculation(self):
        self._run("bullish", 3000, 3030)  # correct (1.0)
        self._run("bullish", 3000, 3009)  # partial (0.5)
        self._run("bullish", 3000, 2985)  # incorrect (0.0)
        stats = self.engine.get_stats()
        # (1 + 0.5) / 3 = 0.5
        self.assertAlmostEqual(stats["overall_accuracy"], 0.5, places=6)

    def test_06_unverified_due_to_data_increments(self):
        self.engine._fetch_price_range = MagicMock(return_value=(None, None))
        r = _review(my_call="bullish")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(self.engine.unverified_due_to_data, 1)
        self.assertEqual(self.engine.reviews_verified, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 8 — 無法解析方向
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnparseableDirection(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()
        self.engine._fetch_price_range = MagicMock(return_value=(3000.0, 3030.0))

    def test_01_no_direction_keyword_gives_unverified(self):
        r = _review(my_call="tempo=active (no directional signal)")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(r.hindsight_correct, "unverified")
        self.assertIn("無法解析", r.hindsight_notes)

    def test_02_unverified_not_counted_in_verified(self):
        r = _review(my_call="no keywords here")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(self.engine.reviews_verified, 0)

    def test_03_parse_direction_bullish(self):
        self.assertEqual(self.engine._parse_direction("bullish signal"), "bullish")

    def test_04_parse_direction_bearish(self):
        self.assertEqual(self.engine._parse_direction("bearish trend"), "bearish")

    def test_05_parse_direction_neutral(self):
        self.assertEqual(self.engine._parse_direction("neutral stance"), "neutral")

    def test_06_parse_direction_none(self):
        self.assertIsNone(self.engine._parse_direction("active tempo"))


# ═══════════════════════════════════════════════════════════════════════════════
# Group 9 — 廣播 hindsight.verified
# ═══════════════════════════════════════════════════════════════════════════════

class TestBusBroadcast(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def test_01_successful_verification_broadcasts(self):
        received = []
        get_bus().subscribe("hindsight.verified",
                            lambda m: received.append(m.payload), role="test")
        self.engine._fetch_price_range = MagicMock(return_value=(3000.0, 3030.0))
        r = _review(my_call="bullish")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], r)

    def test_02_no_broadcast_for_unparseable_direction(self):
        received = []
        get_bus().subscribe("hindsight.verified",
                            lambda m: received.append(m.payload), role="test")
        self.engine._fetch_price_range = MagicMock(return_value=(3000.0, 3030.0))
        r = _review(my_call="no direction here")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(len(received), 0)

    def test_03_no_broadcast_when_price_data_missing(self):
        received = []
        get_bus().subscribe("hindsight.verified",
                            lambda m: received.append(m.payload), role="test")
        self.engine._fetch_price_range = MagicMock(return_value=(None, None))
        r = _review(my_call="bullish")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        self.assertEqual(len(received), 0)

    def test_04_broadcast_payload_has_hindsight_fields(self):
        received = []
        get_bus().subscribe("hindsight.verified",
                            lambda m: received.append(m.payload), role="test")
        self.engine._fetch_price_range = MagicMock(return_value=(3000.0, 3030.0))
        r = _review(my_call="bullish")
        _add_pending(self.engine, r, verify_at=_past())
        self.engine.run_verification_cycle()
        payload = received[0]
        self.assertIsNotNone(payload.hindsight_correct)
        self.assertEqual(payload.hindsight_verifier, "HINDSIGHT_ENGINE")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 10 — Role Accuracy 計算
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleAccuracy(unittest.TestCase):

    def setUp(self):
        self.engine = _fresh()

    def _verify(self, role_code: str, my_call: str,
                start: float, end: float) -> None:
        r = _review(role_code=role_code, my_call=my_call)
        _add_pending(self.engine, r, verify_at=_past())
        self.engine._fetch_price_range = MagicMock(return_value=(start, end))
        self.engine.run_verification_cycle()

    def test_01_no_history_returns_zero_count(self):
        result = self.engine.get_role_accuracy("CA-01")
        self.assertEqual(result["verified_count"], 0)

    def test_02_weighted_score_correct_partial_incorrect(self):
        # correct=1, partial=1, incorrect=1 → weighted = (1+0.5)/3 = 0.5
        self._verify("CA-01", "bullish", 3000, 3030)  # +1%   → correct
        self._verify("CA-01", "bullish", 3000, 3009)  # +0.3% → partial
        self._verify("CA-01", "bullish", 3000, 2985)  # -0.5% → incorrect
        result = self.engine.get_role_accuracy("CA-01")
        self.assertEqual(result["verified_count"], 3)
        self.assertAlmostEqual(result["weighted_score"], 0.5, places=6)

    def test_03_rates_sum_to_one(self):
        self._verify("IO-01", "bullish", 3000, 3030)  # correct
        self._verify("IO-01", "bearish", 3000, 2970)  # correct
        self._verify("IO-01", "bullish", 3000, 2985)  # incorrect
        result = self.engine.get_role_accuracy("IO-01")
        total = result["correct_rate"] + result["partial_rate"] + result["incorrect_rate"]
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_04_different_role_codes_separated(self):
        self._verify("CA-01", "bullish", 3000, 3030)   # CA-01 correct
        self._verify("GA-01", "bearish", 3000, 2985)   # GA-01 incorrect (bearish but tiny drop)
        ca_result = self.engine.get_role_accuracy("CA-01")
        ga_result = self.engine.get_role_accuracy("GA-01")
        self.assertEqual(ca_result["verified_count"], 1)
        self.assertEqual(ga_result["verified_count"], 1)
        self.assertAlmostEqual(ca_result["correct_rate"],   1.0, places=6)

    def test_05_all_correct_gives_full_score(self):
        for _ in range(5):
            self._verify("TK-01", "bullish", 3000, 3030)   # +1% → correct
        result = self.engine.get_role_accuracy("TK-01")
        self.assertAlmostEqual(result["weighted_score"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
