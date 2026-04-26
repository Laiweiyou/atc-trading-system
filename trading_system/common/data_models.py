# -*- coding: utf-8 -*-
"""ATC 核心資料結構。全部 dataclass，含 to_dict / from_dict。"""
from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Literal, List, Optional


# ─── Serialization helpers ─────────────────────────────────────────────────────

def _serialize(v):
    """遞迴序列化：datetime→isoformat, dataclass→to_dict(), list/dict 遞迴。"""
    if isinstance(v, datetime):
        return v.isoformat()
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return v.to_dict()
    if isinstance(v, list):
        return [_serialize(i) for i in v]
    if isinstance(v, dict):
        return {k: _serialize(val) for k, val in v.items()}
    return v


def _dt(s) -> datetime:
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s)


def _dt_opt(s) -> Optional[datetime]:
    return None if s is None else _dt(s)


def _fields_to_dict(obj) -> dict:
    return {f.name: _serialize(getattr(obj, f.name)) for f in dataclasses.fields(obj)}


# ─── 1. SubReport ─────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SubReport:
    role_name:      str
    role_code:      str
    direction:      Literal["bullish", "bearish", "neutral"]
    sub_confidence: float
    reasoning:      str
    data_used:      dict
    timestamp:      datetime
    staleness_flag: bool = False

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SubReport:
        return cls(
            role_name=d["role_name"],
            role_code=d["role_code"],
            direction=d["direction"],
            sub_confidence=float(d["sub_confidence"]),
            reasoning=d["reasoning"],
            data_used=d["data_used"],
            timestamp=_dt(d["timestamp"]),
            staleness_flag=d.get("staleness_flag", False),
        )


# ─── 2. DebateResult ──────────────────────────────────────────────────────────

@dataclasses.dataclass
class DebateResult:
    debate_id:          str
    report_a:           SubReport
    report_b:           SubReport
    consensus_type:     Literal["agreed", "discussed_agreed", "dual_track"]
    final_direction:    str
    final_confidence:   float
    combined_reasoning: str
    timestamp:          datetime
    key_disagreement:   Optional[str] = None

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DebateResult:
        return cls(
            debate_id=d["debate_id"],
            report_a=SubReport.from_dict(d["report_a"]),
            report_b=SubReport.from_dict(d["report_b"]),
            consensus_type=d["consensus_type"],
            final_direction=d["final_direction"],
            final_confidence=float(d["final_confidence"]),
            combined_reasoning=d["combined_reasoning"],
            timestamp=_dt(d["timestamp"]),
            key_disagreement=d.get("key_disagreement"),
        )


# ─── 3. CourseReport ──────────────────────────────────────────────────────────

@dataclasses.dataclass
class CourseReport:
    course_name:      str
    course_code:      str
    manager_name:     str
    debate_results:   List[DebateResult]
    course_direction: Literal["bullish", "bearish", "neutral"]
    course_confidence: float
    freshness_grade:  Literal["real_time", "recent", "delayed", "stale"]
    data_health:      dict
    flash_alerts:     List[str]
    self_review:      dict
    timestamp:        datetime

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> CourseReport:
        return cls(
            course_name=d["course_name"],
            course_code=d["course_code"],
            manager_name=d["manager_name"],
            debate_results=[DebateResult.from_dict(r) for r in d["debate_results"]],
            course_direction=d["course_direction"],
            course_confidence=float(d["course_confidence"]),
            freshness_grade=d["freshness_grade"],
            data_health=d["data_health"],
            flash_alerts=d["flash_alerts"],
            self_review=d["self_review"],
            timestamp=_dt(d["timestamp"]),
        )


# ─── 4. SnapshotBundle ────────────────────────────────────────────────────────

@dataclasses.dataclass
class SnapshotBundle:
    snapshot_id:          str
    snapshot_time:        datetime
    overall_data_quality: Literal["good", "acceptable", "degraded"]
    io_report:            Optional[CourseReport] = None
    ca_report:            Optional[CourseReport] = None
    ga_report:            Optional[CourseReport] = None
    tk_report:            Optional[CourseReport] = None

    @property
    def timestamp(self) -> datetime:
        return self.snapshot_time

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SnapshotBundle:
        def _cr(key):
            return CourseReport.from_dict(d[key]) if d.get(key) else None
        return cls(
            snapshot_id=d["snapshot_id"],
            snapshot_time=_dt(d["snapshot_time"]),
            overall_data_quality=d["overall_data_quality"],
            io_report=_cr("io_report"),
            ca_report=_cr("ca_report"),
            ga_report=_cr("ga_report"),
            tk_report=_cr("tk_report"),
        )


# ─── 5. TradingProposal ───────────────────────────────────────────────────────

@dataclasses.dataclass
class TradingProposal:
    proposal_id:          str
    symbol:               str
    direction:            Literal["long", "short"]
    entry_type:           Literal["market", "limit"]
    position_size_usd:    float
    stop_loss:            float
    composite_score:      float
    direction_confidence: float
    environment_type:     str
    selected_strategy:    str
    reasoning:            str
    based_on_snapshot:    str
    timestamp:            datetime
    leverage:             int           = 1
    entry_price:          Optional[float] = None
    take_profit:          Optional[float] = None

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> TradingProposal:
        return cls(
            proposal_id=d["proposal_id"],
            symbol=d["symbol"],
            direction=d["direction"],
            entry_type=d["entry_type"],
            position_size_usd=float(d["position_size_usd"]),
            stop_loss=float(d["stop_loss"]),
            composite_score=float(d["composite_score"]),
            direction_confidence=float(d["direction_confidence"]),
            environment_type=d["environment_type"],
            selected_strategy=d["selected_strategy"],
            reasoning=d["reasoning"],
            based_on_snapshot=d["based_on_snapshot"],
            timestamp=_dt(d["timestamp"]),
            leverage=int(d.get("leverage", 1)),
            entry_price=d.get("entry_price"),
            take_profit=d.get("take_profit"),
        )


# ─── 6. RiskAssessment ────────────────────────────────────────────────────────

@dataclasses.dataclass
class RiskAssessment:
    assessment_id:              str
    proposal_id:                str
    decision:                   Literal["APPROVED", "MODIFIED", "REJECTED"]
    reasoning:                  str
    reverse_analysis_internal:  str
    reverse_analysis_external:  str
    timestamp:                  datetime
    modified_position_size:     Optional[float] = None
    modified_stop_loss:         Optional[float] = None
    rejection_reason:           Optional[str]   = None

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RiskAssessment:
        return cls(
            assessment_id=d["assessment_id"],
            proposal_id=d["proposal_id"],
            decision=d["decision"],
            reasoning=d["reasoning"],
            reverse_analysis_internal=d["reverse_analysis_internal"],
            reverse_analysis_external=d["reverse_analysis_external"],
            timestamp=_dt(d["timestamp"]),
            modified_position_size=d.get("modified_position_size"),
            modified_stop_loss=d.get("modified_stop_loss"),
            rejection_reason=d.get("rejection_reason"),
        )


# ─── 7. ArbiterDecision ───────────────────────────────────────────────────────

@dataclasses.dataclass
class ArbiterDecision:
    decision_id:            str
    proposal_id:            str
    assessment_id:          str
    final_decision:         Literal["EXECUTE", "WAIT", "ABORT"]
    tempo_factor:           float
    tendency_coefficient:   float
    reasoning:              str
    timestamp:              datetime

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ArbiterDecision:
        return cls(
            decision_id=d["decision_id"],
            proposal_id=d["proposal_id"],
            assessment_id=d["assessment_id"],
            final_decision=d["final_decision"],
            tempo_factor=float(d["tempo_factor"]),
            tendency_coefficient=float(d["tendency_coefficient"]),
            reasoning=d["reasoning"],
            timestamp=_dt(d["timestamp"]),
        )


# ─── 8. ExecutionResult ───────────────────────────────────────────────────────

@dataclasses.dataclass
class ExecutionResult:
    execution_id:         str
    decision_id:          str
    status:               Literal["FILLED", "PARTIAL", "FAILED", "CANCELLED"]
    timestamp:            datetime
    executed_price:       Optional[float] = None
    executed_size:        Optional[float] = None
    actual_slippage_pct:  Optional[float] = None
    exchange_order_id:    Optional[str]   = None
    error_message:        Optional[str]   = None

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ExecutionResult:
        return cls(
            execution_id=d["execution_id"],
            decision_id=d["decision_id"],
            status=d["status"],
            timestamp=_dt(d["timestamp"]),
            executed_price=d.get("executed_price"),
            executed_size=d.get("executed_size"),
            actual_slippage_pct=d.get("actual_slippage_pct"),
            exchange_order_id=d.get("exchange_order_id"),
            error_message=d.get("error_message"),
        )


# ─── 9. AnomalyEvent ──────────────────────────────────────────────────────────

@dataclasses.dataclass
class AnomalyEvent:
    event_id:       str
    event_type:     Literal["FLASH_MOVE", "VOLUME_SPIKE", "WIDE_RANGE"]
    symbol:         str
    magnitude:      float
    severity:       float
    timestamp:      datetime
    triggered_alert: bool
    direction:      Optional[Literal["up", "down"]] = None

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> AnomalyEvent:
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            symbol=d["symbol"],
            magnitude=float(d["magnitude"]),
            severity=float(d["severity"]),
            timestamp=_dt(d["timestamp"]),
            triggered_alert=d["triggered_alert"],
            direction=d.get("direction"),
        )


# ─── 10. NewsEvent ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class NewsEvent:
    event_id:              str
    event_type:            str
    headline:              str
    summary:               str
    source_count:          int
    cross_validated:       bool
    vader_sentiment:       float
    vader_confidence:      float
    entities:              List[str]
    first_seen:            datetime
    latest_update:         datetime
    secondary_type:        Optional[str] = None
    is_key_figure_statement: bool        = False
    figure_name:           Optional[str] = None

    @property
    def timestamp(self) -> datetime:
        return self.first_seen

    def to_dict(self) -> dict:
        return _fields_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict) -> NewsEvent:
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            headline=d["headline"],
            summary=d["summary"],
            source_count=int(d["source_count"]),
            cross_validated=d["cross_validated"],
            vader_sentiment=float(d["vader_sentiment"]),
            vader_confidence=float(d["vader_confidence"]),
            entities=d["entities"],
            first_seen=_dt(d["first_seen"]),
            latest_update=_dt(d["latest_update"]),
            secondary_type=d.get("secondary_type"),
            is_key_figure_statement=d.get("is_key_figure_statement", False),
            figure_name=d.get("figure_name"),
        )
