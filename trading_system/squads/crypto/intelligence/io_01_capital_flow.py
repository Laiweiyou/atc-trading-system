# -*- coding: utf-8 -*-
"""ATC IO-01 老徐+小曾（資金流分析）— 歷史百分位 vs 趨勢斜率雙人激辯組。"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class CapitalFlowAnalyst:
    """
    通用資金流分析員 — 老徐和小曾共用，差別在 mode。

    mode="historical_percentile" → 老徐 IO-01a（橫向比較型）
    mode="trend_slope"           → 小曾 IO-01b（縱向趨勢型）
    """

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("historical_percentile", "trend_slope"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "historical_percentile":
            self.role_name = "老徐"
            self.role_code = "IO-01a"
        else:
            self.role_name = "小曾"
            self.role_code = "IO-01b"

        self.logger = get_logger(self.role_name)

        self.funding_rate_history:    deque = deque(maxlen=200)
        self.oi_history:              deque = deque(maxlen=200)
        self.long_short_ratio_history: deque = deque(maxlen=200)

        self.last_analysis: Optional[SubReport] = None

    # ─── Data Fetch ───────────────────────────────────────────────────────────

    def fetch_data(self, symbol: str = "ETHUSDT") -> dict:
        """從 Bybit 取得最新資料（兩人共用）。"""
        data: dict = {}

        # 1. 資金費率
        funding = self.gateway.get_funding_rate(symbol, limit=48)
        if funding.get("success"):
            try:
                rates = funding["data"].get("list", [])
                if rates:
                    data["funding_rates"] = [float(r["fundingRate"]) for r in rates]
                    data["latest_funding"] = data["funding_rates"][0]
            except Exception as e:
                self.logger.warning(f"解析資金費率失敗: {e}")

        # 2. OI
        oi = self.gateway.get_open_interest(symbol, interval="5min", limit=48)
        if oi.get("success"):
            try:
                ois = oi["data"].get("list", [])
                if ois:
                    data["oi_history"] = [float(o["openInterest"]) for o in ois]
                    data["latest_oi"]  = data["oi_history"][0]
            except Exception as e:
                self.logger.warning(f"解析 OI 失敗: {e}")

        # 3. 多空比
        ratio = self.gateway.get_account_ratio(symbol, period="1h", limit=24)
        if ratio.get("success"):
            try:
                ratios = ratio["data"].get("list", [])
                if ratios:
                    data["long_short_ratios"]  = [float(r["buyRatio"]) for r in ratios]
                    data["latest_long_ratio"]  = data["long_short_ratios"][0]
            except Exception as e:
                self.logger.warning(f"解析多空比失敗: {e}")

        return data

    # ─── Analyze ──────────────────────────────────────────────────────────────

    def analyze(self, symbol: str = "ETHUSDT") -> SubReport:
        """執行分析，回傳 SubReport。"""
        data = self.fetch_data(symbol)

        if not data:
            return self._create_empty_report("資料取得失敗")

        if self.mode == "historical_percentile":
            return self._historical_analysis(data)
        return self._trend_analysis(data)

    # ─── Historical (老徐) ────────────────────────────────────────────────────

    def _historical_analysis(self, data: dict) -> SubReport:
        """老徐的視角：歷史百分位。"""
        signals:  list[tuple[str, float, str]] = []
        data_used: dict                          = {}

        # 1. 資金費率百分位
        if "funding_rates" in data and len(data["funding_rates"]) >= 10:
            rates   = sorted(data["funding_rates"])
            current = data["latest_funding"]
            percentile = sum(1 for r in rates if r <= current) / len(rates) * 100
            data_used["funding_percentile"] = percentile
            data_used["latest_funding"]     = current

            if percentile > 90:
                signals.append(("bearish", 0.4, f"資金費率歷史 {percentile:.0f}% 位置（過熱）"))
            elif percentile > 75:
                signals.append(("bearish", 0.2, f"資金費率偏高 {percentile:.0f}%"))
            elif percentile < 10:
                signals.append(("bullish", 0.4, f"資金費率歷史 {percentile:.0f}% 位置（過冷反彈）"))
            elif percentile < 25:
                signals.append(("bullish", 0.2, f"資金費率偏低 {percentile:.0f}%"))

        # 2. OI 百分位
        if "oi_history" in data and len(data["oi_history"]) >= 10:
            ois        = sorted(data["oi_history"])
            current_oi = data["latest_oi"]
            oi_percentile = sum(1 for o in ois if o <= current_oi) / len(ois) * 100
            data_used["oi_percentile"] = oi_percentile

            if oi_percentile > 90:
                signals.append(("bearish", 0.3, f"OI 處於極高位 {oi_percentile:.0f}%（爆倉風險）"))
            elif oi_percentile > 75:
                signals.append(("neutral", 0.2, f"OI 偏高"))
            elif oi_percentile < 25:
                signals.append(("bullish", 0.2, f"OI 偏低，市場冷靜"))

        # 3. 多空比百分位
        if "long_short_ratios" in data and len(data["long_short_ratios"]) >= 10:
            ratios        = sorted(data["long_short_ratios"])
            current_ratio = data["latest_long_ratio"]
            lr_percentile = sum(1 for r in ratios if r <= current_ratio) / len(ratios) * 100
            data_used["long_short_percentile"] = lr_percentile

            if lr_percentile > 85 or current_ratio > 0.7:
                signals.append(("bearish", 0.3, f"散戶過度看多 {current_ratio:.2f}（反向訊號）"))
            elif lr_percentile < 15 or current_ratio < 0.4:
                signals.append(("bullish", 0.3, f"散戶過度看空 {current_ratio:.2f}（反向訊號）"))

        # 4. 爆倉分佈估算（v3.1）
        if "latest_oi" in data and "latest_funding" in data:
            data_used["estimated_long_cost"]  = self._estimate_long_avg_cost(data)
            data_used["estimated_short_cost"] = self._estimate_short_avg_cost(data)

        return self._synthesize_report(signals, data_used)

    # ─── Trend (小曾) ─────────────────────────────────────────────────────────

    def _trend_analysis(self, data: dict) -> SubReport:
        """小曾的視角：趨勢和斜率。"""
        signals:  list[tuple[str, float, str]] = []
        data_used: dict                          = {}

        # 1. 資金費率趨勢
        if "funding_rates" in data and len(data["funding_rates"]) >= 5:
            recent = data["funding_rates"][:5]          # 最新在前
            slope  = self._calc_slope(recent[::-1])     # 轉成時序後算斜率
            data_used["funding_slope"] = slope

            if slope > 0.0001:
                signals.append(("bullish", 0.3, "資金費率上升趨勢（多頭累積）"))
            elif slope < -0.0001:
                signals.append(("bearish", 0.3, "資金費率下降趨勢（空頭累積）"))

        # 2. OI 加速度
        if "oi_history" in data and len(data["oi_history"]) >= 5:
            recent_oi  = data["oi_history"][:5]
            oi_change_pct = (recent_oi[0] - recent_oi[-1]) / recent_oi[-1] * 100
            data_used["oi_change_pct"] = oi_change_pct

            if oi_change_pct > 5:
                signals.append(("bullish", 0.3, f"OI 加速增加 {oi_change_pct:.1f}%（資金湧入）"))
            elif oi_change_pct < -5:
                signals.append(("bearish", 0.3, f"OI 加速減少 {oi_change_pct:.1f}%（資金撤離）"))

        # 3. 多空比變化
        if "long_short_ratios" in data and len(data["long_short_ratios"]) >= 5:
            recent_ratios = data["long_short_ratios"][:5]
            ratio_change  = recent_ratios[0] - recent_ratios[-1]
            data_used["ratio_change"] = ratio_change

            if ratio_change > 0.05:
                signals.append(("bearish", 0.2, "散戶轉向看多（反向訊號）"))
            elif ratio_change < -0.05:
                signals.append(("bullish", 0.2, "散戶轉向看空（反向訊號）"))

        return self._synthesize_report(signals, data_used)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _calc_slope(self, values: list) -> float:
        """計算簡易最小二乘斜率。"""
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        numerator   = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        return numerator / denominator if denominator else 0.0

    def _estimate_long_avg_cost(self, data: dict) -> float:
        """爆倉估算：估算多頭平均成本（Phase 5 用 K 線改善）。"""
        return 0.0

    def _estimate_short_avg_cost(self, data: dict) -> float:
        return 0.0

    def _synthesize_report(
        self,
        signals:  list[tuple[str, float, str]],
        data_used: dict,
    ) -> SubReport:
        """綜合 signals 為 SubReport。"""
        if not signals:
            direction  = "neutral"
            confidence = 0.3
            reasoning  = "無顯著訊號"
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

        report = SubReport(
            role_name      = self.role_name,
            role_code      = self.role_code,
            direction      = direction,
            sub_confidence = confidence,
            reasoning      = reasoning,
            data_used      = data_used,
            timestamp      = datetime.now(),
            staleness_flag = False,
        )
        self.last_analysis = report
        return report

    def _create_empty_report(self, reason: str) -> SubReport:
        return SubReport(
            role_name      = self.role_name,
            role_code      = self.role_code,
            direction      = "neutral",
            sub_confidence = 0.1,
            reasoning      = reason,
            data_used      = {},
            timestamp      = datetime.now(),
            staleness_flag = True,
        )


# ─── CapitalFlowSection ───────────────────────────────────────────────────────

class CapitalFlowSection:
    """老徐+小曾的雙人組統籌（IO-01 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("IO-01-Section")

        self.laoxu   = CapitalFlowAnalyst("historical_percentile", gateway=self.gateway, bus=self.bus)
        self.xiaozeng = CapitalFlowAnalyst("trend_slope",          gateway=self.gateway, bus=self.bus)

        self.debate_history: deque[DebateResult] = deque(maxlen=50)

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self, symbol: str = "ETHUSDT") -> DebateResult:
        """執行雙人激辯，回傳 DebateResult。"""
        report_a = self.laoxu.analyze(symbol)
        report_b = self.xiaozeng.analyze(symbol)

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"IO-01-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
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
        """通用比對邏輯（與 AU-03 / DM-02 一致）。"""
        same_direction  = report_a.direction == report_b.direction
        confidence_diff = abs(report_a.sub_confidence - report_b.sub_confidence)

        if same_direction and confidence_diff <= 0.2:
            consensus_type   = "agreed"
            final_direction  = report_a.direction
            final_confidence = (report_a.sub_confidence + report_b.sub_confidence) / 2
            reasoning = f"老徐: {report_a.reasoning} | 小曾: {report_b.reasoning}"

        elif same_direction:
            consensus_type  = "discussed_agreed"
            final_direction = report_a.direction
            total_w         = report_a.sub_confidence + report_b.sub_confidence
            final_confidence = (
                (report_a.sub_confidence ** 2 + report_b.sub_confidence ** 2) / total_w
            )
            reasoning = (
                f"方向一致但信心差異: 老徐 {report_a.sub_confidence:.2f} "
                f"vs 小曾 {report_b.sub_confidence:.2f}"
            )

        else:
            consensus_type = "dual_track"
            severity = {"bearish": 2, "neutral": 1, "bullish": 0}
            if severity.get(report_a.direction, 1) >= severity.get(report_b.direction, 1):
                final_direction  = report_a.direction
                final_confidence = report_a.sub_confidence * 0.8
            else:
                final_direction  = report_b.direction
                final_confidence = report_b.sub_confidence * 0.8
            reasoning = (
                f"大分歧採保守: 老徐 {report_a.direction} | 小曾 {report_b.direction}"
            )
            self.logger.warning(f"IO-01 雙人大分歧: {reasoning}")

        return consensus_type, final_direction, final_confidence, reasoning

    def _identify_disagreement(
        self,
        report_a: SubReport,
        report_b: SubReport,
    ) -> Optional[str]:
        if report_a.direction != report_b.direction:
            return (
                f"方向分歧: 老徐={report_a.direction} vs 小曾={report_b.direction}"
            )
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 老徐={report_a.sub_confidence:.2f} "
                f"vs 小曾={report_b.sub_confidence:.2f}"
            )
        return None

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        latest = self.debate_history[-1] if self.debate_history else None
        agreed = sum(1 for d in self.debate_history if d.consensus_type == "agreed")
        return {
            "section":        "IO-01-Section",
            "debate_count":   len(self.debate_history),
            "latest_debate":  latest.to_dict() if latest else None,
            "consensus_rate": (
                agreed / len(self.debate_history) if self.debate_history else 0.0
            ),
        }
