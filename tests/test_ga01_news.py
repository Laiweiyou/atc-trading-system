# -*- coding: utf-8 -*-
"""Tests for GA-01 阿蕭+芸芸（新聞分析）— Phase 3 Step 12."""
import io
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.global_affairs.ga_01_news import (
    NewsAnalyst,
    NewsSection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _analyzed_news(title, score, confidence=None, source="Test", summary=""):
    """Pre-analyzed news item (skips fetch + VADER step)."""
    if confidence is None:
        confidence = abs(score)
    return {
        "title":           title,
        "summary":         summary,
        "source":          source,
        "published":       "",
        "link":            "",
        "sentiment_score": score,
        "sentiment_label": "positive" if score > 0.05 else ("negative" if score < -0.05 else "neutral"),
        "confidence":      confidence,
    }


def _raw_news(title, summary="", source="Test"):
    """Un-analyzed news item (title + summary only)."""
    return {"title": title, "summary": summary, "source": source,
            "published": "", "link": ""}


def _make_subreport(direction, confidence, stale=False):
    return SubReport(
        role_name="test", role_code="TEST",
        direction=direction, sub_confidence=confidence,
        reasoning="test", data_used={},
        timestamp=datetime.now(), staleness_flag=stale,
    )


def _fresh_analyst(mode, clear_history=True):
    if clear_history:
        get_bus().clear()
    analyst = NewsAnalyst(mode, gateway=MagicMock())
    if mode == "structural_impact":
        analyst.historical_events = []   # isolate from live DB in most tests
    return analyst


def _fresh_section():
    get_bus().clear()
    return NewsSection(gateway=MagicMock())


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGA01News(unittest.TestCase):

    # ── 01: 兩位分析員角色初始化 ──────────────────────────────────────────────

    def test_01_analyst_roles(self):
        axiao  = _fresh_analyst("immediate_impact")
        yunyun = _fresh_analyst("structural_impact")

        self.assertEqual(axiao.role_name,  "阿蕭")
        self.assertEqual(axiao.role_code,  "GA-01a")
        self.assertEqual(axiao.mode,       "immediate_impact")

        self.assertEqual(yunyun.role_name, "芸芸")
        self.assertEqual(yunyun.role_code, "GA-01b")
        self.assertEqual(yunyun.mode,      "structural_impact")

        # 芸芸有 historical_events 屬性；阿蕭沒有
        self.assertTrue(hasattr(yunyun, "historical_events"))
        self.assertFalse(hasattr(axiao,  "historical_events"))

    # ── 02: 阿蕭即時分析 — 高衝擊負面新聞 → bearish ───────────────────────────

    def test_02_immediate_bearish_high_impact(self):
        # 5 news items with strong negative score (confidence=0.6 > 0.4 threshold)
        # avg_score = -0.6 < -0.3 → bearish signal weight = min(0.8, 0.8) = 0.8
        analyst = _fresh_analyst("immediate_impact")
        analyzed = [_analyzed_news(f"Crypto crash headline {i}", -0.6, 0.6)
                    for i in range(5)]

        report = analyst._immediate_analysis(analyzed)

        self.assertIsInstance(report, SubReport)
        self.assertEqual(report.direction,  "bearish")
        self.assertAlmostEqual(report.sub_confidence, 0.8, places=5)
        self.assertGreater(len(report.data_used["high_impact_news"]), 0)

    # ── 03: 阿蕭 — 低信心新聞 → neutral（無高衝擊）────────────────────────────

    def test_03_immediate_low_confidence_neutral(self):
        # confidence=0.3 < 0.4 threshold → no high_impact news
        analyst  = _fresh_analyst("immediate_impact")
        analyzed = [_analyzed_news("Crypto market flat today", -0.5, 0.3)]

        report = analyst._immediate_analysis(analyzed)

        self.assertEqual(report.direction,  "neutral")
        self.assertAlmostEqual(report.sub_confidence, 0.3)

    # ── 04: 芸芸結構分析 — 非結構性新聞 → neutral ─────────────────────────────

    def test_04_structural_non_structural_news_neutral(self):
        # No structural keywords (regulation/fed/tariff/etc) in text
        analyst  = _fresh_analyst("structural_impact")
        analyzed = [_analyzed_news("Bitcoin price steady as traders watch", -0.5, 0.5)]

        report = analyst._structural_analysis(analyzed)

        self.assertEqual(report.direction,  "neutral")
        self.assertAlmostEqual(report.sub_confidence, 0.4)
        self.assertEqual(report.data_used["structural_news_count"], 0)

    # ── 05: 芸芸結構分析 — regulation/fed 關鍵詞 → 偵測並分析 ───────────────

    def test_05_structural_detects_regulation_keywords(self):
        analyst  = _fresh_analyst("structural_impact")
        analyzed = [
            _analyzed_news("SEC regulation crackdown on crypto markets", -0.8, 0.8),
            _analyzed_news("Bitcoin price rises on sentiment", 0.1, 0.1),  # non-structural
        ]

        report = analyst._structural_analysis(analyzed)

        self.assertEqual(report.data_used["structural_news_count"], 1)
        self.assertEqual(report.direction, "bearish")   # struct_score=-0.8 < -0.4

    # ── 06: 兩人方向一致 → agreed ────────────────────────────────────────────

    def test_06_agreed_both_bearish(self):
        section = _fresh_section()
        section.axiao.analyze  = MagicMock(return_value=_make_subreport("bearish", 0.7))
        section.yunyun.analyze = MagicMock(return_value=_make_subreport("bearish", 0.6))

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type, "agreed")
        self.assertEqual(result.final_direction, "bearish")
        self.assertAlmostEqual(result.final_confidence, 0.65)

    # ── 07: 大分歧（阿蕭 bearish，芸芸 neutral）→ dual_track ─────────────────

    def test_07_dual_track_axiao_bearish_yunyun_neutral(self):
        section = _fresh_section()
        section.axiao.analyze  = MagicMock(return_value=_make_subreport("bearish", 0.7))
        section.yunyun.analyze = MagicMock(return_value=_make_subreport("neutral", 0.4))

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type, "dual_track")
        # severity: bearish=2 > neutral=1 → final=bearish (axiao's)
        self.assertEqual(result.final_direction, "bearish")
        self.assertAlmostEqual(result.final_confidence, 0.7 * 0.8, places=5)
        self.assertIsNotNone(result.key_disagreement)

    # ── 08: 真實 VADER 整合（不做 HTTP，直接跑情緒分析）─────────────────────

    def test_08_vader_integration(self):
        analyst = _fresh_analyst("immediate_impact")

        neg_news = _raw_news(
            "Bitcoin crashes 20% after SEC bans crypto exchanges",
            summary="Major regulatory crackdown leads to market collapse",
        )
        analyzed = analyst.analyze_news_sentiment([neg_news])

        self.assertEqual(len(analyzed), 1)
        item = analyzed[0]
        self.assertIn("sentiment_score", item)
        self.assertIn("sentiment_label", item)
        self.assertIn("confidence",      item)
        self.assertLess(item["sentiment_score"], 0)    # strongly negative text
        self.assertGreater(item["confidence"], 0)

    # ── 09: 歷史事件庫比對 — ≥3 類似事件 → 衝擊打折 ─────────────────────────

    def test_09_historical_events_dampens_impact(self):
        analyst = _fresh_analyst("structural_impact")

        # 3 historical events all matching "tariff" keyword
        analyst.historical_events = [
            {"key_entities": ["tariff", "US"]},
            {"key_entities": ["tariff", "China"]},
            {"key_entities": ["tariff", "EU"]},
        ]

        # structural news with "tariff" in title (matches STRUCTURAL_KEYWORDS too)
        analyzed = [
            _analyzed_news("US tariff regulation impact on crypto", -0.6, 0.6,
                           summary="trade war fears")
        ]

        report = analyst._structural_analysis(analyzed)

        # similar_historical_events should be 3
        self.assertIn("similar_historical_events", report.data_used)
        self.assertEqual(report.data_used["similar_historical_events"], 3)

        # Dampened confidence: original -0.6 → *0.6 = -0.36 → weaker signal
        self.assertLess(report.sub_confidence, 0.7)   # lower than undampened ~0.7

    # ── 10: 歷史事件庫整合 — 芸芸初始化時自動載入 ────────────────────────────

    def test_10_yunyun_loads_historical_events_on_init(self):
        get_bus().clear()
        # Do NOT override historical_events — test real loading
        yunyun = NewsAnalyst("structural_impact", gateway=MagicMock())

        self.assertTrue(hasattr(yunyun, "historical_events"))
        self.assertIsInstance(yunyun.historical_events, list)
        self.assertGreater(len(yunyun.historical_events), 0)   # 15 events in DB

    # ── 11: conduct_debate 回傳完整 DebateResult ──────────────────────────────

    def test_11_conduct_debate_full_flow(self):
        section = _fresh_section()
        section.axiao.analyze  = MagicMock(return_value=_make_subreport("bullish", 0.6))
        section.yunyun.analyze = MagicMock(return_value=_make_subreport("bullish", 0.5))

        result = section.conduct_debate()

        self.assertIsInstance(result, DebateResult)
        self.assertTrue(result.debate_id.startswith("GA-01-"))
        self.assertIn(result.consensus_type, ("agreed", "discussed_agreed", "dual_track"))
        self.assertIsInstance(result.report_a, SubReport)
        self.assertIsInstance(result.report_b, SubReport)
        self.assertEqual(len(section.debate_history), 1)

    # ── 12: 極端負面新聞觸發 critical_negative 警告 ────────────────────────────

    def test_12_critical_negative_news_adds_bearish_signal(self):
        analyst  = _fresh_analyst("immediate_impact")
        analyzed = [
            _analyzed_news("Bitcoin hacked — exchange collapses", -0.85, 0.85),  # < -0.7
        ]

        report = analyst._immediate_analysis(analyzed)

        self.assertEqual(report.direction, "bearish")
        self.assertIn("critical_negative_count", report.data_used)
        self.assertEqual(report.data_used["critical_negative_count"], 1)

    # ── 13: discussed_agreed（同向信心差距 > 0.2）──────────────────────────────

    def test_13_discussed_agreed_same_direction_large_gap(self):
        section = _fresh_section()
        section.axiao.analyze  = MagicMock(return_value=_make_subreport("bearish", 0.8))
        section.yunyun.analyze = MagicMock(return_value=_make_subreport("bearish", 0.3))

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type, "discussed_agreed")
        self.assertEqual(result.final_direction, "bearish")
        expected = (0.8**2 + 0.3**2) / (0.8 + 0.3)
        self.assertAlmostEqual(result.final_confidence, expected, places=5)

    # ── 14: 無新聞 → stale SubReport ────────────────────────────────────────

    def test_14_no_news_returns_stale(self):
        analyst = _fresh_analyst("immediate_impact")
        analyst.fetch_recent_news = MagicMock(return_value=[])

        report, = [analyst.analyze()]

        self.assertTrue(report.staleness_flag)
        self.assertEqual(report.direction, "neutral")
        self.assertEqual(report.data_used["news_count"], 0)

    # ── 15: _immediate_analysis 正面新聞 → bullish ────────────────────────────

    def test_15_immediate_bullish_positive_news(self):
        analyst  = _fresh_analyst("immediate_impact")
        analyzed = [_analyzed_news(f"Bitcoin rallies on ETF approval {i}", 0.7, 0.7)
                    for i in range(3)]

        report = analyst._immediate_analysis(analyzed)

        self.assertEqual(report.direction, "bullish")
        self.assertAlmostEqual(report.sub_confidence, min(0.7 + 0.2, 0.8), places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
