# -*- coding: utf-8 -*-
"""Tests for trading_system.strategy.risk_officer — 怡姐（風控官）。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import unittest
from datetime import datetime

from trading_system.common.data_models import AnomalyEvent, TradingProposal
from trading_system.common.message_bus import get_bus, reset_bus
from trading_system.strategy.risk_officer import RiskOfficer


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _proposal(
    direction="long",
    position_size_usd=50.0,
    entry_price=3000.0,
    stop_loss=2940.0,      # long: 2% below; gives stop_dist=60, stop_pct=0.02
    take_profit=3120.0,    # long: 4% above; reward=120, RR=2.0
    composite_score=0.5,
    environment_type="trending_bullish",
    **kwargs,
) -> TradingProposal:
    base = dict(
        proposal_id="P-TEST",
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
        timestamp=datetime.now(),
        entry_price=entry_price,
        take_profit=take_profit,
    )
    base.update(kwargs)
    return TradingProposal(**base)


def _fresh() -> RiskOfficer:
    reset_bus()
    return RiskOfficer()


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — 初始化
# ═══════════════════════════════════════════════════════════════════════════════

class TestInit(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_defaults(self):
        o = self.officer
        self.assertEqual(o.current_alert_level, "GREEN")
        self.assertEqual(o.consecutive_losses, 0)
        self.assertEqual(len(o.recent_anomalies), 0)

    def test_02_assessment_counters(self):
        o = self.officer
        self.assertEqual(o.assessments_total,    0)
        self.assertEqual(o.assessments_approved, 0)
        self.assertEqual(o.assessments_modified, 0)
        self.assertEqual(o.assessments_rejected, 0)

    def test_03_recent_assessments_deque_maxlen(self):
        self.assertEqual(self.officer.recent_assessments.maxlen, 50)

    def test_04_subscriptions(self):
        bus = get_bus()
        self.assertIn("怡姐", bus.get_subscribers("proposal.submitted"))
        self.assertIn("怡姐", bus.get_subscribers("au01.status_update"))
        self.assertIn("怡姐", bus.get_subscribers("anomaly.detected"))

    def test_05_role_name_code(self):
        self.assertEqual(self.officer.role_name, "怡姐")
        self.assertEqual(self.officer.role_code, "Risk-Officer")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — 內部風險：正常提案
# ═══════════════════════════════════════════════════════════════════════════════

class TestInternalCheck_Clean(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_clean_long_proposal(self):
        # entry=3000, stop=2940 (2%), tp=3120 (4%), score=0.5 → severity 0.0
        severity, reasoning = self.officer._check_internal(_proposal())
        self.assertAlmostEqual(severity, 0.0)
        self.assertIn("正常", reasoning)

    def test_02_clean_short_proposal(self):
        # short: entry=3000, stop=3060 (2% above), tp=2880 (4% below)
        prop = _proposal(direction="short", stop_loss=3060.0, take_profit=2880.0,
                         composite_score=-0.5)
        severity, reasoning = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 0.0)
        self.assertIn("正常", reasoning)

    def test_03_no_take_profit_skips_rr(self):
        # no tp → RR check skipped, severity stays 0
        prop = _proposal(take_profit=None)
        severity, _ = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — 內部風險：倉位上限
# ═══════════════════════════════════════════════════════════════════════════════

class TestInternalCheck_PositionCap(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_exactly_at_cap_not_rejected(self):
        # 100.0 == MAX_POSITION_USD → not > → no reject
        prop = _proposal(position_size_usd=100.0)
        severity, _ = self.officer._check_internal(prop)
        self.assertLess(severity, 1.0)

    def test_02_over_cap_rejected(self):
        prop = _proposal(position_size_usd=100.01)
        severity, reasoning = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 1.0)
        self.assertIn("超過上限", reasoning)

    def test_03_way_over_cap(self):
        prop = _proposal(position_size_usd=200.0)
        severity, _ = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4 — 內部風險：止損距離、R/R、信心度
# ═══════════════════════════════════════════════════════════════════════════════

class TestInternalCheck_StopAndRR(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_tight_stop_adds_severity(self):
        # entry=3000, stop=2999 → stop_pct=0.033% < 0.5% → +0.5
        prop = _proposal(entry_price=3000.0, stop_loss=2999.0, take_profit=3009.0)
        severity, reasoning = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 0.5)
        self.assertIn("止損距離過小", reasoning)

    def test_02_bad_rr_adds_severity(self):
        # entry=3000, stop=2970 (1%), tp=3010 → reward=10, risk=30, RR=0.333 < 1.0 → +0.3
        prop = _proposal(entry_price=3000.0, stop_loss=2970.0, take_profit=3010.0)
        severity, reasoning = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 0.3)
        self.assertIn("R/R", reasoning)

    def test_03_tight_stop_and_bad_rr_combined(self):
        # entry=3000, stop=2999 (tight +0.5), tp=3000.5 (reward=0.5, risk=1.0, RR=0.5 → +0.3)
        prop = _proposal(entry_price=3000.0, stop_loss=2999.0, take_profit=3000.5)
        severity, _ = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 0.8)

    def test_04_low_composite_confidence(self):
        # |composite| = 0.2 < 0.3 → +0.2
        prop = _proposal(composite_score=0.2)
        severity, reasoning = self.officer._check_internal(prop)
        self.assertAlmostEqual(severity, 0.2)
        self.assertIn("複合信心度偏低", reasoning)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5 — 外部風險：警戒等級
# ═══════════════════════════════════════════════════════════════════════════════

class TestExternalCheck_AlertLevel(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def _ext(self, level):
        self.officer.current_alert_level = level
        return self.officer._check_external(_proposal())

    def test_01_green_no_severity(self):
        severity, reasoning = self._ext("GREEN")
        self.assertAlmostEqual(severity, 0.0)
        self.assertIn("正常", reasoning)

    def test_02_yellow_adds_0_2(self):
        severity, reasoning = self._ext("YELLOW")
        self.assertAlmostEqual(severity, 0.2)
        self.assertIn("YELLOW", reasoning)

    def test_03_orange_adds_0_5(self):
        severity, reasoning = self._ext("ORANGE")
        self.assertAlmostEqual(severity, 0.5)
        self.assertIn("ORANGE", reasoning)

    def test_04_red_returns_1_0(self):
        severity, reasoning = self._ext("RED")
        self.assertAlmostEqual(severity, 1.0)
        self.assertIn("禁止交易", reasoning)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6 — 外部風險：連敗次數
# ═══════════════════════════════════════════════════════════════════════════════

class TestExternalCheck_ConsecutiveLosses(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_no_losses(self):
        self.officer.consecutive_losses = 0
        severity, _ = self.officer._check_external(_proposal())
        self.assertAlmostEqual(severity, 0.0)

    def test_02_med_losses_add_0_2(self):
        self.officer.consecutive_losses = 3
        severity, reasoning = self.officer._check_external(_proposal())
        self.assertAlmostEqual(severity, 0.2)
        self.assertIn("連敗", reasoning)

    def test_03_high_losses_add_0_4(self):
        self.officer.consecutive_losses = 5
        severity, reasoning = self.officer._check_external(_proposal())
        self.assertAlmostEqual(severity, 0.4)
        self.assertIn("連敗", reasoning)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 7 — 外部風險：近期異常事件
# ═══════════════════════════════════════════════════════════════════════════════

class TestExternalCheck_Anomalies(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_no_anomalies(self):
        severity, _ = self.officer._check_external(_proposal())
        self.assertAlmostEqual(severity, 0.0)

    def test_02_one_anomaly_adds_0_2(self):
        self.officer.recent_anomalies.append((time.time(), 0.8))
        severity, reasoning = self.officer._check_external(_proposal())
        self.assertAlmostEqual(severity, 0.2)
        self.assertIn("異常事件", reasoning)

    def test_03_three_anomalies_add_0_4(self):
        now = time.time()
        for _ in range(3):
            self.officer.recent_anomalies.append((now, 0.8))
        severity, reasoning = self.officer._check_external(_proposal())
        self.assertAlmostEqual(severity, 0.4)
        self.assertIn("異常事件", reasoning)

    def test_04_old_anomalies_ignored(self):
        # anomaly outside 30-minute window
        old_ts = time.time() - 3700
        self.officer.recent_anomalies.append((old_ts, 0.8))
        severity, _ = self.officer._check_external(_proposal())
        self.assertAlmostEqual(severity, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 8 — 決策：嚴重修正（severity ≥ 0.7）
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecision_ModifiedSevere(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def _severe_prop(self, **kwargs):
        # tight stop + bad RR → int_sev = 0.8; external = 0 → combined = 0.8
        defaults = dict(
            entry_price=3000.0,
            stop_loss=2999.0,
            take_profit=3000.5,  # reward=0.5, risk=1.0, RR=0.5
            position_size_usd=60.0,
            composite_score=0.5,
        )
        defaults.update(kwargs)
        return _proposal(**defaults)

    def test_01_decision_is_modified(self):
        result = self.officer.assess_proposal(self._severe_prop())
        self.assertEqual(result.decision, "MODIFIED")

    def test_02_position_reduced_to_40pct(self):
        # GREEN alert (×1.0), 0 losses (×1.0) → pos × 0.4
        result = self.officer.assess_proposal(self._severe_prop(position_size_usd=60.0))
        self.assertAlmostEqual(result.modified_position_size, 24.0, places=6)

    def test_03_stop_tightened_long(self):
        # entry=3000, stop=2999 → distance=1 → mod_stop = 3000 - 0.7 = 2999.3
        result = self.officer.assess_proposal(self._severe_prop(direction="long"))
        self.assertAlmostEqual(result.modified_stop_loss, 2999.3, places=6)

    def test_04_stop_tightened_short(self):
        # short: entry=3000, stop=3001 (tight), tp=2999.5 (reward=0.5, risk=1.0, RR=0.5)
        prop = _proposal(direction="short", entry_price=3000.0, stop_loss=3001.0,
                         take_profit=2999.5, composite_score=-0.5)
        result = self.officer.assess_proposal(prop)
        # mod_stop = 3000 + (3001-3000) × 0.7 = 3000.7
        self.assertAlmostEqual(result.modified_stop_loss, 3000.7, places=6)

    def test_05_loss_factor_applied_5_losses(self):
        # 5 losses → loss_factor=0.5; GREEN → alert_factor=1.0
        # mod_pos = 60 × 0.4 × 1.0 × 0.5 = 12.0
        self.officer.consecutive_losses = 5
        result = self.officer.assess_proposal(self._severe_prop(position_size_usd=60.0))
        self.assertAlmostEqual(result.modified_position_size, 12.0, places=6)

    def test_06_rejection_reason_is_none(self):
        result = self.officer.assess_proposal(self._severe_prop())
        self.assertIsNone(result.rejection_reason)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 9 — 決策：中度修正（0.4 ≤ severity < 0.7）
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecision_ModifiedModerate(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def _moderate_prop(self, **kwargs):
        # tight stop only → int_sev=0.5; external=0 → combined=0.5
        defaults = dict(
            entry_price=3000.0,
            stop_loss=2999.0,
            take_profit=3009.0,  # reward=9, risk=1, RR=9 ✓
            position_size_usd=60.0,
            composite_score=0.5,
        )
        defaults.update(kwargs)
        return _proposal(**defaults)

    def test_01_decision_is_modified(self):
        result = self.officer.assess_proposal(self._moderate_prop())
        self.assertEqual(result.decision, "MODIFIED")

    def test_02_position_reduced_to_70pct(self):
        # GREEN (×1.0), 0 losses (×1.0) → pos × 0.7
        result = self.officer.assess_proposal(self._moderate_prop(position_size_usd=60.0))
        self.assertAlmostEqual(result.modified_position_size, 42.0, places=6)

    def test_03_stop_loss_unchanged(self):
        result = self.officer.assess_proposal(self._moderate_prop())
        self.assertIsNone(result.modified_stop_loss)

    def test_04_alert_factor_applied_yellow(self):
        # YELLOW → alert_factor=0.7; int_sev=0.5, ext_sev=0.2 → combined=0.5 → moderate
        # mod_pos = 60 × 0.7 × 0.7 = 29.4
        self.officer.current_alert_level = "YELLOW"
        result = self.officer.assess_proposal(self._moderate_prop(position_size_usd=60.0))
        self.assertAlmostEqual(result.modified_position_size, 29.4, places=6)

    def test_05_loss_adj_applied_3_losses(self):
        # 3 losses → ×0.8; GREEN → ×1.0 → pos × 0.7 × 0.8 = 33.6
        self.officer.consecutive_losses = 3
        result = self.officer.assess_proposal(self._moderate_prop(position_size_usd=60.0))
        self.assertAlmostEqual(result.modified_position_size, 33.6, places=6)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 10 — Bus 整合
# ═══════════════════════════════════════════════════════════════════════════════

class TestBusIntegration(unittest.TestCase):

    def setUp(self):
        self.officer = _fresh()

    def test_01_proposal_submitted_triggers_assessment(self):
        received = []
        get_bus().subscribe("assessment.complete", lambda m: received.append(m.payload),
                            role="test-listener")
        get_bus().publish("proposal.submitted", _proposal(), sender="小蘇")
        self.assertEqual(len(received), 1)
        self.assertIn(received[0].decision, ("APPROVED", "MODIFIED", "REJECTED"))

    def test_02_assessment_stats_incremented(self):
        get_bus().publish("proposal.submitted", _proposal(), sender="小蘇")
        self.assertEqual(self.officer.assessments_total, 1)

    def test_03_au01_update_dict_updates_alert_level(self):
        self.assertEqual(self.officer.current_alert_level, "GREEN")
        get_bus().publish("au01.status_update",
                          {"alert_level": "ORANGE", "consecutive_losses": 4},
                          sender="AU-01")
        self.assertEqual(self.officer.current_alert_level, "ORANGE")

    def test_04_au01_update_dict_updates_losses(self):
        get_bus().publish("au01.status_update",
                          {"alert_level": "YELLOW", "consecutive_losses": 4},
                          sender="AU-01")
        self.assertEqual(self.officer.consecutive_losses, 4)

    def test_05_anomaly_detected_updates_deque(self):
        anomaly = AnomalyEvent(
            event_id="A-001", event_type="FLASH_MOVE", symbol="ETHUSDT",
            magnitude=0.05, severity=0.85, timestamp=datetime.now(),
            triggered_alert=True,
        )
        get_bus().publish("anomaly.detected", anomaly, sender="CA-03")
        self.assertEqual(len(self.officer.recent_anomalies), 1)
        self.assertAlmostEqual(self.officer.recent_anomalies[0][1], 0.85)

    def test_06_rejected_proposal_sets_rejection_reason(self):
        # RED alert → ext_sev=1.0 → REJECTED
        self.officer.current_alert_level = "RED"
        result = self.officer.assess_proposal(_proposal())
        self.assertEqual(result.decision, "REJECTED")
        self.assertIsNotNone(result.rejection_reason)
        self.assertIn("禁止交易", result.rejection_reason)

    def test_07_approved_clears_modification_fields(self):
        # Clean proposal → APPROVED; no modifications
        result = self.officer.assess_proposal(_proposal())
        self.assertEqual(result.decision, "APPROVED")
        self.assertIsNone(result.modified_position_size)
        self.assertIsNone(result.modified_stop_loss)
        self.assertIsNone(result.rejection_reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
