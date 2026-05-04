# -*- coding: utf-8 -*-
"""ATC TK-02 華哥（節奏記憶員）— 追蹤節奏的歷史變化模式。"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

from trading_system.common.logger import get_logger

if TYPE_CHECKING:
    from trading_system.squads.crypto.tempo.tk_01_tempo_indicators import TempoIndicators


class TempoMemory:
    """華哥 — 節奏歷史學家，從 TK-01 的 history 提供統計脈絡與轉換偵測。"""

    role_name = "華哥"
    role_code = "TK-02"

    def __init__(self, tk01: "TempoIndicators") -> None:
        self.tk01   = tk01
        self.logger = get_logger("華哥")

        self.transition_history: deque[dict] = deque(maxlen=50)

    # ─── History stats ────────────────────────────────────────────────────────

    def get_tempo_history_stats(self) -> dict:
        """從 TK-01 的 history 計算統計摘要。"""
        history = list(self.tk01.history)
        if len(history) < 10:
            return {"available": False}

        recent_scores = [
            self._compute_score_from_indicator(ind)["score"]
            for ind in history[-50:]
        ]

        if not recent_scores:
            return {"available": False}

        current = recent_scores[-1]
        return {
            "available":          True,
            "current_score":      current,
            "avg_score_recent":   sum(recent_scores) / len(recent_scores),
            "max_score":          max(recent_scores),
            "min_score":          min(recent_scores),
            "current_percentile": (
                sum(1 for s in recent_scores if s <= current) / len(recent_scores) * 100
            ),
            "sample_size":        len(recent_scores),
        }

    # ─── Transition detection ─────────────────────────────────────────────────

    def detect_transition(self, current_score: float) -> dict:
        """偵測節奏是否出現轉換點（大幅加速或減速）。"""
        history = list(self.tk01.history)
        if len(history) < 5:
            return {"transition_detected": False}

        recent_5   = [self._compute_score_from_indicator(ind)["score"] for ind in history[-5:]]
        avg_recent = sum(recent_5) / len(recent_5)

        change_pct = (current_score - avg_recent) / max(1, avg_recent) * 100

        if abs(change_pct) > 30:
            transition_type = "speedup" if change_pct > 0 else "slowdown"
            self.transition_history.append({
                "type":       transition_type,
                "from_score": avg_recent,
                "to_score":   current_score,
                "timestamp":  datetime.now(),
            })
            return {
                "transition_detected": True,
                "type":                transition_type,
                "magnitude":           change_pct,
                "from_avg":            avg_recent,
                "to_current":          current_score,
            }

        return {"transition_detected": False}

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _compute_score_from_indicator(self, ind: dict) -> dict:
        """從單一 indicator dict 重算節奏分數（與 TK-01 邏輯一致）。"""
        score = 50

        if ind["volatility_pct"] > 5:
            score += 25
        elif ind["volatility_pct"] > 3:
            score += 15
        elif ind["volatility_pct"] < 1.5:
            score -= 15

        if ind["volume_activity_ratio"] > 1.5:
            score += 20
        elif ind["volume_activity_ratio"] < 0.7:
            score -= 15

        if ind.get("sudden_change_detected"):
            score += 10

        return {"score": max(0, min(100, score))}
