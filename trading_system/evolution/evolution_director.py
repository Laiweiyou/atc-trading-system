# -*- coding: utf-8 -*-
"""ATC Evolution Director（進化部經理）— 大劉，角色準確率監控與調整提案。"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class EvolutionDirector:
    role_name = "大劉"
    role_code = "TO-Manager"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("大劉")

        self.bus.subscribe("hindsight.verified",  self._on_hindsight, role="大劉")
        self.bus.subscribe("baseline.comparison", self._on_baseline,  role="大劉")

        # 冷卻期管理 role_code → cooldown_until timestamp (float)
        self.role_cooldowns:          dict[str, float] = {}
        self.adjustment_cooldown_days: int              = 7
        self.role_cooldown_seconds:    int              = 7 * 86400

        # 提案歷史
        self.adjustments_proposed:   deque = deque(maxlen=200)
        self.suggestions_proposed:   deque = deque(maxlen=200)
        self.adjustments_rolled_back: int  = 0

        # 大劉自我約束
        self.consecutive_invalid_adjustments: int   = 0
        self.self_weight_multiplier:          float = 1.0

        # 角色準確率快取 role_code → list of {"result", "timestamp"}
        self.role_accuracy_buffer: dict[str, list] = {}

        # 評估週期
        self.evaluation_interval:    int              = 86400
        self.last_evaluation_time:   Optional[float]  = None

        # 門檻
        self.min_sample_size:               int   = 20
        self.adjustment_trigger_threshold:  float = 0.50

    # ─── Bus Callbacks ────────────────────────────────────────────────────────

    def _on_hindsight(self, message) -> None:
        review = message.payload
        if not hasattr(review, "role_code"):
            return

        result = getattr(review, "hindsight_correct", None)
        if result not in ("correct", "incorrect", "partial_correct"):
            return

        role = review.role_code
        if role not in self.role_accuracy_buffer:
            self.role_accuracy_buffer[role] = []

        self.role_accuracy_buffer[role].append({
            "result":    result,
            "timestamp": time.time(),
        })

        # 保留最近 100 筆
        if len(self.role_accuracy_buffer[role]) > 100:
            self.role_accuracy_buffer[role] = self.role_accuracy_buffer[role][-100:]

    def _on_baseline(self, message) -> None:
        pass

    # ─── 評估 ─────────────────────────────────────────────────────────────────

    def evaluate_all_roles(self) -> list:
        """每日評估所有角色，找出需要調整的；回傳本次產出的提案清單。"""
        proposals = []
        now = time.time()

        for role_code, history in self.role_accuracy_buffer.items():
            if len(history) < self.min_sample_size:
                continue

            cooldown_until = self.role_cooldowns.get(role_code, 0)
            if now < cooldown_until:
                continue

            recent = history[-30:]
            correct = sum(1 for h in recent if h["result"] == "correct")
            partial = sum(1 for h in recent if h["result"] == "partial_correct")
            weighted_accuracy = (correct + partial * 0.5) / len(recent)

            if weighted_accuracy < self.adjustment_trigger_threshold:
                proposal = self._build_proposal(role_code, weighted_accuracy, len(recent))
                proposals.append(proposal)

        for p in proposals:
            if p["type"] == "ADJUSTMENT":
                self._execute_adjustment(p)
            else:
                self._submit_suggestion(p)

        return proposals

    def _build_proposal(self, role_code: str, accuracy: float, sample_size: int) -> dict:
        if accuracy < 0.35:
            return {
                "type":             "SUGGESTION",
                "target_role":      role_code,
                "current_accuracy": accuracy,
                "sample_size":      sample_size,
                "recommendation":   f"建議大幅檢討 {role_code} 的判斷邏輯，可能需要重寫部分判斷規則",
                "proposed_action":  "manual_review",
                "timestamp":        datetime.now(),
            }
        # 0.35 ~ 0.50
        return {
            "type":                 "ADJUSTMENT",
            "target_role":          role_code,
            "current_accuracy":     accuracy,
            "sample_size":          sample_size,
            "recommendation":       f"{role_code} 準確率 {accuracy:.2f}，建議微調觸發門檻",
            "proposed_action":      "tighten_thresholds",
            "adjustment_magnitude": 0.1,
            "timestamp":            datetime.now(),
        }

    def _execute_adjustment(self, proposal: dict) -> None:
        role_code = proposal["target_role"]
        self.role_cooldowns[role_code] = time.time() + self.role_cooldown_seconds

        proposal["executed_at"] = datetime.now()
        proposal["status"]      = "EXECUTED"
        proposal["rollback_at"] = time.time() + self.role_cooldown_seconds
        self.adjustments_proposed.append(proposal)

        self.bus.publish("evolution.adjustment", proposal, sender="大劉")
        self.logger.info(
            f"自動執行調整: {role_code} 準確率 {proposal['current_accuracy']:.2f}"
        )

    def _submit_suggestion(self, proposal: dict) -> None:
        proposal["status"] = "PENDING_APPROVAL"
        self.suggestions_proposed.append(proposal)

        self.bus.publish("evolution.suggestion", proposal, sender="大劉")
        self.logger.warning(
            f"提出建議（需人類審核）: {proposal['target_role']} "
            f"準確率 {proposal['current_accuracy']:.2f}"
        )

    # ─── 效果檢查 ─────────────────────────────────────────────────────────────

    def check_adjustment_effects(self) -> None:
        """檢查過去調整的效果，必要時回滾。"""
        now = time.time()

        for adjustment in list(self.adjustments_proposed):
            if adjustment.get("status") != "EXECUTED":
                continue

            rollback_at = adjustment.get("rollback_at", 0)
            if now < rollback_at:
                continue

            role_code       = adjustment["target_role"]
            current_history = self.role_accuracy_buffer.get(role_code, [])

            executed_at_dt  = adjustment.get("executed_at", datetime.now())
            adjustment_time = executed_at_dt.timestamp()

            after_adjustment = [
                h for h in current_history
                if h["timestamp"] >= adjustment_time
            ]

            if len(after_adjustment) < 10:
                continue

            correct = sum(1 for h in after_adjustment if h["result"] == "correct")
            partial = sum(1 for h in after_adjustment if h["result"] == "partial_correct")
            new_accuracy = (correct + partial * 0.5) / len(after_adjustment)

            old_accuracy = adjustment["current_accuracy"]
            improvement  = new_accuracy - old_accuracy

            if improvement < 0.05:
                self._rollback_adjustment(adjustment, new_accuracy)
            else:
                adjustment["status"]      = "CONFIRMED"
                adjustment["new_accuracy"] = new_accuracy
                adjustment["improvement"]  = improvement
                self.consecutive_invalid_adjustments = 0

    def _rollback_adjustment(self, adjustment: dict, new_accuracy: float) -> None:
        adjustment["status"]         = "ROLLED_BACK"
        adjustment["new_accuracy"]   = new_accuracy
        adjustment["rollback_reason"] = (
            f"改善不足（{new_accuracy:.2f} vs {adjustment['current_accuracy']:.2f}）"
        )

        self.adjustments_rolled_back          += 1
        self.consecutive_invalid_adjustments  += 1

        if self.consecutive_invalid_adjustments >= 5:
            self.self_weight_multiplier = max(
                0.5, self.self_weight_multiplier - 0.1
            )
            self.logger.warning(
                f"連續 {self.consecutive_invalid_adjustments} 次無效調整，"
                f"自我降權至 {self.self_weight_multiplier}"
            )

        self.bus.publish("evolution.rollback", adjustment, sender="大劉")
        self.logger.info(f"回滾調整: {adjustment['target_role']}")

    # ─── 主循環 ───────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (self.last_evaluation_time is None
                or now - self.last_evaluation_time >= self.evaluation_interval):
            self.evaluate_all_roles()
            self.check_adjustment_effects()
            self.last_evaluation_time = now

    # ─── 狀態查詢 ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "role":                        self.role_name,
            "adjustments_proposed_total":  len(self.adjustments_proposed),
            "suggestions_proposed_total":  len(self.suggestions_proposed),
            "adjustments_rolled_back":     self.adjustments_rolled_back,
            "consecutive_invalid":         self.consecutive_invalid_adjustments,
            "self_weight":                 self.self_weight_multiplier,
            "active_cooldowns":            sum(
                1 for t in self.role_cooldowns.values() if time.time() < t
            ),
        }
