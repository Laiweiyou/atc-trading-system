# -*- coding: utf-8 -*-
"""ATC GA-02 阿呂+萱萱（監管分析）— 條文解讀 vs 執行脈絡雙人激辯組。"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class RegulatoryAnalyst:
    """通用監管分析員 — 阿呂和萱萱共用，差別在 mode。

    mode="literal"     → 阿呂 GA-02a（條文嚴格度解讀）
    mode="contextual"  → 萱萱 GA-02b（執行脈絡判斷）
    """

    REGULATORY_FEEDS: dict[str, str] = {
        "SEC": (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            "?action=getcurrent&type=8-K&dateb=&owner=include&count=40&output=atom"
        ),
        "CFTC": "https://news.google.com/rss/search?q=when:7d+CFTC+enforcement+OR+ruling",
        "Reuters Reg": (
            "https://news.google.com/rss/search"
            "?q=when:24h+SEC+OR+CFTC+OR+regulation+OR+enforcement+allinurl:reuters.com"
        ),
    }

    REGULATORY_KEYWORDS: list[str] = [
        "sec", "cftc", "regulation", "regulatory", "enforcement", "ruling",
        "lawsuit", "subpoena", "fine", "penalty", "investigation",
        "compliance", "ban", "prohibit", "restrict", "license",
        "approve", "denied", "rejected", "guidelines",
    ]

    STRICT_KEYWORDS: dict[str, list[str]] = {
        "high_strictness":   ["ban", "prohibit", "criminal", "felony", "indict", "charged"],
        "medium_strictness": ["fine", "penalty", "lawsuit", "subpoena", "enforcement"],
        "low_strictness":    ["guideline", "framework", "consultation", "proposed", "comment period"],
    }

    WEAK_ENFORCEMENT_KEYWORDS:   list[str] = ["dropped", "dismissed", "settled", "lenient", "delayed"]
    STRONG_ENFORCEMENT_KEYWORDS: list[str] = ["indicted", "charged", "raid", "criminal", "arrested"]

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("literal", "contextual"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "literal":
            self.role_name = "阿呂"
            self.role_code = "GA-02a"
        else:
            self.role_name = "萱萱"
            self.role_code = "GA-02b"

        self.logger = get_logger(self.role_name)

        self.enforcement_history: dict = {
            "sec_recent_actions": 0,
            "fines_collected":    0,
            "cases_dropped":      0,
        }

        self.last_analysis_time: Optional[float] = None

    # ─── Data fetch ───────────────────────────────────────────────────────────

    def fetch_regulatory_news(self) -> list[dict]:
        """從監管 RSS 來源抓取新聞。"""
        import feedparser
        import requests
        from trading_system.common.config import RSS_USER_AGENT

        all_news: list[dict] = []

        for source_name, url in self.REGULATORY_FEEDS.items():
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

                for entry in feed.entries[:10]:
                    title   = entry.get("title", "")
                    summary = entry.get("summary", "")
                    text    = (title + " " + summary).lower()

                    if any(kw in text for kw in self.REGULATORY_KEYWORDS):
                        all_news.append({
                            "title":     title,
                            "summary":   summary[:300],
                            "source":    source_name,
                            "published": entry.get("published", ""),
                        })
            except Exception as e:
                self.logger.debug(f"{source_name} 抓取失敗: {e}")
                continue

        return all_news

    # ─── Analyze ──────────────────────────────────────────────────────────────

    def analyze(self) -> SubReport:
        news = self.fetch_regulatory_news()

        if not news:
            return SubReport(
                role_name      = self.role_name,
                role_code      = self.role_code,
                direction      = "neutral",
                sub_confidence = 0.3,
                reasoning      = "無監管新聞",
                data_used      = {"news_count": 0},
                timestamp      = datetime.now(),
                staleness_flag = True,
            )

        from trading_system.common.vader_enhanced import analyze_sentiment
        for n in news:
            text = n["title"] + ". " + n.get("summary", "")
            result = analyze_sentiment(text)
            n["sentiment_score"]      = result["score"]
            n["sentiment_confidence"] = result["confidence"]

        if self.mode == "literal":
            return self._literal_analysis(news)
        return self._contextual_analysis(news)

    # ─── Literal (阿呂) ───────────────────────────────────────────────────────

    def _literal_analysis(self, news_list: list[dict]) -> SubReport:
        """阿呂的視角：條文嚴格度。"""
        signals: list[tuple[str, float, str]] = []
        data_used: dict = {"news_count": len(news_list), "strict_news": []}

        high_count = medium_count = low_count = 0

        for n in news_list:
            text = (n["title"] + " " + n.get("summary", "")).lower()

            if any(kw in text for kw in self.STRICT_KEYWORDS["high_strictness"]):
                high_count += 1
                data_used["strict_news"].append({
                    "title": n["title"][:80],
                    "level": "high",
                    "score": n["sentiment_score"],
                })
            elif any(kw in text for kw in self.STRICT_KEYWORDS["medium_strictness"]):
                medium_count += 1
                data_used["strict_news"].append({
                    "title": n["title"][:80],
                    "level": "medium",
                    "score": n["sentiment_score"],
                })
            elif any(kw in text for kw in self.STRICT_KEYWORDS["low_strictness"]):
                low_count += 1

        data_used["high_strictness"]   = high_count
        data_used["medium_strictness"] = medium_count
        data_used["low_strictness"]    = low_count

        if high_count >= 2:
            signals.append(("bearish", 0.6, f"{high_count} 則高嚴格度監管事件（ban/criminal）"))
        elif high_count >= 1:
            signals.append(("bearish", 0.4, f"{high_count} 則高嚴格度監管"))

        if medium_count >= 3:
            signals.append(("bearish", 0.3, f"{medium_count} 則中等嚴格度（fines/lawsuits）"))
        elif medium_count >= 1:
            signals.append(("bearish", 0.15, f"{medium_count} 則中等嚴格度"))

        if low_count >= 2 and high_count == 0:
            signals.append(("bullish", 0.2, f"{low_count} 則理性討論型新聞"))

        if news_list:
            avg_sentiment = sum(n["sentiment_score"] for n in news_list) / len(news_list)
            data_used["avg_sentiment"] = avg_sentiment

            if avg_sentiment > 0.2 and high_count >= 1:
                signals.append(("neutral", 0.2, "嚴格度高但情緒正面（監管已處理）"))

        return self._synthesize(signals, data_used)

    # ─── Contextual (萱萱) ────────────────────────────────────────────────────

    def _contextual_analysis(self, news_list: list[dict]) -> SubReport:
        """萱萱的視角：執行脈絡。"""
        signals: list[tuple[str, float, str]] = []
        data_used: dict = {"news_count": len(news_list), "contextual_assessment": []}

        weak_count = strong_count = 0

        for n in news_list:
            text = (n["title"] + " " + n.get("summary", "")).lower()

            if any(kw in text for kw in self.WEAK_ENFORCEMENT_KEYWORDS):
                weak_count += 1
                data_used["contextual_assessment"].append({
                    "title": n["title"][:80],
                    "tone":  "weak",
                })
            elif any(kw in text for kw in self.STRONG_ENFORCEMENT_KEYWORDS):
                strong_count += 1
                data_used["contextual_assessment"].append({
                    "title": n["title"][:80],
                    "tone":  "strong",
                })

        data_used["weak_enforcement_signals"]   = weak_count
        data_used["strong_enforcement_signals"] = strong_count

        if strong_count >= 2:
            signals.append(("bearish", 0.5, f"{strong_count} 則強執行訊號"))
        elif strong_count >= 1:
            signals.append(("bearish", 0.25, f"{strong_count} 則強執行訊號"))

        if weak_count >= 2:
            signals.append(("bullish", 0.3, f"{weak_count} 則弱執行訊號（監管軟化）"))
        elif weak_count >= 1:
            signals.append(("bullish", 0.15, f"{weak_count} 則弱執行訊號"))

        if news_list:
            avg_sentiment = sum(n["sentiment_score"] for n in news_list) / len(news_list)
            data_used["avg_sentiment"] = avg_sentiment

            if avg_sentiment > 0.3:
                signals.append(("bullish", 0.3,
                               f"監管新聞整體情緒正面 (avg={avg_sentiment:.2f})"))
            elif avg_sentiment < -0.3:
                signals.append(("bearish", 0.3,
                               f"監管新聞整體情緒負面 (avg={avg_sentiment:.2f})"))

        if strong_count >= 1 and weak_count >= 1:
            signals.append(("bearish", 0.2, "監管方向不確定（強弱訊號並存）"))

        return self._synthesize(signals, data_used)

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
                reasoning      = "無顯著監管訊號",
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
            confidence = min(0.4 + neutral_w * 0.2, 0.95)

        reasoning = "; ".join(r for _, _, r in signals)

        return SubReport(
            role_name      = self.role_name,
            role_code      = self.role_code,
            direction      = direction,
            sub_confidence = confidence,
            reasoning      = reasoning,
            data_used      = data_used,
            timestamp      = datetime.now(),
            staleness_flag = False,
        )


# ─── RegulatorySection ────────────────────────────────────────────────────────

class RegulatorySection:
    """阿呂+萱萱雙人組統籌（GA-02 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway  = gateway or get_gateway()
        self.bus      = bus or get_bus()
        self.logger   = get_logger("GA-02-Section")

        self.alu      = RegulatoryAnalyst("literal",    gateway=self.gateway, bus=self.bus)
        self.xuanxuan = RegulatoryAnalyst("contextual", gateway=self.gateway, bus=self.bus)

        self.debate_history: deque[DebateResult] = deque(maxlen=50)

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self) -> DebateResult:
        report_a = self.alu.analyze()
        report_b = self.xuanxuan.analyze()

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"GA-02-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
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
        result = _engine_compare(report_a, report_b, "阿呂", "萱萱")
        if result["consensus_type"] == "dual_track":
            self.logger.warning(f"GA-02 雙人大分歧: {result['reasoning']}")
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
            return f"方向分歧: 阿呂={report_a.direction} vs 萱萱={report_b.direction}"
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 阿呂={report_a.sub_confidence:.2f} "
                f"vs 萱萱={report_b.sub_confidence:.2f}"
            )
        return None
