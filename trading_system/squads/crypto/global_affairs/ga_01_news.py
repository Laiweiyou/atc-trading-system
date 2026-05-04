# -*- coding: utf-8 -*-
"""ATC GA-01 阿蕭+芸芸（新聞情緒分析）— 即時影響 vs 結構影響雙人激辯組。"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class NewsAnalyst:
    """通用新聞分析員 — 阿蕭和芸芸共用，差別在 mode。

    mode="immediate_impact"  → 阿蕭 GA-01a（24h 即時衝擊視角）
    mode="structural_impact" → 芸芸 GA-01b（結構性長期影響視角）
    """

    # RSS 來源（最重要的 10 個）
    RSS_FEEDS: dict[str, str] = {
        "BBC World":    "https://feeds.bbci.co.uk/news/world/rss.xml",
        "Al Jazeera":   "https://www.aljazeera.com/xml/rss/all.xml",
        "Reuters":      "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com",
        "AP News":      "https://news.google.com/rss/search?q=when:24h+allinurl:apnews.com",
        "CNBC World":   "https://www.cnbc.com/id/100727362/device/rss/rss.html",
        "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "NPR":          "https://feeds.npr.org/1001/rss.xml",
        "Bloomberg":    "https://news.google.com/rss/search?q=when:24h+allinurl:bloomberg.com",
        "CoinDesk":     "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CoinTelegraph":"https://cointelegraph.com/rss",
    }

    CRYPTO_KEYWORDS: list[str] = [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
        "blockchain", "binance", "coinbase", "sec", "regulation",
        "fed", "interest rate", "inflation", "tariff", "sanctions",
        "trump", "powell", "stablecoin", "usdt", "usdc",
    ]

    STRUCTURAL_KEYWORDS: list[str] = [
        "regulation", "regulatory", "law", "ruling", "policy",
        "sanction", "tariff", "war", "conflict", "fed", "interest rate",
        "etf", "approval", "ban",
    ]

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("immediate_impact", "structural_impact"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "immediate_impact":
            self.role_name = "阿蕭"
            self.role_code = "GA-01a"
        else:
            self.role_name = "芸芸"
            self.role_code = "GA-01b"

        self.logger = get_logger(self.role_name)

        if mode == "structural_impact":
            try:
                from trading_system.common.historical_events_db import load_events
                self.historical_events: list[dict] = load_events()
            except Exception as e:
                self.logger.warning(f"載入歷史事件庫失敗: {e}")
                self.historical_events = []

        self.last_analysis_time: Optional[float] = None
        self.analysis_history: deque[SubReport] = deque(maxlen=50)

    # ─── Data fetch ───────────────────────────────────────────────────────────

    def fetch_recent_news(self, max_per_feed: int = 5) -> list[dict]:
        """從 RSS 抓最近的加密相關新聞。"""
        import feedparser
        import requests
        from trading_system.common.config import RSS_USER_AGENT

        all_news: list[dict] = []

        for source_name, url in self.RSS_FEEDS.items():
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": RSS_USER_AGENT},
                    timeout=10,
                    allow_redirects=True,
                )
                if response.status_code != 200:
                    continue

                feed = feedparser.parse(response.content)

                for entry in feed.entries[:max_per_feed]:
                    title   = entry.get("title", "")
                    summary = entry.get("summary", "")
                    text    = (title + " " + summary).lower()

                    if any(kw in text for kw in self.CRYPTO_KEYWORDS):
                        all_news.append({
                            "title":     title,
                            "summary":   summary[:300],
                            "source":    source_name,
                            "published": entry.get("published", ""),
                            "link":      entry.get("link", ""),
                        })
            except Exception as e:
                self.logger.debug(f"{source_name} 抓取失敗: {e}")
                continue

        return all_news

    # ─── Sentiment ────────────────────────────────────────────────────────────

    def analyze_news_sentiment(self, news_list: list[dict]) -> list[dict]:
        """用增強版 VADER 分析每則新聞。"""
        from trading_system.common.vader_enhanced import analyze_sentiment

        analyzed: list[dict] = []
        for news in news_list:
            text   = news["title"] + ". " + news.get("summary", "")
            result = analyze_sentiment(text)
            analyzed.append({
                **news,
                "sentiment_score": result["score"],
                "sentiment_label": result["label"],
                "confidence":      result["confidence"],
            })
        return analyzed

    # ─── Analyze ──────────────────────────────────────────────────────────────

    def analyze(self) -> SubReport:
        news = self.fetch_recent_news()

        if not news:
            return SubReport(
                role_name      = self.role_name,
                role_code      = self.role_code,
                direction      = "neutral",
                sub_confidence = 0.2,
                reasoning      = "無相關新聞",
                data_used      = {"news_count": 0},
                timestamp      = datetime.now(),
                staleness_flag = True,
            )

        analyzed = self.analyze_news_sentiment(news)

        if self.mode == "immediate_impact":
            return self._immediate_analysis(analyzed)
        return self._structural_analysis(analyzed)

    # ─── Immediate (阿蕭) ─────────────────────────────────────────────────────

    def _immediate_analysis(self, news_list: list[dict]) -> SubReport:
        """阿蕭的視角：24h 即時衝擊。"""
        signals: list[tuple[str, float, str]] = []
        data_used: dict = {
            "news_count":      len(news_list),
            "high_impact_news": [],
        }

        high_impact = [n for n in news_list if n["confidence"] > 0.4]

        if not high_impact:
            return SubReport(
                role_name      = self.role_name,
                role_code      = self.role_code,
                direction      = "neutral",
                sub_confidence = 0.3,
                reasoning      = f"分析了 {len(news_list)} 則新聞，無高衝擊事件",
                data_used      = data_used,
                timestamp      = datetime.now(),
                staleness_flag = False,
            )

        total_score = 0.0
        for n in high_impact:
            total_score += n["sentiment_score"]
            data_used["high_impact_news"].append({
                "title":  n["title"][:80],
                "score":  n["sentiment_score"],
                "source": n["source"],
            })

        avg_score = total_score / len(high_impact)
        data_used["avg_sentiment_score"] = avg_score

        if avg_score > 0.3:
            signals.append(("bullish", min(abs(avg_score) + 0.2, 0.8),
                           f"{len(high_impact)} 則高衝擊新聞偏多 (avg={avg_score:.2f})"))
        elif avg_score < -0.3:
            signals.append(("bearish", min(abs(avg_score) + 0.2, 0.8),
                           f"{len(high_impact)} 則高衝擊新聞偏空 (avg={avg_score:.2f})"))
        elif abs(avg_score) > 0.1:
            direction = "bullish" if avg_score > 0 else "bearish"
            signals.append((direction, 0.3, f"輕微偏向 (avg={avg_score:.2f})"))

        critical_negative = [n for n in news_list if n["sentiment_score"] < -0.7]
        if critical_negative:
            data_used["critical_negative_count"] = len(critical_negative)
            signals.append(("bearish", 0.4, f"{len(critical_negative)} 則極端負面新聞"))

        return self._synthesize(signals, data_used)

    # ─── Structural (芸芸) ────────────────────────────────────────────────────

    def _structural_analysis(self, news_list: list[dict]) -> SubReport:
        """芸芸的視角：結構性長期影響。"""
        signals: list[tuple[str, float, str]] = []
        data_used: dict = {
            "news_count":      len(news_list),
            "structural_news": [],
        }

        structural_news = [
            n for n in news_list
            if any(kw in (n["title"] + " " + n.get("summary", "")).lower()
                   for kw in self.STRUCTURAL_KEYWORDS)
        ]
        data_used["structural_news_count"] = len(structural_news)

        if not structural_news:
            return SubReport(
                role_name      = self.role_name,
                role_code      = self.role_code,
                direction      = "neutral",
                sub_confidence = 0.4,
                reasoning      = f"分析了 {len(news_list)} 則新聞，無結構性事件",
                data_used      = data_used,
                timestamp      = datetime.now(),
                staleness_flag = False,
            )

        struct_score = (
            sum(n["sentiment_score"] for n in structural_news) / len(structural_news)
        )
        data_used["structural_avg_score"] = struct_score

        for n in structural_news[:5]:
            data_used["structural_news"].append({
                "title":  n["title"][:80],
                "score":  n["sentiment_score"],
                "source": n["source"],
            })

        # 歷史比對（芸芸專屬）
        if getattr(self, "historical_events", None):
            similar_count = self._count_similar_historical(structural_news)
            data_used["similar_historical_events"] = similar_count

            if similar_count >= 3:
                struct_score *= 0.6
                signals.append(("neutral", 0.2,
                               f"歷史上有 {similar_count} 個類似事件，衝擊已被消化"))

        if struct_score > 0.4:
            signals.append(("bullish", min(abs(struct_score) + 0.1, 0.7),
                           f"結構性正面 (avg={struct_score:.2f})"))
        elif struct_score < -0.4:
            signals.append(("bearish", min(abs(struct_score) + 0.1, 0.7),
                           f"結構性負面 (avg={struct_score:.2f})"))
        elif abs(struct_score) > 0.15:
            direction = "bullish" if struct_score > 0 else "bearish"
            signals.append((direction, 0.25, "輕微結構偏向"))

        return self._synthesize(signals, data_used)

    def _count_similar_historical(self, news_list: list[dict]) -> int:
        all_text = " ".join(
            (n["title"] + " " + n.get("summary", "")).lower()
            for n in news_list
        )
        return sum(
            1 for event in self.historical_events
            if any(e.lower() in all_text for e in event.get("key_entities", []))
        )

    # ─── Synthesize ───────────────────────────────────────────────────────────

    def _synthesize(
        self,
        signals: list[tuple[str, float, str]],
        data_used: dict,
    ) -> SubReport:
        if not signals:
            return SubReport(
                role_name      = self.role_name,
                role_code      = self.role_code,
                direction      = "neutral",
                sub_confidence = 0.3,
                reasoning      = "無顯著訊號",
                data_used      = data_used,
                timestamp      = datetime.now(),
                staleness_flag = False,
            )

        bullish_w = sum(w for d, w, _ in signals if d == "bullish")
        bearish_w = sum(w for d, w, _ in signals if d == "bearish")
        neutral_w = sum(w for d, w, _ in signals if d == "neutral")

        if bullish_w > bearish_w * 1.2:
            direction  = "bullish"
            confidence = min(bullish_w, 0.95)
        elif bearish_w > bullish_w * 1.2:
            direction  = "bearish"
            confidence = min(bearish_w, 0.95)
        else:
            direction  = "neutral"
            confidence = min(0.4 + neutral_w * 0.3, 0.95)

        reasoning = "; ".join(r for _, _, r in signals)

        report = SubReport(
            role_name      = self.role_name,
            role_code      = self.role_code,
            direction      = direction,
            sub_confidence = confidence,
            reasoning      = reasoning,
            data_used      = data_used,
            timestamp      = datetime.now(),
            staleness_flag = False,
        )
        self.analysis_history.append(report)
        return report


# ─── NewsSection ──────────────────────────────────────────────────────────────

class NewsSection:
    """阿蕭+芸芸雙人組統籌（GA-01 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("GA-01-Section")

        self.axiao  = NewsAnalyst("immediate_impact",  gateway=self.gateway, bus=self.bus)
        self.yunyun = NewsAnalyst("structural_impact", gateway=self.gateway, bus=self.bus)

        self.debate_history: deque[DebateResult] = deque(maxlen=50)

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self) -> DebateResult:
        report_a = self.axiao.analyze()
        report_b = self.yunyun.analyze()

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"GA-01-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            report_a           = report_a,
            report_b           = report_b,
            consensus_type     = consensus_type,
            final_direction    = final_direction,
            final_confidence   = final_confidence,
            combined_reasoning = reasoning,
            key_disagreement   = self._identify_disagreement(report_a, report_b),
            timestamp          = datetime.now(),
        )

        self.debate_history.append(debate)
        return debate

    def _compare_reports(
        self,
        report_a: SubReport,
        report_b: SubReport,
    ) -> tuple[str, str, float, str]:
        """委派給通用雙人激辯引擎。"""
        from trading_system.common.debate_engine import compare_reports as _engine_compare
        result = _engine_compare(report_a, report_b, "阿蕭", "芸芸")
        if result["consensus_type"] == "dual_track":
            self.logger.warning(f"GA-01 雙人大分歧: {result['reasoning']}")
        return (
            result["consensus_type"],
            result["final_direction"],
            result["final_confidence"],
            result["reasoning"],
        )

    def _identify_disagreement(
        self,
        report_a: SubReport,
        report_b: SubReport,
    ) -> Optional[str]:
        if report_a.direction != report_b.direction:
            return f"方向分歧: 阿蕭={report_a.direction} vs 芸芸={report_b.direction}"
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 阿蕭={report_a.sub_confidence:.2f} "
                f"vs 芸芸={report_b.sub_confidence:.2f}"
            )
        return None
