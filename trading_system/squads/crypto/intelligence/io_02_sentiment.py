# -*- coding: utf-8 -*-
"""ATC IO-02 阿賴+珊珊（情緒分析）— 機率型 vs 讀心型雙人激辯組。"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime
from typing import Optional

import requests as _req

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

_FGI_URL        = "https://api.alternative.me/fng/?limit=10"
_COINGECKO_URL  = "https://api.coingecko.com/api/v3/coins/markets"
_HTTP_TIMEOUT   = 10
_CG_TIMEOUT     = 15


class SentimentAnalyst:
    """
    通用情緒分析員 — 阿賴和珊珊共用，差別在 mode。

    mode="probability"      → 阿賴 IO-02a（機率型）
    mode="context_reading"  → 珊珊 IO-02b（讀心型）
    """

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("probability", "context_reading"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "probability":
            self.role_name = "阿賴"
            self.role_code = "IO-02a"
        else:
            self.role_name = "珊珊"
            self.role_code = "IO-02b"

        self.logger = get_logger(self.role_name)

        self.fgi_history:        deque = deque(maxlen=30)
        self.stablecoin_history: deque = deque(maxlen=48)

    # ─── Data Fetch ───────────────────────────────────────────────────────────

    def fetch_data(self) -> dict:
        """取得情緒資料（兩人共用）。"""
        data: dict = {}

        # 1. FGI（Alternative.me）
        try:
            resp = _req.get(_FGI_URL, timeout=_HTTP_TIMEOUT)
            if resp.status_code == 200:
                fgi_list = resp.json().get("data", [])
                if fgi_list:
                    data["fgi_current"]        = int(fgi_list[0]["value"])
                    data["fgi_classification"] = fgi_list[0]["value_classification"]
                    data["fgi_history"]        = [int(d["value"]) for d in fgi_list]
        except Exception as e:
            self.logger.warning(f"FGI 取得失敗: {e}")

        # 2. 穩定幣市值（CoinGecko）
        try:
            resp = _req.get(
                _COINGECKO_URL,
                params={
                    "vs_currency": "usd",
                    "ids":         "tether,usd-coin",
                    "order":       "market_cap_desc",
                },
                timeout=_CG_TIMEOUT,
            )
            if resp.status_code == 200:
                coins = resp.json()
                usdt  = next((c for c in coins if c["id"] == "tether"),   None)
                usdc  = next((c for c in coins if c["id"] == "usd-coin"), None)
                if usdt:
                    data["usdt_mcap"] = usdt["market_cap"]
                if usdc:
                    data["usdc_mcap"] = usdc["market_cap"]
                data["total_stablecoin_mcap"] = (
                    data.get("usdt_mcap", 0) + data.get("usdc_mcap", 0)
                )
        except Exception as e:
            self.logger.warning(f"穩定幣市值取得失敗: {e}")

        # 3. OI（Bybit，用於爆倉估算）
        oi = self.gateway.get_open_interest("ETHUSDT", interval="5min", limit=24)
        if oi.get("success"):
            try:
                ois = oi["data"].get("list", [])
                if ois:
                    data["oi_history"]    = [float(o["openInterest"]) for o in ois]
                    data["oi_change_24h"] = (
                        (data["oi_history"][0] - data["oi_history"][-1])
                        / data["oi_history"][-1] * 100
                    )
            except Exception:
                pass

        return data

    # ─── Analyze ──────────────────────────────────────────────────────────────

    def analyze(self) -> SubReport:
        data = self.fetch_data()

        if not data:
            return self._create_empty_report("資料取得失敗")

        if self.mode == "probability":
            return self._probability_analysis(data)
        return self._context_analysis(data)

    # ─── Probability (阿賴) ───────────────────────────────────────────────────

    def _probability_analysis(self, data: dict) -> SubReport:
        """阿賴的視角：把每個訊號轉成上漲機率。"""
        signals:  list[tuple[float, float, str]] = []   # (probability, weight, reason)
        data_used: dict                            = {}

        # 1. FGI → 上漲機率（反向邏輯）
        if "fgi_current" in data:
            fgi = data["fgi_current"]
            data_used["fgi"] = fgi

            if fgi < 20:
                signals.append((0.75, 0.35, f"FGI {fgi}（極度恐懼，反向訊號上漲機率 75%）"))
            elif fgi < 35:
                signals.append((0.60, 0.25, f"FGI {fgi}（恐懼，上漲機率 60%）"))
            elif fgi < 55:
                signals.append((0.50, 0.15, f"FGI {fgi}（中性）"))
            elif fgi < 75:
                signals.append((0.40, 0.25, f"FGI {fgi}（貪婪，上漲機率 40%）"))
            else:
                signals.append((0.25, 0.35, f"FGI {fgi}（極度貪婪，反向訊號）"))

        # 2. 穩定幣市值 → 上漲機率
        if "total_stablecoin_mcap" in data:
            total = data["total_stablecoin_mcap"]
            data_used["stablecoin_mcap"] = total

            if total > 270_000_000_000:
                signals.append((0.60, 0.30, f"穩定幣市值 {total/1e9:.0f}B（充足）"))
            elif total < 240_000_000_000:
                signals.append((0.40, 0.30, f"穩定幣市值 {total/1e9:.0f}B（撤離）"))
            else:
                signals.append((0.50, 0.20, f"穩定幣市值 {total/1e9:.0f}B（中性）"))

        # 3. OI 變化 → 上漲機率
        if "oi_change_24h" in data:
            oi_change = data["oi_change_24h"]
            data_used["oi_change_pct"] = oi_change

            if oi_change > 10:
                signals.append((0.55, 0.20, f"OI 24h +{oi_change:.1f}%（資金湧入）"))
            elif oi_change < -10:
                signals.append((0.45, 0.20, f"OI 24h {oi_change:.1f}%（資金撤離）"))
            else:
                signals.append((0.50, 0.15, f"OI 變化 {oi_change:.1f}%"))

        if not signals:
            return self._create_empty_report("無訊號")

        total_weight  = sum(w for _, w, _ in signals)
        weighted_prob = sum(p * w for p, w, _ in signals) / total_weight
        data_used["combined_probability"] = weighted_prob

        if weighted_prob >= 0.6:
            direction  = "bullish"
            confidence = (weighted_prob - 0.5) * 2
        elif weighted_prob <= 0.4:
            direction  = "bearish"
            confidence = (0.5 - weighted_prob) * 2
        else:
            direction  = "neutral"
            confidence = 0.3

        confidence = min(confidence, 0.95)
        reasoning  = "; ".join(r for _, _, r in signals)

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

    # ─── Context Reading (珊珊) ───────────────────────────────────────────────

    def _context_analysis(self, data: dict) -> SubReport:
        """珊珊的視角：看脈絡和轉折。"""
        signals:  list[tuple[str, float, str]] = []
        data_used: dict                          = {}

        # 1. FGI 趨勢（5天脈絡）
        if "fgi_history" in data and len(data["fgi_history"]) >= 5:
            recent = data["fgi_history"][:5]    # newest first
            change = recent[0] - recent[-1]     # positive = improving
            data_used["fgi_change_5d"] = change
            data_used["fgi_history"]   = recent

            if change > 15:
                signals.append(("bullish", 0.4, f"FGI 5 天上升 {change} 點（情緒回暖）"))
            elif change > 8:
                signals.append(("bullish", 0.2, f"FGI 緩慢回暖 +{change}"))
            elif change < -15:
                signals.append(("bearish", 0.4, f"FGI 5 天下降 {abs(change)} 點（情緒惡化）"))
            elif change < -8:
                signals.append(("bearish", 0.2, f"FGI 緩慢下降 {change}"))

        # 2. 穩定幣市值的「脈絡」
        if "total_stablecoin_mcap" in data:
            data_used["stablecoin_mcap"] = data["total_stablecoin_mcap"]
            fgi_now = data.get("fgi_current")

            if fgi_now is not None:
                if fgi_now < 35 and data["total_stablecoin_mcap"] > 260_000_000_000:
                    signals.append(("bullish", 0.3, "情緒恐懼但資金未撤，可能是底部"))
                elif fgi_now > 65 and data["total_stablecoin_mcap"] < 250_000_000_000:
                    signals.append(("bearish", 0.3, "情緒貪婪但資金已轉移，可能見頂"))

        # 3. OI 脈絡解讀
        if "oi_change_24h" in data and "fgi_current" in data:
            oi_change = data["oi_change_24h"]
            fgi       = data["fgi_current"]

            if oi_change > 5 and fgi > 50:
                signals.append(("bullish", 0.25, "OI 增加且 FGI 高（多頭累積）"))
            elif oi_change > 5 and fgi < 40:
                signals.append(("bearish", 0.25, "OI 增加但 FGI 低（空頭累積）"))

        if not signals:
            return self._create_empty_report("無脈絡訊號")

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

    # ─── Helpers ──────────────────────────────────────────────────────────────

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


# ─── SentimentSection ─────────────────────────────────────────────────────────

class SentimentSection:
    """阿賴+珊珊雙人組統籌（IO-02 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway  = gateway or get_gateway()
        self.bus      = bus or get_bus()
        self.logger   = get_logger("IO-02-Section")

        self.alai     = SentimentAnalyst("probability",     gateway=self.gateway, bus=self.bus)
        self.shanshan = SentimentAnalyst("context_reading", gateway=self.gateway, bus=self.bus)

        self.debate_history: deque[DebateResult] = deque(maxlen=50)

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self) -> DebateResult:
        report_a = self.alai.analyze()
        report_b = self.shanshan.analyze()

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"IO-02-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
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
        result = _engine_compare(report_a, report_b, "阿賴", "珊珊")
        if result["consensus_type"] == "dual_track":
            self.logger.warning(f"IO-02 雙人大分歧: {result['reasoning']}")
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
            return (
                f"方向分歧: 阿賴={report_a.direction} vs 珊珊={report_b.direction}"
            )
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 阿賴={report_a.sub_confidence:.2f} "
                f"vs 珊珊={report_b.sub_confidence:.2f}"
            )
        return None

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        latest = self.debate_history[-1] if self.debate_history else None
        agreed = sum(1 for d in self.debate_history if d.consensus_type == "agreed")
        return {
            "section":        "IO-02-Section",
            "debate_count":   len(self.debate_history),
            "latest_debate":  latest.to_dict() if latest else None,
            "consensus_rate": (
                agreed / len(self.debate_history) if self.debate_history else 0.0
            ),
        }
