# -*- coding: utf-8 -*-
"""Tests for TK 課 小施+華哥+老廖（節奏評估）— Phase 3 Step 15."""
import io
import sys
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import AnomalyEvent, CourseReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.tempo.tk_01_tempo_indicators import TempoIndicators
from trading_system.squads.crypto.tempo.tk_02_tempo_memory import TempoMemory
from trading_system.squads.crypto.tempo.tempo_section import TempoSection


# ── Helpers ───────────────────────────────────────────────────────────────────

def _1h_bar(ts_ms, price=1800.0, vol=1000.0, spread=0.002):
    """Single 1h OHLCV bar."""
    return {
        "timestamp": ts_ms,
        "open":      price,
        "high":      price * (1 + spread),
        "low":       price * (1 - spread),
        "close":     price,
        "volume":    vol,
    }


def _make_klines(n=200, price=1800.0, vol=1000.0):
    """n uniform 1h bars (newest last)."""
    now_ms = int(datetime.now().timestamp() * 1000)
    return [_1h_bar(now_ms - (n - 1 - i) * 3_600_000, price, vol) for i in range(n)]


def _make_indicator(volatility_pct=2.5, vol_ratio=1.0, sudden=False):
    """Fake pre-computed indicator dict."""
    return {
        "symbol":                "ETHUSDT",
        "current_price":         1800.0,
        "volatility_pct":        volatility_pct,
        "volume_activity_ratio": vol_ratio,
        "trend_strength_pct":    0.5,
        "sudden_change_detected": sudden,
        "std_deviation":         2.5 if sudden else 0.3,
        "timestamp":             datetime.now(),
    }


def _make_anomaly(severity, event_id="evt-001"):
    return AnomalyEvent(
        event_id       = event_id,
        event_type     = "FLASH_MOVE",
        symbol         = "ETHUSDT",
        magnitude      = 0.12,
        severity       = severity,
        timestamp      = datetime.now(),
        triggered_alert = True,
        direction      = "down",
    )


def _fresh_tk01():
    get_bus().clear()
    tk01 = TempoIndicators(gateway=MagicMock())
    return tk01


def _fresh_section():
    get_bus().clear()
    return TempoSection(gateway=MagicMock())


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTkSection(unittest.TestCase):

    # ── 01: TK-01 compute_indicators 回傳完整結構 ──────────────────────────────

    def test_01_compute_indicators_complete_structure(self):
        tk01 = _fresh_tk01()
        tk01.fetch_klines = MagicMock(
            return_value={"1h": _make_klines(200), "1d": []}
        )

        result = tk01.compute_indicators()

        self.assertIsNotNone(result)
        for key in ("volatility_pct", "volume_activity_ratio", "trend_strength_pct",
                    "sudden_change_detected", "std_deviation",
                    "current_price", "symbol", "timestamp"):
            self.assertIn(key, result)

        # 小施 history 也更新了
        self.assertEqual(len(tk01.history), 1)
        self.assertIs(tk01.last_indicators, result)

    # ── 02: TK-01 tempo_score — 高活躍 vs 低活躍 ─────────────────────────────

    def test_02_tempo_score_high_and_low_activity(self):
        tk01 = _fresh_tk01()

        # 高波動 + 高量能 + 急速變化 → 50+25+20+10=105 → cap 100 → "high_activity"
        tk01.last_indicators = _make_indicator(6.0, 2.0, sudden=True)
        high = tk01.get_tempo_score()
        self.assertGreater(high["score"], 70)
        self.assertEqual(high["level"], "high_activity")

        # 低波動 + 低量能 → 50-15-15=20 → "low_activity"
        tk01.last_indicators = _make_indicator(1.0, 0.5, sudden=False)
        low = tk01.get_tempo_score()
        self.assertLess(low["score"], 40)
        self.assertEqual(low["level"], "low_activity")

    # ── 03: TK-02 歷史統計 + percentile ─────────────────────────────────────

    def test_03_history_stats_and_percentile(self):
        tk01 = _fresh_tk01()
        tk02 = TempoMemory(tk01)

        # 5 個高分（vol=4.0 → score=65）+ 5 個低分（vol=1.0 → score=35）
        for _ in range(5):
            tk01.history.append(_make_indicator(4.0, 1.0))  # score=65
        for _ in range(5):
            tk01.history.append(_make_indicator(1.0, 1.0))  # score=35

        stats = tk02.get_tempo_history_stats()

        self.assertTrue(stats["available"])
        self.assertEqual(stats["current_score"],  35)          # 最後一個
        self.assertAlmostEqual(stats["avg_score_recent"], 50.0, places=1)
        self.assertAlmostEqual(stats["current_percentile"], 50.0, places=1)
        self.assertEqual(stats["sample_size"], 10)

    # ── 04: TK-02 轉換偵測 — 低→高 speedup ──────────────────────────────────

    def test_04_transition_detection_speedup(self):
        tk01 = _fresh_tk01()
        tk02 = TempoMemory(tk01)

        # 5 個低分（vol=1.0 → score=35）
        for _ in range(5):
            tk01.history.append(_make_indicator(1.0, 1.0))

        # 目前分數跳到 80
        result = tk02.detect_transition(current_score=80)

        # change_pct = (80-35)/35*100 ≈ 128 > 30 → speedup
        self.assertTrue(result["transition_detected"])
        self.assertEqual(result["type"], "speedup")
        self.assertGreater(result["magnitude"], 30)
        self.assertEqual(len(tk02.transition_history), 1)

    # ── 05: 老廖 tempo 判斷 — 四種情境 ──────────────────────────────────────

    def test_05_determine_tempo_all_cases(self):
        section = _fresh_section()

        # ≥ 85 → rest（過熱）
        r = section._determine_tempo({"score": 90}, {}, {"transition_detected": False})
        self.assertEqual(r["tempo"], "rest")

        # 65 ≤ score < 85 → active
        r = section._determine_tempo({"score": 70}, {}, {"transition_detected": False})
        self.assertEqual(r["tempo"], "active")

        # 35 ≤ score < 65 → cautious
        r = section._determine_tempo({"score": 50}, {}, {"transition_detected": False})
        self.assertEqual(r["tempo"], "cautious")

        # < 35 → rest（低活躍）
        r = section._determine_tempo({"score": 20}, {}, {"transition_detected": False})
        self.assertEqual(r["tempo"], "rest")

    # ── 06: 高嚴重度異常 → 強制 cautious ─────────────────────────────────────

    def test_06_high_severity_anomaly_forces_cautious(self):
        section = _fresh_section()

        # Before anomaly: score=70 → active
        r = section._determine_tempo({"score": 70}, {}, {"transition_detected": False})
        self.assertEqual(r["tempo"], "active")

        get_bus().publish("anomaly.detected", _make_anomaly(0.8), sender="test")

        self.assertIsNotNone(section.forced_caution_until)
        self.assertGreater(section.forced_caution_until, time.time())

        # Despite score=70, forced cautious overrides
        r = section._determine_tempo({"score": 70}, {}, {"transition_detected": False})
        self.assertEqual(r["tempo"], "cautious")
        self.assertAlmostEqual(r["confidence"], 0.9)

    # ── 07: 30 分鐘後解除強制 cautious ──────────────────────────────────────

    def test_07_forced_caution_expires(self):
        section = _fresh_section()
        get_bus().publish("anomaly.detected", _make_anomaly(0.8), sender="test")
        self.assertIsNotNone(section.forced_caution_until)

        # 模擬時間已過期
        section.forced_caution_until = time.time() - 1

        # score=70 → active again
        r = section._determine_tempo({"score": 70}, {}, {"transition_detected": False})
        self.assertEqual(r["tempo"], "active")

    # ── 08: produce_course_report 廣播 report.tk ─────────────────────────────

    def test_08_produce_course_report_publishes_to_bus(self):
        section = _fresh_section()
        ind = _make_indicator()
        section.tk_01.compute_indicators = MagicMock(return_value=ind)
        section.tk_01.get_tempo_score    = MagicMock(return_value={
            "score": 50, "level": "moderate",
            "reasoning": "平穩", "indicators": ind,
        })

        received = []
        get_bus().subscribe("report.tk", lambda m: received.append(m.payload), role="test")

        report = section.produce_course_report()

        self.assertIsInstance(report, CourseReport)
        self.assertEqual(report.course_code,   "TK")
        self.assertEqual(report.manager_name,  "老廖")
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], report)
        self.assertEqual(section.reports_produced, 1)
        self.assertIsNotNone(section.last_report_time)

        # score=50 → cautious → neutral
        self.assertEqual(report.course_direction, "neutral")
        self.assertEqual(report.self_review["tempo"], "cautious")

    # ── 09: run_cycle 節流（600 秒）────────────────────────────────────────

    def test_09_run_cycle_throttles_at_600s(self):
        section      = _fresh_section()
        mock_produce = MagicMock()
        section.produce_course_report = mock_produce

        # First call: no last_report_time → fires
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 1)

        # Too recent → skips
        section.last_report_time = time.time()
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 1)

        # 601 seconds elapsed → fires
        section.last_report_time = time.time() - 601
        section.run_cycle()
        self.assertEqual(mock_produce.call_count, 2)

    # ── 10: 全管道整合測試（mock fetch_klines，真實計算）────────────────────

    def test_10_full_pipeline_integration(self):
        section = _fresh_section()
        section.tk_01.fetch_klines = MagicMock(
            return_value={"1h": _make_klines(200), "1d": []}
        )

        received = []
        get_bus().subscribe(
            "report.tk", lambda m: received.append(m.payload), role="test-integ"
        )

        report = section.produce_course_report()

        self.assertIsInstance(report, CourseReport)
        self.assertIn(report.course_direction, ("bullish", "bearish", "neutral"))
        self.assertEqual(report.course_code, "TK")
        self.assertEqual(len(report.debate_results), 1)

        debate = report.debate_results[0]
        self.assertEqual(debate.report_a.role_name, "小施")
        self.assertEqual(debate.report_b.role_name, "華哥")
        self.assertTrue(debate.debate_id.startswith("TK-"))

        self.assertIn("tk_01_indicators", report.data_health)
        self.assertIn("tk_02_history",    report.data_health)
        self.assertIn("tempo",            report.self_review)
        self.assertTrue(report.data_health["tk_01_indicators"])
        self.assertGreater(len(received), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
