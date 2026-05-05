# -*- coding: utf-8 -*-
"""ATC 老王（仲裁者）— 決策鏈最後一關，產出 ArbiterDecision。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import ArbiterDecision, RiskAssessment, TradingProposal
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class Arbiter:
    role_name = "老王"
    role_code = "Arbiter"

    # ─── Tempo → 倉位因子 ─────────────────────────────────────────────────────
    _TEMPO_POSITION_FACTOR: dict[str, float] = {
        "active":   1.0,
        "cautious": 0.5,
        "rest":     0.0,
    }

    # ─── 傾向係數門檻 ─────────────────────────────────────────────────────────
    _TENDENCY_MIN          = 0.3
    _TENDENCY_MAX          = 0.7
    _TENDENCY_EXEC_HIGH    = 0.7   # EXECUTE 佔比超此 → 降低傾向
    _TENDENCY_ABORT_HIGH   = 0.7   # ABORT 佔比超此 → 提高傾向
    _TENDENCY_MIN_SAMPLES  = 5     # 不足樣本時回傳中性 0.5

    # ─── 其他門檻 ─────────────────────────────────────────────────────────────
    _MIN_POSITION_USD      = 20.0  # 最小有效倉位
    _PROPOSAL_TTL_SEC      = 600   # 提案存活 10 分鐘
    _CAUTIOUS_CONF_MIN     = 0.4   # cautious tempo 下最低信心門檻
    _TENDENCY_CONF_MIN     = 0.5   # 傾向係數抑制時的信心門檻

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("老王")

        from trading_system.common.snapshot_builder import get_snapshot_builder
        self.snapshot_builder = get_snapshot_builder()

        # 暫存等待審核的提案
        self.pending_proposals: dict[str, TradingProposal] = {}

        # 傾向係數歷史（最近 20 個決策）
        self.recent_decisions: deque[dict] = deque(maxlen=20)

        # 統計
        self.decisions_made = 0
        self.execute_count  = 0
        self.wait_count     = 0
        self.abort_count    = 0

        self.bus.subscribe("proposal.submitted",  self._on_proposal,   role="老王")
        self.bus.subscribe("assessment.complete", self._on_assessment, role="老王")

    # ─── Bus callbacks ────────────────────────────────────────────────────────

    def _on_proposal(self, message) -> None:
        proposal = message.payload
        if not isinstance(proposal, TradingProposal):
            return

        self.pending_proposals[proposal.proposal_id] = proposal

        # 清理 TTL 過期的提案
        now   = datetime.now()
        stale = [
            pid for pid, p in self.pending_proposals.items()
            if (now - p.timestamp).total_seconds() > self._PROPOSAL_TTL_SEC
        ]
        for pid in stale:
            del self.pending_proposals[pid]

    def _on_assessment(self, message) -> None:
        assessment = message.payload
        if not isinstance(assessment, RiskAssessment):
            return

        proposal = self.pending_proposals.get(assessment.proposal_id)
        if proposal is None:
            self.logger.warning(f"找不到對應提案 {assessment.proposal_id}")
            return

        decision = self.make_decision(proposal, assessment)

        self.bus.publish(
            "decision.final",
            {"decision": decision, "proposal": proposal},
            sender="老王",
        )

        self.pending_proposals.pop(assessment.proposal_id, None)

    # ─── 主決策流程 ───────────────────────────────────────────────────────────

    def make_decision(
        self,
        proposal: TradingProposal,
        assessment: RiskAssessment,
    ) -> ArbiterDecision:
        """三層判斷 → EXECUTE / WAIT / ABORT。"""
        snapshot            = self.snapshot_builder.build_snapshot()
        tempo               = self._extract_tempo(snapshot)
        tempo_factor        = self._TEMPO_POSITION_FACTOR.get(tempo, 0.5)
        tendency            = self._compute_tendency_coefficient()

        final_decision, reasoning = self._make_final_decision(
            proposal, assessment, tempo, tempo_factor, tendency
        )

        decision = ArbiterDecision(
            decision_id          = str(uuid.uuid4()),
            proposal_id          = proposal.proposal_id,
            assessment_id        = assessment.assessment_id,
            final_decision       = final_decision,
            tempo_factor         = tempo_factor,
            tendency_coefficient = tendency,
            reasoning            = reasoning,
            timestamp            = datetime.now(),
        )

        self.decisions_made += 1
        if final_decision == "EXECUTE":
            self.execute_count += 1
        elif final_decision == "WAIT":
            self.wait_count += 1
        else:
            self.abort_count += 1

        self.recent_decisions.append(
            {"decision": final_decision, "timestamp": time.time()}
        )

        self.logger.info(
            f"裁決 {proposal.proposal_id}: {final_decision} "
            f"(tempo={tempo}, tendency={tendency:.2f})"
        )
        return decision

    # ─── 決策邏輯 ─────────────────────────────────────────────────────────────

    def _make_final_decision(
        self,
        proposal: TradingProposal,
        assessment: RiskAssessment,
        tempo: str,
        tempo_factor: float,
        tendency: float,
    ) -> tuple[str, str]:
        # 1. 怡姐拒絕 → ABORT
        if assessment.decision == "REJECTED":
            return "ABORT", f"風控拒絕: {assessment.rejection_reason}"

        # 2. Tempo rest → ABORT
        if tempo == "rest":
            return "ABORT", "TK 課判定 rest，暫停所有交易"

        # 3. 倉位調整後過小 → ABORT
        if assessment.decision == "MODIFIED" and assessment.modified_position_size:
            actual_size = assessment.modified_position_size * tempo_factor
        else:
            actual_size = proposal.position_size_usd * tempo_factor

        if actual_size < self._MIN_POSITION_USD:
            return "ABORT", f"倉位過小 ${actual_size:.2f} < ${self._MIN_POSITION_USD:.0f}"

        # 4. Cautious + 低信心 → WAIT
        confidence = abs(proposal.composite_score)
        if tempo == "cautious" and confidence < self._CAUTIOUS_CONF_MIN:
            return "WAIT", (
                f"tempo cautious + 信心 {confidence:.2f} < {self._CAUTIOUS_CONF_MIN}，"
                "等待更明確訊號"
            )

        # 5. 傾向係數低 + 低信心 → WAIT
        if tendency < self._TENDENCY_MIN + 0.1 and confidence < self._TENDENCY_CONF_MIN:
            return "WAIT", (
                f"近期過度執行（tendency={tendency:.2f}），保守等待"
            )

        # 6. 執行
        if assessment.decision == "MODIFIED":
            return "EXECUTE", (
                f"執行（風控修改後），tempo={tempo}, factor={tempo_factor}"
            )
        return "EXECUTE", f"執行（風控通過），tempo={tempo}, factor={tempo_factor}"

    # ─── Tempo 萃取 ───────────────────────────────────────────────────────────

    def _extract_tempo(self, snapshot) -> str:
        if snapshot is None or snapshot.tk_report is None:
            return "cautious"
        direction = snapshot.tk_report.course_direction
        return {
            "bullish": "active",
            "neutral": "cautious",
            "bearish": "rest",
        }.get(direction, "cautious")

    # ─── 傾向係數 ─────────────────────────────────────────────────────────────

    def _compute_tendency_coefficient(self) -> float:
        """
        最近決策中 EXECUTE 比例高 → 降低傾向；ABORT 比例高 → 提高傾向。
        樣本不足（< 5）時回傳中性 0.5。
        """
        if len(self.recent_decisions) < self._TENDENCY_MIN_SAMPLES:
            return 0.5

        recent       = list(self.recent_decisions)
        n            = len(recent)
        exec_rate    = sum(1 for d in recent if d["decision"] == "EXECUTE") / n
        abort_rate   = sum(1 for d in recent if d["decision"] == "ABORT")   / n

        if exec_rate > self._TENDENCY_EXEC_HIGH:
            return max(self._TENDENCY_MIN, 0.5 - (exec_rate - self._TENDENCY_EXEC_HIGH))
        if abort_rate > self._TENDENCY_ABORT_HIGH:
            return min(self._TENDENCY_MAX, 0.5 + (abort_rate - self._TENDENCY_ABORT_HIGH))
        return 0.5

    # ─── 狀態查詢 ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "role":               self.role_name,
            "decisions_made":     self.decisions_made,
            "execute_count":      self.execute_count,
            "wait_count":         self.wait_count,
            "abort_count":        self.abort_count,
            "current_tendency":   self._compute_tendency_coefficient(),
            "pending_proposals":  len(self.pending_proposals),
        }
