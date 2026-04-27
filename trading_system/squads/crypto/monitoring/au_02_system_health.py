# -*- coding: utf-8 -*-
"""ATC AU-02 英姐（系統健康監控員）— 角色存活、訊息流量、系統資源監控。"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

import trading_system.common.config as _cfg
from trading_system.common.api_gateway import get_gateway
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None
    _HAS_PSUTIL = False

_ROLE_NAME = "英姐"
_ROLE_CODE  = "AU-02"

# 角色活躍門檻（秒）
_ACTIVE_THRESHOLD_SEC  = 60
_STALE_THRESHOLD_SEC   = 300

# 系統健康 degraded 門檻
_STALE_DEGRADED_COUNT  = 2

# run_cycle 間隔
_RESOURCE_CHECK_INTERVAL_SEC = 30


class SystemHealthMonitor:
    """
    AU-02 英姐：系統健康監控員。

    核心功能：
      - update_role_activity(role_name): 更新角色最後活躍時間
      - check_role_liveness(): 分類 active / stale / missing
      - _track_message(message): 計算各 channel 訊息流量
      - check_message_flow(): 回傳每分鐘速率、總計、by_channel
      - check_system_resources(): psutil CPU/記憶體（無 psutil 則回傳 0）
      - evaluate_health(): missing→critical, stale≥2→degraded, else→healthy
      - get_system_health_report(): 完整報告
      - run_cycle(): 每 30 秒做資源檢查，每輪做 evaluate_health
    """

    def __init__(
        self,
        tracked_roles: List[str],
        tracked_channels: List[str],
        gateway=None,
    ) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = get_bus()
        self.logger  = get_logger(_ROLE_NAME)

        self.tracked_roles:    List[str] = list(tracked_roles)
        self.tracked_channels: List[str] = list(tracked_channels)

        # 角色活躍記錄
        self.role_activity: Dict[str, float] = {}

        # 訊息流量統計
        self.message_counts:    Dict[str, int] = defaultdict(int)
        self.message_timestamps: List[float]    = []
        self.total_messages:    int             = 0
        self._tracking_start:   float           = time.time()

        # 健康狀態
        self.current_health:        str              = "healthy"
        self.health_changed_at:     Optional[float]  = None
        self.last_health_reason:    str              = ""

        # 資源快取
        self.last_cpu_pct:    float = 0.0
        self.last_memory_mb:  float = 0.0
        self.last_resource_check: Optional[float] = None

        # 訂閱
        self.bus.subscribe("system.warning", self._track_message, role=_ROLE_CODE)
        for ch in self.tracked_channels:
            self.bus.subscribe(ch, self._track_message, role=_ROLE_CODE)

    # ─── Role Liveness ────────────────────────────────────────────────────────

    def update_role_activity(self, role_name: str) -> None:
        """記錄 role_name 的最後活躍時間。"""
        self.role_activity[role_name] = time.time()

    def check_role_liveness(self) -> dict:
        """
        根據最後活躍時間，將 tracked_roles 分成：
          active  : < 60 秒
          stale   : 60 秒 ~ 300 秒
          missing : ≥ 300 秒，或從未回報
        """
        now = time.time()
        active:  List[str] = []
        stale:   List[str] = []
        missing: List[str] = []

        for role in self.tracked_roles:
            last = self.role_activity.get(role)
            if last is None:
                missing.append(role)
            else:
                age = now - last
                if age < _ACTIVE_THRESHOLD_SEC:
                    active.append(role)
                elif age < _STALE_THRESHOLD_SEC:
                    stale.append(role)
                else:
                    missing.append(role)

        return {"active": active, "stale": stale, "missing": missing}

    # ─── Message Tracking ─────────────────────────────────────────────────────

    def _track_message(self, message) -> None:
        """計數各 channel 訊息，並更新發送者活躍時間。"""
        ch     = message.channel
        sender = message.sender

        self.message_counts[ch] += 1
        self.total_messages     += 1
        self.message_timestamps.append(time.time())

        if sender in self.tracked_roles:
            self.update_role_activity(sender)

    def check_message_flow(self) -> dict:
        """
        回傳：
          rate_per_minute : 過去 1 分鐘訊息速率
          total_messages  : 累計總訊息
          by_channel      : dict[channel, count]
        """
        now    = time.time()
        cutoff = now - 60.0
        recent = sum(1 for t in self.message_timestamps if t >= cutoff)

        elapsed   = now - self._tracking_start
        rate_rpm  = round(recent / max(elapsed / 60.0, 1.0) * 1.0, 4) if elapsed > 0 else 0.0
        # 直接用最近 60 秒計數更直觀
        rate_rpm  = recent  # count in last 60 s

        return {
            "rate_per_minute": rate_rpm,
            "total_messages":  self.total_messages,
            "by_channel":      dict(self.message_counts),
        }

    # ─── System Resources ─────────────────────────────────────────────────────

    def check_system_resources(self) -> dict:
        """使用 psutil 取得 CPU / 記憶體；無 psutil 時回傳 0。"""
        if _HAS_PSUTIL:
            try:
                cpu_pct   = _psutil.cpu_percent(interval=0.1)
                mem_info  = _psutil.virtual_memory()
                memory_mb = round(mem_info.used / 1024 / 1024, 1)
            except Exception:
                cpu_pct   = 0.0
                memory_mb = 0.0
        else:
            cpu_pct   = 0.0
            memory_mb = 0.0

        self.last_cpu_pct   = cpu_pct
        self.last_memory_mb = memory_mb
        self.last_resource_check = time.time()

        return {
            "cpu_pct":   cpu_pct,
            "memory_mb": memory_mb,
            "psutil_available": _HAS_PSUTIL,
        }

    # ─── Health Evaluation ────────────────────────────────────────────────────

    def evaluate_health(self) -> str:
        """
        missing 角色存在 → critical
        stale ≥ 2        → degraded
        otherwise        → healthy
        回傳新健康等級字串，並在等級改變時發送 FlashAlert。
        """
        liveness = self.check_role_liveness()
        missing  = liveness["missing"]
        stale    = liveness["stale"]

        if missing:
            new_health = "critical"
            reason     = f"角色失蹤: {missing}"
        elif len(stale) >= _STALE_DEGRADED_COUNT:
            new_health = "degraded"
            reason     = f"角色遲滯: {stale}"
        else:
            new_health = "healthy"
            reason     = "所有角色正常"

        self.last_health_reason = reason

        if new_health != self.current_health:
            old_health           = self.current_health
            self.current_health  = new_health
            self.health_changed_at = time.time()
            self.logger.warning(f"系統健康變化: {old_health} → {new_health} ({reason})")
            self._publish_health_change(new_health, reason)

        return new_health

    def _publish_health_change(self, new_health: str, reason: str) -> None:
        if new_health == "critical":
            alert_type = "DATA_OFFLINE"
            level      = "critical"
            recipients = ["全員"]
            requires   = True
        else:  # degraded
            alert_type = "ANOMALY_FLASH"
            level      = "warning"
            recipients = ["怡姐", "老王", "老蘇"]
            requires   = False

        send_flash(FlashAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=alert_type,
            alert_level=level,
            sender=_ROLE_CODE,
            target_recipients=recipients,
            title=f"系統健康: {new_health.upper()}",
            message=reason,
            related_data={
                "new_health":  new_health,
                "reason":      reason,
                "liveness":    self.check_role_liveness(),
            },
            timestamp=datetime.now(timezone.utc),
            requires_acknowledgment=requires,
        ))

    # ─── Health Report ────────────────────────────────────────────────────────

    def get_system_health_report(self) -> dict:
        """產出完整系統健康報告。"""
        liveness      = self.check_role_liveness()
        message_flow  = self.check_message_flow()
        resources     = {
            "cpu_pct":          self.last_cpu_pct,
            "memory_mb":        self.last_memory_mb,
            "psutil_available": _HAS_PSUTIL,
        }
        subscriber_counts = {
            ch: len(self.bus.get_subscribers(ch))
            for ch in self.tracked_channels
        }
        gateway_stats = self.gateway.get_stats()

        return {
            "role_liveness":    liveness,
            "message_flow":     message_flow,
            "system_resources": resources,
            "bus_subscribers":  subscriber_counts,
            "gateway_stats":    gateway_stats,
            "health_summary": {
                "current_health":  self.current_health,
                "health_reason":   self.last_health_reason,
                "health_changed_at": (
                    datetime.fromtimestamp(self.health_changed_at, tz=timezone.utc).isoformat()
                    if self.health_changed_at else None
                ),
            },
        }

    # ─── Run Cycle ────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (
            self.last_resource_check is None
            or now - self.last_resource_check >= _RESOURCE_CHECK_INTERVAL_SEC
        ):
            self.check_system_resources()

        self.evaluate_health()
