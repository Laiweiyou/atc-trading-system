# -*- coding: utf-8 -*-
"""ATC TK-01 小施（節奏指標員）— 量化市場節奏。"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class TempoIndicators:
    """小施 — 節奏指標員，計算波動率、量能活躍度、趨勢強度與急速變化。"""

    role_name = "小施"
    role_code = "TK-01"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("小施")

        self.last_indicators: Optional[dict] = None
        self.history: deque[dict] = deque(maxlen=200)

    # ─── Data fetch ───────────────────────────────────────────────────────────

    def fetch_klines(self, symbol: str = "ETHUSDT") -> dict:
        """取得 1H（7 天）和 1D（30 天）K 線。"""
        result_1h = self.gateway.get_market_kline(symbol, "60", limit=168)
        result_1d = self.gateway.get_market_kline(symbol, "D",  limit=30)

        klines_1h: list[dict] = []
        klines_1d: list[dict] = []

        if result_1h.get("success"):
            try:
                raw = result_1h["data"].get("list", [])
                for k in reversed(raw):
                    klines_1h.append({
                        "timestamp": int(k[0]),
                        "open":      float(k[1]),
                        "high":      float(k[2]),
                        "low":       float(k[3]),
                        "close":     float(k[4]),
                        "volume":    float(k[5]),
                    })
            except Exception:
                pass

        if result_1d.get("success"):
            try:
                raw = result_1d["data"].get("list", [])
                for k in reversed(raw):
                    klines_1d.append({
                        "timestamp": int(k[0]),
                        "open":      float(k[1]),
                        "high":      float(k[2]),
                        "low":       float(k[3]),
                        "close":     float(k[4]),
                        "volume":    float(k[5]),
                    })
            except Exception:
                pass

        return {"1h": klines_1h, "1d": klines_1d}

    # ─── Calculations ─────────────────────────────────────────────────────────

    def calculate_atr(self, klines: list[dict], period: int = 14) -> Optional[float]:
        """計算 ATR（Average True Range）。"""
        if len(klines) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(klines)):
            high       = klines[i]["high"]
            low        = klines[i]["low"]
            prev_close = klines[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        return sum(true_ranges[-period:]) / period

    def compute_indicators(self, symbol: str = "ETHUSDT") -> Optional[dict]:
        """計算所有節奏指標，並存入 history。"""
        klines    = self.fetch_klines(symbol)
        klines_1h = klines["1h"]

        if not klines_1h:
            return None

        latest = klines_1h[-1]

        # 1. 波動率（ATR / 價格）
        atr = self.calculate_atr(klines_1h, period=24)
        volatility_pct = (atr / latest["close"] * 100) if (atr and latest["close"]) else 0.0

        # 2. 成交量活躍度（最近 24H vs 7 天均量）
        if len(klines_1h) >= 168:
            recent_24h_vol    = sum(k["volume"] for k in klines_1h[-24:])
            week_avg_24h_vol  = sum(k["volume"] for k in klines_1h[-168:]) / 168 * 24
            volume_activity_ratio = recent_24h_vol / week_avg_24h_vol if week_avg_24h_vol else 1.0
        else:
            volume_activity_ratio = 1.0

        # 3. 趨勢強度（價格 vs MA20）
        if len(klines_1h) >= 20:
            ma20           = sum(k["close"] for k in klines_1h[-20:]) / 20
            trend_strength = (latest["close"] - ma20) / ma20 * 100
        else:
            trend_strength = 0.0

        # 4. 急速變化偵測（最近 1H 是否超過 2σ）
        if len(klines_1h) >= 24:
            recent_changes = [
                (klines_1h[i]["close"] - klines_1h[i - 1]["close"])
                / klines_1h[i - 1]["close"] * 100
                for i in range(-23, 0)
            ]
            mean_change = sum(recent_changes) / len(recent_changes)
            std_change  = (
                sum((c - mean_change) ** 2 for c in recent_changes) / len(recent_changes)
            ) ** 0.5

            latest_change = recent_changes[-1]
            std_deviation = (latest_change - mean_change) / std_change if std_change else 0.0
            sudden_change = abs(std_deviation) > 2
        else:
            std_deviation = 0.0
            sudden_change = False

        indicators = {
            "symbol":                symbol,
            "current_price":         latest["close"],
            "volatility_pct":        volatility_pct,
            "volume_activity_ratio": volume_activity_ratio,
            "trend_strength_pct":    trend_strength,
            "sudden_change_detected": sudden_change,
            "std_deviation":         std_deviation,
            "timestamp":             datetime.now(),
        }

        self.last_indicators = indicators
        self.history.append(indicators)
        return indicators

    # ─── Tempo score ──────────────────────────────────────────────────────────

    def get_tempo_score(self) -> dict:
        """產出節奏分數（0–100，越高越活躍）。"""
        ind = self.last_indicators
        if not ind:
            return {"score": 50, "level": "moderate", "reasoning": "資料不足"}

        score   = 50
        reasons: list[str] = []

        # 波動率
        if ind["volatility_pct"] > 5:
            score += 25
            reasons.append(f"高波動 {ind['volatility_pct']:.1f}%")
        elif ind["volatility_pct"] > 3:
            score += 15
            reasons.append(f"中波動 {ind['volatility_pct']:.1f}%")
        elif ind["volatility_pct"] < 1.5:
            score -= 15
            reasons.append(f"低波動 {ind['volatility_pct']:.1f}%")

        # 量能活躍度
        if ind["volume_activity_ratio"] > 1.5:
            score += 20
            reasons.append(f"量能活躍 {ind['volume_activity_ratio']:.1f}x")
        elif ind["volume_activity_ratio"] < 0.7:
            score -= 15
            reasons.append(f"量能萎縮 {ind['volume_activity_ratio']:.1f}x")

        # 急速變化
        if ind["sudden_change_detected"]:
            score += 10
            reasons.append("急速變化偵測")

        score = max(0, min(100, score))

        if score >= 70:
            level = "high_activity"
        elif score >= 40:
            level = "moderate"
        else:
            level = "low_activity"

        return {
            "score":      score,
            "level":      level,
            "reasoning":  "; ".join(reasons) if reasons else "節奏平穩",
            "indicators": ind,
        }
