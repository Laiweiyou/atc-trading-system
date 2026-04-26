# -*- coding: utf-8 -*-
"""ATC KPI 追蹤與績效評級模型。"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Literal, List

# ─── Grade constants ──────────────────────────────────────────────────────────

# 評級條件（score = kpi_rate * 70 + hindsight * 30）
GRADE_THRESHOLDS: dict[str, dict] = {
    "S": {"min_score": 90.0, "min_kpi_rate": 1.00, "min_hindsight": 0.75},
    "A": {"min_score": 80.0, "min_kpi_rate": 0.70, "min_hindsight": 0.65},
    "B": {"min_score": 70.0, "min_kpi_rate": 0.50, "min_hindsight": 0.55},
    "C": {"min_score": 60.0, "min_kpi_rate": 0.00, "min_hindsight": 0.00},
    "D": {"min_score":  0.0, "min_kpi_rate": 0.00, "min_hindsight": 0.00},
}

# 系統影響（D 級降權）
GRADE_SYSTEM_IMPACT: dict[str, dict] = {
    "S": {"weight_multiplier": 1.2, "description": "全能加分"},
    "A": {"weight_multiplier": 1.1, "description": "表現優秀"},
    "B": {"weight_multiplier": 1.0, "description": "正常"},
    "C": {"weight_multiplier": 0.8, "description": "需要改善"},
    "D": {"weight_multiplier": 0.5, "description": "降權處置"},
}


def _compute_score(kpi_rate: float, hindsight: float) -> float:
    return round(kpi_rate * 70 + hindsight * 30, 2)


def _determine_grade(kpi_rate: float, hindsight: float, score: float) -> str:
    """從 S 往 D 逐一核對條件，回傳最高符合等級。"""
    th = GRADE_THRESHOLDS
    if score >= th["S"]["min_score"] and kpi_rate >= th["S"]["min_kpi_rate"] and hindsight > th["S"]["min_hindsight"]:
        return "S"
    if score >= th["A"]["min_score"] and kpi_rate >= th["A"]["min_kpi_rate"] and hindsight > th["A"]["min_hindsight"]:
        return "A"
    if score >= th["B"]["min_score"] and kpi_rate >= th["B"]["min_kpi_rate"] and hindsight > th["B"]["min_hindsight"]:
        return "B"
    if score >= th["C"]["min_score"]:
        return "C"
    return "D"


# ─── 1. KPIDefinition ─────────────────────────────────────────────────────────

@dataclasses.dataclass
class KPIDefinition:
    kpi_id:             str
    role_name:          str
    kpi_name:           str
    target_value:       float
    target_direction:   Literal["greater_than", "less_than", "equal_to"]
    measurement_period: Literal["daily", "weekly", "monthly"]
    description:        str

    def check_achieved(self, actual_value: float) -> bool:
        if self.target_direction == "greater_than":
            return actual_value >= self.target_value
        if self.target_direction == "less_than":
            return actual_value <= self.target_value
        return abs(actual_value - self.target_value) < 1e-9

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> KPIDefinition:
        return cls(
            kpi_id=d["kpi_id"],
            role_name=d["role_name"],
            kpi_name=d["kpi_name"],
            target_value=float(d["target_value"]),
            target_direction=d["target_direction"],
            measurement_period=d["measurement_period"],
            description=d["description"],
        )


# ─── 2. KPIRecord ─────────────────────────────────────────────────────────────

@dataclasses.dataclass
class KPIRecord:
    record_id:    str
    kpi_id:       str
    role_name:    str
    period:       str
    actual_value: float
    target_value: float
    achieved:     bool
    timestamp:    datetime
    notes:        str

    def to_dict(self) -> dict:
        return {
            "record_id":    self.record_id,
            "kpi_id":       self.kpi_id,
            "role_name":    self.role_name,
            "period":       self.period,
            "actual_value": self.actual_value,
            "target_value": self.target_value,
            "achieved":     self.achieved,
            "timestamp":    self.timestamp.isoformat(),
            "notes":        self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KPIRecord:
        ts = d["timestamp"]
        return cls(
            record_id=d["record_id"],
            kpi_id=d["kpi_id"],
            role_name=d["role_name"],
            period=d["period"],
            actual_value=float(d["actual_value"]),
            target_value=float(d["target_value"]),
            achieved=bool(d["achieved"]),
            timestamp=(ts if isinstance(ts, datetime) else datetime.fromisoformat(ts)),
            notes=d["notes"],
        )


# ─── 3. PerformanceGrade ──────────────────────────────────────────────────────

@dataclasses.dataclass
class PerformanceGrade:
    grade_id:             str
    role_name:            str
    period:               str
    grade:                Literal["S", "A", "B", "C", "D"]
    kpi_records:          List[KPIRecord]
    kpi_achievement_rate: float
    hindsight_accuracy:   float
    overall_score:        float
    cao_comments:         str
    system_impact:        dict
    timestamp:            datetime

    def to_dict(self) -> dict:
        return {
            "grade_id":             self.grade_id,
            "role_name":            self.role_name,
            "period":               self.period,
            "grade":                self.grade,
            "kpi_records":          [r.to_dict() for r in self.kpi_records],
            "kpi_achievement_rate": self.kpi_achievement_rate,
            "hindsight_accuracy":   self.hindsight_accuracy,
            "overall_score":        self.overall_score,
            "cao_comments":         self.cao_comments,
            "system_impact":        self.system_impact,
            "timestamp":            self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PerformanceGrade:
        ts = d["timestamp"]
        return cls(
            grade_id=d["grade_id"],
            role_name=d["role_name"],
            period=d["period"],
            grade=d["grade"],
            kpi_records=[KPIRecord.from_dict(r) for r in d["kpi_records"]],
            kpi_achievement_rate=float(d["kpi_achievement_rate"]),
            hindsight_accuracy=float(d["hindsight_accuracy"]),
            overall_score=float(d["overall_score"]),
            cao_comments=d["cao_comments"],
            system_impact=d["system_impact"],
            timestamp=(ts if isinstance(ts, datetime) else datetime.fromisoformat(ts)),
        )


# ─── Factory function ─────────────────────────────────────────────────────────

def compute_performance_grade(
    grade_id:          str,
    role_name:         str,
    period:            str,
    kpi_records:       List[KPIRecord],
    hindsight_accuracy: float,
    cao_comments:      str = "",
) -> PerformanceGrade:
    """
    根據 KPI 紀錄與自評正確率計算績效等級。
    overall_score = kpi_achievement_rate * 70 + hindsight_accuracy * 30
    """
    n        = len(kpi_records)
    achieved = sum(1 for r in kpi_records if r.achieved)
    kpi_rate = round(achieved / n, 4) if n > 0 else 0.0
    score    = _compute_score(kpi_rate, hindsight_accuracy)
    grade    = _determine_grade(kpi_rate, hindsight_accuracy, score)

    return PerformanceGrade(
        grade_id=grade_id,
        role_name=role_name,
        period=period,
        grade=grade,
        kpi_records=kpi_records,
        kpi_achievement_rate=kpi_rate,
        hindsight_accuracy=hindsight_accuracy,
        overall_score=score,
        cao_comments=cao_comments,
        system_impact=dict(GRADE_SYSTEM_IMPACT[grade]),
        timestamp=datetime.now(timezone.utc),
    )
