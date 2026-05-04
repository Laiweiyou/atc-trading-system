# -*- coding: utf-8 -*-
"""ATC IO-Manager 婷姐（市場情報課主管）— 統籌 IO-01/02/03 三組激辯。"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import CourseReport
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class IntelligenceSection:
    role_name = "婷姐"
    role_code = "IO-Manager"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("婷姐")

        from trading_system.squads.crypto.intelligence.io_01_capital_flow import CapitalFlowSection
        from trading_system.squads.crypto.intelligence.io_02_sentiment import SentimentSection
        from trading_system.squads.crypto.intelligence.io_03_onchain import OnChainSection

        self.io_01 = CapitalFlowSection(gateway=self.gateway, bus=self.bus)
        self.io_02 = SentimentSection(gateway=self.gateway, bus=self.bus)
        self.io_03 = OnChainSection(gateway=self.gateway, bus=self.bus)

        self.weights = {
            "io_01": 0.50,
            "io_02": 0.15,
            "io_03": 0.35,
        }

        self.report_interval  = 300
        self.last_report_time: Optional[float] = None

        self.reports_produced = 0
        self.recent_reports: deque[CourseReport] = deque(maxlen=20)

        self.bus.subscribe("io.request_report", self._on_request_report, role="婷姐")

    # ─── Subscription handler ─────────────────────────────────────────────────

    def _on_request_report(self, message) -> None:
        self.logger.info("收到主動報告請求")
        self.produce_course_report()

    # ─── Core report ──────────────────────────────────────────────────────────

    def produce_course_report(self) -> CourseReport:
        """執行三組激辯並彙整為課級 CourseReport，廣播到 report.io。"""
        debate_01 = self.io_01.conduct_debate()
        debate_02 = self.io_02.conduct_debate()
        debate_03 = self.io_03.conduct_debate()

        debates = [debate_01, debate_02, debate_03]

        course_direction, course_confidence = self._compute_course_score(
            debate_01, debate_02, debate_03
        )

        freshness   = self._compute_freshness(debates)
        data_health = self._compute_data_health(debates)

        flash_alerts = []
        for debate, name in zip(debates, ["IO-01", "IO-02", "IO-03"]):
            if debate.consensus_type == "dual_track":
                flash_alerts.append(f"{name} 雙人大分歧: {debate.key_disagreement}")

        report = CourseReport(
            course_name       = "市場情報課",
            course_code       = "IO",
            manager_name      = "婷姐",
            debate_results    = debates,
            course_direction  = course_direction,
            course_confidence = course_confidence,
            freshness_grade   = freshness,
            data_health       = data_health,
            flash_alerts      = flash_alerts,
            self_review       = {
                "role":             "婷姐",
                "my_call":          f"{course_direction} @ {course_confidence:.2f}",
                "reasoning":        self._summarize_reasoning(debates),
                "consensus_count":  sum(1 for d in debates if d.consensus_type == "agreed"),
                "dual_track_count": len(flash_alerts),
            },
            timestamp = datetime.now(),
        )

        self.bus.publish("report.io", report, sender="婷姐")

        self.reports_produced    += 1
        self.last_report_time     = time.time()
        self.recent_reports.append(report)

        return report

    # ─── Score computation ────────────────────────────────────────────────────

    def _compute_course_score(self, d01, d02, d03) -> tuple[str, float]:
        """計算課級方向與信心度（含 staleness 過濾、dual_track 懲罰、一致性加成）。"""
        def dir_val(direction: str) -> int:
            return {"bullish": 1, "bearish": -1, "neutral": 0}[direction]

        # Staleness 過濾：任一 sub-report 過期 → 該組權重歸零
        weights = dict(self.weights)
        if d01.report_a.staleness_flag or d01.report_b.staleness_flag:
            weights["io_01"] = 0
        if d02.report_a.staleness_flag or d02.report_b.staleness_flag:
            weights["io_02"] = 0
        if d03.report_a.staleness_flag or d03.report_b.staleness_flag:
            weights["io_03"] = 0

        total = sum(weights.values())
        if total == 0:
            return "neutral", 0.1

        weights = {k: v / total for k, v in weights.items()}

        composite = (
            dir_val(d01.final_direction) * d01.final_confidence * weights["io_01"]
            + dir_val(d02.final_direction) * d02.final_confidence * weights["io_02"]
            + dir_val(d03.final_direction) * d03.final_confidence * weights["io_03"]
        )

        if composite > 0.1:
            direction = "bullish"
        elif composite < -0.1:
            direction = "bearish"
        else:
            direction = "neutral"

        confidence = abs(composite)

        # Dual_track 懲罰
        dual_track_count = sum(1 for d in [d01, d02, d03] if d.consensus_type == "dual_track")
        if dual_track_count > 0:
            confidence *= (1 - 0.2 * dual_track_count / 3)

        # 三組方向全一致加成
        directions = [d01.final_direction, d02.final_direction, d03.final_direction]
        if len(set(directions)) == 1 and directions[0] != "neutral":
            confidence = min(confidence + 0.1, 0.95)

        confidence = max(min(confidence, 0.95), 0.0)

        return direction, confidence

    # ─── Freshness & health ───────────────────────────────────────────────────

    def _compute_freshness(self, debates: list) -> str:
        all_timestamps = []
        for d in debates:
            all_timestamps.append(d.report_a.timestamp)
            all_timestamps.append(d.report_b.timestamp)

        if not all_timestamps:
            return "stale"

        oldest      = min(all_timestamps)
        age_seconds = (datetime.now() - oldest).total_seconds()

        if age_seconds < 60:
            return "real_time"
        elif age_seconds < 300:
            return "recent"
        elif age_seconds < 1800:
            return "delayed"
        else:
            return "stale"

    def _compute_data_health(self, debates: list) -> dict:
        return {
            "io_01_funding_data":    not (debates[0].report_a.staleness_flag or debates[0].report_b.staleness_flag),
            "io_02_sentiment_data":  not (debates[1].report_a.staleness_flag or debates[1].report_b.staleness_flag),
            "io_03_onchain_data":    not (debates[2].report_a.staleness_flag or debates[2].report_b.staleness_flag),
            "all_debates_completed": all(d is not None for d in debates),
        }

    def _summarize_reasoning(self, debates: list) -> str:
        summaries = []
        for d, name in zip(debates, ["IO-01 資金流", "IO-02 情緒", "IO-03 鏈上"]):
            summaries.append(f"{name}: {d.final_direction}({d.final_confidence:.2f})")
        return " | ".join(summaries)

    # ─── Cycle & status ───────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (self.last_report_time is None
                or now - self.last_report_time >= self.report_interval):
            self.produce_course_report()

    def get_section_status(self) -> dict:
        return {
            "manager":          self.role_name,
            "reports_produced": self.reports_produced,
            "last_report_time": self.last_report_time,
            "weights":          self.weights,
            "latest_report":    self.recent_reports[-1].to_dict() if self.recent_reports else None,
        }
