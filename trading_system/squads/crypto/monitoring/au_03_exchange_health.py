# -*- coding: utf-8 -*-
"""ATC AU-03 君君/阿豪/小馬（交易所健康度監控）— 雙人激辯組。"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

_NEGATIVE_KEYWORDS = ["hack", "down", "withdraw", "frozen", "stuck", "scam", "fraud"]


# ─── ExchangeHealthAnalyst ────────────────────────────────────────────────────

class ExchangeHealthAnalyst:
    """
    通用分析員 — 君君和阿豪都用這個 class，差別在 mode 參數。

    mode="quantitative" → 君君 AU-03a（量化數據型）
    mode="qualitative"  → 阿豪 AU-03b（質化情報型）
    """

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("quantitative", "qualitative"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "quantitative":
            self.role_name = "君君"
            self.role_code = "AU-03a"
        else:
            self.role_name = "阿豪"
            self.role_code = "AU-03b"

        self.logger               = get_logger(self.role_name)
        self.last_analysis_time:  Optional[datetime] = None
        self.analysis_history:    deque[SubReport]   = deque(maxlen=50)

    # ─── Public ───────────────────────────────────────────────────────────────

    def analyze(self) -> SubReport:
        if self.mode == "quantitative":
            return self._quantitative_analysis()
        return self._qualitative_analysis()

    # ─── Quantitative (君君) ──────────────────────────────────────────────────

    def _quantitative_analysis(self) -> SubReport:
        data_used: dict = {}
        signals:   list = []   # (direction, weight, reason)

        # 1. API 延遲分析
        api_stats  = self.gateway.get_stats()
        avg_latency = api_stats.get("avg_response_time_ms", 0)
        data_used["api_avg_latency_ms"] = avg_latency

        if avg_latency > 1000:
            signals.append(("bearish", 0.4, f"API 延遲過高 {avg_latency:.0f}ms"))
        elif avg_latency > 500:
            signals.append(("bearish", 0.2, f"API 延遲偏高 {avg_latency:.0f}ms"))
        elif avg_latency < 200:
            signals.append(("bullish", 0.1, "API 延遲正常"))

        # 2. API 錯誤率
        errors_last_hour = api_stats.get("errors_last_hour", 0)
        total_recent     = api_stats.get("requests_last_hour", 1)
        error_rate       = errors_last_hour / max(1, total_recent)
        data_used["api_error_rate"] = error_rate

        if error_rate > 0.1:
            signals.append(("bearish", 0.5, f"API 錯誤率 {error_rate*100:.1f}%"))
        elif error_rate > 0.03:
            signals.append(("bearish", 0.2, f"API 錯誤率略高 {error_rate*100:.1f}%"))

        # 3. 心跳健康
        health = self.gateway.health_check()
        data_used["gateway_health"] = health
        if not health.get("healthy", True):
            signals.append(("bearish", 0.6, "Gateway 健康檢查失敗"))

        return self._synthesize_report(signals, data_used)

    # ─── Qualitative (阿豪) ───────────────────────────────────────────────────

    def _qualitative_analysis(self) -> SubReport:
        data_used: dict = {}
        signals:   list = []

        try:
            import feedparser
            feed    = feedparser.parse("https://www.reddit.com/r/Bybit/new/.rss")
            entries = feed.entries[:10]
            data_used["reddit_post_count"] = len(entries)

            if len(entries) == 0:
                signals.append(("bearish", 0.3, "無法取得 Reddit 內容"))
            else:
                from trading_system.common.vader_enhanced import analyze_sentiment

                sentiments:             list = []
                negative_keywords_count: int  = 0

                for entry in entries:
                    title  = entry.get("title", "")
                    result = analyze_sentiment(title)
                    sentiments.append(result["score"])

                    title_lower = title.lower()
                    if any(kw in title_lower for kw in _NEGATIVE_KEYWORDS):
                        negative_keywords_count += 1

                avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0
                data_used["avg_sentiment"]          = avg_sentiment
                data_used["negative_keyword_posts"] = negative_keywords_count

                if avg_sentiment < -0.3:
                    signals.append(("bearish", 0.5, f"社群情緒明顯負面 {avg_sentiment:.2f}"))
                elif avg_sentiment < -0.1:
                    signals.append(("bearish", 0.2, f"社群情緒偏負面 {avg_sentiment:.2f}"))
                elif avg_sentiment > 0.2:
                    signals.append(("bullish", 0.2, "社群情緒正面"))

                if negative_keywords_count >= 3:
                    signals.append(("bearish", 0.5, f"{negative_keywords_count} 篇含負面關鍵詞"))
                elif negative_keywords_count >= 1:
                    signals.append(("bearish", 0.2, f"{negative_keywords_count} 篇含負面關鍵詞"))

        except Exception as e:
            self.logger.warning(f"質化分析失敗: {e}")
            data_used["error"] = str(e)
            signals.append(("neutral", 0.3, "資料源不可用"))

        return self._synthesize_report(signals, data_used)

    # ─── Synthesis ────────────────────────────────────────────────────────────

    def _synthesize_report(self, signals: list, data_used: dict) -> SubReport:
        if not signals:
            direction  = "neutral"
            confidence = 0.3
            reasoning  = "無顯著訊號"
        else:
            bullish_weight = sum(w for d, w, _ in signals if d == "bullish")
            bearish_weight = sum(w for d, w, _ in signals if d == "bearish")

            if bullish_weight > bearish_weight:
                direction  = "bullish"
                confidence = min(bullish_weight, 0.95)
            elif bearish_weight > bullish_weight:
                direction  = "bearish"
                confidence = min(bearish_weight, 0.95)
            else:
                direction  = "neutral"
                confidence = 0.4

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
        self.last_analysis_time = datetime.now()
        return report


# ─── ExchangeHealthSection ────────────────────────────────────────────────────

class ExchangeHealthSection:
    """小馬主管的雙人組統籌。"""

    role_name = "小馬"
    role_code = "AU-03-Manager"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("小馬")

        self.junjun = ExchangeHealthAnalyst("quantitative", gateway=self.gateway, bus=self.bus)
        self.ahao   = ExchangeHealthAnalyst("qualitative",  gateway=self.gateway, bus=self.bus)

        self.debate_history:    deque[DebateResult] = deque(maxlen=20)
        self.last_health_status: str                = "healthy"

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self) -> DebateResult:
        report_a = self.junjun.analyze()
        report_b = self.ahao.analyze()

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate_result = DebateResult(
            debate_id          = f"AU-03-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            report_a           = report_a,
            report_b           = report_b,
            consensus_type     = consensus_type,
            final_direction    = final_direction,
            final_confidence   = final_confidence,
            combined_reasoning = reasoning,
            key_disagreement   = self._identify_disagreement(report_a, report_b),
            timestamp          = datetime.now(),
        )

        self.debate_history.append(debate_result)
        self._update_health_status(debate_result)
        return debate_result

    def _compare_reports(
        self,
        report_a: SubReport,
        report_b: SubReport,
    ) -> tuple[str, str, float, str]:
        """通用比對函數（雙人激辯的核心邏輯）。回傳 (consensus_type, direction, confidence, reasoning)。"""
        same_direction  = report_a.direction == report_b.direction
        confidence_diff = abs(report_a.sub_confidence - report_b.sub_confidence)

        if same_direction and confidence_diff <= 0.2:
            consensus_type   = "agreed"
            final_direction  = report_a.direction
            final_confidence = (report_a.sub_confidence + report_b.sub_confidence) / 2
            reasoning = (
                f"君君: {report_a.reasoning} | 阿豪: {report_b.reasoning}"
            )

        elif same_direction:
            consensus_type  = "discussed_agreed"
            final_direction = report_a.direction
            total_weight    = report_a.sub_confidence + report_b.sub_confidence
            final_confidence = (
                (report_a.sub_confidence ** 2 + report_b.sub_confidence ** 2)
                / total_weight
            )
            reasoning = (
                f"方向一致但信心差異大: 君君 {report_a.sub_confidence:.2f} "
                f"vs 阿豪 {report_b.sub_confidence:.2f}"
            )

        else:
            consensus_type = "dual_track"
            severity = {"bearish": 2, "neutral": 1, "bullish": 0}

            if severity.get(report_a.direction, 1) >= severity.get(report_b.direction, 1):
                final_direction  = report_a.direction
                final_confidence = report_a.sub_confidence * 0.8
            else:
                final_direction  = report_b.direction
                final_confidence = report_b.sub_confidence * 0.8

            reasoning = (
                f"大分歧採保守: 君君 {report_a.direction} | 阿豪 {report_b.direction}"
            )
            self.logger.warning(f"AU-03 雙人大分歧: {reasoning}")

        return consensus_type, final_direction, final_confidence, reasoning

    def _identify_disagreement(
        self, report_a: SubReport, report_b: SubReport
    ) -> Optional[str]:
        if report_a.direction != report_b.direction:
            return (
                f"方向分歧: 君君={report_a.direction} vs 阿豪={report_b.direction}"
            )
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 君君={report_a.sub_confidence:.2f} "
                f"vs 阿豪={report_b.sub_confidence:.2f}"
            )
        return None

    # ─── Health Status ────────────────────────────────────────────────────────

    def _update_health_status(self, debate: DebateResult) -> None:
        if debate.final_direction == "bearish" and debate.final_confidence > 0.6:
            new_status = "critical"
        elif debate.final_direction == "bearish" and debate.final_confidence > 0.4:
            new_status = "suspicious"
        elif debate.final_direction == "bearish":
            new_status = "degraded"
        else:
            new_status = "healthy"

        if new_status != self.last_health_status:
            self._publish_health_change(self.last_health_status, new_status, debate)
            self.last_health_status = new_status

    def _publish_health_change(
        self, old: str, new: str, debate: DebateResult
    ) -> None:
        if new not in ("suspicious", "critical"):
            return

        send_flash(FlashAlert(
            alert_id               = str(uuid.uuid4()),
            alert_type             = "DATA_OFFLINE" if new == "critical" else "ANOMALY_FLASH",
            alert_level            = "critical" if new == "critical" else "warning",
            sender                 = self.role_code,
            target_recipients      = ["怡姐", "老蘇", "阿成"],
            title                  = f"交易所健康狀態變化: {old} → {new}",
            message                = debate.combined_reasoning,
            related_data           = {"debate_id": debate.debate_id},
            timestamp              = datetime.now(timezone.utc),
            requires_acknowledgment = (new == "critical"),
        ))

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        latest_debate = self.debate_history[-1] if self.debate_history else None
        return {
            "manager":         self.role_name,
            "exchange_health": self.last_health_status,
            "latest_debate":   latest_debate.to_dict() if latest_debate else None,
            "debate_count":    len(self.debate_history),
            "consensus_rate":  self._calculate_consensus_rate(),
        }

    def _calculate_consensus_rate(self) -> float:
        if not self.debate_history:
            return 0.0
        agreed = sum(
            1 for d in self.debate_history if d.consensus_type == "agreed"
        )
        return agreed / len(self.debate_history)
