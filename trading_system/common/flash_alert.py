# -*- coding: utf-8 -*-
"""ATC 快報系統，建立在 message_bus 之上。"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Literal, List


# ─── FlashAlert ───────────────────────────────────────────────────────────────

@dataclasses.dataclass
class FlashAlert:
    alert_id:                str
    alert_type:              Literal["GA_CRITICAL", "AU_RED", "EX_FAIL",
                                     "ANOMALY_FLASH", "DATA_OFFLINE"]
    alert_level:             Literal["info", "warning", "critical"]
    sender:                  str
    target_recipients:       List[str]
    title:                   str
    message:                 str
    related_data:            dict
    timestamp:               datetime
    requires_acknowledgment: bool = False

    def to_dict(self) -> dict:
        return {
            "alert_id":                self.alert_id,
            "alert_type":              self.alert_type,
            "alert_level":             self.alert_level,
            "sender":                  self.sender,
            "target_recipients":       self.target_recipients,
            "title":                   self.title,
            "message":                 self.message,
            "related_data":            self.related_data,
            "timestamp":               self.timestamp.isoformat(),
            "requires_acknowledgment": self.requires_acknowledgment,
        }


# ─── Module-level state ───────────────────────────────────────────────────────

_sent_alerts: dict[str, FlashAlert] = {}
_acks:         dict[str, set[str]]  = {}  # alert_id → set of roles that acknowledged


# ─── Public API ───────────────────────────────────────────────────────────────

def send_flash(alert: FlashAlert) -> None:
    """
    發送快報：
    - critical 級別 → log_critical_event（永久記錄）
    - 透過 message_bus 廣播到 "alert.flash" channel
    """
    from trading_system.common.logger import get_logger, log_critical_event
    from trading_system.common.message_bus import get_bus

    _log = get_logger(alert.sender)
    _sent_alerts[alert.alert_id] = alert

    if alert.alert_level == "critical":
        log_critical_event(
            role=alert.sender,
            event_type=f"FLASH_{alert.alert_type}",
            details={
                "alert_id":          alert.alert_id,
                "title":             alert.title,
                "message":           alert.message,
                "target_recipients": alert.target_recipients,
                "related_data":      alert.related_data,
            },
        )

    _log.warning(
        f"[{alert.alert_level.upper()}] 快報: {alert.title} "
        f"→ {alert.target_recipients}"
    )

    get_bus().publish(
        channel="alert.flash",
        payload=alert.to_dict(),
        sender=alert.sender,
    )


def acknowledge_alert(alert_id: str, role: str) -> bool:
    """
    role 確認收到 alert_id。
    回傳 True 表示確認成功；False 表示找不到該 alert。
    """
    if alert_id not in _sent_alerts:
        return False
    _acks.setdefault(alert_id, set()).add(role)
    return True


def get_unacknowledged_critical() -> list[FlashAlert]:
    """
    回傳尚未被所有 target_recipients 確認的 critical 快報
    （僅限 requires_acknowledgment=True）。
    """
    result = []
    for alert_id, alert in _sent_alerts.items():
        if alert.alert_level == "critical" and alert.requires_acknowledgment:
            acked  = _acks.get(alert_id, set())
            pending = [r for r in alert.target_recipients if r not in acked]
            if pending:
                result.append(alert)
    return result


def reset_flash_state() -> None:
    """清除所有快報狀態（測試用）。"""
    _sent_alerts.clear()
    _acks.clear()
