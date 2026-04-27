# -*- coding: utf-8 -*-
"""ATC EX-02 阿成（緊急應變員）— 止損監控、閃崩應對、緊急清倉。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import trading_system.common.config as _cfg
from trading_system.common.config import RunMode
from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import AnomalyEvent
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.message_bus import get_bus
from trading_system.common.logger import get_logger

_ROLE_NAME = "阿成"
_ROLE_CODE  = "EX-02"


class EmergencyExecutor:
    """
    EX-02 阿成：緊急應變員。

    觸發場景：
      1. 收到 FLASH_MOVE (severity ≥ 0.7) → enter_flash_crash_mode()
      2. 收到 AU_RED 快報 → emergency_close_all()
      3. 收到 GA_CRITICAL critical 快報 → emergency_close_all()
      4. check_stop_losses() 偵測到止損觸及 → _close_position()
    """

    FLASH_MOVE_SEVERITY_THRESHOLD = 0.7
    VOLUME_SPIKE_EXTREME_THRESHOLD = 0.9

    def __init__(self, ex03_connection) -> None:
        self.gateway = get_gateway()
        self.bus     = get_bus()
        self.logger  = get_logger(_ROLE_NAME)
        self.ex03    = ex03_connection

        self.bus.subscribe("anomaly.detected", self._on_anomaly,     role=_ROLE_CODE)
        self.bus.subscribe("alert.flash",      self._on_flash_alert, role=_ROLE_CODE)

        self.flash_crash_mode:   bool  = False
        self.emergency_actions_count:  int   = 0
        self.emergency_history: deque  = deque(maxlen=100)

        self.stop_loss_check_interval: int          = 5
        self.last_stop_loss_check:     Optional[float] = None

        # 閃崩時止損收緊幅度（% of distance to entry）
        self.flash_mode_stop_tightening_pct: int = 30

    # ─── Bus Callbacks ────────────────────────────────────────────────────────

    def _on_anomaly(self, message) -> None:
        anomaly: AnomalyEvent = message.payload

        if anomaly.event_type == "FLASH_MOVE" and anomaly.severity >= self.FLASH_MOVE_SEVERITY_THRESHOLD:
            self.enter_flash_crash_mode(anomaly)
        elif anomaly.event_type == "VOLUME_SPIKE" and anomaly.severity >= self.VOLUME_SPIKE_EXTREME_THRESHOLD:
            self.logger.warning(f"極端量能異常: severity={anomaly.severity}")

    def _on_flash_alert(self, message) -> None:
        payload = message.payload
        # send_flash() 發布 to_dict() → dict；直接 publish → FlashAlert object
        if isinstance(payload, dict):
            alert_type  = payload.get("alert_type", "")
            alert_level = payload.get("alert_level", "")
            title       = payload.get("title", "")
        else:
            alert_type  = getattr(payload, "alert_type", "")
            alert_level = getattr(payload, "alert_level", "")
            title       = getattr(payload, "title", "")

        if alert_type == "AU_RED":
            self.emergency_close_all("AU_RED 警戒")
        elif alert_type == "GA_CRITICAL" and alert_level == "critical":
            self.emergency_close_all(f"GA critical 新聞: {title}")

    # ─── Flash Crash Mode ─────────────────────────────────────────────────────

    def enter_flash_crash_mode(self, trigger_event: AnomalyEvent) -> None:
        if self.flash_crash_mode:
            return

        self.flash_crash_mode = True
        self.logger.critical(
            f"進入閃崩模式: {trigger_event.event_type}, sev={trigger_event.severity}"
        )

        # 收緊所有持倉的止損
        for symbol, pos in list(self.ex03.known_positions.items()):
            self._tighten_stop_loss(symbol, pos)

        send_flash(FlashAlert(
            alert_id=str(uuid.uuid4()),
            alert_type="ANOMALY_FLASH",
            alert_level="critical",
            sender=_ROLE_CODE,
            target_recipients=["怡姐", "老廖", "宏哥"],
            title="閃崩模式啟動",
            message=(
                f"觸發事件: {trigger_event.event_type}, "
                f"severity={trigger_event.severity}"
            ),
            related_data={
                "event": trigger_event.to_dict()
                if hasattr(trigger_event, "to_dict")
                else str(trigger_event)
            },
            timestamp=datetime.now(timezone.utc),
            requires_acknowledgment=True,
        ))

        self.emergency_actions_count += 1
        self.emergency_history.append({
            "type":      "FLASH_CRASH_MODE_ENTER",
            "trigger":   str(trigger_event),
            "timestamp": datetime.now(timezone.utc),
        })

    def exit_flash_crash_mode(self) -> None:
        if not self.flash_crash_mode:
            return
        self.flash_crash_mode = False
        self.logger.info("退出閃崩模式")

    def _tighten_stop_loss(self, symbol: str, position: dict) -> Optional[float]:
        """
        將止損向入場價靠近 flash_mode_stop_tightening_pct %。
        更新 ex03 的已知持倉，DRY-RUN 下只模擬，LIVE 下需修改交易所止損單。
        回傳新的止損價（float），若資訊不足回傳 None。
        """
        try:
            original_stop = float(position.get("stop_loss") or 0)
            entry_price   = float(position.get("entry_price") or 0)
        except (TypeError, ValueError):
            return None

        side = position.get("side", "")

        if not (original_stop and entry_price and side):
            return None

        ratio = self.flash_mode_stop_tightening_pct / 100

        if side == "Buy":
            distance = entry_price - original_stop
            new_stop = original_stop + distance * ratio
        else:
            distance = original_stop - entry_price
            new_stop = original_stop - distance * ratio

        new_stop = round(new_stop, 8)
        self.logger.warning(f"收緊止損: {symbol} {original_stop} → {new_stop}")

        updated = dict(position)
        updated["stop_loss"] = new_stop
        self.ex03.update_known_position(symbol, updated)

        if _cfg.CURRENT_MODE == RunMode.DRY_RUN:
            self.logger.info(f"[DRY-RUN] 模擬收緊止損: {symbol}")

        return new_stop

    # ─── Emergency Close ──────────────────────────────────────────────────────

    def emergency_close_all(self, reason: str) -> None:
        self.logger.critical(f"緊急清倉觸發: {reason}")

        positions = dict(self.ex03.known_positions)
        if not positions:
            self.logger.info("沒有持倉需要清倉")
            return

        closed = [
            self._close_position(symbol, pos, reason)
            for symbol, pos in positions.items()
        ]

        send_flash(FlashAlert(
            alert_id=str(uuid.uuid4()),
            alert_type="ANOMALY_FLASH",
            alert_level="critical",
            sender=_ROLE_CODE,
            target_recipients=["全員"],
            title=f"緊急清倉執行：{reason}",
            message=f"已平倉 {len(closed)} 個持倉",
            related_data={"closed_positions": closed},
            timestamp=datetime.now(timezone.utc),
            requires_acknowledgment=True,
        ))

        self.emergency_actions_count += 1
        self.emergency_history.append({
            "type":      "EMERGENCY_CLOSE_ALL",
            "reason":    reason,
            "closed":    closed,
            "timestamp": datetime.now(timezone.utc),
        })

    def _close_position(self, symbol: str, position: dict, reason: str) -> dict:
        if _cfg.CURRENT_MODE == RunMode.DRY_RUN:
            self.logger.info(f"[DRY-RUN] 模擬平倉: {symbol}")
            return {"symbol": symbol, "status": "DRY_RUN_CLOSED", "reason": reason}

        side = "Sell" if position.get("side") == "Buy" else "Buy"
        result = self.gateway.place_order(
            symbol=symbol,
            side=side,
            order_type="Market",
            qty=str(position.get("size", "")),
        )

        if result["success"]:
            self.ex03.update_known_position(symbol, {})
            return {"symbol": symbol, "status": "CLOSED", "reason": reason}
        else:
            return {"symbol": symbol, "status": "FAILED", "reason": result.get("error", "")}

    # ─── Stop Loss Monitor ────────────────────────────────────────────────────

    def check_stop_losses(self) -> None:
        """
        主動檢查每個持倉的止損距離。
        距離 < 1% → WARNING；距離 ≤ 0（觸發）→ 平倉。
        """
        for symbol, pos in list(self.ex03.known_positions.items()):
            try:
                current_price = self._get_current_price(symbol)
                stop_loss     = float(pos.get("stop_loss") or 0)
                side          = pos.get("side", "")
            except (TypeError, ValueError):
                continue

            if not (current_price and stop_loss and side):
                continue

            if side == "Buy":
                distance_pct = (current_price - stop_loss) / stop_loss * 100
            else:
                distance_pct = (stop_loss - current_price) / stop_loss * 100

            if distance_pct <= 0:
                self.logger.critical(
                    f"止損觸發: {symbol} 當前 {current_price} vs 止損 {stop_loss}"
                )
                self._close_position(symbol, pos, "止損觸發")
                self.emergency_actions_count += 1
                self.emergency_history.append({
                    "type":      "STOP_LOSS_TRIGGERED",
                    "symbol":    symbol,
                    "price":     current_price,
                    "stop_loss": stop_loss,
                    "timestamp": datetime.now(timezone.utc),
                })
            elif distance_pct < 1.0:
                self.logger.warning(
                    f"接近止損: {symbol} 距離 {distance_pct:.4f}%"
                )

    def _get_current_price(self, symbol: str) -> float:
        kline = self.gateway.get_market_kline(symbol, "1", limit=1)
        if kline["success"]:
            try:
                return float(kline["data"]["list"][0][4])
            except (IndexError, KeyError, ValueError):
                return 0.0
        return 0.0

    # ─── Run Cycle ────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (
            self.last_stop_loss_check is None
            or now - self.last_stop_loss_check >= self.stop_loss_check_interval
        ):
            self.check_stop_losses()
            self.last_stop_loss_check = now
