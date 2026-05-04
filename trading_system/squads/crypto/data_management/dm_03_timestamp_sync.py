# -*- coding: utf-8 -*-
"""ATC DM-03 琪琪（時間戳同步員）— 快照監督員，確保各課資料新鮮。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SnapshotBundle
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

_COURSES = ("io", "ca", "ga", "tk")


class TimestampSynchronizer:
    """
    DM-03 琪琪：快照包監督員。

    職責：
      - 訂閱 report.{io,ca,ga,tk}，維護各課最後回報時間
      - build_snapshot() → 呼叫 Phase 1 的 SnapshotBuilder 並附加過時偵測
      - get_freshness_summary() → 各課新鮮度概覽
      - _check_staleness() → 超過預期間隔 2/3 倍時發警告/FlashAlert
    """

    role_name = "琪琪"
    role_code = "DM-03"

    # 各課預期更新頻率（秒）
    expected_intervals: dict[str, int] = {
        "io": 300,   # IO 每 5 分鐘
        "ca": 60,    # CA 每 1 分鐘
        "ga": 1080,  # GA 每 18 分鐘
        "tk": 600,   # TK 每 10 分鐘
    }

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger(self.role_name)

        from trading_system.common.snapshot_builder import get_snapshot_builder
        self.snapshot_builder = get_snapshot_builder()

        # 各課最後回報時間（Unix timestamp）
        self.last_report_times: dict[str, Optional[float]] = {
            c: None for c in _COURSES
        }

        # 訂閱所有課的報告 channel
        for course in _COURSES:
            self.bus.subscribe(
                f"report.{course}",
                lambda msg, c=course: self._on_report_received(c, msg),
                role=self.role_code,
            )

        # 統計
        self.snapshot_count:      int                  = 0
        self.staleness_warnings:  deque[dict]          = deque(maxlen=100)

    # ─── Bus Callback ─────────────────────────────────────────────────────────

    def _on_report_received(self, course: str, message) -> None:
        self.last_report_times[course] = time.time()
        self.logger.debug(f"收到 {course} 課報告")

    # ─── Snapshot ─────────────────────────────────────────────────────────────

    def build_snapshot(self) -> SnapshotBundle:
        """建造當前快照，並附加過時偵測。"""
        snapshot = self.snapshot_builder.build_snapshot()
        self.snapshot_count += 1
        self._check_staleness()
        return snapshot

    # ─── Staleness Detection ──────────────────────────────────────────────────

    def _check_staleness(self) -> None:
        """檢查各課是否超過預期更新間隔。"""
        now = time.time()
        for course, last_time in self.last_report_times.items():
            if last_time is None:
                continue

            elapsed  = now - last_time
            expected = self.expected_intervals[course]

            if elapsed > expected * 3:
                self._emit_staleness_warning(course, elapsed, expected, "critical")
            elif elapsed > expected * 2:
                self._emit_staleness_warning(course, elapsed, expected, "warning")

    def _emit_staleness_warning(
        self,
        course:   str,
        elapsed:  float,
        expected: int,
        severity: str,
    ) -> None:
        """發出資料過時警告（每課每 60 秒最多一次）。"""
        now = time.time()
        recent = [
            w for w in self.staleness_warnings
            if w["course"] == course and now - w["timestamp"] < 60
        ]
        if recent:
            return

        warning: dict = {
            "course":           course,
            "elapsed_seconds":  elapsed,
            "expected_seconds": expected,
            "severity":         severity,
            "timestamp":        now,
        }
        self.staleness_warnings.append(warning)
        self.logger.warning(
            f"{course} 課資料過時 {elapsed:.0f}s（預期 {expected}s）"
        )

        if severity == "critical":
            send_flash(FlashAlert(
                alert_id               = str(uuid.uuid4()),
                alert_type             = "DATA_OFFLINE",
                alert_level            = "critical",
                sender                 = self.role_code,
                target_recipients      = ["小蔡", "老蘇"],
                title                  = f"{course} 課資料嚴重過時",
                message                = (
                    f"已 {elapsed:.0f}s 未收到報告（預期 {expected}s）"
                ),
                related_data           = warning,
                timestamp              = datetime.now(timezone.utc),
                requires_acknowledgment = True,
            ))

    # ─── Freshness Summary ────────────────────────────────────────────────────

    def get_freshness_summary(self) -> dict:
        """各課新鮮度概覽。"""
        now     = time.time()
        summary = {}

        for course, last_time in self.last_report_times.items():
            if last_time is None:
                summary[course] = {
                    "status":           "no_data",
                    "elapsed_seconds":  None,
                    "freshness_grade":  "stale",
                }
                continue

            elapsed  = now - last_time
            expected = self.expected_intervals[course]

            if elapsed < expected:
                grade = "real_time" if elapsed < expected * 0.3 else "recent"
            elif elapsed < expected * 2:
                grade = "delayed"
            else:
                grade = "stale"

            summary[course] = {
                "status":           "ok" if grade in ("real_time", "recent") else "warning",
                "elapsed_seconds":  elapsed,
                "expected_seconds": expected,
                "freshness_grade":  grade,
            }

        return summary

    # ─── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "snapshots_built":         self.snapshot_count,
            "staleness_warnings_total": len(self.staleness_warnings),
            "current_freshness":       self.get_freshness_summary(),
        }
