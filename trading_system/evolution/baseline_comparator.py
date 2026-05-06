# -*- coding: utf-8 -*-
"""ATC Baseline Comparator（基準比對員）— 阿柯，毒舌系統績效比對。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import trading_system.common.config as _cfg
from trading_system.common.api_gateway import get_gateway
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class BaselineComparator:
    role_name = "阿柯"
    role_code = "TO-03"

    _OVERHAUL_THRESHOLD = 28

    def __init__(
        self,
        gateway=None,
        bus=None,
        initial_eth_price: Optional[float] = None,
    ) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("TO-03")

        self.initial_capital: float = _cfg.INITIAL_CAPITAL_USD

        # B&H baseline
        self.initial_eth_price: Optional[float] = (
            initial_eth_price if initial_eth_price is not None
            else self._fetch_eth_price()
        )
        self.bh_initial_eth_amount: Optional[float] = (
            self.initial_capital / self.initial_eth_price
            if self.initial_eth_price else None
        )

        # Tracking
        self.comparison_history:         list[dict] = []
        self.consecutive_losses_to_zero: int        = 0
        self.system_beats_bh_count:      int        = 0
        self.system_beats_zero_count:    int        = 0

        self.bus.subscribe("au01.daily_pnl",     self._on_daily_pnl,     role="TO-03")
        self.bus.subscribe("au01.status_update",  self._on_status_update,  role="TO-03")

    # ─── 價格取得 ─────────────────────────────────────────────────────────────

    def _fetch_eth_price(self) -> Optional[float]:
        result = self.gateway.get_market_kline("ETHUSDT", "1", limit=1)
        if not result.get("success"):
            return None
        try:
            klines = result["data"].get("list", [])
            if klines:
                return float(klines[0][4])
            return None
        except Exception as exc:
            self.logger.warning(f"ETH 價格解析失敗: {exc}")
            return None

    # ─── Bus Callbacks ────────────────────────────────────────────────────────

    def _on_daily_pnl(self, message) -> None:
        payload = message.payload
        if not isinstance(payload, dict):
            return
        cumulative_pnl = payload.get("cumulative_pnl")
        if cumulative_pnl is None:
            return
        date = payload.get("date", datetime.now().strftime("%Y-%m-%d"))
        self.compute_daily_comparison(date, float(cumulative_pnl))

    def _on_status_update(self, message) -> None:
        pass

    # ─── 每日比對 ─────────────────────────────────────────────────────────────

    def compute_daily_comparison(self, date: str, system_cumulative_pnl: float) -> dict:
        """計算三條曲線並發布比對結果。"""
        current_eth_price = self._fetch_eth_price()

        system_value = self.initial_capital + system_cumulative_pnl
        zero_value   = self.initial_capital

        if current_eth_price is not None and self.bh_initial_eth_amount is not None:
            bh_value: Optional[float] = self.bh_initial_eth_amount * current_eth_price
        else:
            bh_value = None

        beats_bh   = (bh_value is not None) and (system_value > bh_value)
        beats_zero = system_value > zero_value

        if beats_zero:
            self.consecutive_losses_to_zero = 0
            self.system_beats_zero_count   += 1
        else:
            self.consecutive_losses_to_zero += 1

        if beats_bh:
            self.system_beats_bh_count += 1

        comment = self._generate_comment(bh_value, beats_bh, beats_zero)

        comparison = {
            "date":                       date,
            "system_value":               round(system_value, 4),
            "bh_value":                   round(bh_value, 4) if bh_value is not None else None,
            "zero_value":                 zero_value,
            "beats_bh":                   beats_bh,
            "beats_zero":                 beats_zero,
            "consecutive_losses_to_zero": self.consecutive_losses_to_zero,
            "comment":                    comment,
        }
        self.comparison_history.append(comparison)

        if self.consecutive_losses_to_zero >= self._OVERHAUL_THRESHOLD:
            self._send_overhaul_alert()

        self.bus.publish("baseline.comparison", comparison, sender="TO-03")
        return comparison

    # ─── 毒舌評語 ─────────────────────────────────────────────────────────────

    def _generate_comment(
        self,
        bh_value: Optional[float],
        beats_bh: bool,
        beats_zero: bool,
    ) -> str:
        if beats_bh:
            return "今天竟然贏了買著放，明天能不能繼續我可不保證。"
        if beats_zero:
            if bh_value is not None:
                return "恭喜沒虧，但買完 ETH 躺著睡的人都比你強，加油啦。"
            return "勉強沒虧而已，ETH 行情不明，先別得意。"
        return "連放著不動都比你強，你到底在幹嘛？建議直接躺平。"

    # ─── OVERHAUL 警告 ────────────────────────────────────────────────────────

    def _send_overhaul_alert(self) -> None:
        send_flash(FlashAlert(
            alert_id=str(uuid.uuid4()),
            alert_type="ANOMALY_FLASH",
            alert_level="critical",
            sender="TO-03",
            target_recipients=["全員"],
            title=f"OVERHAUL 警告：連續 {self.consecutive_losses_to_zero} 天跑輸零操作",
            message=(
                f"系統已連續 {self.consecutive_losses_to_zero} 天無法超越零操作基準，"
                "阿柯強烈建議全面重構策略。"
            ),
            related_data={"consecutive_losses_to_zero": self.consecutive_losses_to_zero},
            timestamp=datetime.now(timezone.utc),
            requires_acknowledgment=True,
        ))

    # ─── 近期摘要 ─────────────────────────────────────────────────────────────

    def get_recent_summary(self, days: int = 7) -> dict:
        recent = self.comparison_history[-days:]
        if not recent:
            return {
                "days":                       0,
                "system_beats_bh":            0,
                "system_beats_zero":          0,
                "consecutive_losses_to_zero": self.consecutive_losses_to_zero,
                "recent_comments":            [],
            }
        return {
            "days":                       len(recent),
            "system_beats_bh":            sum(1 for r in recent if r["beats_bh"]),
            "system_beats_zero":          sum(1 for r in recent if r["beats_zero"]),
            "consecutive_losses_to_zero": self.consecutive_losses_to_zero,
            "recent_comments":            [r["comment"] for r in recent[-3:]],
        }
