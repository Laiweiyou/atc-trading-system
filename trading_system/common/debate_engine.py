# -*- coding: utf-8 -*-
"""通用雙人激辯引擎（Phase 4）。

所有激辯組的 _compare_reports 邏輯完全一致，統一在此實作。
各組保留自己的 _compare_reports wrapper 方法以維持介面不變，
內部委派給 compare_reports()。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from trading_system.common.data_models import DebateResult, SubReport

_DEFAULT_SEVERITY: dict[str, int] = {"bearish": 2, "neutral": 1, "bullish": 0}


def compare_reports(
    report_a: SubReport,
    report_b: SubReport,
    role_a_label: str = "分析員 A",
    role_b_label: str = "分析員 B",
    consensus_threshold: float = 0.2,
    dual_track_penalty: float = 0.8,
    severity_order: Optional[dict[str, int]] = None,
) -> dict:
    """通用雙人激辯比對。

    回傳：
    {
        "consensus_type":   "agreed" | "discussed_agreed" | "dual_track",
        "final_direction":  str,
        "final_confidence": float,
        "reasoning":        str,
        "key_disagreement": str | None,
    }

    三種情境：
      1. agreed        — 方向一致 且 信心差 ≤ consensus_threshold
      2. discussed_agreed — 方向一致 但 信心差 > consensus_threshold（加權平均）
      3. dual_track    — 方向不同 → 採保守原則（severity_order 最高者獲勝，×penalty）
    """
    severity = severity_order if severity_order is not None else _DEFAULT_SEVERITY

    same_direction  = report_a.direction == report_b.direction
    confidence_diff = abs(report_a.sub_confidence - report_b.sub_confidence)

    if same_direction and confidence_diff <= consensus_threshold:
        consensus_type   = "agreed"
        final_direction  = report_a.direction
        final_confidence = (report_a.sub_confidence + report_b.sub_confidence) / 2
        reasoning        = (
            f"{role_a_label}: {report_a.reasoning} | {role_b_label}: {report_b.reasoning}"
        )
        key_disagreement = None

    elif same_direction:
        consensus_type  = "discussed_agreed"
        final_direction = report_a.direction
        total_w         = report_a.sub_confidence + report_b.sub_confidence
        final_confidence = (
            (report_a.sub_confidence ** 2 + report_b.sub_confidence ** 2) / total_w
            if total_w > 0 else 0.0
        )
        reasoning = (
            f"方向一致但信心差異大: {role_a_label} {report_a.sub_confidence:.2f} "
            f"vs {role_b_label} {report_b.sub_confidence:.2f}"
        )
        key_disagreement = (
            f"信心差距: {role_a_label} {report_a.sub_confidence:.2f} "
            f"vs {role_b_label} {report_b.sub_confidence:.2f}"
        )

    else:
        consensus_type = "dual_track"
        if severity.get(report_a.direction, 1) >= severity.get(report_b.direction, 1):
            final_direction  = report_a.direction
            final_confidence = report_a.sub_confidence * dual_track_penalty
        else:
            final_direction  = report_b.direction
            final_confidence = report_b.sub_confidence * dual_track_penalty
        reasoning = (
            f"大分歧採保守: {role_a_label} {report_a.direction} "
            f"| {role_b_label} {report_b.direction}"
        )
        key_disagreement = (
            f"{role_a_label} {report_a.direction} vs {role_b_label} {report_b.direction}"
        )

    return {
        "consensus_type":   consensus_type,
        "final_direction":  final_direction,
        "final_confidence": final_confidence,
        "reasoning":        reasoning,
        "key_disagreement": key_disagreement,
    }


def make_debate_result(
    report_a: SubReport,
    report_b: SubReport,
    debate_id_prefix: str,
    role_a_label: str = "分析員 A",
    role_b_label: str = "分析員 B",
    consensus_threshold: float = 0.2,
    dual_track_penalty: float = 0.8,
    severity_order: Optional[dict[str, int]] = None,
) -> DebateResult:
    """一鍵產出 DebateResult，內部呼叫 compare_reports。"""
    comparison = compare_reports(
        report_a, report_b, role_a_label, role_b_label,
        consensus_threshold, dual_track_penalty, severity_order,
    )
    return DebateResult(
        debate_id          = f"{debate_id_prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        report_a           = report_a,
        report_b           = report_b,
        consensus_type     = comparison["consensus_type"],
        final_direction    = comparison["final_direction"],
        final_confidence   = comparison["final_confidence"],
        combined_reasoning = comparison["reasoning"],
        key_disagreement   = comparison["key_disagreement"],
        timestamp          = datetime.now(),
    )
