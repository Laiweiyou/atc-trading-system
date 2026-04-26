# -*- coding: utf-8 -*-
"""ATC 訊息總線（同步 pub/sub，Stage 1 單程序版）。"""
from __future__ import annotations

import dataclasses
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

_HISTORY_LIMIT = 1000


# ─── Message ──────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Message:
    message_id: str
    channel:    str
    sender:     str
    timestamp:  datetime
    payload:    Any

    def to_dict(self) -> dict:
        payload_out = (
            self.payload.to_dict()
            if (dataclasses.is_dataclass(self.payload)
                and not isinstance(self.payload, type)
                and hasattr(self.payload, "to_dict"))
            else self.payload
        )
        return {
            "message_id": self.message_id,
            "channel":    self.channel,
            "sender":     self.sender,
            "timestamp":  self.timestamp.isoformat(),
            "payload":    payload_out,
        }


# ─── MessageBus ───────────────────────────────────────────────────────────────

class MessageBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[str, Callable]]] = {}
        self._history:     dict[str, deque[Message]]             = {}

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, channel: str, callback: Callable, role: str) -> None:
        """role 訂閱 channel；同一 role 重複訂閱同一 channel 無效。"""
        subs = self._subscribers.setdefault(channel, [])
        if any(r == role for r, _ in subs):
            return
        subs.append((role, callback))

    def unsubscribe(self, channel: str, role: str) -> bool:
        """取消訂閱，回傳是否找到並移除。"""
        if channel not in self._subscribers:
            return False
        before = len(self._subscribers[channel])
        self._subscribers[channel] = [
            (r, cb) for r, cb in self._subscribers[channel] if r != role
        ]
        return len(self._subscribers[channel]) < before

    def get_subscribers(self, channel: str) -> List[str]:
        return [r for r, _ in self._subscribers.get(channel, [])]

    # ── Publish ───────────────────────────────────────────────────────────────

    def publish(self, channel: str, payload: Any, sender: str) -> str:
        """向 channel 發送訊息，呼叫所有訂閱者，回傳 message_id。"""
        from trading_system.common.logger import get_logger
        _log = get_logger("MessageBus")

        msg = Message(
            message_id=str(uuid.uuid4()),
            channel=channel,
            sender=sender,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
        )

        if channel not in self._history:
            self._history[channel] = deque(maxlen=_HISTORY_LIMIT)
        self._history[channel].append(msg)

        # 複製清單避免 callback 內修改訂閱清單時發生問題
        for role, callback in list(self._subscribers.get(channel, [])):
            try:
                callback(msg)
            except Exception as exc:
                _log.exception(
                    f"channel={channel} subscriber={role} callback 拋出例外: {exc}"
                )

        return msg.message_id

    # ── History ───────────────────────────────────────────────────────────────

    def get_message_history(self, channel: str, limit: int = 100) -> List[Message]:
        """回傳最新 limit 筆歷史訊息（最舊在前）。"""
        msgs = list(self._history.get(channel, deque()))
        return msgs[-limit:] if limit < len(msgs) else msgs

    # ── Utility ───────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """清除所有訂閱者和歷史（測試用）。"""
        self._subscribers.clear()
        self._history.clear()


# ─── Singleton ────────────────────────────────────────────────────────────────

_bus_instance: Optional[MessageBus] = None


def get_bus() -> MessageBus:
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = MessageBus()
    return _bus_instance


def reset_bus() -> None:
    """重設全域單例（測試用）。"""
    global _bus_instance
    _bus_instance = None
