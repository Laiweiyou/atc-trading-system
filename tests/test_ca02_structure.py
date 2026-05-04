# -*- coding: utf-8 -*-
"""Tests for CA-02 小林+慧慧（市場結構分析）— Phase 3 Step 9."""
import io
import math
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.technical.ca_02_structure import (
    StructureAnalyst,
    StructureSection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kline(ts, o, h, l, c, v=1000.0):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _flat_klines(n: int, price: float = 100.0) -> list:
    """n klines all at the same price."""
    return [_kline(i * 1000, price, price + 1, price - 1, price) for i in range(n)]


def _to_bybit_raw(klines: list) -> list:
    return [
        [k["timestamp"], k["open"], k["high"], k["low"], k["close"], k["volume"], 0]
        for k in reversed(klines)
    ]


def _make_gateway(klines: list):
    gw = MagicMock()
    gw.get_market_kline.return_value = {
        "success": True,
        "data": {"list": _to_bybit_raw(klines)},
    }
    return gw


def _fresh_analyst(mode: str, klines: list) -> StructureAnalyst:
    get_bus().clear()
    return StructureAnalyst(mode, gateway=_make_gateway(klines))


def _fresh_section(klines_xiaolin=None, klines_huihui=None) -> StructureSection:
    """StructureSection where each analyst gets its own kline set."""
    get_bus().clear()
    section = StructureSection(gateway=MagicMock())
    if klines_xiaolin is not None:
        section.xiaolin.fetch_klines = lambda symbol="ETHUSDT": klines_xiaolin
    if klines_huihui is not None:
        section.huihui.fetch_klines = lambda symbol="ETHUSDT": klines_huihui
    return section


# ── Build a kline series with intentional swing highs/lows ───────────────────

def _build_swing_klines() -> list:
    """
    Hand-crafted 30-bar series so that with lookback=5 we get clear swing H/L:
      - bar 7 is a local high (high=120, neighbours ≤ 112)
      - bar 22 is a local low  (low=80,  neighbours ≥ 88)
    """
    klines = []
    for i in range(30):
        if i == 7:
            klines.append(_kline(i * 1000, 110, 120, 108, 115))  # swing high
        elif i == 22:
            klines.append(_kline(i * 1000, 90, 92, 80, 85))      # swing low
        else:
            klines.append(_kline(i * 1000, 100, 112, 88, 100))
    return klines


def _uptrend_klines(n: int = 80) -> list:
    """Sinusoidal oscillation on a rising baseline → HH + HL swing pattern.

    Period = 15 bars, so each peak/trough is spaced 15 bars apart.
    Rising baseline (0.2/bar) ensures successive peaks and troughs are higher.
    Each bar has a unique high (no ties), so only true peaks become swing highs.
    """
    klines = []
    for i in range(n):
        mid = 100 + i * 0.2 + 8 * math.sin(i / 15.0 * 2 * math.pi)
        klines.append(_kline(i * 1000, mid, mid + 1.0, mid - 1.0, mid))
    return klines


def _downtrend_klines(n: int = 80) -> list:
    """Sinusoidal oscillation on a falling baseline → LH + LL swing pattern."""
    klines = []
    for i in range(n):
        mid = 200 - i * 0.2 + 8 * math.sin(i / 15.0 * 2 * math.pi)
        klines.append(_kline(i * 1000, mid, mid + 1.0, mid - 1.0, mid))
    return klines


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCA02Structure(unittest.TestCase):

    # ── 01: 初始化 roles ──────────────────────────────────────────────────────

    def test_01_init_roles(self):
        section = _fresh_section()
        self.assertEqual(section.xiaolin.role_name, "小林")
        self.assertEqual(section.xiaolin.role_code, "CA-02a")
        self.assertEqual(section.huihui.role_name,  "慧慧")
        self.assertEqual(section.huihui.role_code,  "CA-02b")
        self.assertEqual(section.xiaolin.kline_interval, "60")
        self.assertEqual(section.huihui.kline_interval,  "240")

    # ── 02: find_swing_highs 識別區域高點 ────────────────────────────────────

    def test_02_find_swing_highs(self):
        analyst = _fresh_analyst("recent_structure", _flat_klines(50))
        klines  = _build_swing_klines()
        highs   = analyst.find_swing_highs(klines, lookback=5)
        prices  = [h["price"] for h in highs]
        self.assertIn(120.0, prices)       # bar 7 should be detected

    # ── 03: find_swing_lows 識別區域低點 ─────────────────────────────────────

    def test_03_find_swing_lows(self):
        analyst = _fresh_analyst("recent_structure", _flat_klines(50))
        klines  = _build_swing_klines()
        lows    = analyst.find_swing_lows(klines, lookback=5)
        prices  = [l["price"] for l in lows]
        self.assertIn(80.0, prices)        # bar 22 should be detected

    # ── 04: find_key_levels 回傳正確壓力/支撐 ────────────────────────────────

    def test_04_find_key_levels(self):
        analyst = _fresh_analyst("recent_structure", _flat_klines(50))
        highs   = [{"price": 120.0, "index": 7,  "timestamp": 7000},
                   {"price": 130.0, "index": 15, "timestamp": 15000}]
        lows    = [{"price":  80.0, "index": 22, "timestamp": 22000},
                   {"price":  70.0, "index": 25, "timestamp": 25000}]
        levels  = analyst.find_key_levels(highs, lows, current_price=100.0)

        self.assertEqual(levels["nearest_resistance"], 120.0)
        self.assertEqual(levels["second_resistance"],  130.0)
        self.assertEqual(levels["nearest_support"],     80.0)
        self.assertEqual(levels["second_support"],      70.0)

    # ── 05: 上升結構識別 → bullish ───────────────────────────────────────────

    def test_05_uptrend_structure_bullish(self):
        klines  = _uptrend_klines(80)
        analyst = _fresh_analyst("recent_structure", klines)
        analyst.fetch_klines = lambda symbol="ETHUSDT": klines
        report  = analyst.analyze()

        self.assertIsInstance(report, SubReport)
        self.assertEqual(report.direction, "bullish")
        self.assertIn("上升結構", report.reasoning)

    # ── 06: 下降結構識別 → bearish ───────────────────────────────────────────

    def test_06_downtrend_structure_bearish(self):
        klines  = _downtrend_klines(80)
        analyst = _fresh_analyst("recent_structure", klines)
        analyst.fetch_klines = lambda symbol="ETHUSDT": klines
        report  = analyst.analyze()

        self.assertIsInstance(report, SubReport)
        self.assertEqual(report.direction, "bearish")
        self.assertIn("下降結構", report.reasoning)

    # ── 07: 資料不足 → stale SubReport ───────────────────────────────────────

    def test_07_insufficient_klines_stale(self):
        klines  = _flat_klines(10)   # < 30, triggers stale path
        analyst = _fresh_analyst("recent_structure", klines)
        analyst.fetch_klines = lambda symbol="ETHUSDT": klines
        report  = analyst.analyze()

        self.assertTrue(report.staleness_flag)
        self.assertEqual(report.direction, "neutral")

    # ── 08: Section agreed bearish（兩人都看到壓力）───────────────────────────

    def test_08_section_agreed_bearish(self):
        # build klines where price is just below a resistance (bearish signal)
        # Price ≈ 100, resistance ≈ 101  → distance < 1% → bearish 0.4 each
        klines = []
        for i in range(60):
            if i == 20:
                klines.append(_kline(i * 1000, 100, 108, 98, 105))  # swing high 108
            elif i == 40:
                klines.append(_kline(i * 1000, 100, 108, 97, 104))  # swing high 108
            else:
                klines.append(_kline(i * 1000, 100, 103, 97, 100))

        # current price = 100, nearest_resistance ≈ 108 (distance ≈ 8%) → not < 3%
        # Let's instead build with tiny resistance gap
        # Use a price=106.5 with swing high at 107 (gap ~0.47% < 1% → bearish 0.4)
        klines2 = []
        for i in range(60):
            if i == 20:
                klines2.append(_kline(i * 1000, 105, 107, 103, 106))  # swing high = 107
            elif i == 40:
                klines2.append(_kline(i * 1000, 105, 107, 102, 106))  # swing high = 107
            else:
                klines2.append(_kline(i * 1000, 106, 107, 105, 106.5))

        section = _fresh_section(klines_xiaolin=klines2, klines_huihui=klines2)
        result  = section.conduct_debate()

        self.assertIsInstance(result, DebateResult)
        self.assertIn(result.consensus_type, ("agreed", "discussed_agreed"))
        self.assertEqual(result.final_direction, "bearish")

    # ── 09: Section dual_track（近期突破 vs 歷史大壓力）────────────────────────

    def test_09_section_dual_track(self):
        # 小林 sees uptrend klines → bullish
        # 慧慧 sees downtrend klines → bearish
        bullish_klines = _uptrend_klines(80)
        bearish_klines = _downtrend_klines(80)

        section = _fresh_section(klines_xiaolin=bullish_klines,
                                  klines_huihui=bearish_klines)
        result  = section.conduct_debate()

        self.assertEqual(result.consensus_type, "dual_track")
        # bearish severity (2) beats bullish (0)
        self.assertEqual(result.final_direction, "bearish")
        self.assertIsNotNone(result.key_disagreement)

    # ── 10: debate_id format ─────────────────────────────────────────────────

    def test_10_debate_id_format(self):
        section = _fresh_section(klines_xiaolin=_flat_klines(60),
                                  klines_huihui=_flat_klines(60))
        result  = section.conduct_debate()
        self.assertTrue(result.debate_id.startswith("CA-02-"))

    # ── 11: debate_history accumulates ───────────────────────────────────────

    def test_11_debate_history_accumulates(self):
        section = _fresh_section(klines_xiaolin=_flat_klines(60),
                                  klines_huihui=_flat_klines(60))
        section.conduct_debate()
        section.conduct_debate()
        self.assertEqual(len(section.debate_history), 2)

    # ── 12: discussed_agreed（同向但信心差距 > 0.2）────────────────────────────

    def test_12_discussed_agreed(self):
        section = _fresh_section()
        # inject two SubReports with same direction but large confidence gap
        from trading_system.common.data_models import SubReport
        now = datetime.now()
        ra = SubReport("小林", "CA-02a", "bullish", 0.7, "test", {}, now)
        rb = SubReport("慧慧", "CA-02b", "bullish", 0.3, "test", {}, now)

        ctype, direction, conf, _ = section._compare_reports(ra, rb)

        self.assertEqual(ctype, "discussed_agreed")
        self.assertEqual(direction, "bullish")
        expected = (0.7 ** 2 + 0.3 ** 2) / (0.7 + 0.3)   # 0.49+0.09 = 0.58
        self.assertAlmostEqual(conf, expected, places=5)

    # ── 13: agreed（同向，差距 ≤ 0.2）────────────────────────────────────────

    def test_13_agreed(self):
        section = _fresh_section()
        now = datetime.now()
        ra = SubReport("小林", "CA-02a", "bearish", 0.5, "test", {}, now)
        rb = SubReport("慧慧", "CA-02b", "bearish", 0.4, "test", {}, now)

        ctype, direction, conf, _ = section._compare_reports(ra, rb)

        self.assertEqual(ctype, "agreed")
        self.assertEqual(direction, "bearish")
        self.assertAlmostEqual(conf, 0.45)

    # ── 14: key_disagreement populated on direction mismatch ─────────────────

    def test_14_key_disagreement_on_direction_mismatch(self):
        section = _fresh_section()
        now = datetime.now()
        ra = SubReport("小林", "CA-02a", "bullish", 0.5, "test", {}, now)
        rb = SubReport("慧慧", "CA-02b", "bearish", 0.5, "test", {}, now)

        result = section._identify_disagreement(ra, rb)
        self.assertIsNotNone(result)
        self.assertIn("方向分歧", result)

    # ── 15: fetch_klines reverses Bybit newest-first ─────────────────────────

    def test_15_fetch_klines_reverses_bybit_order(self):
        gw = MagicMock()
        gw.get_market_kline.return_value = {
            "success": True,
            "data": {"list": [
                [3000, 103, 104, 102, 103, 1000, 0],
                [2000, 102, 103, 101, 102, 1000, 0],
                [1000, 101, 102, 100, 101, 1000, 0],
            ]},
        }
        get_bus().clear()
        analyst = StructureAnalyst("recent_structure", gateway=gw)
        klines  = analyst.fetch_klines()

        self.assertEqual(len(klines), 3)
        self.assertEqual(klines[0]["timestamp"], 1000)   # oldest first
        self.assertEqual(klines[-1]["timestamp"], 3000)  # newest last


if __name__ == "__main__":
    unittest.main(verbosity=2)
