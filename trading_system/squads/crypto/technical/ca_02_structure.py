# -*- coding: utf-8 -*-
"""ATC CA-02 小林+慧慧（市場結構分析）— 近期 vs 歷史雙人激辯組。"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class StructureAnalyst:
    """通用結構分析員 — 小林和慧慧共用，差別在 mode。

    mode="recent_structure"     → 小林 CA-02a（近期 100 根 1H）
    mode="historical_structure" → 慧慧 CA-02b（歷史 500 根 4H）
    """

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("recent_structure", "historical_structure"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "recent_structure":
            self.role_name      = "小林"
            self.role_code      = "CA-02a"
            self.kline_count    = 100
            self.kline_interval = "60"   # 1H
        else:
            self.role_name      = "慧慧"
            self.role_code      = "CA-02b"
            self.kline_count    = 500
            self.kline_interval = "240"  # 4H

        self.logger = get_logger(self.role_name)

    # ─── Data fetch ───────────────────────────────────────────────────────────

    def fetch_klines(self, symbol: str = "ETHUSDT") -> list:
        result = self.gateway.get_market_kline(
            symbol, self.kline_interval, limit=self.kline_count
        )
        if not result["success"]:
            return []

        try:
            raw    = result["data"].get("list", [])
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

    # ─── Structure detection ──────────────────────────────────────────────────

    def find_swing_highs(self, klines: list, lookback: int = 5) -> list:
        """找出 swing high（在左右各 lookback 根都是最高的 K 線）。"""
        highs = []
        for i in range(lookback, len(klines) - lookback):
            current = klines[i]["high"]
            if all(klines[j]["high"] <= current
                   for j in range(i - lookback, i + lookback + 1) if j != i):
                highs.append({
                    "timestamp": klines[i]["timestamp"],
                    "price":     current,
                    "index":     i,
                })
        return highs

    def find_swing_lows(self, klines: list, lookback: int = 5) -> list:
        """找出 swing low（在左右各 lookback 根都是最低的 K 線）。"""
        lows = []
        for i in range(lookback, len(klines) - lookback):
            current = klines[i]["low"]
            if all(klines[j]["low"] >= current
                   for j in range(i - lookback, i + lookback + 1) if j != i):
                lows.append({
                    "timestamp": klines[i]["timestamp"],
                    "price":     current,
                    "index":     i,
                })
        return lows

    def find_key_levels(
        self,
        swing_highs: list,
        swing_lows:  list,
        current_price: float,
    ) -> dict:
        """當前價上方最近壓力、下方最近支撐（各取前 5 個）。"""
        resistances = sorted(
            h["price"] for h in swing_highs if h["price"] > current_price
        )
        supports = sorted(
            (l["price"] for l in swing_lows if l["price"] < current_price),
            reverse=True,
        )
        return {
            "nearest_resistance": resistances[0] if resistances else None,
            "second_resistance":  resistances[1] if len(resistances) > 1 else None,
            "nearest_support":    supports[0]    if supports    else None,
            "second_support":     supports[1]    if len(supports) > 1 else None,
            "all_resistances":    resistances[:5],
            "all_supports":       supports[:5],
        }

    # ─── Analyze ──────────────────────────────────────────────────────────────

    def analyze(self, symbol: str = "ETHUSDT") -> SubReport:
        klines = self.fetch_klines(symbol)

        if not klines or len(klines) < 30:
            return SubReport(
                role_name      = self.role_name,
                role_code      = self.role_code,
                direction      = "neutral",
                sub_confidence = 0.1,
                reasoning      = "K 線資料不足",
                data_used      = {},
                timestamp      = datetime.now(),
                staleness_flag = True,
            )

        current_price = klines[-1]["close"]
        lookback      = 5 if self.mode == "recent_structure" else 10

        swing_highs = self.find_swing_highs(klines, lookback)
        swing_lows  = self.find_swing_lows(klines,  lookback)
        levels      = self.find_key_levels(swing_highs, swing_lows, current_price)

        signals: list[tuple[str, float, str]] = []
        data_used = {
            "kline_count":      len(klines),
            "interval":         self.kline_interval,
            "current_price":    current_price,
            "swing_high_count": len(swing_highs),
            "swing_low_count":  len(swing_lows),
            "levels":           levels,
        }

        # 1. 距離壓力支撐
        if levels["nearest_resistance"]:
            d = (levels["nearest_resistance"] - current_price) / current_price * 100
            data_used["distance_to_resistance_pct"] = d
            if d < 1:
                signals.append(("bearish", 0.4, f"接近壓力 {levels['nearest_resistance']:.2f}（{d:.1f}%）"))
            elif d < 3:
                signals.append(("bearish", 0.2, f"靠近壓力 {d:.1f}%"))

        if levels["nearest_support"]:
            d = (current_price - levels["nearest_support"]) / current_price * 100
            data_used["distance_to_support_pct"] = d
            if d < 1:
                signals.append(("bullish", 0.4, f"接近支撐 {levels['nearest_support']:.2f}（{d:.1f}%）"))
            elif d < 3:
                signals.append(("bullish", 0.2, f"靠近支撐 {d:.1f}%"))

        # 2. 結構判斷（HH+HL = 上升，LH+LL = 下降）
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            rh = [h["price"] for h in swing_highs[-2:]]
            rl = [l["price"] for l in swing_lows[-2:]]

            if rh[-1] > rh[0] and rl[-1] > rl[0]:
                signals.append(("bullish", 0.3, "上升結構（HH + HL）"))
                data_used["structure"] = "uptrend"
            elif rh[-1] < rh[0] and rl[-1] < rl[0]:
                signals.append(("bearish", 0.3, "下降結構（LH + LL）"))
                data_used["structure"] = "downtrend"
            else:
                signals.append(("neutral", 0.1, "震盪結構"))
                data_used["structure"] = "ranging"

        # 3. 突破 / 跌破判斷
        if levels["nearest_resistance"] and current_price > levels["nearest_resistance"]:
            signals.append(("bullish", 0.3, f"突破壓力 {levels['nearest_resistance']:.2f}"))

        if levels["nearest_support"] and current_price < levels["nearest_support"]:
            signals.append(("bearish", 0.3, f"跌破支撐 {levels['nearest_support']:.2f}"))

        # 綜合
        if not signals:
            direction  = "neutral"
            confidence = 0.3
            reasoning  = "結構訊號不明顯"
        else:
            bullish_w = sum(w for d, w, _ in signals if d == "bullish")
            bearish_w = sum(w for d, w, _ in signals if d == "bearish")

            if bullish_w > bearish_w * 1.2:
                direction  = "bullish"
                confidence = min(bullish_w, 0.95)
            elif bearish_w > bullish_w * 1.2:
                direction  = "bearish"
                confidence = min(bearish_w, 0.95)
            else:
                direction  = "neutral"
                confidence = 0.4

            reasoning = "; ".join(r for _, _, r in signals)

        return SubReport(
            role_name      = self.role_name,
            role_code      = self.role_code,
            direction      = direction,
            sub_confidence = confidence,
            reasoning      = reasoning,
            data_used      = data_used,
            timestamp      = datetime.now(),
            staleness_flag = False,
        )


# ─── StructureSection ─────────────────────────────────────────────────────────

class StructureSection:
    """小林+慧慧雙人組統籌（CA-02 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("CA-02-Section")

        self.xiaolin = StructureAnalyst("recent_structure",    gateway=self.gateway, bus=self.bus)
        self.huihui  = StructureAnalyst("historical_structure", gateway=self.gateway, bus=self.bus)

        self.debate_history: deque[DebateResult] = deque(maxlen=50)

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self, symbol: str = "ETHUSDT") -> DebateResult:
        report_a = self.xiaolin.analyze(symbol)
        report_b = self.huihui.analyze(symbol)

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"CA-02-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            report_a           = report_a,
            report_b           = report_b,
            consensus_type     = consensus_type,
            final_direction    = final_direction,
            final_confidence   = final_confidence,
            combined_reasoning = reasoning,
            key_disagreement   = self._identify_disagreement(report_a, report_b),
            timestamp          = datetime.now(),
        )

        self.debate_history.append(debate)
        return debate

    def _compare_reports(
        self,
        report_a: SubReport,
        report_b: SubReport,
    ) -> tuple[str, str, float, str]:
        """委派給通用雙人激辯引擎。"""
        from trading_system.common.debate_engine import compare_reports as _engine_compare
        result = _engine_compare(report_a, report_b, "小林", "慧慧")
        if result["consensus_type"] == "dual_track":
            self.logger.warning(f"CA-02 雙人大分歧: {result['reasoning']}")
        return (
            result["consensus_type"],
            result["final_direction"],
            result["final_confidence"],
            result["reasoning"],
        )

    def _identify_disagreement(
        self,
        report_a: SubReport,
        report_b: SubReport,
    ) -> Optional[str]:
        if report_a.direction != report_b.direction:
            return f"方向分歧: 小林={report_a.direction} vs 慧慧={report_b.direction}"
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 小林={report_a.sub_confidence:.2f} "
                f"vs 慧慧={report_b.sub_confidence:.2f}"
            )
        return None
