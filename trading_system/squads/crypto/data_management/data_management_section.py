# -*- coding: utf-8 -*-
"""ATC DM-Manager 小蔡（資料管理課主管）— 資料品質與同步監督。"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.data_management.dm_02_quality_check import DataQualitySection
from trading_system.squads.crypto.data_management.dm_03_timestamp_sync import TimestampSynchronizer

# 接受來自蓉蓉/小方/琪琪 的 FlashAlert（role_name 或 role_code）
_DM_SENDERS = frozenset(["蓉蓉", "小方", "琪琪", "DM-02a", "DM-02b", "DM-03"])


class DataManagementSection:
    """
    小蔡 DM-Manager：資料管理課統籌主管。

    職責：
      - 管理 DM-02（蓉蓉+小方）與 DM-03（琪琪）
      - 訂閱 alert.flash，統計嚴重警報
      - produce_health_report() → 綜合 API 狀態 + 資料新鮮度
      - run_cycle() → 每 300 秒觸發一次健康報告
    """

    role_name = "小蔡"
    role_code = "DM-Manager"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger(self.role_name)

        self.dm02_section = DataQualitySection(gateway=self.gateway, bus=self.bus)
        self.dm03         = TimestampSynchronizer(gateway=self.gateway, bus=self.bus)

        # 訂閱 FlashAlert
        self.bus.subscribe("alert.flash", self._on_alert, role=self.role_code)

        self.report_interval:          int             = 300
        self.last_report_time:         Optional[float] = None
        self.reports_produced:         int             = 0
        self.critical_alerts_observed: int             = 0
        self.recent_alerts:            deque[dict]     = deque(maxlen=50)

    # ─── Alert Handler ────────────────────────────────────────────────────────

    def _on_alert(self, message) -> None:
        sender  = message.sender
        payload = message.payload if isinstance(message.payload, dict) else {}

        if sender not in _DM_SENDERS:
            return

        self.recent_alerts.append(payload)

        if payload.get("alert_level") == "critical":
            self.critical_alerts_observed += 1
            self.logger.warning(
                f"收到嚴重警報 from {sender}: {payload.get('title', '')}"
            )

    # ─── Health Report ────────────────────────────────────────────────────────

    def produce_health_report(self) -> dict:
        """產生綜合健康報告並廣播至 report.dm。"""
        api_stats  = self.gateway.get_stats()
        api_health = self.gateway.health_check()
        freshness  = self.dm03.get_freshness_summary()

        score  = self._compute_health_score(api_stats, api_health, freshness)
        status = self._classify_health(score)

        report = {
            "manager":                   self.role_name,
            "role_code":                 self.role_code,
            "timestamp":                 datetime.now(timezone.utc).isoformat(),
            "health_score":              score,
            "health_status":             status,
            "api_stats":                 api_stats,
            "api_health":                api_health,
            "freshness_summary":         freshness,
            "reports_produced":          self.reports_produced + 1,
            "critical_alerts_observed":  self.critical_alerts_observed,
            "recent_alert_count":        len(self.recent_alerts),
        }

        self.bus.publish("report.dm", report, sender=self.role_code)
        self.reports_produced    += 1
        self.last_report_time     = time.time()

        self.logger.info(
            f"健康報告：score={score:.1f} status={status}"
        )
        return report

    # ─── Scoring ──────────────────────────────────────────────────────────────

    def _compute_health_score(
        self,
        api_stats:  dict,
        api_health: dict,
        freshness:  dict,
    ) -> float:
        score = 100.0

        # API 整體健康
        if not api_health.get("healthy", True):
            score -= 30

        # 錯誤率
        total    = api_stats.get("total_requests", 0)
        errors   = api_stats.get("error_count", 0)
        error_rate = errors / total if total > 0 else 0.0
        if error_rate > 0.10:
            score -= 20
        elif error_rate > 0.03:
            score -= 10

        # 資料新鮮度（每課）
        for _course, info in freshness.items():
            grade = info.get("freshness_grade", "stale")
            if grade == "stale":
                score -= 8
            elif grade == "delayed":
                score -= 4

        # 嚴重警報
        if self.critical_alerts_observed > 5:
            score -= 20
        elif self.critical_alerts_observed > 2:
            score -= 10

        if len(self.recent_alerts) > 10:
            score -= 5

        return max(0.0, score)

    def _classify_health(self, score: float) -> str:
        if score >= 80:
            return "healthy"
        elif score >= 60:
            return "acceptable"
        elif score >= 40:
            return "degraded"
        else:
            return "critical"

    # ─── Cycle ────────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        """若距上次報告已超過 report_interval 秒（或從未報告），觸發健康報告。"""
        now = time.time()
        if self.last_report_time is None or (now - self.last_report_time) >= self.report_interval:
            self.produce_health_report()

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_section_status(self) -> dict:
        return {
            "manager":                   self.role_name,
            "role_code":                 self.role_code,
            "reports_produced":          self.reports_produced,
            "critical_alerts_observed":  self.critical_alerts_observed,
            "last_report_time":          self.last_report_time,
            "freshness":                 self.dm03.get_freshness_summary(),
        }
