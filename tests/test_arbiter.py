# -*- coding: utf-8 -*-
"""Tests for trading_system.strategy.arbiter — 老王（仲裁者）。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from trading_system.common.data_models import (
    ArbiterDecision, CourseReport,
    RiskAssessment, SnapshotBundle, TradingProposal,
)
from trading_system.common.message_bus import get_bus, reset_bus
from trading_system.common.snapshot_builder import reset_snapshot_builder
from trading_system.strategy.arbiter import Arbiter


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _course_report(direction: str) -> CourseReport:
    return CourseReport(
        course_name="節奏評估課",
        course_code="TK",
        manager_name="老廖",
        debate_results=[],
        course_direction=direction,
        course_confidence=0.7,
        freshness_grade="real_time",
        data_health={},
        flash_alerts=[],
        self_review={},
        timestamp=datetime.now(),
    )


def _snapshot(tk_dir: str = "bullish") -> SnapshotBundle:
    import uuid
    return SnapshotBundle(
        snapshot_id=str(uuid.uuid4()),
        snapshot_time=datetime.now(),
        overall_data_quality="good",
        tk_report=_course_report(tk_dir),
    )


def _snapshot_no_tk() -> SnapshotBundle:
    import uuid
    return SnapshotBundle(
        snapshot_id=str(uuid.uuid4()),
        snapshot_time=datetime.now(),
        overall_data_quality="good",
    )


def _proposal(
    proposal_id: str = "P-TEST",
    direction: str = "long",
    position_size_usd: float = 50.0,
    entry_price: float = 3000.0,
    stop_loss: float = 2940.0,
    take_profit: float = 3120.0,
    composite_score: float = 0.5,
    environment_type: str = "trending_bullish",
    timestamp: datetime = None,
) -> TradingProposal:
    return TradingProposal(
        proposal_id=proposal_id,
        symbol="ETHUSDT",
        direction=direction,
        entry_type="market",
        position_size_usd=position_size_usd,
        stop_loss=stop_loss,
        composite_score=composite_score,
        direction_confidence=abs(composite_score),
        environment_type=environment_type,
        selected_strategy="trend_following",
        reasoning="test",
        based_on_snapshot="SNAP-TEST",
        timestamp=timestamp or datetime.now(),
        entry_price=entry_price,
        take_profit=take_profit,
    )


def _assessment(
    proposal: TradingProposal,
    decision: str = "APPROVED",
    modified_position_size: float = None,
    rejection_reason: str = None,
) -> RiskAssessment:
    return RiskAssessment(
        assessment_id="A-TEST",
        proposal_id=proposal.proposal_id,
        decision=decision,
        reasoning="test",
        reverse_analysis_internal="test",
        reverse_analysis_external="test",
        timestamp=datetime.now(),
        modified_position_size=modified_position_size,
        modified_stop_loss=None,
        rejection_reason=rejection_reason,
    )


def _fresh(snap: SnapshotBundle = None) -> Arbiter:
    reset_bus()
    reset_snapshot_builder()
    a = Arbiter()
    a.snapshot_builder.build_snapshot = MagicMock(
        return_value=snap if snap is not None else _snapshot("bullish")
    )
    return a


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — 初始化
# ═══════════════════════════════════════════════════════════════════════════════

class TestInit(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_role_name_code(self):
        self.assertEqual(self.officer.role_name, "老王")
        self.assertEqual(self.officer.role_code, "Arbiter")

    def test_02_subscriptions(self):
        bus = get_bus()
        self.assertIn("老王", bus.get_subscribers("proposal.submitted"))
        self.assertIn("老王", bus.get_subscribers("assessment.complete"))

    def test_03_defaults(self):
        o = self.officer
        self.assertEqual(o.decisions_made, 0)
        self.assertEqual(o.execute_count,  0)
        self.assertEqual(o.wait_count,     0)
        self.assertEqual(o.abort_count,    0)
        self.assertEqual(len(o.pending_proposals), 0)

    def test_04_recent_decisions_deque_maxlen(self):
        self.assertEqual(self.officer.recent_decisions.maxlen, 20)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — Proposal 暫存
# ═══════════════════════════════════════════════════════════════════════════════

class TestPendingProposals(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_proposal_stored_on_bus_event(self):
        prop = _proposal()
        get_bus().publish("proposal.submitted", prop, sender="小蘇")
        self.assertIn("P-TEST", self.officer.pending_proposals)

    def test_02_same_proposal_published_twice_not_duplicated(self):
        prop = _proposal()
        get_bus().publish("proposal.submitted", prop, sender="小蘇")
        get_bus().publish("proposal.submitted", prop, sender="小蘇")
        self.assertEqual(len(self.officer.pending_proposals), 1)

    def test_03_non_proposal_payload_ignored(self):
        get_bus().publish("proposal.submitted", {"not": "a proposal"}, sender="小蘇")
        self.assertEqual(len(self.officer.pending_proposals), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — 過期 Proposal 清理
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleProposalCleanup(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_stale_proposal_removed_when_new_arrives(self):
        # 11 minutes old → exceeds 600 s TTL
        old_ts = datetime.now() - timedelta(seconds=660)
        old_prop = _proposal("P-OLD", timestamp=old_ts)
        self.officer.pending_proposals["P-OLD"] = old_prop

        new_prop = _proposal("P-NEW")
        get_bus().publish("proposal.submitted", new_prop, sender="小蘇")

        self.assertNotIn("P-OLD", self.officer.pending_proposals)
        self.assertIn("P-NEW",   self.officer.pending_proposals)

    def test_02_fresh_proposal_not_removed(self):
        # Just-created proposal should survive
        prop = _proposal("P-FRESH")
        get_bus().publish("proposal.submitted", prop, sender="小蘇")
        self.assertIn("P-FRESH", self.officer.pending_proposals)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — 怡姐 REJECTED → ABORT
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecision_Abort_Rejected(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_rejected_assessment_gives_abort(self):
        prop = _proposal()
        assessment = _assessment(prop, decision="REJECTED", rejection_reason="部位超限")
        result = self.officer.make_decision(prop, assessment)
        self.assertEqual(result.final_decision, "ABORT")

    def test_02_abort_reasoning_mentions_rejection(self):
        prop = _proposal()
        assessment = _assessment(prop, decision="REJECTED", rejection_reason="部位超限")
        result = self.officer.make_decision(prop, assessment)
        self.assertIn("風控拒絕", result.reasoning)

    def test_03_rejected_overrides_active_tempo(self):
        # Even active tempo cannot override REJECTED
        prop = _proposal(composite_score=0.9)
        assessment = _assessment(prop, decision="REJECTED", rejection_reason="RED alert")
        result = self.officer.make_decision(prop, assessment)
        self.assertEqual(result.final_decision, "ABORT")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — Tempo=rest → ABORT
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecision_Abort_Rest(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh(snap=_snapshot("bearish"))  # rest

    def test_01_rest_tempo_gives_abort(self):
        prop = _proposal()
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "ABORT")

    def test_02_rest_tempo_reasoning(self):
        prop = _proposal()
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertIn("rest", result.reasoning)

    def test_03_rest_tempo_overrides_approved_assessment(self):
        # APPROVED but rest → still ABORT
        prop = _proposal(composite_score=0.9, position_size_usd=80.0)
        result = self.officer.make_decision(prop, _assessment(prop, decision="APPROVED"))
        self.assertEqual(result.final_decision, "ABORT")

    def test_04_no_tk_report_defaults_to_cautious(self):
        officer = _fresh(snap=_snapshot_no_tk())
        # cautious (0.5) × 50 = 25 >= 20, composite=0.5 >= 0.4 → EXECUTE
        prop = _proposal()
        result = officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "EXECUTE")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6 — Tempo=cautious + 低信心 → WAIT
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecision_Wait_Cautious(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh(snap=_snapshot("neutral"))  # cautious

    def test_01_cautious_with_low_confidence_gives_wait(self):
        # composite=0.3 < 0.4 → WAIT; position 50×0.5=25 >= 20 ✓
        prop = _proposal(composite_score=0.3)
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "WAIT")

    def test_02_cautious_with_high_confidence_gives_execute(self):
        # composite=0.5 >= 0.4 → not WAIT; 50×0.5=25 >= 20 → EXECUTE
        prop = _proposal(composite_score=0.5)
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "EXECUTE")

    def test_03_wait_reasoning_mentions_cautious(self):
        prop = _proposal(composite_score=0.3)
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertIn("cautious", result.reasoning)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 7 — 倉位過小 → ABORT
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecision_Abort_TinyPosition(unittest.TestCase):

    def test_01_cautious_shrinks_position_below_min(self):
        # cautious (×0.5) × 30 = 15 < 20 → ABORT; composite=0.5 (≥0.4 so not WAIT)
        officer = _fresh(snap=_snapshot("neutral"))
        prop = _proposal(position_size_usd=30.0, composite_score=0.5)
        result = officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "ABORT")
        self.assertIn("倉位過小", result.reasoning)

    def test_02_modified_position_too_small(self):
        # MODIFIED with size=15; active (×1.0) → 15 < 20 → ABORT
        officer = _fresh(snap=_snapshot("bullish"))
        prop = _proposal(composite_score=0.5)
        assessment = _assessment(prop, decision="MODIFIED", modified_position_size=15.0)
        result = officer.make_decision(prop, assessment)
        self.assertEqual(result.final_decision, "ABORT")

    def test_03_exactly_at_minimum_not_aborted(self):
        # active (×1.0) × 20 = 20.0 — not < 20 → OK
        officer = _fresh(snap=_snapshot("bullish"))
        prop = _proposal(position_size_usd=20.0, composite_score=0.5)
        result = officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "EXECUTE")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 8 — 傾向係數計算
# ═══════════════════════════════════════════════════════════════════════════════

class TestTendencyCoefficient(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_fewer_than_5_decisions_returns_neutral(self):
        for _ in range(4):
            self.officer.recent_decisions.append(
                {"decision": "EXECUTE", "timestamp": time.time()}
            )
        self.assertAlmostEqual(self.officer._compute_tendency_coefficient(), 0.5)

    def test_02_all_execute_gives_min_tendency(self):
        # execute_rate = 1.0 > 0.7 → max(0.3, 0.5 - 0.3) = 0.3
        for _ in range(10):
            self.officer.recent_decisions.append(
                {"decision": "EXECUTE", "timestamp": time.time()}
            )
        self.assertAlmostEqual(self.officer._compute_tendency_coefficient(), 0.3)

    def test_03_all_abort_gives_max_tendency(self):
        # abort_rate = 1.0 > 0.7 → min(0.7, 0.5 + 0.3) = 0.7
        for _ in range(10):
            self.officer.recent_decisions.append(
                {"decision": "ABORT", "timestamp": time.time()}
            )
        self.assertAlmostEqual(self.officer._compute_tendency_coefficient(), 0.7)

    def test_04_mixed_decisions_returns_neutral(self):
        # 5 EXECUTE + 5 ABORT → exec_rate = 0.5, abort_rate = 0.5 → 0.5
        for _ in range(5):
            self.officer.recent_decisions.append(
                {"decision": "EXECUTE", "timestamp": time.time()}
            )
        for _ in range(5):
            self.officer.recent_decisions.append(
                {"decision": "ABORT", "timestamp": time.time()}
            )
        self.assertAlmostEqual(self.officer._compute_tendency_coefficient(), 0.5)

    def test_05_exactly_70pct_execute_stays_neutral(self):
        # 7 EXECUTE + 3 ABORT → exec_rate = 0.7, not > 0.7 → 0.5
        for _ in range(7):
            self.officer.recent_decisions.append(
                {"decision": "EXECUTE", "timestamp": time.time()}
            )
        for _ in range(3):
            self.officer.recent_decisions.append(
                {"decision": "ABORT", "timestamp": time.time()}
            )
        self.assertAlmostEqual(self.officer._compute_tendency_coefficient(), 0.5)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 9 — 完整流程：APPROVED
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullFlow_Approved(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh(snap=_snapshot("bullish"))

    def test_01_approved_gives_execute_via_bus(self):
        received = []
        get_bus().subscribe(
            "decision.final", lambda m: received.append(m.payload), role="test"
        )
        prop = _proposal()
        get_bus().publish("proposal.submitted",  prop,               sender="小蘇")
        get_bus().publish("assessment.complete", _assessment(prop),  sender="怡姐")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["decision"].final_decision, "EXECUTE")

    def test_02_decision_stats_incremented(self):
        prop = _proposal()
        get_bus().publish("proposal.submitted",  prop,              sender="小蘇")
        get_bus().publish("assessment.complete", _assessment(prop), sender="怡姐")
        self.assertEqual(self.officer.decisions_made, 1)
        self.assertEqual(self.officer.execute_count,  1)

    def test_03_proposal_removed_from_pending_after_decision(self):
        prop = _proposal()
        get_bus().publish("proposal.submitted",  prop,              sender="小蘇")
        get_bus().publish("assessment.complete", _assessment(prop), sender="怡姐")
        self.assertNotIn("P-TEST", self.officer.pending_proposals)

    def test_04_arbiter_decision_fields_populated(self):
        received = []
        get_bus().subscribe(
            "decision.final", lambda m: received.append(m.payload), role="test"
        )
        prop = _proposal()
        get_bus().publish("proposal.submitted",  prop,              sender="小蘇")
        get_bus().publish("assessment.complete", _assessment(prop), sender="怡姐")
        d = received[0]["decision"]
        self.assertIsInstance(d, ArbiterDecision)
        self.assertEqual(d.proposal_id,  "P-TEST")
        self.assertEqual(d.assessment_id, "A-TEST")
        self.assertAlmostEqual(d.tempo_factor, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 10 — 完整流程：MODIFIED
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullFlow_Modified(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh(snap=_snapshot("bullish"))  # active, factor=1.0

    def test_01_modified_gives_execute_when_size_ok(self):
        # modified_position_size=30 × 1.0 = 30 >= 20 → EXECUTE
        prop = _proposal()
        assessment = _assessment(prop, decision="MODIFIED", modified_position_size=30.0)
        get_bus().publish("proposal.submitted",  prop,       sender="小蘇")
        get_bus().publish("assessment.complete", assessment, sender="怡姐")
        self.assertEqual(self.officer.execute_count, 1)

    def test_02_modified_reasoning_contains_modified(self):
        received = []
        get_bus().subscribe(
            "decision.final", lambda m: received.append(m.payload), role="test"
        )
        prop = _proposal()
        assessment = _assessment(prop, decision="MODIFIED", modified_position_size=30.0)
        get_bus().publish("proposal.submitted",  prop,       sender="小蘇")
        get_bus().publish("assessment.complete", assessment, sender="怡姐")
        self.assertIn("修改", received[0]["decision"].reasoning)

    def test_03_modified_with_tiny_position_gives_abort(self):
        # modified_position_size=10 × 1.0 = 10 < 20 → ABORT
        prop = _proposal()
        assessment = _assessment(prop, decision="MODIFIED", modified_position_size=10.0)
        get_bus().publish("proposal.submitted",  prop,       sender="小蘇")
        get_bus().publish("assessment.complete", assessment, sender="怡姐")
        self.assertEqual(self.officer.abort_count, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 11 — tempo=active 但傾向係數低 → 仍可能 WAIT
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecision_Wait_LowTendency(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh(snap=_snapshot("bullish"))  # active

    def _fill_execute(self, n: int = 10):
        for _ in range(n):
            self.officer.recent_decisions.append(
                {"decision": "EXECUTE", "timestamp": time.time()}
            )

    def test_01_low_tendency_with_low_confidence_gives_wait(self):
        # 10 EXECUTE → tendency = 0.3 (<0.4); composite=0.4 (<0.5) → WAIT
        self._fill_execute(10)
        prop = _proposal(composite_score=0.4)
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "WAIT")

    def test_02_low_tendency_but_high_confidence_gives_execute(self):
        # tendency = 0.3 but composite=0.6 >= 0.5 → EXECUTE
        self._fill_execute(10)
        prop = _proposal(composite_score=0.6)
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "EXECUTE")

    def test_03_normal_tendency_low_confidence_gives_execute(self):
        # tendency = 0.5 (mixed), composite=0.4 < 0.5 but tendency >= 0.4 → EXECUTE
        for _ in range(5):
            self.officer.recent_decisions.append({"decision": "EXECUTE", "timestamp": time.time()})
        for _ in range(5):
            self.officer.recent_decisions.append({"decision": "ABORT", "timestamp": time.time()})
        prop = _proposal(composite_score=0.4)
        result = self.officer.make_decision(prop, _assessment(prop))
        self.assertEqual(result.final_decision, "EXECUTE")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 12 — 找不到對應 Proposal
# ═══════════════════════════════════════════════════════════════════════════════

class TestMissingProposal(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_no_crash_when_proposal_missing(self):
        # Publish assessment without prior proposal.submitted
        assessment = _assessment(_proposal(), decision="APPROVED")
        try:
            get_bus().publish("assessment.complete", assessment, sender="怡姐")
        except Exception as e:
            self.fail(f"Should not raise, but got: {e}")

    def test_02_no_decision_published_when_proposal_missing(self):
        received = []
        get_bus().subscribe(
            "decision.final", lambda m: received.append(m.payload), role="test"
        )
        assessment = _assessment(_proposal(), decision="APPROVED")
        get_bus().publish("assessment.complete", assessment, sender="怡姐")
        self.assertEqual(len(received), 0)

    def test_03_decisions_made_not_incremented(self):
        assessment = _assessment(_proposal(), decision="APPROVED")
        get_bus().publish("assessment.complete", assessment, sender="怡姐")
        self.assertEqual(self.officer.decisions_made, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
