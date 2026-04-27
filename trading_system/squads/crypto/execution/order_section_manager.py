# -*- coding: utf-8 -*-
"""ATC EX-Manager 宏哥（下單課主管）— 統籌小慧/阿成/芬姐，監督執行品質。"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from trading_system.common.api_gateway import get_gateway
from trading_system.common.feedback_models import SelfReview
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

if TYPE_CHECKING:
    from trading_system.squads.crypto.execution.ex_01_normal_order import NormalOrderExecutor
    from trading_system.squads.crypto.execution.ex_02_emergency import EmergencyExecutor
    from trading_system.squads.crypto.execution.ex_03_connection import ConnectionMaintainer

_ROLE_NAME = "宏哥"
_ROLE_CODE  = "EX-Manager"

# 連線判斷閾值
_CONN_MAX_CONSECUTIVE_FAIL  = 3
_CONN_MAX_HEARTBEAT_AGE_SEC = 60
_CONN_MIN_SUCCESS_RATE      = 0.5

# 執行品質門檻（至少 5 筆觀察後才評估）
_MIN_OBSERVATIONS_FOR_QUALITY = 5
_MIN_SUCCESS_RATE_QUALITY     = 0.8


class OrderSectionManager:
    """
    EX-Manager 宏哥：下單課主管。

    職責：
      - 觀察 execution.result，彙整全課執行品質統計
      - 透過 get_section_status() 提供其他課查詢
      - produce_self_review() 產出課級自評
      - emergency_dispatch() 主動觸發阿成的緊急應變
    """

    def __init__(
        self,
        ex01: "NormalOrderExecutor",
        ex02: "EmergencyExecutor",
        ex03: "ConnectionMaintainer",
    ) -> None:
        self.gateway = get_gateway()
        self.bus     = get_bus()
        self.logger  = get_logger(_ROLE_NAME)

        self.ex01 = ex01
        self.ex02 = ex02
        self.ex03 = ex03

        self.bus.subscribe("execution.result", self._on_execution_result, role=_ROLE_CODE)

        self.section_stats: dict = {
            "total_decisions_received":   0,
            "executions_dispatched":      0,
            "execution_results_observed": 0,
            "successful_executions":      0,
            "failed_executions":          0,
            "average_slippage_bps":       0.0,
            "section_uptime_start":       datetime.now(timezone.utc),
        }

        self.recent_results: deque = deque(maxlen=50)

    # ─── Bus Callback ─────────────────────────────────────────────────────────

    def _on_execution_result(self, message) -> None:
        """觀察執行結果，更新課級統計。"""
        payload = message.payload

        # 接受 ExecutionResult 物件或含 'status' 的 dict
        if hasattr(payload, "status"):
            result = payload
        elif isinstance(payload, dict) and "status" in payload:
            # 輕量支援 dict 格式（後向兼容）
            result = type("_R", (), {
                "status":              payload.get("status"),
                "actual_slippage_pct": payload.get("actual_slippage_pct"),
                "error_message":       payload.get("error_message"),
            })()
        else:
            return

        self.section_stats["execution_results_observed"] += 1

        if result.status == "FILLED":
            self.section_stats["successful_executions"] += 1
            slippage_pct = result.actual_slippage_pct
            if slippage_pct is not None:
                count   = self.section_stats["successful_executions"]
                old_avg = self.section_stats["average_slippage_bps"]
                new_avg = (old_avg * (count - 1) + slippage_pct * 100) / count
                self.section_stats["average_slippage_bps"] = round(new_avg, 4)
        elif result.status == "FAILED":
            self.section_stats["failed_executions"] += 1
            self.logger.warning(f"執行失敗觀察: {result.error_message}")

        self.recent_results.append(payload)

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_section_status(self) -> dict:
        """提供其他課查詢下單課完整狀態。"""
        conn_health = self.ex03.get_health_status()
        ex01_stats  = self.ex01.get_stats()
        ex02_stats  = {
            "flash_crash_mode":       self.ex02.flash_crash_mode,
            "emergency_actions_count": self.ex02.emergency_actions_count,
            "recent_emergencies":     list(self.ex02.emergency_history)[-3:],
        }

        overall = self._compute_overall_health(conn_health, ex01_stats, ex02_stats)

        return {
            "manager":           _ROLE_NAME,
            "section_stats":     dict(self.section_stats),
            "connection_health": conn_health,
            "normal_executor":   ex01_stats,
            "emergency_executor": ex02_stats,
            "overall_health":    overall,
        }

    def _compute_overall_health(
        self,
        conn_health: dict,
        ex01_stats:  dict,
        ex02_stats:  dict,
    ) -> str:
        # 連線健康判斷
        consecutive_fail = conn_health.get("consecutive_failures", 0)
        heartbeat_age    = conn_health.get("last_heartbeat_age_seconds", -1)
        success_rate_c   = conn_health.get("success_rate", 1.0)

        is_connected = (
            consecutive_fail < _CONN_MAX_CONSECUTIVE_FAIL
            and (heartbeat_age < 0 or heartbeat_age < _CONN_MAX_HEARTBEAT_AGE_SEC)
            and success_rate_c >= _CONN_MIN_SUCCESS_RATE
        )
        if not is_connected:
            return "critical"

        # 閃崩模式
        if ex02_stats.get("flash_crash_mode"):
            return "degraded"

        # 執行成功率過低
        observed = self.section_stats["execution_results_observed"]
        if observed >= _MIN_OBSERVATIONS_FOR_QUALITY:
            success = self.section_stats["successful_executions"]
            if success / observed < _MIN_SUCCESS_RATE_QUALITY:
                return "degraded"

        return "healthy"

    # ─── Self Review ──────────────────────────────────────────────────────────

    def produce_self_review(self) -> SelfReview:
        """產出課級 SelfReview，並廣播到 feedback.submitted。"""
        status = self.get_section_status()
        observed = self.section_stats["execution_results_observed"]
        success  = self.section_stats["successful_executions"]

        review = SelfReview(
            role_name=_ROLE_NAME,
            role_code=_ROLE_CODE,
            work_type="執行部統籌",
            timestamp=datetime.now(timezone.utc),
            my_call=f"section_health={status['overall_health']}",
            confidence_at_time=(
                1.0 if status["overall_health"] == "healthy"
                else 0.5 if status["overall_health"] == "degraded"
                else 0.3
            ),
            reasoning=(
                f"連線consecutive_failures={status['connection_health'].get('consecutive_failures', 0)}, "
                f"執行成功率={success}/{observed}, "
                f"閃崩模式={status['emergency_executor']['flash_crash_mode']}"
            ),
            data_used={
                "connection_health": status["connection_health"],
                "section_stats":     status["section_stats"],
            },
        )

        self.bus.publish("feedback.submitted", review, sender=_ROLE_CODE)
        self.logger.info(
            f"self_review 產出: health={status['overall_health']}, "
            f"confidence={review.confidence_at_time}"
        )
        return review

    # ─── Emergency Dispatch ───────────────────────────────────────────────────

    def emergency_dispatch(self, reason: str) -> None:
        """主動命令阿成執行緊急應變（例如收到 ORANGE 警戒時）。"""
        self.logger.warning(f"宏哥手動觸發緊急應變: {reason}")
        self.ex02.emergency_close_all(reason)
