# -*- coding: utf-8 -*-
"""ATC AU-01 阿康（績效監控員）— P&L 追蹤、連敗計數、警戒等級管理。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import trading_system.common.config as _cfg
from trading_system.common.api_gateway import get_gateway
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

_ROLE_NAME = "阿康"
_ROLE_CODE  = "AU-01"

# 連敗警戒門檻
_CONSEC_YELLOW = 5
_CONSEC_ORANGE = 8

# 警戒等級順序（用於升降判斷）
_LEVEL_ORDER = ["GREEN", "YELLOW", "ORANGE", "RED"]


class PerformanceMonitor:
    """
    AU-01 阿康：績效監控員。

    核心功能：
      - 訂閱 execution.result，累計成交次數
      - update_pnl(amount, is_realized) 由平倉方呼叫，更新損益
      - _evaluate_alert_level() 根據日損 % 與連敗數判斷警戒等級
      - update_balance() 每 5 分鐘拉一次 Bybit 帳戶餘額
      - get_performance_report() 回傳完整績效報告
    """

    def __init__(self, gateway=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = get_bus()
        self.logger  = get_logger(_ROLE_NAME)

        self.bus.subscribe("execution.result", self._on_execution_result, role=_ROLE_CODE)

        # 帳戶狀態
        self.initial_capital_usd:  float          = _cfg.INITIAL_CAPITAL_USD
        self.current_balance_usd:  Optional[float] = None
        self.last_balance_check:   Optional[float] = None
        self.balance_check_interval: int           = 300

        # 損益統計
        self.daily_pnl:    float = 0.0
        self.weekly_pnl:   float = 0.0
        self.total_pnl:    float = 0.0
        self.realized_pnl: float = 0.0
        self.unrealized_pnl: float = 0.0

        # 交易統計
        self.total_trades:            int = 0
        self.winning_trades:          int = 0
        self.losing_trades:           int = 0
        self.consecutive_losses:      int = 0
        self.max_consecutive_losses:  int = 0
        self.recent_pnl_history: deque[dict] = deque(maxlen=100)

        # 警戒狀態
        self.current_alert_level:   str              = "GREEN"
        self.alert_level_changed_at: Optional[datetime] = None

        # 每日重置基準
        now = datetime.now()
        self.last_daily_reset: datetime = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    # ─── Bus Callback ─────────────────────────────────────────────────────────

    def _on_execution_result(self, message) -> None:
        payload = message.payload
        if not hasattr(payload, "status"):
            return
        if payload.status != "FILLED":
            return
        self.total_trades += 1
        self.logger.info(f"觀察執行結果: {payload.execution_id}")

    # ─── P&L Update ───────────────────────────────────────────────────────────

    def update_pnl(self, trade_pnl_usd: float, is_realized: bool = True) -> None:
        """
        更新損益。
          is_realized=True  → 已實現盈虧（累加到 realized / daily / total）
          is_realized=False → 未實現盈虧（覆蓋 unrealized_pnl）
        """
        if is_realized:
            self.realized_pnl += trade_pnl_usd
            self.daily_pnl    += trade_pnl_usd
            self.total_pnl    += trade_pnl_usd

            if trade_pnl_usd > 0:
                self.winning_trades    += 1
                self.consecutive_losses = 0
            elif trade_pnl_usd < 0:
                self.losing_trades         += 1
                self.consecutive_losses    += 1
                self.max_consecutive_losses = max(
                    self.max_consecutive_losses, self.consecutive_losses
                )

            self.recent_pnl_history.append({
                "pnl":       trade_pnl_usd,
                "timestamp": datetime.now(timezone.utc),
            })
        else:
            self.unrealized_pnl = trade_pnl_usd

        self._evaluate_alert_level()

    # ─── Alert Evaluation ─────────────────────────────────────────────────────

    def _evaluate_alert_level(self) -> None:
        """根據日損 % 與連敗數決定警戒等級，等級升高時發送 FlashAlert。"""
        if self.current_balance_usd is None:
            return

        loss_pct = abs(min(0.0, self.daily_pnl)) / self.initial_capital_usd * 100

        # 損失百分比決定基準等級
        if loss_pct >= _cfg.RED_LOSS_PCT:
            new_level = "RED"
        elif loss_pct >= _cfg.ORANGE_LOSS_PCT:
            new_level = "ORANGE"
        elif loss_pct >= _cfg.YELLOW_LOSS_PCT:
            new_level = "YELLOW"
        else:
            new_level = "GREEN"

        # 連敗數可以提升警戒（但不能降低）
        if self.consecutive_losses >= _CONSEC_ORANGE and new_level in ("GREEN", "YELLOW"):
            new_level = "ORANGE"
        elif self.consecutive_losses >= _CONSEC_YELLOW and new_level == "GREEN":
            new_level = "YELLOW"

        if new_level != self.current_alert_level:
            old_level = self.current_alert_level
            self.current_alert_level    = new_level
            self.alert_level_changed_at = datetime.now(timezone.utc)
            self.logger.warning(f"警戒等級變化: {old_level} → {new_level}")
            self._publish_alert_change(old_level, new_level)

    def _publish_alert_change(self, old_level: str, new_level: str) -> None:
        level_to_severity = {
            "GREEN":  "info",
            "YELLOW": "warning",
            "ORANGE": "critical",
            "RED":    "critical",
        }
        recipients = ["全員"] if new_level == "RED" else ["怡姐", "老王", "老蘇"]

        send_flash(FlashAlert(
            alert_id=str(uuid.uuid4()),
            alert_type="AU_RED" if new_level == "RED" else "ANOMALY_FLASH",
            alert_level=level_to_severity[new_level],
            sender=_ROLE_CODE,
            target_recipients=recipients,
            title=f"警戒升級: {old_level} → {new_level}",
            message=(
                f"日損益 {self.daily_pnl:.2f} USD, "
                f"連敗 {self.consecutive_losses} 次"
            ),
            related_data={
                "old_level":          old_level,
                "new_level":          new_level,
                "daily_pnl":          self.daily_pnl,
                "consecutive_losses": self.consecutive_losses,
                "loss_pct":           round(
                    abs(min(0.0, self.daily_pnl)) / self.initial_capital_usd * 100, 4
                ),
            },
            timestamp=datetime.now(timezone.utc),
            requires_acknowledgment=(new_level in ("ORANGE", "RED")),
        ))

    # ─── Balance ──────────────────────────────────────────────────────────────

    def update_balance(self) -> bool:
        """
        拉取 Bybit 帳戶餘額。
        成功 → 更新 current_balance_usd，回傳 True。
        失敗（無 API key / 網路錯誤）→ 使用 initial_capital_usd 作為 fallback，回傳 False。
        無論成敗，last_balance_check 都會更新。
        """
        result = self.gateway.get_account_balance()
        self.last_balance_check = time.time()

        if result["success"]:
            try:
                accounts = result["data"].get("list", [])
                if accounts:
                    raw = accounts[0].get("totalEquity", None)
                    self.current_balance_usd = (
                        float(raw) if raw is not None else self.initial_capital_usd
                    )
                else:
                    self.current_balance_usd = self.initial_capital_usd
            except Exception as e:
                self.logger.warning(f"解析餘額失敗: {e}")
                self.current_balance_usd = self.initial_capital_usd
            return True

        # 失敗時 fallback（DRY-RUN / 未設定 key 常見）
        if self.current_balance_usd is None:
            self.current_balance_usd = self.initial_capital_usd
        return False

    # ─── Daily Reset ──────────────────────────────────────────────────────────

    def daily_reset(self) -> bool:
        """
        若當前 UTC 日期比 last_daily_reset 新，執行每日重置。
        回傳 True 表示確實做了重置。
        """
        now        = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if today_start <= self.last_daily_reset:
            return False

        self.logger.info(f"執行日損益重置: 昨日損益 {self.daily_pnl:.2f}")
        self.weekly_pnl += self.daily_pnl
        self.daily_pnl   = 0.0
        self.last_daily_reset = today_start

        # 重置警戒（連敗未達門檻時回到 GREEN）
        if self.consecutive_losses < _CONSEC_YELLOW:
            old = self.current_alert_level
            self.current_alert_level = "GREEN"
            if old != "GREEN":
                self._publish_alert_change(old, "GREEN")

        return True

    # ─── Performance Report ───────────────────────────────────────────────────

    def get_performance_report(self) -> dict:
        """產出完整績效報告。"""
        traded = self.winning_trades + self.losing_trades
        win_rate = round(self.winning_trades / max(1, traded), 4)

        age_sec = None
        if self.alert_level_changed_at is not None:
            age_sec = round(
                (datetime.now(timezone.utc) - self.alert_level_changed_at).total_seconds(),
                1,
            )

        return {
            "balance": {
                "initial":        self.initial_capital_usd,
                "current":        self.current_balance_usd,
                "total_pnl":      self.total_pnl,
                "daily_pnl":      self.daily_pnl,
                "weekly_pnl":     self.weekly_pnl,
                "realized_pnl":   self.realized_pnl,
                "unrealized_pnl": self.unrealized_pnl,
            },
            "trade_stats": {
                "total_trades":            self.total_trades,
                "winning_trades":          self.winning_trades,
                "losing_trades":           self.losing_trades,
                "win_rate":                win_rate,
                "consecutive_losses":      self.consecutive_losses,
                "max_consecutive_losses":  self.max_consecutive_losses,
            },
            "alert_status": {
                "current_level":              self.current_alert_level,
                "changed_at":                 self.alert_level_changed_at,
                "duration_at_current_level":  age_sec,
            },
        }

    # ─── Run Cycle ────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (
            self.last_balance_check is None
            or now - self.last_balance_check >= self.balance_check_interval
        ):
            self.update_balance()

        self.daily_reset()
