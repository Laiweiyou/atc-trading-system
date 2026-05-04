# -*- coding: utf-8 -*-
"""ATC 靜姐（CA 課主管）— 技術分析課統籌。"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import (
    CourseReport,
    DebateResult,
    SubReport,
)
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class TechnicalSection:
    """靜姐 — CA 課主管，統籌 CA-01/02/03，產出課級 CourseReport。"""

    role_name = "靜姐"
    role_code = "CA-Manager"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("靜姐")

        from trading_system.squads.crypto.technical.ca_01_indicators import IndicatorSection
        from trading_system.squads.crypto.technical.ca_02_structure import StructureSection
        from trading_system.squads.crypto.technical.ca_03_volume import VolumeSection

        self.ca_01 = IndicatorSection(gateway=self.gateway, bus=self.bus)
        self.ca_02 = StructureSection(gateway=self.gateway, bus=self.bus)
        self.ca_03 = VolumeSection(gateway=self.gateway, bus=self.bus)

        self.weights = {"ca_01": 0.35, "ca_02": 0.40, "ca_03": 0.25}

        self.report_interval  = 60
        self.last_report_time: Optional[float] = None

        self.reports_produced = 0
        self.recent_reports: deque[CourseReport] = deque(maxlen=20)

        self.bus.subscribe("ca.request_report", self._on_request_report, role="靜姐")

    # ─── Bus callbacks ────────────────────────────────────────────────────────

    def _on_request_report(self, message) -> None:
        self.logger.info("收到主動報告請求")
        self.produce_course_report()

    # ─── Core ─────────────────────────────────────────────────────────────────

    def produce_course_report(self, symbol: str = "ETHUSDT") -> CourseReport:
        """CA-01 覆核 + CA-02/03 激辯 → 課級 CourseReport → bus。"""
        ca01_report = self.ca_01.compute_with_review(symbol)
        ca02_debate = self.ca_02.conduct_debate(symbol)
        ca03_debate = self.ca_03.conduct_debate(symbol)

        course_direction, course_confidence = self._compute_course_score(
            ca01_report, ca02_debate, ca03_debate
        )

        ca01_pseudo = self._wrap_ca01_as_debate(ca01_report)
        all_debates = [ca01_pseudo, ca02_debate, ca03_debate]

        freshness = self._compute_freshness(all_debates)

        flash_alerts: list[str] = []
        if ca02_debate.consensus_type == "dual_track":
            flash_alerts.append(f"CA-02 結構分析大分歧: {ca02_debate.key_disagreement}")
        if ca03_debate.consensus_type == "dual_track":
            flash_alerts.append(f"CA-03 量能分析大分歧: {ca03_debate.key_disagreement}")

        anomaly_count = ca03_debate.report_a.data_used.get("anomaly_count", 0)
        if anomaly_count > 0:
            flash_alerts.append(f"CA-03 偵測到 {anomaly_count} 個異常事件")

        report = CourseReport(
            course_name      = "技術分析課",
            course_code      = "CA",
            manager_name     = self.role_name,
            debate_results   = all_debates,
            course_direction = course_direction,
            course_confidence= course_confidence,
            freshness_grade  = freshness,
            data_health      = {
                "ca_01_indicators": not ca01_report.staleness_flag,
                "ca_02_structure":  not (ca02_debate.report_a.staleness_flag
                                         or ca02_debate.report_b.staleness_flag),
                "ca_03_volume":     not (ca03_debate.report_a.staleness_flag
                                         or ca03_debate.report_b.staleness_flag),
                "anomaly_events_count": anomaly_count,
            },
            flash_alerts = flash_alerts,
            self_review  = {
                "role":               self.role_name,
                "my_call":            f"{course_direction} @ {course_confidence:.2f}",
                "reasoning":          self._summarize_reasoning(ca01_report, ca02_debate, ca03_debate),
                "anomalies_detected": anomaly_count,
            },
            timestamp = datetime.now(),
        )

        self.bus.publish("report.ca", report, sender="靜姐")
        self.reports_produced += 1
        self.last_report_time  = time.time()
        self.recent_reports.append(report)

        return report

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _wrap_ca01_as_debate(self, sub_report: SubReport) -> DebateResult:
        """把 CA-01 的單一 SubReport 包裝成 DebateResult 格式（統一介面）。"""
        return DebateResult(
            debate_id          = f"CA-01-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            report_a           = sub_report,
            report_b           = sub_report,
            consensus_type     = "agreed",
            final_direction    = sub_report.direction,
            final_confidence   = sub_report.sub_confidence,
            combined_reasoning = sub_report.reasoning,
            key_disagreement   = None,
            timestamp          = datetime.now(),
        )

    def _compute_course_score(
        self,
        ca01_report: SubReport,
        ca02_debate: DebateResult,
        ca03_debate: DebateResult,
    ) -> tuple[str, float]:
        def dir_val(d: str) -> int:
            return {"bullish": 1, "bearish": -1, "neutral": 0}.get(d, 0)

        weights = dict(self.weights)

        if ca01_report.staleness_flag:
            weights["ca_01"] = 0
        if ca02_debate.report_a.staleness_flag or ca02_debate.report_b.staleness_flag:
            weights["ca_02"] = 0
        if ca03_debate.report_a.staleness_flag or ca03_debate.report_b.staleness_flag:
            weights["ca_03"] = 0

        total = sum(weights.values())
        if total == 0:
            return "neutral", 0.1

        weights = {k: v / total for k, v in weights.items()}

        composite = (
            dir_val(ca01_report.direction) * ca01_report.sub_confidence * weights["ca_01"]
            + dir_val(ca02_debate.final_direction) * ca02_debate.final_confidence * weights["ca_02"]
            + dir_val(ca03_debate.final_direction) * ca03_debate.final_confidence * weights["ca_03"]
        )

        if composite > 0.1:
            direction = "bullish"
        elif composite < -0.1:
            direction = "bearish"
        else:
            direction = "neutral"

        confidence = abs(composite)

        # dual_track 懲罰（CA-02 和 CA-03 才有激辯，最多 2 個）
        dual_count = sum(
            1 for d in [ca02_debate, ca03_debate]
            if d.consensus_type == "dual_track"
        )
        if dual_count > 0:
            confidence *= (1 - 0.15 * dual_count)

        # 三組方向一致加成
        if (ca01_report.direction == ca02_debate.final_direction
                == ca03_debate.final_direction
                and ca01_report.direction != "neutral"):
            confidence = min(confidence + 0.1, 0.95)

        confidence = max(min(confidence, 0.95), 0.0)
        return direction, confidence

    def _compute_freshness(self, debates: list[DebateResult]) -> str:
        all_ts = []
        for d in debates:
            all_ts.append(d.report_a.timestamp)
            if d.report_b is not d.report_a:
                all_ts.append(d.report_b.timestamp)

        if not all_ts:
            return "stale"

        age = (datetime.now() - min(all_ts)).total_seconds()
        if age < 60:
            return "real_time"
        elif age < 300:
            return "recent"
        elif age < 1800:
            return "delayed"
        return "stale"

    def _summarize_reasoning(
        self,
        ca01: SubReport,
        ca02: DebateResult,
        ca03: DebateResult,
    ) -> str:
        return (
            f"指標: {ca01.direction}({ca01.sub_confidence:.2f}) | "
            f"結構: {ca02.final_direction}({ca02.final_confidence:.2f}) | "
            f"量能: {ca03.final_direction}({ca03.final_confidence:.2f})"
        )

    # ─── Lifecycle ────────────────────────────────────────────────────────────

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
            "latest_report":    (
                self.recent_reports[-1].to_dict() if self.recent_reports else None
            ),
        }
