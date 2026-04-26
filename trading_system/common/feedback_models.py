# -*- coding: utf-8 -*-
"""ATC 反饋與自評模型。"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Literal, List, Optional


def _dt(s) -> datetime:
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s)


def _dt_opt(s) -> Optional[datetime]:
    return None if s is None else _dt(s)


# ─── 1. SelfReview ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SelfReview:
    role_name:           str
    role_code:           str
    work_type:           str
    timestamp:           datetime
    my_call:             str
    confidence_at_time:  float
    reasoning:           str
    data_used:           dict
    review_id:           str = dataclasses.field(
                             default_factory=lambda: str(uuid.uuid4()))
    hindsight_correct:   Optional[Literal[
                             "correct", "incorrect",
                             "partial_correct", "unverified"]] = None
    hindsight_verified_at: Optional[datetime] = None
    hindsight_verifier:  Optional[str] = None
    hindsight_notes:     Optional[str] = None

    # ── Verification helpers ─────────────────────────────────────────────────

    def mark_correct(self, verifier: str, notes: str = "") -> None:
        self._mark("correct", verifier, notes)

    def mark_incorrect(self, verifier: str, notes: str = "") -> None:
        self._mark("incorrect", verifier, notes)

    def mark_partial(self, verifier: str, notes: str) -> None:
        self._mark("partial_correct", verifier, notes)

    def is_verified(self) -> bool:
        return self.hindsight_correct not in (None, "unverified")

    def _mark(self, verdict: str, verifier: str, notes: str) -> None:
        self.hindsight_correct     = verdict
        self.hindsight_verified_at = datetime.now(timezone.utc)
        self.hindsight_verifier    = verifier
        self.hindsight_notes       = notes

    # ── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "review_id":            self.review_id,
            "role_name":            self.role_name,
            "role_code":            self.role_code,
            "work_type":            self.work_type,
            "timestamp":            self.timestamp.isoformat(),
            "my_call":              self.my_call,
            "confidence_at_time":   self.confidence_at_time,
            "reasoning":            self.reasoning,
            "data_used":            self.data_used,
            "hindsight_correct":    self.hindsight_correct,
            "hindsight_verified_at": (
                self.hindsight_verified_at.isoformat()
                if self.hindsight_verified_at else None
            ),
            "hindsight_verifier":   self.hindsight_verifier,
            "hindsight_notes":      self.hindsight_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SelfReview:
        obj = cls(
            role_name=d["role_name"],
            role_code=d["role_code"],
            work_type=d["work_type"],
            timestamp=_dt(d["timestamp"]),
            my_call=d["my_call"],
            confidence_at_time=float(d["confidence_at_time"]),
            reasoning=d["reasoning"],
            data_used=d["data_used"],
        )
        obj.review_id           = d.get("review_id", obj.review_id)
        obj.hindsight_correct   = d.get("hindsight_correct")
        obj.hindsight_verified_at = _dt_opt(d.get("hindsight_verified_at"))
        obj.hindsight_verifier  = d.get("hindsight_verifier")
        obj.hindsight_notes     = d.get("hindsight_notes")
        return obj


# ─── 2. ReviewBatch ───────────────────────────────────────────────────────────

@dataclasses.dataclass
class ReviewBatch:
    batch_id:     str
    course_code:  str
    period_start: datetime
    period_end:   datetime
    reviews:      List[SelfReview]

    # ── Query helpers ────────────────────────────────────────────────────────

    def get_by_role(self, role_name: str) -> List[SelfReview]:
        return [r for r in self.reviews if r.role_name == role_name]

    def get_unverified(self) -> List[SelfReview]:
        return [r for r in self.reviews if not r.is_verified()]

    def calculate_accuracy(self) -> float:
        """
        已驗證 review 中的加權正確率：
        correct=1.0, partial_correct=0.5, incorrect=0.0。
        無已驗證 review 時回傳 0.0。
        """
        verified = [r for r in self.reviews if r.is_verified()]
        if not verified:
            return 0.0
        score = sum(
            1.0 if r.hindsight_correct == "correct" else
            0.5 if r.hindsight_correct == "partial_correct" else
            0.0
            for r in verified
        )
        return round(score / len(verified), 4)

    # ── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "batch_id":     self.batch_id,
            "course_code":  self.course_code,
            "period_start": self.period_start.isoformat(),
            "period_end":   self.period_end.isoformat(),
            "reviews":      [r.to_dict() for r in self.reviews],
        }

    @classmethod
    def from_dict(cls, d: dict) -> ReviewBatch:
        return cls(
            batch_id=d["batch_id"],
            course_code=d["course_code"],
            period_start=_dt(d["period_start"]),
            period_end=_dt(d["period_end"]),
            reviews=[SelfReview.from_dict(r) for r in d["reviews"]],
        )
