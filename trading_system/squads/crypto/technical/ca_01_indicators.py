# -*- coding: utf-8 -*-
"""ATC CA-01 阿盧+伶伶（指標計算 + 覆核）— 主從覆核結構。"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SubReport
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class IndicatorCalculator:
    """阿盧 — 指標計算機（CA-01）。"""

    role_name = "阿盧"
    role_code = "CA-01"

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("阿盧")

        self.kline_cache: dict   = {}
        self.last_indicators: dict = {}

    # ─── Data fetch ───────────────────────────────────────────────────────────

    def fetch_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        """取得 K 線資料（Bybit 回傳最新在前，反轉成時序）。"""
        result = self.gateway.get_market_kline(symbol, interval, limit=limit)
        if not result["success"]:
            return []

        try:
            raw = result["data"].get("list", [])
            klines = []
            for k in reversed(raw):
                klines.append({
                    "timestamp": int(k[0]),
                    "open":      float(k[1]),
                    "high":      float(k[2]),
                    "low":       float(k[3]),
                    "close":     float(k[4]),
                    "volume":    float(k[5]),
                })
            return klines
        except Exception as e:
            self.logger.warning(f"解析 K 線失敗: {e}")
            return []

    # ─── Indicators ───────────────────────────────────────────────────────────

    def calculate_rsi(self, klines: list, period: int = 14) -> Optional[float]:
        """RSI(period) — 簡易版（非 Wilder 平滑）。"""
        if len(klines) < period + 1:
            return None

        closes = [k["close"] for k in klines]
        gains, losses = [], []

        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs  = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_ma(self, klines: list, period: int) -> Optional[float]:
        """簡單移動平均（SMA）。"""
        if len(klines) < period:
            return None
        closes = [k["close"] for k in klines[-period:]]
        return sum(closes) / period

    def calculate_ema(self, klines: list, period: int) -> Optional[float]:
        """指數移動平均（EMA）— 以 SMA 為初始值。"""
        if len(klines) < period:
            return None

        closes     = [k["close"] for k in klines]
        multiplier = 2 / (period + 1)
        ema        = sum(closes[:period]) / period

        for close in closes[period:]:
            ema = (close - ema) * multiplier + ema

        return ema

    def calculate_macd(self, klines: list) -> Optional[dict]:
        """MACD = EMA12 − EMA26（signal 省略，留給 CA-02）。"""
        if len(klines) < 35:
            return None

        ema_12 = self.calculate_ema(klines, 12)
        ema_26 = self.calculate_ema(klines, 26)

        if ema_12 is None or ema_26 is None:
            return None

        return {
            "macd":   ema_12 - ema_26,
            "ema_12": ema_12,
            "ema_26": ema_26,
        }

    def calculate_bollinger(
        self,
        klines: list,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Optional[dict]:
        """Bollinger Bands（middle ± std_dev × σ）。"""
        if len(klines) < period:
            return None

        closes   = [k["close"] for k in klines[-period:]]
        ma       = sum(closes) / period
        variance = sum((c - ma) ** 2 for c in closes) / period
        std      = variance ** 0.5

        return {
            "middle":    ma,
            "upper":     ma + std_dev * std,
            "lower":     ma - std_dev * std,
            "bandwidth": (std_dev * std * 2) / ma * 100 if ma else 0.0,
        }

    def calculate_eth_btc_ratio(self) -> Optional[dict]:
        """ETH/BTC 24h 相對強弱（v3.1 新增）。"""
        eth_klines = self.fetch_klines("ETHUSDT", "60", limit=24)
        btc_klines = self.fetch_klines("BTCUSDT", "60", limit=24)

        if not eth_klines or not btc_klines:
            return None

        eth_change = (eth_klines[-1]["close"] - eth_klines[0]["close"]) / eth_klines[0]["close"] * 100
        btc_change = (btc_klines[-1]["close"] - btc_klines[0]["close"]) / btc_klines[0]["close"] * 100

        return {
            "eth_change_24h":    eth_change,
            "btc_change_24h":    btc_change,
            "relative_strength": eth_change - btc_change,
        }

    def compute_all_indicators(
        self,
        symbol: str   = "ETHUSDT",
        interval: str = "60",
    ) -> Optional[dict]:
        """計算所有指標，回傳完整 dict 或 None。"""
        klines = self.fetch_klines(symbol, interval, limit=200)
        if not klines:
            return None

        indicators = {
            "symbol":        symbol,
            "interval":      interval,
            "current_price": klines[-1]["close"],
            "rsi_14":        self.calculate_rsi(klines, 14),
            "ma_20":         self.calculate_ma(klines, 20),
            "ma_50":         self.calculate_ma(klines, 50),
            "ma_200":        self.calculate_ma(klines, 200),
            "ema_12":        self.calculate_ema(klines, 12),
            "ema_26":        self.calculate_ema(klines, 26),
            "macd":          self.calculate_macd(klines),
            "bollinger":     self.calculate_bollinger(klines, 20, 2.0),
            "kline_count":   len(klines),
            "timestamp":     datetime.now(),
        }

        if symbol == "ETHUSDT":
            indicators["eth_btc"] = self.calculate_eth_btc_ratio()

        self.last_indicators = indicators
        return indicators


# ─── IndicatorReviewer ────────────────────────────────────────────────────────

class IndicatorReviewer:
    """伶伶 — 計算覆核員（CA-01r）。"""

    role_name = "伶伶"
    role_code = "CA-01r"

    def __init__(self, calculator: IndicatorCalculator) -> None:
        self.calculator   = calculator
        self.logger       = get_logger("伶伶")
        self.issues_found: deque = deque(maxlen=100)

    def review_indicators(self, indicators: dict) -> dict:
        """覆核指標計算結果，回傳 {status, issues, issue_count}。"""
        issues: list[str] = []

        if not indicators:
            return {"status": "no_data", "issues": ["指標為空"], "issue_count": 1}

        price = indicators.get("current_price")
        rsi   = indicators.get("rsi_14")

        # 1. RSI 範圍
        if rsi is not None and not (0 <= rsi <= 100):
            issues.append(f"RSI 超出範圍: {rsi}")

        # 2. MA 偏離幅度
        if price:
            for key in ("ma_20", "ma_50", "ma_200"):
                ma = indicators.get(key)
                if ma is not None:
                    deviation = abs(ma - price) / price
                    if deviation > 0.5:
                        issues.append(f"{key} 偏離當前價過大: {deviation*100:.1f}%")

        # 3. Bollinger 順序
        bb = indicators.get("bollinger")
        if bb:
            if not (bb["lower"] < bb["middle"] < bb["upper"]):
                issues.append("Bollinger 順序錯誤")
            if price and not (bb["lower"] * 0.5 < price < bb["upper"] * 1.5):
                issues.append("當前價遠離布林帶")

        # 4. MACD 一致性
        macd = indicators.get("macd")
        if macd:
            e12, e26, mv = macd.get("ema_12"), macd.get("ema_26"), macd.get("macd")
            if all(v is not None for v in [e12, e26, mv]):
                if abs(mv - (e12 - e26)) > 0.01:
                    issues.append("MACD 值不一致")

        # 5. 跳變偵測（與上次比較）
        if getattr(self, "_last_indicators", None):
            last_rsi = self._last_indicators.get("rsi_14")
            if rsi and last_rsi and abs(rsi - last_rsi) > 30:
                issues.append(f"RSI 跳變過大: {last_rsi:.1f} → {rsi:.1f}")

        self._last_indicators = indicators

        if issues:
            self.issues_found.append({
                "timestamp":            datetime.now(),
                "issues":               issues,
                "indicators_snapshot":  dict(indicators),
            })
            self.logger.warning(f"指標覆核發現 {len(issues)} 個問題: {issues}")

        return {
            "status":      "passed" if not issues else "failed",
            "issues":      issues,
            "issue_count": len(issues),
        }


# ─── IndicatorSection ─────────────────────────────────────────────────────────

class IndicatorSection:
    """阿盧+伶伶統籌（CA-01 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway   = gateway or get_gateway()
        self.bus       = bus or get_bus()
        self.logger    = get_logger("CA-01-Section")

        self.alu       = IndicatorCalculator(gateway=self.gateway, bus=self.bus)
        self.lingling  = IndicatorReviewer(self.alu)

        self.history: deque[SubReport] = deque(maxlen=50)

    # ─── Core ─────────────────────────────────────────────────────────────────

    def compute_with_review(
        self,
        symbol: str   = "ETHUSDT",
        interval: str = "60",
    ) -> SubReport:
        """阿盧計算 → 伶伶覆核 → SubReport。"""
        indicators = self.alu.compute_all_indicators(symbol, interval)

        if not indicators:
            report = SubReport(
                role_name      = "CA-01",
                role_code      = "CA-01",
                direction      = "neutral",
                sub_confidence = 0.1,
                reasoning      = "無法取得 K 線資料",
                data_used      = {},
                timestamp      = datetime.now(),
                staleness_flag = True,
            )
            self.history.append(report)
            return report

        review = self.lingling.review_indicators(indicators)

        confidence_penalty = (
            min(0.5, len(review["issues"]) * 0.1) if review["status"] == "failed" else 0
        )

        direction, confidence, reasoning = self._derive_direction(indicators)
        confidence = max(0.0, confidence - confidence_penalty)

        suffix = (
            f" (覆核發現 {len(review['issues'])} 問題)" if review["issues"] else ""
        )

        report = SubReport(
            role_name      = "CA-01",
            role_code      = "CA-01",
            direction      = direction,
            sub_confidence = confidence,
            reasoning      = reasoning + suffix,
            data_used      = {
                "indicators":    indicators,
                "review_result": review,
            },
            timestamp      = datetime.now(),
            staleness_flag = False,
        )

        self.history.append(report)
        return report

    # ─── Direction derivation ─────────────────────────────────────────────────

    def _derive_direction(self, ind: dict) -> tuple[str, float, str]:
        """從指標推導市場方向，回傳 (direction, confidence, reasoning)。"""
        signals: list[tuple[str, float, str]] = []

        # 1. RSI
        rsi = ind.get("rsi_14")
        if rsi is not None:
            if rsi < 30:
                signals.append(("bullish", 0.3,  f"RSI {rsi:.1f} 超賣"))
            elif rsi < 40:
                signals.append(("bullish", 0.15, f"RSI {rsi:.1f} 偏低"))
            elif rsi > 70:
                signals.append(("bearish", 0.3,  f"RSI {rsi:.1f} 超買"))
            elif rsi > 60:
                signals.append(("bearish", 0.15, f"RSI {rsi:.1f} 偏高"))

        # 2. MA 排列
        price  = ind.get("current_price")
        ma_20  = ind.get("ma_20")
        ma_50  = ind.get("ma_50")
        ma_200 = ind.get("ma_200")

        if all(v is not None for v in [price, ma_20, ma_50, ma_200]):
            if price > ma_20 > ma_50 > ma_200:
                signals.append(("bullish", 0.3, "完美多頭排列"))
            elif price > ma_20 > ma_50:
                signals.append(("bullish", 0.2, "短中期多頭"))
            elif price < ma_20 < ma_50 < ma_200:
                signals.append(("bearish", 0.3, "完美空頭排列"))
            elif price < ma_20 < ma_50:
                signals.append(("bearish", 0.2, "短中期空頭"))

        # 3. MACD
        macd = ind.get("macd")
        if macd and macd.get("macd") is not None:
            mv = macd["macd"]
            if mv > 5:
                signals.append(("bullish", 0.2, f"MACD 正值 {mv:.1f}"))
            elif mv < -5:
                signals.append(("bearish", 0.2, f"MACD 負值 {mv:.1f}"))

        # 4. Bollinger 位置
        bb = ind.get("bollinger")
        if bb and price:
            if price > bb["upper"]:
                signals.append(("bearish", 0.15, "突破布林上軌（過熱）"))
            elif price < bb["lower"]:
                signals.append(("bullish", 0.15, "突破布林下軌（過冷）"))

        # 5. ETH/BTC 相對強弱
        eth_btc = ind.get("eth_btc")
        if eth_btc:
            rs = eth_btc.get("relative_strength", 0)
            if rs > 2:
                signals.append(("bullish", 0.1, f"ETH 強於 BTC {rs:.1f}%"))
            elif rs < -2:
                signals.append(("bearish", 0.1, f"ETH 弱於 BTC {abs(rs):.1f}%"))

        if not signals:
            return "neutral", 0.3, "指標無顯著訊號"

        bullish_w = sum(w for d, w, _ in signals if d == "bullish")
        bearish_w = sum(w for d, w, _ in signals if d == "bearish")

        if bullish_w > bearish_w * 1.3:
            direction  = "bullish"
            confidence = min(bullish_w, 0.95)
        elif bearish_w > bullish_w * 1.3:
            direction  = "bearish"
            confidence = min(bearish_w, 0.95)
        else:
            direction  = "neutral"
            confidence = 0.4

        reasoning = "; ".join(r for _, _, r in signals)
        return direction, confidence, reasoning
