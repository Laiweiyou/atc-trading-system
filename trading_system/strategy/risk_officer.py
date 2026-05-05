# -*- coding: utf-8 -*-
"""ATC 怡姐（風控官）— 敏敏+阿彭雙視角評估，產出 RiskAssessment。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.config import MAX_POSITION_USD
from trading_system.common.data_models import RiskAssessment, TradingProposal
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class RiskOfficer:
    role_name = "怡姐"
    role_code = "Risk-Officer"

    # ─── 警戒等級 → 倉位因子 ─────────────────────────────────────────────────────
    _ALERT_POSITION_FACTOR: dict[str, float] = {
        "GREEN":  1.0,
        "YELLOW": 0.7,
        "ORANGE": 0.4,
        "RED":    0.0,
    }

    # ─── 警戒等級 → 嚴重度分值 ───────────────────────────────────────────────────
    _ALERT_SEVERITY: dict[str, float] = {
        "GREEN":  0.0,
        "YELLOW": 0.2,
        "ORANGE": 0.5,
        "RED":    1.0,
    }

    # ─── 內部風險門檻 ─────────────────────────────────────────────────────────────
    _MIN_STOP_PCT   = 0.005   # 止損距離 < 0.5% of entry → +0.5
    _MIN_RR_RATIO   = 1.0     # 回報/風險 < 1.0 → +0.3
    _MIN_SCORE_CONF = 0.3     # |composite_score| < 0.3 → +0.2

    # ─── 外部風險門檻 ─────────────────────────────────────────────────────────────
    _CONSEC_LOSS_HIGH   = 5     # 連敗 ≥5 → +0.4
    _CONSEC_LOSS_MED    = 3     # 連敗 ≥3 → +0.2
    _ANOMALY_HIGH       = 3     # 近期 ≥3 → +0.4
    _ANOMALY_LOW        = 1     # 近期 ≥1 → +0.2
    _ANOMALY_WINDOW_SEC = 1800  # 30 分鐘視窗

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("怡姐")

        # ─ 外部狀態（由訂閱更新）
        self.current_alert_level: str                    = "GREEN"
        self.consecutive_losses:  int                    = 0
        self.recent_anomalies:    deque[tuple[float, float]] = deque(maxlen=50)

        # ─ 統計
        self.assessments_total    = 0
        self.assessments_approved = 0
        self.assessments_modified = 0
        self.assessments_rejected = 0
        self.recent_assessments:  deque[RiskAssessment] = deque(maxlen=50)

        self.bus.subscribe("proposal.submitted", self._on_proposal,    role="怡姐")
        self.bus.subscribe("au01.status_update", self._on_au01_update, role="怡姐")
        self.bus.subscribe("anomaly.detected",   self._on_anomaly,     role="怡姐")

    # ─── Bus callbacks ────────────────────────────────────────────────────────

    def _on_proposal(self, message) -> None:
        self.assess_proposal(message.payload)

    def _on_au01_update(self, message) -> None:
        payload = message.payload
        if isinstance(payload, dict):
            self.current_alert_level = payload.get("alert_level",        "GREEN")
            self.consecutive_losses  = payload.get("consecutive_losses", 0)
        else:
            self.current_alert_level = getattr(payload, "alert_level",        "GREEN")
            self.consecutive_losses  = getattr(payload, "consecutive_losses", 0)

    def _on_anomaly(self, message) -> None:
        anomaly  = message.payload
        severity = (
            anomaly.get("severity", 0.0) if isinstance(anomaly, dict)
            else getattr(anomaly, "severity", 0.0)
        )
        self.recent_anomalies.append((time.time(), severity))

    # ─── 主流程 ───────────────────────────────────────────────────────────────

    def assess_proposal(self, proposal: TradingProposal) -> RiskAssessment:
        """敏敏 + 阿彭雙視角，產出 RiskAssessment 並廣播到 assessment.complete。"""
        int_severity, int_reasoning = self._check_internal(proposal)
        ext_severity, ext_reasoning = self._check_external(proposal)
        combined = max(int_severity, ext_severity)

        if combined >= 1.0:
            decision      = "REJECTED"
            mod_pos       = None
            mod_stop      = None
            reject_reason = f"嚴重度 {combined:.2f}: {int_reasoning} | {ext_reasoning}"
        elif combined >= 0.7:
            decision      = "MODIFIED"
            mod_pos, mod_stop = self._modify_severe(proposal)
            reject_reason = None
        elif combined >= 0.4:
            decision      = "MODIFIED"
            mod_pos, mod_stop = self._modify_moderate(proposal)
            reject_reason = None
        else:
            decision      = "APPROVED"
            mod_pos       = None
            mod_stop      = None
            reject_reason = None

        assessment = RiskAssessment(
            assessment_id             = str(uuid.uuid4()),
            proposal_id               = proposal.proposal_id,
            decision                  = decision,
            reasoning                 = f"綜合嚴重度: {combined:.2f} → {decision}",
            reverse_analysis_internal = int_reasoning,
            reverse_analysis_external = ext_reasoning,
            timestamp                 = datetime.now(),
            modified_position_size    = mod_pos,
            modified_stop_loss        = mod_stop,
            rejection_reason          = reject_reason,
        )

        self.bus.publish("assessment.complete", assessment, sender="怡姐")
        self.assessments_total += 1
        if decision == "APPROVED":
            self.assessments_approved += 1
        elif decision == "MODIFIED":
            self.assessments_modified += 1
        else:
            self.assessments_rejected += 1
        self.recent_assessments.append(assessment)

        self.logger.info(f"風控評估: {decision} (severity={combined:.2f})")
        return assessment

    # ─── 內部風險（敏敏視角）────────────────────────────────────────────────────

    def _check_internal(self, proposal: TradingProposal) -> tuple[float, str]:
        """檢查：倉位上限、止損距離、R/R 比率、複合信心度。"""
        # 部位絕對上限（立即拒絕）
        if proposal.position_size_usd > MAX_POSITION_USD:
            return 1.0, (
                f"部位 {proposal.position_size_usd:.1f} 超過上限 {MAX_POSITION_USD}"
            )

        severity = 0.0
        reasons:  list[str] = []

        if proposal.entry_price and proposal.entry_price > 0:
            stop_dist = abs(proposal.entry_price - proposal.stop_loss)
            stop_pct  = stop_dist / proposal.entry_price

            if stop_pct < self._MIN_STOP_PCT:
                severity += 0.5
                reasons.append(f"止損距離過小 ({stop_pct * 100:.3f}%)")

            if proposal.take_profit is not None and stop_dist > 0:
                reward = abs(proposal.take_profit - proposal.entry_price)
                rr     = reward / stop_dist
                if rr < self._MIN_RR_RATIO:
                    severity += 0.3
                    reasons.append(f"R/R 比率不足 ({rr:.2f})")

        if abs(proposal.composite_score) < self._MIN_SCORE_CONF:
            severity += 0.2
            reasons.append(f"複合信心度偏低 ({proposal.composite_score:.2f})")

        severity  = min(severity, 1.0)
        reasoning = "; ".join(reasons) if reasons else "內部風險正常"
        return severity, reasoning

    # ─── 外部風險（阿彭視角）────────────────────────────────────────────────────

    def _check_external(self, proposal: TradingProposal) -> tuple[float, str]:
        """檢查：警戒等級、連敗次數、近期異常事件、環境類型。"""
        # 警戒等級（RED 立即拒絕）
        alert_sev = self._ALERT_SEVERITY.get(self.current_alert_level, 0.0)
        if alert_sev >= 1.0:
            return 1.0, f"警戒等級 {self.current_alert_level} → 禁止交易"

        severity = alert_sev
        reasons: list[str] = []
        if alert_sev > 0:
            reasons.append(f"警戒 {self.current_alert_level}")

        # 連敗次數
        if self.consecutive_losses >= self._CONSEC_LOSS_HIGH:
            severity += 0.4
            reasons.append(f"連敗 {self.consecutive_losses} 次")
        elif self.consecutive_losses >= self._CONSEC_LOSS_MED:
            severity += 0.2
            reasons.append(f"連敗 {self.consecutive_losses} 次")

        # 近期異常事件（30 分鐘視窗）
        cutoff     = time.time() - self._ANOMALY_WINDOW_SEC
        recent_cnt = sum(1 for ts, _ in self.recent_anomalies if ts >= cutoff)
        if recent_cnt >= self._ANOMALY_HIGH:
            severity += 0.4
            reasons.append(f"近期 {recent_cnt} 個異常事件")
        elif recent_cnt >= self._ANOMALY_LOW:
            severity += 0.2
            reasons.append(f"近期 {recent_cnt} 個異常事件")

        # 環境類型
        if proposal.environment_type in ("high_volatility", "unclear"):
            severity += 0.3
            reasons.append(f"環境 {proposal.environment_type} 不適合交易")

        severity  = min(severity, 1.0)
        reasoning = "; ".join(reasons) if reasons else "外部風險正常"
        return severity, reasoning

    # ─── 嚴重修正（severity ≥ 0.7）─────────────────────────────────────────────

    def _modify_severe(
        self, proposal: TradingProposal
    ) -> tuple[Optional[float], Optional[float]]:
        """倉位縮至 40%；止損收緊 30%。"""
        alert_factor = self._ALERT_POSITION_FACTOR.get(self.current_alert_level, 1.0)
        if self.consecutive_losses >= self._CONSEC_LOSS_HIGH:
            loss_factor = 0.5
        elif self.consecutive_losses >= self._CONSEC_LOSS_MED:
            loss_factor = 0.7
        else:
            loss_factor = 1.0

        mod_pos = proposal.position_size_usd * 0.4 * alert_factor * loss_factor

        if proposal.entry_price is not None:
            distance = abs(proposal.entry_price - proposal.stop_loss)
            if proposal.direction == "long":
                mod_stop = proposal.entry_price - distance * 0.7
            else:
                mod_stop = proposal.entry_price + distance * 0.7
        else:
            mod_stop = None

        return mod_pos, mod_stop

    # ─── 中度修正（severity ≥ 0.4）─────────────────────────────────────────────

    def _modify_moderate(
        self, proposal: TradingProposal
    ) -> tuple[Optional[float], Optional[float]]:
        """倉位縮至 70%；止損不變。"""
        alert_factor = self._ALERT_POSITION_FACTOR.get(self.current_alert_level, 1.0)
        loss_adj     = 0.8 if self.consecutive_losses >= self._CONSEC_LOSS_MED else 1.0

        mod_pos = proposal.position_size_usd * 0.7 * alert_factor * loss_adj
        return mod_pos, None

    # ─── 狀態查詢 ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "role":                  self.role_name,
            "current_alert_level":   self.current_alert_level,
            "consecutive_losses":    self.consecutive_losses,
            "assessments_total":     self.assessments_total,
            "assessments_approved":  self.assessments_approved,
            "assessments_modified":  self.assessments_modified,
            "assessments_rejected":  self.assessments_rejected,
        }
