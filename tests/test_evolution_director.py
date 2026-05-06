# -*- coding: utf-8 -*-
"""tests/test_evolution_director.py — 10 個測試組，覆蓋大劉（EvolutionDirector）所有核心邏輯。"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import unittest
from datetime import datetime

from trading_system.common.feedback_models import SelfReview
from trading_system.common.message_bus import get_bus, reset_bus
from trading_system.evolution.evolution_director import EvolutionDirector


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fresh() -> EvolutionDirector:
    reset_bus()
    return EvolutionDirector()


def _review(role_code: str, result: str) -> SelfReview:
    """Create a SelfReview with hindsight_correct pre-filled."""
    r = SelfReview(
        role_name=role_code,
        role_code=role_code,
        work_type="direction",
        timestamp=datetime.now(),
        my_call="bullish",
        confidence_at_time=0.7,
        reasoning="test",
        data_used={},
    )
    r.hindsight_correct = result
    return r


def _fill_buffer(director: EvolutionDirector, role_code: str, results: list[str]) -> None:
    """Insert reviews directly into the accuracy buffer (bypasses bus for speed)."""
    if role_code not in director.role_accuracy_buffer:
        director.role_accuracy_buffer[role_code] = []
    for r in results:
        director.role_accuracy_buffer[role_code].append({
            "result":    r,
            "timestamp": time.time(),
        })


def _make_executed_adj(director: EvolutionDirector,
                       role_code: str,
                       old_accuracy: float = 0.40,
                       elapsed_seconds: float = 200.0) -> dict:
    """Add a fake EXECUTED adjustment that is already past its rollback_at."""
    past_dt = datetime.fromtimestamp(time.time() - elapsed_seconds)
    adj = {
        "type":                 "ADJUSTMENT",
        "target_role":          role_code,
        "current_accuracy":     old_accuracy,
        "sample_size":          25,
        "recommendation":       "test",
        "proposed_action":      "tighten_thresholds",
        "adjustment_magnitude": 0.1,
        "timestamp":            past_dt,
        "executed_at":          past_dt,
        "status":               "EXECUTED",
        "rollback_at":          time.time() - 1,   # already elapsed
    }
    director.adjustments_proposed.append(adj)
    return adj


# ─── Group 01: 初始化與訂閱 ────────────────────────────────────────────────────

class TestGroup01_Initialization(unittest.TestCase):

    def setUp(self):
        self.d = _fresh()

    def test_01_role_name(self):
        self.assertEqual(self.d.role_name, "大劉")

    def test_02_role_code(self):
        self.assertEqual(self.d.role_code, "TO-Manager")

    def test_03_subscribes_to_hindsight_verified(self):
        self.assertIn("大劉", get_bus().get_subscribers("hindsight.verified"))

    def test_04_subscribes_to_baseline_comparison(self):
        self.assertIn("大劉", get_bus().get_subscribers("baseline.comparison"))

    def test_05_initial_self_weight(self):
        self.assertAlmostEqual(self.d.self_weight_multiplier, 1.0)

    def test_06_initial_counters(self):
        self.assertEqual(self.d.adjustments_rolled_back, 0)
        self.assertEqual(self.d.consecutive_invalid_adjustments, 0)

    def test_07_initial_buffers_empty(self):
        self.assertEqual(len(self.d.role_accuracy_buffer), 0)
        self.assertEqual(len(self.d.adjustments_proposed), 0)
        self.assertEqual(len(self.d.suggestions_proposed), 0)

    def test_08_evaluation_interval_is_24h(self):
        self.assertEqual(self.d.evaluation_interval, 86400)


# ─── Group 02: 累積 hindsight 結果 ────────────────────────────────────────────

class TestGroup02_HindsightAccumulation(unittest.TestCase):

    def setUp(self):
        self.d = _fresh()

    def test_01_buffer_grows_on_hindsight_message(self):
        get_bus().publish("hindsight.verified", _review("CA-01", "correct"), sender="HINDSIGHT")
        self.assertIn("CA-01", self.d.role_accuracy_buffer)
        self.assertEqual(len(self.d.role_accuracy_buffer["CA-01"]), 1)

    def test_02_result_stored_correctly(self):
        get_bus().publish("hindsight.verified", _review("CA-01", "incorrect"), sender="HINDSIGHT")
        entry = self.d.role_accuracy_buffer["CA-01"][0]
        self.assertEqual(entry["result"], "incorrect")

    def test_03_multiple_roles_tracked_separately(self):
        get_bus().publish("hindsight.verified", _review("CA-01", "correct"), sender="HINDSIGHT")
        get_bus().publish("hindsight.verified", _review("EX-01", "incorrect"), sender="HINDSIGHT")
        self.assertIn("CA-01", self.d.role_accuracy_buffer)
        self.assertIn("EX-01", self.d.role_accuracy_buffer)

    def test_04_unverified_result_ignored(self):
        r = _review("CA-01", "unverified")
        get_bus().publish("hindsight.verified", r, sender="HINDSIGHT")
        self.assertNotIn("CA-01", self.d.role_accuracy_buffer)

    def test_05_partial_correct_stored(self):
        get_bus().publish("hindsight.verified", _review("IO-01", "partial_correct"), sender="HINDSIGHT")
        self.assertEqual(self.d.role_accuracy_buffer["IO-01"][0]["result"], "partial_correct")

    def test_06_buffer_capped_at_100(self):
        for _ in range(105):
            get_bus().publish("hindsight.verified", _review("GA-01", "incorrect"), sender="HINDSIGHT")
        self.assertLessEqual(len(self.d.role_accuracy_buffer["GA-01"]), 100)

    def test_07_non_review_payload_ignored(self):
        get_bus().publish("hindsight.verified", {"junk": True}, sender="HINDSIGHT")
        self.assertEqual(len(self.d.role_accuracy_buffer), 0)


# ─── Group 03: 樣本不足跳過 ───────────────────────────────────────────────────

class TestGroup03_InsufficientSamples(unittest.TestCase):

    def test_01_no_proposal_below_min_sample(self):
        d = _fresh()
        _fill_buffer(d, "CA-01", ["incorrect"] * 5)
        proposals = d.evaluate_all_roles()
        self.assertEqual(len(proposals), 0)

    def test_02_no_proposal_at_exactly_19(self):
        d = _fresh()
        _fill_buffer(d, "CA-01", ["incorrect"] * 19)
        proposals = d.evaluate_all_roles()
        self.assertEqual(len(proposals), 0)

    def test_03_proposal_at_exactly_20(self):
        d = _fresh()
        # All incorrect → accuracy 0.0 < 0.50 → triggers
        _fill_buffer(d, "CA-01", ["incorrect"] * 20)
        proposals = d.evaluate_all_roles()
        self.assertEqual(len(proposals), 1)

    def test_04_no_proposal_when_accuracy_above_threshold(self):
        d = _fresh()
        # 20 correct → accuracy 1.0 ≥ 0.50 → no proposal
        _fill_buffer(d, "CA-01", ["correct"] * 20)
        proposals = d.evaluate_all_roles()
        self.assertEqual(len(proposals), 0)


# ─── Group 04: 觸發 ADJUSTMENT（準確率 0.40）────────────────────────────────

class TestGroup04_TriggerAdjustment(unittest.TestCase):

    def setUp(self):
        self.d = _fresh()
        # 25 reviews: 10 correct, 15 incorrect → weighted = 10/25 = 0.40 (0.35≤x<0.50)
        _fill_buffer(self.d, "IO-01", ["correct"] * 10 + ["incorrect"] * 15)
        self.proposals = self.d.evaluate_all_roles()

    def test_01_one_proposal_produced(self):
        self.assertEqual(len(self.proposals), 1)

    def test_02_proposal_type_is_adjustment(self):
        self.assertEqual(self.proposals[0]["type"], "ADJUSTMENT")

    def test_03_target_role_correct(self):
        self.assertEqual(self.proposals[0]["target_role"], "IO-01")

    def test_04_adjustment_recorded_in_deque(self):
        self.assertEqual(len(self.d.adjustments_proposed), 1)

    def test_05_evolution_adjustment_published(self):
        history = get_bus().get_message_history("evolution.adjustment", limit=10)
        self.assertEqual(len(history), 1)

    def test_06_adjustment_status_is_executed(self):
        self.assertEqual(self.proposals[0]["status"], "EXECUTED")

    def test_07_cooldown_set_for_role(self):
        self.assertIn("IO-01", self.d.role_cooldowns)
        self.assertGreater(self.d.role_cooldowns["IO-01"], time.time())


# ─── Group 05: 觸發 SUGGESTION（準確率 < 0.35）────────────────────────────────

class TestGroup05_TriggerSuggestion(unittest.TestCase):

    def setUp(self):
        self.d = _fresh()
        # 25 reviews: 0 correct, 25 incorrect → accuracy 0.0 < 0.35 → SUGGESTION
        _fill_buffer(self.d, "GA-01", ["incorrect"] * 25)
        self.proposals = self.d.evaluate_all_roles()

    def test_01_one_proposal_produced(self):
        self.assertEqual(len(self.proposals), 1)

    def test_02_proposal_type_is_suggestion(self):
        self.assertEqual(self.proposals[0]["type"], "SUGGESTION")

    def test_03_suggestion_recorded_in_deque(self):
        self.assertEqual(len(self.d.suggestions_proposed), 1)

    def test_04_evolution_suggestion_published(self):
        history = get_bus().get_message_history("evolution.suggestion", limit=10)
        self.assertEqual(len(history), 1)

    def test_05_suggestion_status_pending(self):
        self.assertEqual(self.proposals[0]["status"], "PENDING_APPROVAL")

    def test_06_suggestion_not_in_adjustment_deque(self):
        self.assertEqual(len(self.d.adjustments_proposed), 0)


# ─── Group 06: 冷卻期阻擋 ─────────────────────────────────────────────────────

class TestGroup06_CooldownBlocking(unittest.TestCase):

    def test_01_second_evaluation_blocked_by_cooldown(self):
        d = _fresh()
        # accuracy=0.40 (ADJUSTMENT range) → sets cooldown
        _fill_buffer(d, "TK-01", ["correct"] * 10 + ["incorrect"] * 15)
        first = d.evaluate_all_roles()
        self.assertEqual(len(first), 1)
        _fill_buffer(d, "TK-01", ["incorrect"] * 5)
        second = d.evaluate_all_roles()
        self.assertEqual(len(second), 0)

    def test_02_cooldown_stored_for_correct_role(self):
        d = _fresh()
        # Only ADJUSTMENT proposals set cooldowns (accuracy 0.35–0.50)
        _fill_buffer(d, "TK-01", ["correct"] * 10 + ["incorrect"] * 15)
        d.evaluate_all_roles()
        self.assertIn("TK-01", d.role_cooldowns)

    def test_03_other_role_not_blocked(self):
        d = _fresh()
        # TK-01 gets ADJUSTMENT (0.40) → cooldown set
        _fill_buffer(d, "TK-01", ["correct"] * 10 + ["incorrect"] * 15)
        d.evaluate_all_roles()
        # AU-01 is a different role, no cooldown
        _fill_buffer(d, "AU-01", ["incorrect"] * 25)
        second = d.evaluate_all_roles()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["target_role"], "AU-01")

    def test_04_cooldown_cleared_allows_re_evaluation(self):
        d = _fresh()
        _fill_buffer(d, "CA-02", ["incorrect"] * 25)
        d.evaluate_all_roles()
        # Force-expire the cooldown
        d.role_cooldowns["CA-02"] = time.time() - 1
        _fill_buffer(d, "CA-02", ["incorrect"] * 5)
        second = d.evaluate_all_roles()
        self.assertEqual(len(second), 1)


# ─── Group 07: 冷卻期結束 + 有改善 → CONFIRMED ────────────────────────────────

class TestGroup07_ConfirmedAfterImprovement(unittest.TestCase):

    def test_01_status_confirmed_when_improvement_sufficient(self):
        d = _fresh()
        adj = _make_executed_adj(d, "IO-02", old_accuracy=0.40, elapsed_seconds=200)
        # Add 15 high-accuracy reviews after the adjustment timestamp
        _fill_buffer(d, "IO-02", ["correct"] * 13 + ["incorrect"] * 2)
        d.check_adjustment_effects()
        self.assertEqual(adj["status"], "CONFIRMED")

    def test_02_new_accuracy_stored(self):
        d = _fresh()
        adj = _make_executed_adj(d, "IO-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "IO-02", ["correct"] * 13 + ["incorrect"] * 2)
        d.check_adjustment_effects()
        self.assertIn("new_accuracy", adj)

    def test_03_improvement_stored(self):
        d = _fresh()
        adj = _make_executed_adj(d, "IO-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "IO-02", ["correct"] * 13 + ["incorrect"] * 2)
        d.check_adjustment_effects()
        self.assertGreaterEqual(adj.get("improvement", 0), 0.05)

    def test_04_consecutive_invalid_resets_to_zero(self):
        d = _fresh()
        d.consecutive_invalid_adjustments = 3
        adj = _make_executed_adj(d, "IO-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "IO-02", ["correct"] * 13 + ["incorrect"] * 2)
        d.check_adjustment_effects()
        self.assertEqual(d.consecutive_invalid_adjustments, 0)

    def test_05_confirmed_adjustment_not_re_processed(self):
        d = _fresh()
        adj = _make_executed_adj(d, "IO-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "IO-02", ["correct"] * 13 + ["incorrect"] * 2)
        d.check_adjustment_effects()
        d.check_adjustment_effects()  # second call
        self.assertEqual(adj["status"], "CONFIRMED")  # unchanged


# ─── Group 08: 冷卻期結束 + 無改善 → ROLLED_BACK ──────────────────────────────

class TestGroup08_RolledBackNoImprovement(unittest.TestCase):

    def test_01_status_rolled_back_when_no_improvement(self):
        d = _fresh()
        adj = _make_executed_adj(d, "AU-02", old_accuracy=0.40, elapsed_seconds=200)
        # Low-accuracy post-adjustment reviews (improvement < 0.05)
        _fill_buffer(d, "AU-02", ["incorrect"] * 15)
        d.check_adjustment_effects()
        self.assertEqual(adj["status"], "ROLLED_BACK")

    def test_02_adjustments_rolled_back_counter_increments(self):
        d = _fresh()
        _make_executed_adj(d, "AU-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "AU-02", ["incorrect"] * 15)
        d.check_adjustment_effects()
        self.assertEqual(d.adjustments_rolled_back, 1)

    def test_03_consecutive_invalid_increments(self):
        d = _fresh()
        _make_executed_adj(d, "AU-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "AU-02", ["incorrect"] * 15)
        d.check_adjustment_effects()
        self.assertEqual(d.consecutive_invalid_adjustments, 1)

    def test_04_evolution_rollback_published(self):
        d = _fresh()
        _make_executed_adj(d, "AU-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "AU-02", ["incorrect"] * 15)
        d.check_adjustment_effects()
        history = get_bus().get_message_history("evolution.rollback", limit=10)
        self.assertEqual(len(history), 1)

    def test_05_rollback_reason_stored(self):
        d = _fresh()
        adj = _make_executed_adj(d, "AU-02", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "AU-02", ["incorrect"] * 15)
        d.check_adjustment_effects()
        self.assertIn("rollback_reason", adj)

    def test_06_skipped_when_fewer_than_10_post_samples(self):
        d = _fresh()
        adj = _make_executed_adj(d, "AU-03", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "AU-03", ["incorrect"] * 9)  # only 9 → skipped
        d.check_adjustment_effects()
        self.assertEqual(adj["status"], "EXECUTED")  # unchanged


# ─── Group 09: 大劉自我降權 ───────────────────────────────────────────────────

class TestGroup09_SelfWeightReduction(unittest.TestCase):

    def _do_rollback(self, d: EvolutionDirector, role: str) -> None:
        adj = {"target_role": role, "current_accuracy": 0.40,
               "status": "EXECUTED", "proposed_action": "tighten_thresholds"}
        d._rollback_adjustment(adj, 0.38)

    def test_01_weight_unchanged_below_5(self):
        d = _fresh()
        for i in range(4):
            self._do_rollback(d, f"ROLE-{i}")
        self.assertAlmostEqual(d.self_weight_multiplier, 1.0)

    def test_02_weight_drops_at_5th_rollback(self):
        d = _fresh()
        for i in range(5):
            self._do_rollback(d, f"ROLE-{i}")
        self.assertLess(d.self_weight_multiplier, 1.0)

    def test_03_weight_below_0_9_after_6_rollbacks(self):
        d = _fresh()
        for i in range(6):
            self._do_rollback(d, f"ROLE-{i}")
        self.assertLess(d.self_weight_multiplier, 0.9)

    def test_04_weight_floored_at_0_5(self):
        d = _fresh()
        # 50 rollbacks should not drop below 0.5
        for i in range(50):
            self._do_rollback(d, f"ROLE-{i}")
        self.assertGreaterEqual(d.self_weight_multiplier, 0.5)

    def test_05_consecutive_count_accumulates(self):
        d = _fresh()
        for i in range(7):
            self._do_rollback(d, f"ROLE-{i}")
        self.assertEqual(d.consecutive_invalid_adjustments, 7)

    def test_06_consecutive_resets_on_confirmed(self):
        d = _fresh()
        for i in range(3):
            self._do_rollback(d, f"ROLE-{i}")
        self.assertEqual(d.consecutive_invalid_adjustments, 3)
        # Simulate a successful adjustment being confirmed
        adj = _make_executed_adj(d, "CONFIRM-01", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "CONFIRM-01", ["correct"] * 14 + ["incorrect"] * 1)
        d.check_adjustment_effects()
        self.assertEqual(d.consecutive_invalid_adjustments, 0)


# ─── Group 10: 廣播完整流程 ───────────────────────────────────────────────────

class TestGroup10_FullBroadcastFlow(unittest.TestCase):

    def test_01_adjustment_message_sender_is_director(self):
        d = _fresh()
        _fill_buffer(d, "CA-03", ["correct"] * 10 + ["incorrect"] * 15)
        d.evaluate_all_roles()
        msgs = get_bus().get_message_history("evolution.adjustment", limit=10)
        self.assertEqual(msgs[0].sender, "大劉")

    def test_02_suggestion_message_sender_is_director(self):
        d = _fresh()
        _fill_buffer(d, "CA-03", ["incorrect"] * 25)
        d.evaluate_all_roles()
        msgs = get_bus().get_message_history("evolution.suggestion", limit=10)
        self.assertEqual(msgs[0].sender, "大劉")

    def test_03_rollback_message_sender_is_director(self):
        d = _fresh()
        _make_executed_adj(d, "CA-03", old_accuracy=0.40, elapsed_seconds=200)
        _fill_buffer(d, "CA-03", ["incorrect"] * 15)
        d.check_adjustment_effects()
        msgs = get_bus().get_message_history("evolution.rollback", limit=10)
        self.assertEqual(msgs[0].sender, "大劉")

    def test_04_run_cycle_triggers_evaluate_when_overdue(self):
        d = _fresh()
        _fill_buffer(d, "DM-02", ["incorrect"] * 25)
        d.run_cycle()
        msgs = get_bus().get_message_history("evolution.suggestion", limit=10)
        self.assertEqual(len(msgs), 1)

    def test_05_run_cycle_skips_when_not_overdue(self):
        d = _fresh()
        _fill_buffer(d, "DM-02", ["incorrect"] * 25)
        d.run_cycle()  # sets last_evaluation_time
        first_msg_count = len(get_bus().get_message_history("evolution.suggestion", limit=100))
        _fill_buffer(d, "DM-03", ["incorrect"] * 25)
        d.run_cycle()  # should be skipped (interval not elapsed)
        second_msg_count = len(get_bus().get_message_history("evolution.suggestion", limit=100))
        self.assertEqual(first_msg_count, second_msg_count)

    def test_06_get_status_returns_all_fields(self):
        d = _fresh()
        status = d.get_status()
        for key in ("role", "adjustments_proposed_total", "suggestions_proposed_total",
                    "adjustments_rolled_back", "consecutive_invalid", "self_weight",
                    "active_cooldowns"):
            self.assertIn(key, status)

    def test_07_get_status_role_is_correct(self):
        d = _fresh()
        self.assertEqual(d.get_status()["role"], "大劉")

    def test_08_adjustment_payload_has_target_role(self):
        d = _fresh()
        _fill_buffer(d, "EX-02", ["correct"] * 10 + ["incorrect"] * 15)
        d.evaluate_all_roles()
        msg = get_bus().get_message_history("evolution.adjustment", limit=10)[0]
        self.assertEqual(msg.payload["target_role"], "EX-02")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("EvolutionDirector Tests  (10 groups)")
    print("=" * 60)
    unittest.main(verbosity=2)
