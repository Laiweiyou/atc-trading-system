# -*- coding: utf-8 -*-
"""ATC 老廖（TK 課主管）— 節奏評估課統籌。"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import CourseReport, DebateResult, SubReport
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.tempo.tk_01_tempo_indicators import TempoIndicators
from trading_system.squads.crypto.tempo.tk_02_tempo_memory import TempoMemory


class TempoSection:
    """老廖 — TK 課主管，統籌小施（TK-01）和華哥（TK-02），產出節奏建議。"""

    role_name = "老廖"
    role_code = "TK-Manager"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("老廖")

        self.tk_01 = TempoIndicators(gateway=self.gateway, bus=self.bus)
        self.tk_02 = TempoMemory(self.tk_01)

        self.report_interval  = 600
        self.last_report_time: Optional[float] = None

        self.reports_produced = 0
        self.recent_reports: deque[CourseReport] = deque(maxlen=20)
        self.tempo_history:  deque[dict]         = deque(maxlen=100)

        self.forced_caution_until: Optional[float] = None

        self.bus.subscribe("anomaly.detected",  self._on_anomaly,         role="老廖")
        self.bus.subscribe("tk.request_report", self._on_request_report,  role="老廖")

    # ─── Bus callbacks ────────────────────────────────────────────────────────

    def _on_anomaly(self, message) -> None:
        """收到異常 → 強制 cautious 至少 30 分鐘。"""
        anomaly = message.payload
        if not hasattr(anomaly, "severity"):
            return
        if anomaly.severity >= 0.7:
            self.forced_caution_until = time.time() + 1800
            self.logger.warning("異常觸發強制 cautious 30 分鐘")

    def _on_request_report(self, message) -> None:
        self.produce_course_report()

    # ─── Core ─────────────────────────────────────────────────────────────────

    def produce_course_report(self) -> CourseReport:
        """小施計算指標 + 華哥提供脈絡 + 老廖判斷 tempo → CourseReport → bus。"""
        indicators   = self.tk_01.compute_indicators()
        tempo_score  = self.tk_01.get_tempo_score()

        history_stats = self.tk_02.get_tempo_history_stats()
        transition    = (
            self.tk_02.detect_transition(tempo_score["score"])
            if indicators else {"transition_detected": False}
        )

        tempo_rec = self._determine_tempo(tempo_score, history_stats, transition)

        direction_map  = {"active": "bullish", "cautious": "neutral", "rest": "bearish"}
        course_direction  = direction_map[tempo_rec["tempo"]]
        course_confidence = tempo_rec["confidence"]

        tk01_sub = SubReport(
            role_name      = "小施",
            role_code      = "TK-01",
            direction      = course_direction,
            sub_confidence = course_confidence,
            reasoning      = (
                f"tempo_score={tempo_score['score']}, level={tempo_score['level']}"
            ),
            data_used      = (
                {"indicators": indicators, "tempo_score": tempo_score}
                if indicators else {}
            ),
            timestamp      = datetime.now(),
            staleness_flag = indicators is None,
        )

        tk02_sub = SubReport(
            role_name      = "華哥",
            role_code      = "TK-02",
            direction      = course_direction,
            sub_confidence = course_confidence * 0.9,
            reasoning      = (
                f"history_avg={history_stats.get('avg_score_recent', 'N/A')}, "
                f"transition={transition.get('type', 'none')}"
            ),
            data_used      = {"history_stats": history_stats, "transition": transition},
            timestamp      = datetime.now(),
            staleness_flag = not history_stats.get("available", False),
        )

        pseudo_debate = DebateResult(
            debate_id          = f"TK-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            report_a           = tk01_sub,
            report_b           = tk02_sub,
            consensus_type     = "agreed",
            final_direction    = course_direction,
            final_confidence   = course_confidence,
            combined_reasoning = tempo_rec["reasoning"],
            key_disagreement   = None,
            timestamp          = datetime.now(),
        )

        raw_alerts = [
            f"節奏轉換: {transition.get('type')}"
            if transition.get("transition_detected") else None
        ]
        flash_alerts = [a for a in raw_alerts if a is not None]

        report = CourseReport(
            course_name       = "節奏評估課",
            course_code       = "TK",
            manager_name      = self.role_name,
            debate_results    = [pseudo_debate],
            course_direction  = course_direction,
            course_confidence = course_confidence,
            freshness_grade   = "real_time" if indicators else "stale",
            data_health       = {
                "tk_01_indicators": indicators is not None,
                "tk_02_history":    history_stats.get("available", False),
                "forced_caution":   (
                    self.forced_caution_until is not None
                    and time.time() < self.forced_caution_until
                ),
            },
            flash_alerts = flash_alerts,
            self_review  = {
                "role":        self.role_name,
                "tempo":       tempo_rec["tempo"],
                "reasoning":   tempo_rec["reasoning"],
                "tempo_score": tempo_score.get("score") if indicators else None,
            },
            timestamp = datetime.now(),
        )

        self.bus.publish("report.tk", report, sender="老廖")
        self.reports_produced += 1
        self.last_report_time  = time.time()
        self.recent_reports.append(report)
        self.tempo_history.append({
            "tempo":     tempo_rec["tempo"],
            "timestamp": datetime.now(),
        })

        return report

    # ─── Tempo determination ──────────────────────────────────────────────────

    def _determine_tempo(
        self,
        tempo_score:   dict,
        history_stats: dict,
        transition:    dict,
    ) -> dict:
        """老廖核心判斷邏輯：active / cautious / rest。"""
        # 1. 強制 cautious 檢查
        if self.forced_caution_until and time.time() < self.forced_caution_until:
            return {
                "tempo":      "cautious",
                "confidence": 0.9,
                "reasoning":  "異常事件強制 cautious",
            }

        if not tempo_score or "score" not in tempo_score:
            return {
                "tempo":      "cautious",
                "confidence": 0.4,
                "reasoning":  "資料不足，預設保守",
            }

        score = tempo_score["score"]

        # 2. 極端高活躍 → rest（避免追高殺低）
        if score >= 85:
            return {
                "tempo":      "rest",
                "confidence": 0.7,
                "reasoning":  f"極端高活躍（{score}）+ 急速變化，暫避交易",
            }

        # 3. 高活躍 + 明確趨勢 → active
        if score >= 65:
            return {
                "tempo":      "active",
                "confidence": 0.7,
                "reasoning":  f"高活躍（{score}），市場節奏明確，可積極交易",
            }

        # 4. 中等活躍 → cautious
        if score >= 35:
            return {
                "tempo":      "cautious",
                "confidence": 0.6,
                "reasoning":  f"中等活躍（{score}），維持謹慎",
            }

        # 5. 低活躍 → rest
        return {
            "tempo":      "rest",
            "confidence": 0.7,
            "reasoning":  f"低活躍（{score}），市場無方向，暫停交易",
        }

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (self.last_report_time is None
                or now - self.last_report_time >= self.report_interval):
            self.produce_course_report()

    def get_section_status(self) -> dict:
        return {
            "manager":              self.role_name,
            "reports_produced":     self.reports_produced,
            "last_report_time":     self.last_report_time,
            "current_tempo":        (
                self.tempo_history[-1]["tempo"] if self.tempo_history else None
            ),
            "forced_caution_active": (
                self.forced_caution_until is not None
                and time.time() < self.forced_caution_until
            ),
        }
