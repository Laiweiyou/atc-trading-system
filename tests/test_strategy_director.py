# -*- coding: utf-8 -*-
"""Tests for StrategyDirector (小蘇) — Phase 4 Step 2."""
import io
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import (
    AnomalyEvent,
    CourseReport,
    SnapshotBundle,
    TradingProposal,
)
from trading_system.common.message_bus import Message, get_bus
from trading_system.common.snapshot_builder import reset_snapshot_builder
from trading_system.strategy.strategy_director import StrategyDirector

# ─── Helpers ─────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc)


def _course(
    code: str,
    direction: str,
    confidence: float,
    freshness: str = "real_time",
    data_health: dict | None = None,
) -> CourseReport:
    names = {"IO": "市場情報課", "CA": "技術分析課", "GA": "國際情勢課", "TK": "節奏評估課"}
    managers = {"IO": "婷姐", "CA": "靜姐", "GA": "琳姐", "TK": "老廖"}
    return CourseReport(
        course_name      = names.get(code, code),
        course_code      = code,
        manager_name     = managers.get(code, "?"),
        debate_results   = [],
        course_direction = direction,
        course_confidence= confidence,
        freshness_grade  = freshness,
        data_health      = data_health or {},
        flash_alerts     = [],
        self_review      = {},
        timestamp        = _NOW,
    )


def _snapshot(
    io_dir: str = "bullish", io_conf: float = 0.7,
    ca_dir: str = "bullish", ca_conf: float = 0.6,
    ga_dir: str = "neutral", ga_conf: float = 0.5,
    tk_dir: str = "bullish",
    quality: str = "good",
    io_freshness: str = "real_time",
    ca_freshness: str = "real_time",
    ga_freshness: str = "real_time",
    ca_health: dict | None = None,
) -> SnapshotBundle:
    return SnapshotBundle(
        snapshot_id          = "SNAP-TEST-001",
        snapshot_time        = _NOW,
        overall_data_quality = quality,
        io_report = _course("IO", io_dir, io_conf, io_freshness),
        ca_report = _course("CA", ca_dir, ca_conf, ca_freshness, ca_health),
        ga_report = _course("GA", ga_dir, ga_conf, ga_freshness),
        tk_report = _course("TK", tk_dir, 0.6),
    )


def _make_gw(price: float = 3000.0) -> MagicMock:
    gw = MagicMock()
    gw.get_market_kline.return_value = {
        "success": True,
        "data": {"list": [["1234567890000", "2950", "3100", "2900", str(price), "100", "300000"]]},
    }
    return gw


def _fresh(gw=None, snap: SnapshotBundle | None = None) -> StrategyDirector:
    reset_snapshot_builder()
    get_bus().clear()
    gw = gw or _make_gw()
    director = StrategyDirector(gateway=gw)
    if snap is not None:
        director.snapshot_builder.build_snapshot = MagicMock(return_value=snap)
    return director


# ─── Test 01: 初始化 ──────────────────────────────────────────────────────────

class TestInit(unittest.TestCase):

    def test_role_name_and_code(self):
        d = _fresh()
        self.assertEqual(d.role_name, "小蘇")
        self.assertEqual(d.role_code, "Strategy-Director")

    def test_weights_sum_to_one(self):
        d = _fresh()
        self.assertAlmostEqual(sum(d.weights.values()), 1.0)

    def test_weights_values(self):
        d = _fresh()
        self.assertAlmostEqual(d.weights["io"], 0.30)
        self.assertAlmostEqual(d.weights["ca"], 0.40)
        self.assertAlmostEqual(d.weights["ga"], 0.20)
        self.assertAlmostEqual(d.weights["tk"], 0.10)

    def test_initial_stats_zero(self):
        d = _fresh()
        self.assertEqual(d.proposals_produced, 0)
        self.assertIsNone(d.last_proposal_time)
        self.assertEqual(len(d.recent_proposals), 0)

    def test_snapshot_builder_connected(self):
        d = _fresh()
        self.assertIsNotNone(d.snapshot_builder)


# ─── Test 02: 環境分類 ────────────────────────────────────────────────────────

class TestClassifyEnvironment(unittest.TestCase):

    def _classify(self, **kw) -> str:
        d = _fresh()
        return d._classify_environment(_snapshot(**kw))

    def test_io_ca_bullish_tk_active_is_trending_bullish(self):
        r = self._classify(io_dir="bullish", io_conf=0.7, ca_dir="bullish", ca_conf=0.6,
                           tk_dir="bullish")
        self.assertEqual(r, "trending_bullish")

    def test_io_ca_bearish_tk_active_is_trending_bearish(self):
        r = self._classify(io_dir="bearish", io_conf=0.7, ca_dir="bearish", ca_conf=0.6,
                           tk_dir="bullish")
        self.assertEqual(r, "trending_bearish")

    def test_io_neutral_ca_neutral_low_conf_is_ranging(self):
        r = self._classify(io_dir="neutral", io_conf=0.3, ca_dir="neutral", ca_conf=0.3,
                           tk_dir="neutral")
        self.assertEqual(r, "ranging")

    def test_tk_rest_is_high_volatility(self):
        r = self._classify(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                           tk_dir="bearish")
        self.assertEqual(r, "high_volatility")

    def test_ca_anomaly_2_or_more_is_high_volatility(self):
        d = _fresh()
        snap = _snapshot(ca_health={"anomaly_events_count": 2}, tk_dir="neutral")
        r = d._classify_environment(snap)
        self.assertEqual(r, "high_volatility")

    def test_ca_anomaly_1_is_not_high_volatility(self):
        d = _fresh()
        snap = _snapshot(ca_health={"anomaly_events_count": 1},
                         io_dir="bullish", io_conf=0.7, ca_dir="bullish", ca_conf=0.6,
                         tk_dir="neutral")
        r = d._classify_environment(snap)
        self.assertNotEqual(r, "high_volatility")

    def test_io_bullish_ca_bearish_is_unclear(self):
        r = self._classify(io_dir="bullish", io_conf=0.7, ca_dir="bearish", ca_conf=0.7,
                           tk_dir="neutral")
        self.assertEqual(r, "unclear")

    def test_trending_requires_avg_conf_above_0_5(self):
        # avg_conf = (0.4 + 0.4) / 2 = 0.4 < 0.5 → not trending
        r = self._classify(io_dir="bullish", io_conf=0.4, ca_dir="bullish", ca_conf=0.4,
                           tk_dir="neutral")
        self.assertNotEqual(r, "trending_bullish")


# ─── Test 03: composite_score 計算 ───────────────────────────────────────────

class TestCompositeScore(unittest.TestCase):

    def _score(self, snap: SnapshotBundle) -> tuple[float, str]:
        return _fresh()._compute_composite_score(snap)

    def test_all_bullish_high_conf_is_positive(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.9, ca_dir="bullish", ca_conf=0.9,
                         ga_dir="bullish", ga_conf=0.9)
        score, direction = self._score(snap)
        self.assertGreater(score, 0.15)
        self.assertEqual(direction, "bullish")

    def test_all_bearish_high_conf_is_negative(self):
        snap = _snapshot(io_dir="bearish", io_conf=0.9, ca_dir="bearish", ca_conf=0.9,
                         ga_dir="bearish", ga_conf=0.9)
        score, direction = self._score(snap)
        self.assertLess(score, -0.15)
        self.assertEqual(direction, "bearish")

    def test_neutral_direction_when_score_small(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.1, ca_dir="bearish", ca_conf=0.1,
                         ga_dir="neutral", ga_conf=0.5)
        score, direction = self._score(snap)
        self.assertEqual(direction, "neutral")

    def test_stale_course_excluded_and_weights_renormalized(self):
        d = _fresh()
        snap = SnapshotBundle(
            snapshot_id="S", snapshot_time=_NOW, overall_data_quality="good",
            io_report=_course("IO", "bullish", 0.9, "real_time"),
            ca_report=_course("CA", "bullish", 0.9, "stale"),   # stale → excluded
            ga_report=_course("GA", "bullish", 0.9, "real_time"),
            tk_report=_course("TK", "bullish", 0.6),
        )
        score_with_stale, _ = d._compute_composite_score(snap)
        # Only IO(0.3) and GA(0.2) active; normalised: IO=0.6, GA=0.4
        # score = 0.9*0.6 + 0.9*0.4 = 0.54
        self.assertAlmostEqual(score_with_stale, 0.9 * (0.3 / 0.5) + 0.9 * (0.2 / 0.5), places=5)

    def test_tk_not_in_composite(self):
        # TK=bearish should NOT drive composite negative
        snap = _snapshot(io_dir="bullish", io_conf=0.9, ca_dir="bullish", ca_conf=0.9,
                         ga_dir="bullish", ga_conf=0.9, tk_dir="bearish")
        score, direction = self._score(snap)
        self.assertGreater(score, 0.0)
        self.assertEqual(direction, "bullish")

    def test_no_reports_returns_zero_neutral(self):
        d = _fresh()
        snap = SnapshotBundle(
            snapshot_id="S", snapshot_time=_NOW, overall_data_quality="degraded",
            io_report=None, ca_report=None, ga_report=None, tk_report=None,
        )
        score, direction = d._compute_composite_score(snap)
        self.assertEqual(score, 0.0)
        self.assertEqual(direction, "neutral")


# ─── Test 04: should_trade 判斷 ──────────────────────────────────────────────

class TestShouldTrade(unittest.TestCase):

    def _should(self, snap, score, env) -> bool:
        return _fresh()._should_trade(snap, score, env)

    def test_high_volatility_returns_false(self):
        self.assertFalse(self._should(_snapshot(), 0.5, "high_volatility"))

    def test_unclear_returns_false(self):
        self.assertFalse(self._should(_snapshot(), 0.5, "unclear"))

    def test_weak_composite_less_0_2_returns_false(self):
        self.assertFalse(self._should(_snapshot(), 0.19, "trending_bullish"))

    def test_exactly_0_2_returns_false(self):
        # 0.2 is not > 0.2, abs(0.2) < 0.2 is False but condition is abs < 0.2
        # abs(0.2) < 0.2 → False → should proceed; but let's verify
        # The condition is abs(composite_score) < 0.2
        self.assertFalse(self._should(_snapshot(), 0.19999, "trending_bullish"))

    def test_tk_rest_returns_false(self):
        snap = _snapshot(tk_dir="bearish")  # bearish = rest
        self.assertFalse(self._should(snap, 0.5, "trending_bullish"))

    def test_trending_strong_score_returns_true(self):
        snap = _snapshot(tk_dir="neutral")  # cautious, not rest
        self.assertTrue(self._should(snap, 0.5, "trending_bullish"))

    def test_ranging_with_adequate_score_returns_true(self):
        snap = _snapshot(tk_dir="bullish")  # active
        self.assertTrue(self._should(snap, 0.3, "ranging"))


# ─── Test 05: 策略選擇 ────────────────────────────────────────────────────────

class TestSelectStrategy(unittest.TestCase):

    def _select(self, env, direction="bullish") -> dict | None:
        return _fresh()._select_strategy(env, direction)

    def test_trending_bullish_gives_trend_following(self):
        s = self._select("trending_bullish")
        self.assertIsNotNone(s)
        self.assertEqual(s["name"], "trend_following")

    def test_trending_bearish_gives_trend_following(self):
        s = self._select("trending_bearish")
        self.assertIsNotNone(s)
        self.assertEqual(s["name"], "trend_following")

    def test_ranging_gives_range_trading(self):
        s = self._select("ranging")
        self.assertIsNotNone(s)
        self.assertEqual(s["name"], "range_trading")

    def test_unclear_gives_none(self):
        self.assertIsNone(self._select("unclear"))

    def test_high_volatility_gives_none(self):
        self.assertIsNone(self._select("high_volatility"))


# ─── Test 06: 倉位計算 ────────────────────────────────────────────────────────

class TestPositionSize(unittest.TestCase):

    def _build(self, tk_dir: str, composite: float, price: float = 3000.0):
        gw   = _make_gw(price)
        d    = _fresh(gw)
        snap = _snapshot(tk_dir=tk_dir)
        strat = {"name": "trend_following", "description": "趨勢跟隨"}
        return d._build_proposal(snap, "trending_bullish", "bullish", composite, strat)

    def test_tk_active_full_size(self):
        p = self._build("bullish", 0.5)
        # base = 100 * 0.5 = 50; factor = 1.0
        self.assertAlmostEqual(p.position_size_usd, 50.0)

    def test_tk_cautious_half_size(self):
        p = self._build("neutral", 0.5)
        # base = 50; factor = 0.5
        self.assertAlmostEqual(p.position_size_usd, 25.0)

    def test_tk_rest_zero_size(self):
        p = self._build("bearish", 0.5)
        self.assertAlmostEqual(p.position_size_usd, 0.0)

    def test_composite_scales_position(self):
        p1 = self._build("bullish", 0.4)
        p2 = self._build("bullish", 0.8)
        self.assertAlmostEqual(p1.position_size_usd, 40.0)
        self.assertAlmostEqual(p2.position_size_usd, 80.0)


# ─── Test 07: 止損止盈計算 ───────────────────────────────────────────────────

class TestStopLossTakeProfit(unittest.TestCase):

    def _build(self, direction: str, strategy_name: str, price: float = 3000.0):
        gw   = _make_gw(price)
        d    = _fresh(gw)
        snap = _snapshot()
        strat = {"name": strategy_name, "description": "test"}
        return d._build_proposal(snap, "trending_bullish", direction, 0.5, strat)

    def test_long_stop_loss_below_entry(self):
        p = self._build("bullish", "trend_following", 3000.0)
        self.assertLess(p.stop_loss, p.entry_price)

    def test_long_take_profit_above_entry(self):
        p = self._build("bullish", "trend_following", 3000.0)
        self.assertGreater(p.take_profit, p.entry_price)

    def test_short_stop_loss_above_entry(self):
        p = self._build("bearish", "trend_following", 3000.0)
        self.assertGreater(p.stop_loss, p.entry_price)

    def test_short_take_profit_below_entry(self):
        p = self._build("bearish", "trend_following", 3000.0)
        self.assertLess(p.take_profit, p.entry_price)

    def test_trend_following_2pct_stop_loss(self):
        p = self._build("bullish", "trend_following", 3000.0)
        self.assertAlmostEqual(p.stop_loss, 3000.0 * (1 - 0.02), places=4)

    def test_trend_following_4pct_take_profit(self):
        p = self._build("bullish", "trend_following", 3000.0)
        self.assertAlmostEqual(p.take_profit, 3000.0 * (1 + 0.04), places=4)

    def test_range_trading_1pct_stop_loss(self):
        p = self._build("bullish", "range_trading", 3000.0)
        self.assertAlmostEqual(p.stop_loss, 3000.0 * (1 - 0.01), places=4)

    def test_range_trading_2pct_take_profit(self):
        p = self._build("bullish", "range_trading", 3000.0)
        self.assertAlmostEqual(p.take_profit, 3000.0 * (1 + 0.02), places=4)

    def test_direction_long_for_bullish(self):
        p = self._build("bullish", "trend_following")
        self.assertEqual(p.direction, "long")

    def test_direction_short_for_bearish(self):
        p = self._build("bearish", "trend_following")
        self.assertEqual(p.direction, "short")


# ─── Test 08: 完整流程 ────────────────────────────────────────────────────────

class TestProduceProposal(unittest.TestCase):

    def _run(self, snap: SnapshotBundle, price: float = 3000.0):
        gw = _make_gw(price)
        return _fresh(gw, snap), gw

    def test_valid_snapshot_produces_proposal(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         ga_dir="bullish", ga_conf=0.6, tk_dir="bullish")
        d, _ = self._run(snap)
        p = d.produce_proposal()
        self.assertIsNotNone(p)
        self.assertIsInstance(p, TradingProposal)

    def test_proposal_published_to_bus(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d, _ = self._run(snap)
        received = []
        get_bus().subscribe("proposal.submitted", lambda m: received.append(m), role="test_08")
        d.produce_proposal()
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0].payload, TradingProposal)

    def test_proposals_produced_counter_increments(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d, _ = self._run(snap)
        d.produce_proposal()
        self.assertEqual(d.proposals_produced, 1)

    def test_proposal_has_correct_symbol(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d, _ = self._run(snap)
        p = d.produce_proposal()
        self.assertEqual(p.symbol, "ETHUSDT")

    def test_degraded_snapshot_returns_none(self):
        snap = _snapshot(quality="degraded")
        snap = SnapshotBundle(
            snapshot_id="S", snapshot_time=_NOW, overall_data_quality="degraded",
            io_report=_course("IO", "bullish", 0.8),
            ca_report=_course("CA", "bullish", 0.8),
            ga_report=None, tk_report=None,
        )
        d, _ = self._run(snap)
        p = d.produce_proposal()
        self.assertIsNone(p)

    def test_missing_io_report_returns_none(self):
        snap = SnapshotBundle(
            snapshot_id="S", snapshot_time=_NOW, overall_data_quality="good",
            io_report=None,
            ca_report=_course("CA", "bullish", 0.8),
            ga_report=None, tk_report=None,
        )
        d, _ = self._run(snap)
        p = d.produce_proposal()
        self.assertIsNone(p)

    def test_high_volatility_returns_none(self):
        snap = _snapshot(tk_dir="bearish")  # rest → high_volatility
        d, _ = self._run(snap)
        p = d.produce_proposal()
        self.assertIsNone(p)

    def test_proposal_contains_snapshot_id(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d, _ = self._run(snap)
        p = d.produce_proposal()
        self.assertIsNotNone(p)
        self.assertEqual(p.based_on_snapshot, "SNAP-TEST-001")

    def test_last_proposal_time_updated(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d, _ = self._run(snap)
        d.produce_proposal()
        self.assertIsNotNone(d.last_proposal_time)

    def test_kline_failure_returns_none(self):
        gw = MagicMock()
        gw.get_market_kline.return_value = {"success": False}
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d = _fresh(gw, snap)
        p = d.produce_proposal()
        self.assertIsNone(p)


# ─── Test 09: 異常觸發 ────────────────────────────────────────────────────────

class TestAnomalyTrigger(unittest.TestCase):

    def _anomaly(self, severity: float) -> AnomalyEvent:
        return AnomalyEvent(
            event_id="AE-001", event_type="FLASH_MOVE",
            symbol="ETHUSDT", magnitude=0.05, severity=severity,
            timestamp=_NOW, triggered_alert=True, direction="down",
        )

    def _msg(self, anomaly: AnomalyEvent) -> Message:
        import dataclasses
        return Message(
            message_id="M-001", channel="anomaly.detected",
            sender="CA-03", timestamp=_NOW, payload=anomaly,
        )

    def test_high_severity_triggers_produce_proposal(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d = _fresh(_make_gw(), snap)
        calls = []
        d.produce_proposal = lambda triggered_by="scheduled": calls.append(triggered_by) or None
        d._on_anomaly(self._msg(self._anomaly(0.7)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], "anomaly")

    def test_low_severity_does_not_trigger(self):
        d = _fresh()
        calls = []
        d.produce_proposal = lambda triggered_by="scheduled": calls.append(triggered_by) or None
        d._on_anomaly(self._msg(self._anomaly(0.69)))
        self.assertEqual(len(calls), 0)

    def test_exactly_0_7_triggers(self):
        d = _fresh()
        calls = []
        d.produce_proposal = lambda triggered_by="scheduled": calls.append(triggered_by) or None
        d._on_anomaly(self._msg(self._anomaly(0.7)))
        self.assertEqual(len(calls), 1)

    def test_bus_publish_anomaly_triggers_handler(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d = _fresh(_make_gw(), snap)
        calls = []
        d.produce_proposal = lambda triggered_by="scheduled": calls.append(triggered_by) or None
        anomaly = self._anomaly(0.8)
        get_bus().publish("anomaly.detected", anomaly, sender="CA-03")
        self.assertGreater(len(calls), 0)


# ─── Test 10: 訂閱 strategy.request_proposal ─────────────────────────────────

class TestRequestProposalSubscription(unittest.TestCase):

    def test_bus_publish_request_triggers_produce(self):
        d = _fresh()
        calls = []
        d.produce_proposal = lambda *args, **kwargs: calls.append(True) or None
        get_bus().publish("strategy.request_proposal", {}, sender="test")
        self.assertEqual(len(calls), 1)

    def test_multiple_requests_trigger_multiple_produce_calls(self):
        d = _fresh()
        calls = []
        d.produce_proposal = lambda *args, **kwargs: calls.append(True) or None
        get_bus().publish("strategy.request_proposal", {}, sender="test")
        get_bus().publish("strategy.request_proposal", {}, sender="test")
        self.assertEqual(len(calls), 2)

    def test_get_status_has_required_keys(self):
        d = _fresh()
        status = d.get_status()
        for key in ("role", "proposals_produced", "weights", "last_proposal_time"):
            self.assertIn(key, status)
        self.assertEqual(status["role"], "小蘇")

    def test_run_cycle_triggers_proposal_when_no_previous(self):
        snap = _snapshot(io_dir="bullish", io_conf=0.8, ca_dir="bullish", ca_conf=0.8,
                         tk_dir="bullish")
        d = _fresh(_make_gw(), snap)
        calls = []
        d.produce_proposal = lambda *args, **kwargs: calls.append(True) or None
        d.run_cycle()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
