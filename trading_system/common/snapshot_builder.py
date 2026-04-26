# -*- coding: utf-8 -*-
"""
ATC 快照建構器 — 跨課時間同步機制。
訂閱 report.* channels，維護各課最新報告快取，
提供 build_snapshot() 打包 SnapshotBundle 並標註新鮮度。
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Optional

from trading_system.common.data_models import CourseReport, SnapshotBundle
from trading_system.common.message_bus import get_bus, Message

# 新鮮度邊界（秒）
_REAL_TIME_SEC = 60
_RECENT_SEC    = 900   # 15 分鐘
_DELAYED_SEC   = 3600  # 60 分鐘

_REPORT_CHANNELS = ("report.io", "report.ca", "report.ga", "report.tk")


class SnapshotBuilder:
    def __init__(self) -> None:
        self._latest: dict[str, CourseReport] = {}
        self._subscribe()

    # ── Bus subscription ──────────────────────────────────────────────────────

    def _subscribe(self) -> None:
        bus = get_bus()
        for ch in _REPORT_CHANNELS:
            bus.subscribe(ch, self.on_report_received, "SnapshotBuilder")

    def _unsubscribe(self) -> None:
        bus = get_bus()
        for ch in _REPORT_CHANNELS:
            bus.unsubscribe(ch, "SnapshotBuilder")

    # ── Callback ──────────────────────────────────────────────────────────────

    def on_report_received(self, message: Message) -> None:
        payload = message.payload
        if isinstance(payload, CourseReport):
            report = payload
        elif isinstance(payload, dict) and "course_code" in payload:
            try:
                report = CourseReport.from_dict(payload)
            except (KeyError, ValueError):
                return
        else:
            return
        self._latest[report.course_code] = report

    # ── Snapshot builder ──────────────────────────────────────────────────────

    def build_snapshot(self) -> SnapshotBundle:
        now = datetime.now(timezone.utc)

        def _refresh(code: str) -> Optional[CourseReport]:
            report = self._latest.get(code)
            if report is None:
                return None
            grade = self.get_freshness_grade(report.timestamp, now)
            return dataclasses.replace(report, freshness_grade=grade)

        io = _refresh("IO")
        ca = _refresh("CA")
        ga = _refresh("GA")
        tk = _refresh("TK")
        quality = self.get_overall_quality([io, ca, ga, tk])

        return SnapshotBundle(
            snapshot_id=f"SNAP-{now.strftime('%Y%m%d-%H%M%S')}",
            snapshot_time=now,
            overall_data_quality=quality,
            io_report=io,
            ca_report=ca,
            ga_report=ga,
            tk_report=tk,
        )

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def get_freshness_grade(report_time: datetime, now: datetime) -> str:
        """
        real_time  : < 1 分鐘
        recent     : 1 ~ 15 分鐘
        delayed    : 15 ~ 60 分鐘
        stale      : > 60 分鐘
        """
        if report_time.tzinfo is None:
            report_time = report_time.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        age = (now - report_time).total_seconds()
        if age < _REAL_TIME_SEC:
            return "real_time"
        if age < _RECENT_SEC:
            return "recent"
        if age < _DELAYED_SEC:
            return "delayed"
        return "stale"

    @staticmethod
    def get_overall_quality(reports: list[Optional[CourseReport]]) -> str:
        """
        good       : 全部有報告，且無 delayed/stale
        acceptable : 全部有報告，恰好 1 份 delayed，無 stale
        degraded   : 缺報告、有 stale、或超過 1 份 delayed
        """
        if any(r is None for r in reports):
            return "degraded"
        grades     = [r.freshness_grade for r in reports]
        stale_cnt  = grades.count("stale")
        delayed_cnt = grades.count("delayed")
        if stale_cnt > 0 or delayed_cnt > 1:
            return "degraded"
        if delayed_cnt == 1:
            return "acceptable"
        return "good"


# ─── Singleton ────────────────────────────────────────────────────────────────

_snapshot_builder_instance: Optional[SnapshotBuilder] = None


def get_snapshot_builder() -> SnapshotBuilder:
    global _snapshot_builder_instance
    if _snapshot_builder_instance is None:
        _snapshot_builder_instance = SnapshotBuilder()
    return _snapshot_builder_instance


def reset_snapshot_builder() -> None:
    """清除單例並取消訂閱（測試用）。"""
    global _snapshot_builder_instance
    if _snapshot_builder_instance is not None:
        _snapshot_builder_instance._unsubscribe()
    _snapshot_builder_instance = None
