# -*- coding: utf-8 -*-
"""Tests for CA-03 小張+穎穎（量能分析 + 異常事件偵測）— Phase 3 Step 10."""
import io
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import AnomalyEvent, DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.technical.ca_03_volume import (
    VolumeAnalyst,
    VolumeSection,
)

DAY_MS = 24 * 3600 * 1000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _1h_bar(ts_ms, open_p=1800.0, close_p=1800.0, high=None, low=None, vol=1000.0):
    return {
        "timestamp": ts_ms,
        "open":  open_p,
        "high":  (max(open_p, close_p) + 5) if high is None else high,
        "low":   (min(open_p, close_p) - 5) if low  is None else low,
        "close": close_p,
        "volume": vol,
    }


def _1d_bar(ts_ms, open_p=1800.0, high=2000.0, low=1700.0, close_p=1800.0, vol=10000.0):
    return {"timestamp": ts_ms, "open": open_p, "high": high,
            "low": low, "close": close_p, "volume": vol}


def _flat_1h(n=48, vol=1000.0, price=1800.0):
    return [_1h_bar(i * 3600_000, price, price, vol=vol) for i in range(n)]


def _raw_bybit(klines_list):
    """Chronological klines dicts → Bybit newest-first raw list."""
    raw = []
    for k in reversed(klines_list):
        raw.append([k["timestamp"], k["open"], k["high"],
                    k["low"], k["close"], k["volume"], 0])
    return raw


def _make_gateway(klines_1h_chron=None, klines_1d_chron=None):
    gw = MagicMock()
    raw_1h = _raw_bybit(klines_1h_chron) if klines_1h_chron else []
    raw_1d = _raw_bybit(klines_1d_chron) if klines_1d_chron else []

    def side_effect(symbol, interval, limit=None):
        if interval == "60":
            return {"success": True, "data": {"list": raw_1h}}
        if interval == "D":
            return {"success": True, "data": {"list": raw_1d}}
        return {"success": False}

    gw.get_market_kline.side_effect = side_effect
    return gw


def _fresh_analyst(mode, klines_1h=None, klines_1d=None):
    get_bus().clear()
    analyst = VolumeAnalyst(mode, gateway=MagicMock())
    klines_dict = {"1h": klines_1h or [], "1d": klines_1d or []}
    analyst.fetch_klines = lambda symbol="ETHUSDT": klines_dict
    return analyst


def _fresh_section(klines_1h=None, klines_1d=None):
    get_bus().clear()
    gw = _make_gateway(klines_1h, klines_1d)
    return VolumeSection(gateway=gw)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCA03Volume(unittest.TestCase):

    # ── 01: FLASH_MOVE 偵測（小張絕對模式）────────────────────────────────────

    def test_01_flash_move_detected_absolute(self):
        bars = _flat_1h(47) + [_1h_bar(47 * 3600_000, 1800.0, 1980.0)]  # +10%
        analyst = _fresh_analyst("absolute", klines_1h=bars)
        _, anomalies = analyst.analyze()

        flash = [a for a in anomalies if a.event_type == "FLASH_MOVE"]
        self.assertEqual(len(flash), 1)
        self.assertEqual(flash[0].direction, "up")
        self.assertAlmostEqual(flash[0].severity, 0.6, places=5)

    # ── 02: VOLUME_SPIKE 絕對閾值（ratio=5x）────────────────────────────────

    def test_02_volume_spike_absolute(self):
        bars = [_1h_bar(i * 3600_000, vol=1000.0) for i in range(24)]
        bars.append(_1h_bar(24 * 3600_000, vol=5000.0))   # ratio=5x ≥ 4
        analyst = _fresh_analyst("absolute", klines_1h=bars)
        _, anomalies = analyst.analyze()

        vs = [a for a in anomalies if a.event_type == "VOLUME_SPIKE"]
        self.assertEqual(len(vs), 1)
        self.assertAlmostEqual(vs[0].severity, 0.6, places=5)

    # ── 03: WIDE_RANGE 當日日線（range≈19.6%）────────────────────────────────

    def test_03_wide_range_detected(self):
        day_bar = _1d_bar(0, open_p=1800.0, high=2052.0, low=1700.0, close_p=1900.0)
        analyst = _fresh_analyst("absolute", klines_1h=_flat_1h(5), klines_1d=[day_bar])
        _, anomalies = analyst.analyze()

        wr = [a for a in anomalies if a.event_type == "WIDE_RANGE"]
        self.assertEqual(len(wr), 1)
        self.assertGreaterEqual(wr[0].severity, 0.7)

    # ── 04: _calc_severity 分段邊界 ──────────────────────────────────────────

    def test_04_calc_severity_boundaries(self):
        analyst = VolumeAnalyst("absolute", gateway=MagicMock())
        self.assertAlmostEqual(analyst._calc_severity(8,  8, 12, 20), 0.5, places=5)
        self.assertAlmostEqual(analyst._calc_severity(12, 8, 12, 20), 0.7, places=5)
        self.assertAlmostEqual(analyst._calc_severity(25, 10, 15, 25), 0.9, places=5)

    # ── 05: 情境 VOLUME_SPIKE（同時段均量基準）────────────────────────────────

    def test_05_contextual_volume_spike(self):
        # All bars share hour=0 (ts = i * DAY_MS → always midnight)
        bars = [_1h_bar(i * DAY_MS, vol=1000.0) for i in range(47)]
        bars.append(_1h_bar(47 * DAY_MS, vol=4000.0))   # ratio=4 ≥ 3
        analyst = _fresh_analyst("contextual", klines_1h=bars)
        _, anomalies = analyst.analyze()

        vs = [a for a in anomalies if a.event_type == "VOLUME_SPIKE"]
        self.assertEqual(len(vs), 1)
        self.assertAlmostEqual(vs[0].severity, 0.6, places=5)

    # ── 06: 情境無 VOLUME_SPIKE（ratio < 3）─────────────────────────────────

    def test_06_contextual_no_spike_below_threshold(self):
        bars = [_1h_bar(i * DAY_MS, vol=1000.0) for i in range(47)]
        bars.append(_1h_bar(47 * DAY_MS, vol=2500.0))   # ratio=2.5 < 3
        analyst = _fresh_analyst("contextual", klines_1h=bars)
        _, anomalies = analyst.analyze()

        vs = [a for a in anomalies if a.event_type == "VOLUME_SPIKE"]
        self.assertEqual(len(vs), 0)

    # ── 07: 量價齊揚 → bullish ───────────────────────────────────────────────

    def test_07_volume_price_surge_bullish(self):
        # 20 older bars flat at 1800, vol=1000
        older = [_1h_bar(i * 3600_000, 1800.0, 1800.0, vol=1000.0) for i in range(20)]
        # 5 recent bars: rising price (+20 each), vol=1500
        open_prices = [1800, 1820, 1840, 1860, 1880]
        recent = [
            _1h_bar((20 + i) * 3600_000, open_prices[i], open_prices[i] + 20, vol=1500.0)
            for i in range(5)
        ]
        bars = older + recent
        analyst = _fresh_analyst("absolute", klines_1h=bars)
        report, _ = analyst.analyze()

        self.assertEqual(report.direction, "bullish")
        self.assertIn("量價齊揚", report.reasoning)

    # ── 08: 低於閾值時不產生異常事件 ────────────────────────────────────────

    def test_08_no_anomaly_below_threshold(self):
        # 5% change (<8%) and 3x volume (<4x) → no anomalies
        bars = [_1h_bar(i * 3600_000, vol=1000.0) for i in range(24)]
        bars.append(_1h_bar(24 * 3600_000, 1800.0, 1890.0, vol=3000.0))
        analyst = _fresh_analyst("absolute", klines_1h=bars)
        _, anomalies = analyst.analyze()

        self.assertEqual(len(anomalies), 0)

    # ── 09: conduct_debate 發布 anomaly.detected 訊息 ────────────────────────

    def test_09_bus_publish_on_flash_move(self):
        bars = _flat_1h(47) + [_1h_bar(47 * 3600_000, 1800.0, 1980.0)]  # +10%
        section = _fresh_section(klines_1h=bars)

        received = []
        get_bus().subscribe("anomaly.detected", lambda msg: received.append(msg), role="test")

        section.conduct_debate()

        self.assertGreater(len(received), 0)
        self.assertTrue(any(isinstance(m.payload, AnomalyEvent) for m in received))

    # ── 10: 雙重確認加成 severity +0.1 ──────────────────────────────────────

    def test_10_dual_confirmation_boosts_severity(self):
        # Both analysts detect FLASH_MOVE at +10% → confirmed → severity 0.6+0.1=0.7
        bars = _flat_1h(47) + [_1h_bar(47 * 3600_000, 1800.0, 1980.0)]
        section = _fresh_section(klines_1h=bars)

        received = []
        get_bus().subscribe("anomaly.detected", lambda msg: received.append(msg.payload), role="test")

        section.conduct_debate()

        flash = [p for p in received if isinstance(p, AnomalyEvent) and p.event_type == "FLASH_MOVE"]
        self.assertGreater(len(flash), 0)
        self.assertAlmostEqual(flash[0].severity, 0.7, places=5)

    # ── 11: published_anomaly_ids 避免重複發布 ───────────────────────────────

    def test_11_no_duplicate_publish(self):
        get_bus().clear()
        section = VolumeSection(gateway=MagicMock())

        published = []
        get_bus().subscribe("anomaly.detected", lambda msg: published.append(msg), role="test")

        anomaly = AnomalyEvent(
            event_id="TEST-DEDUP-001",
            event_type="FLASH_MOVE",
            symbol="ETHUSDT",
            magnitude=10.0,
            severity=0.6,
            timestamp=datetime.now(),
            triggered_alert=False,
            direction="up",
        )

        section._publish_anomalies([anomaly], [])
        section._publish_anomalies([anomaly], [])   # same event_id → skipped

        self.assertEqual(len(published), 1)

    # ── 12: 絕對觸發 vs 情境不觸發（不同時段量能差異）────────────────────────

    def test_12_absolute_triggers_contextual_skips(self):
        # ts = i*3600_000 → bar_i has hour = i%24
        # bar 23 and bar 47 both have hour=23 (same hour as latest)
        # bars 0-22 & 24-46: vol=500; bar 23: vol=2000; bar 47 (latest): vol=4000
        # absolute avg_24 = (2000+23*500)/24 ≈ 562.5 → ratio≈7.1 ≥ 4 → 小張 fires
        # contextual same_hour_avg = 2000 → ratio=2.0 < 3 → 穎穎 skips
        bars = []
        for i in range(47):
            vol = 2000.0 if i == 23 else 500.0
            bars.append(_1h_bar(i * 3600_000, vol=vol))
        bars.append(_1h_bar(47 * 3600_000, vol=4000.0))

        xiaozhang = _fresh_analyst("absolute",   klines_1h=bars)
        yingying  = _fresh_analyst("contextual", klines_1h=bars)

        _, anomalies_a = xiaozhang.analyze()
        _, anomalies_b = yingying.analyze()

        vs_a = [a for a in anomalies_a if a.event_type == "VOLUME_SPIKE"]
        vs_b = [a for a in anomalies_b if a.event_type == "VOLUME_SPIKE"]

        self.assertGreater(len(vs_a), 0)   # 小張 detects
        self.assertEqual(len(vs_b), 0)     # 穎穎 skips

    # ── 13: K 線不足回傳 stale SubReport ─────────────────────────────────────

    def test_13_no_klines_returns_stale(self):
        gw = MagicMock()
        gw.get_market_kline.return_value = {"success": False}
        get_bus().clear()
        analyst = VolumeAnalyst("absolute", gateway=gw)
        report, anomalies = analyst.analyze()

        self.assertTrue(report.staleness_flag)
        self.assertEqual(report.direction, "neutral")
        self.assertEqual(anomalies, [])

    # ── 14: conduct_debate 回傳 DebateResult 且 history 累積 ─────────────────

    def test_14_conduct_debate_accumulates_history(self):
        bars = _flat_1h(48)
        section = _fresh_section(klines_1h=bars)

        result = section.conduct_debate()
        self.assertIsInstance(result, DebateResult)
        self.assertTrue(result.debate_id.startswith("CA-03-"))

        section.conduct_debate()
        self.assertEqual(len(section.debate_history), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
