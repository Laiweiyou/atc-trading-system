# -*- coding: utf-8 -*-
"""ATC 琳姐（GA 課主管）— 國際情勢課統籌。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import CourseReport, DebateResult
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class GlobalAffairsSection:
    """琳姐 — GA 課主管，統籌 GA-01 新聞組 + GA-02 監管組，產出課級 CourseReport。"""

    role_name = "琳姐"
    role_code = "GA-Manager"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("琳姐")

        from trading_system.squads.crypto.global_affairs.ga_01_news import NewsSection
        from trading_system.squads.crypto.global_affairs.ga_02_regulatory import RegulatorySection

        self.ga_01 = NewsSection(gateway=self.gateway, bus=self.bus)
        self.ga_02 = RegulatorySection(gateway=self.gateway, bus=self.bus)

        self.weights = {"ga_01": 0.65, "ga_02": 0.35}

        self.report_interval  = 1080
        self.last_report_time: Optional[float] = None

        self.reports_produced  = 0
        self.recent_reports:    deque[CourseReport] = deque(maxlen=20)
        self.anomaly_responses: deque[dict]         = deque(maxlen=50)

        self.bus.subscribe("ga.request_report", self._on_request_report, role="琳姐")
        self.bus.subscribe("anomaly.detected",  self._on_anomaly_detected, role="琳姐")

    # ─── Bus callbacks ────────────────────────────────────────────────────────

    def _on_request_report(self, message) -> None:
        self.logger.info("收到主動報告請求")
        self.produce_course_report()

    def _on_anomaly_detected(self, message) -> None:
        """收到 CA-03 的異常事件 → 僅高嚴重度時主動加查新聞並出加急報告。"""
        anomaly = message.payload

        if not hasattr(anomaly, "severity"):
            return
        if anomaly.severity < 0.7:
            return

        self.logger.warning(
            f"收到高嚴重度異常: {anomaly.event_type} sev={anomaly.severity:.2f}, 啟動加查新聞"
        )

        self.anomaly_responses.append({
            "anomaly_id":    anomaly.event_id,
            "anomaly_type":  anomaly.event_type,
            "severity":      anomaly.severity,
            "response_time": datetime.now(),
        })

        self.produce_course_report(triggered_by="anomaly")

    # ─── Core ─────────────────────────────────────────────────────────────────

    def produce_course_report(self, triggered_by: str = "scheduled") -> CourseReport:
        """執行兩組激辯並彙整課級 CourseReport，廣播到 report.ga。"""
        ga01_debate = self.ga_01.conduct_debate()
        ga02_debate = self.ga_02.conduct_debate()

        debates = [ga01_debate, ga02_debate]

        course_direction, course_confidence = self._compute_course_score(
            ga01_debate, ga02_debate
        )

        freshness = self._compute_freshness(debates)

        flash_alerts: list[str] = []
        if triggered_by == "anomaly":
            flash_alerts.insert(0, "本報告由異常事件觸發加急產出")
        if ga01_debate.consensus_type == "dual_track":
            flash_alerts.append(f"GA-01 新聞分析大分歧: {ga01_debate.key_disagreement}")
        if ga02_debate.consensus_type == "dual_track":
            flash_alerts.append(f"GA-02 監管分析大分歧: {ga02_debate.key_disagreement}")

        report = CourseReport(
            course_name       = "國際情勢課",
            course_code       = "GA",
            manager_name      = self.role_name,
            debate_results    = debates,
            course_direction  = course_direction,
            course_confidence = course_confidence,
            freshness_grade   = freshness,
            data_health       = {
                "ga_01_news":       not (ga01_debate.report_a.staleness_flag
                                         or ga01_debate.report_b.staleness_flag),
                "ga_02_regulatory": not (ga02_debate.report_a.staleness_flag
                                         or ga02_debate.report_b.staleness_flag),
                "triggered_by":     triggered_by,
            },
            flash_alerts = flash_alerts,
            self_review  = {
                "role":                    self.role_name,
                "my_call":                 f"{course_direction} @ {course_confidence:.2f}",
                "reasoning":               self._summarize_reasoning(ga01_debate, ga02_debate),
                "triggered_by":            triggered_by,
                "anomaly_responses_total": len(self.anomaly_responses),
            },
            timestamp = datetime.now(),
        )

        self.bus.publish("report.ga", report, sender="琳姐")
        self.reports_produced += 1
        self.last_report_time  = time.time()
        self.recent_reports.append(report)

        if triggered_by == "anomaly":
            send_flash(FlashAlert(
                alert_id                = str(uuid.uuid4()),
                alert_type              = "GA_CRITICAL",
                alert_level             = "warning",
                sender                  = "琳姐",
                target_recipients       = ["怡姐", "老廖", "老蘇"],
                title                   = "GA 加急報告（異常觸發）",
                message                 = f"課級判斷: {course_direction} @ {course_confidence:.2f}",
                related_data            = {"report_id": id(report)},
                timestamp               = datetime.now(),
                requires_acknowledgment = False,
            ))

        return report

    # ─── Scoring ──────────────────────────────────────────────────────────────

    def _compute_course_score(
        self, d01: DebateResult, d02: DebateResult
    ) -> tuple[str, float]:
        def dir_val(d: str) -> int:
            return {"bullish": 1, "bearish": -1, "neutral": 0}.get(d, 0)

        weights = dict(self.weights)

        if d01.report_a.staleness_flag or d01.report_b.staleness_flag:
            weights["ga_01"] = 0
        if d02.report_a.staleness_flag or d02.report_b.staleness_flag:
            weights["ga_02"] = 0

        total = sum(weights.values())
        if total == 0:
            return "neutral", 0.1

        weights = {k: v / total for k, v in weights.items()}

        composite = (
            dir_val(d01.final_direction) * d01.final_confidence * weights["ga_01"]
            + dir_val(d02.final_direction) * d02.final_confidence * weights["ga_02"]
        )

        if composite > 0.1:
            direction = "bullish"
        elif composite < -0.1:
            direction = "bearish"
        else:
            direction = "neutral"

        confidence = abs(composite)

        dual_count = sum(1 for d in [d01, d02] if d.consensus_type == "dual_track")
        if dual_count > 0:
            confidence *= (1 - 0.15 * dual_count)

        if d01.final_direction == d02.final_direction and d01.final_direction != "neutral":
            confidence = min(confidence + 0.1, 0.95)

        confidence = max(min(confidence, 0.95), 0.0)
        return direction, confidence

    def _compute_freshness(self, debates: list[DebateResult]) -> str:
        all_ts = []
        for d in debates:
            all_ts.append(d.report_a.timestamp)
            all_ts.append(d.report_b.timestamp)

        if not all_ts:
            return "stale"

        age = (datetime.now() - min(all_ts)).total_seconds()
        if age < 300:
            return "real_time"
        elif age < 1080:
            return "recent"
        elif age < 3600:
            return "delayed"
        return "stale"

    def _summarize_reasoning(self, ga01: DebateResult, ga02: DebateResult) -> str:
        return (
            f"新聞: {ga01.final_direction}({ga01.final_confidence:.2f}) | "
            f"監管: {ga02.final_direction}({ga02.final_confidence:.2f})"
        )

    # ─── Daily brief ──────────────────────────────────────────────────────────

    def produce_daily_brief(self) -> dict:
        """產出每日結構化日報基礎版（v4.1 新增功能）。"""
        latest = self.recent_reports[-1] if self.recent_reports else None

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "current_market_view": {
                "direction":  latest.course_direction if latest else "neutral",
                "confidence": latest.course_confidence if latest else 0,
                "reasoning":  latest.self_review.get("reasoning", "") if latest else "",
            },
            "anomaly_responses_24h": len([
                r for r in self.anomaly_responses
                if (datetime.now() - r["response_time"]).total_seconds() < 86400
            ]),
            "reports_produced_today": sum(
                1 for r in self.recent_reports
                if r.timestamp.date() == datetime.now().date()
            ),
            "consensus_rate": self._calculate_consensus_rate(),
        }

    def _calculate_consensus_rate(self) -> float:
        total  = 0
        agreed = 0
        for r in self.recent_reports:
            for d in r.debate_results:
                total  += 1
                if d.consensus_type == "agreed":
                    agreed += 1
        return agreed / total if total else 0.0

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (self.last_report_time is None
                or now - self.last_report_time >= self.report_interval):
            self.produce_course_report()

    def get_section_status(self) -> dict:
        return {
            "manager":           self.role_name,
            "reports_produced":  self.reports_produced,
            "anomaly_responses": len(self.anomaly_responses),
            "last_report_time":  self.last_report_time,
            "weights":           self.weights,
            "consensus_rate":    self._calculate_consensus_rate(),
        }
