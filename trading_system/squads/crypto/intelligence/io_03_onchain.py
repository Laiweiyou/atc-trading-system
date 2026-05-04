# -*- coding: utf-8 -*-
"""ATC IO-03 小魏+蓮姐（鏈上監控）— 單筆鯨魚 vs 整體流向雙人激辯組。"""
from __future__ import annotations

import os
import re
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Optional

import requests as _req

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

_ETHERSCAN_API  = "https://api.etherscan.io/api"
_ETHERSCAN_BASE = "https://etherscan.io/address"
_SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


class OnChainAnalyst:
    """
    通用鏈上分析員 — 小魏和蓮姐共用，差別在 mode。

    mode="single_whale"    → 小魏 IO-03a（跟蹤狂：單筆大額轉帳）
    mode="aggregate_flow"  → 蓮姐 IO-03b（望遠鏡：整體餘額趨勢）
    """

    # 主要交易所熱錢包清單
    exchange_wallets: dict[str, str] = {
        "Binance_14": "0x28C6c06298d514Db089934071355E5743bf21d60",
        "Binance_15": "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549",
    }

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("single_whale", "aggregate_flow"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "single_whale":
            self.role_name = "小魏"
            self.role_code = "IO-03a"
        else:
            self.role_name = "蓮姐"
            self.role_code = "IO-03b"

        self.logger = get_logger(self.role_name)

        # 每個錢包最多保存 144 筆（24h × 每 10 分鐘一筆）
        self.balance_history: dict[str, deque] = {
            name: deque(maxlen=144) for name in self.exchange_wallets
        }

        self.large_transfer_threshold = 100    # ETH：路線 B 篩選
        self.whale_alert_threshold    = 5000   # ETH：觸發警報門檻

    # ─── Data Fetch ───────────────────────────────────────────────────────────

    def fetch_wallet_balances(self) -> dict:
        """爬取所有監控錢包的當前餘額（路線 A，Etherscan 網頁）。"""
        balances: dict[str, Optional[float]] = {}

        for name, address in self.exchange_wallets.items():
            try:
                url      = f"{_ETHERSCAN_BASE}/{address}"
                resp     = _req.get(url, headers=_SCRAPE_HEADERS, timeout=15)
                if resp.status_code == 200:
                    match = re.search(
                        r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*ETH', resp.text
                    )
                    if match:
                        balance = float(match.group(1).replace(",", ""))
                        balances[name] = balance
                        self.balance_history[name].append((time.time(), balance))
                    else:
                        balances[name] = None
                else:
                    balances[name] = None
            except Exception as e:
                self.logger.warning(f"取得 {name} 餘額失敗: {e}")
                balances[name] = None

            time.sleep(2)   # 爬蟲間隔

        return balances

    def fetch_recent_transfers(self) -> list:
        """取得最近的大額轉帳（路線 B，Etherscan API）。"""
        api_key = os.environ.get("ETHERSCAN_API_KEY")
        if not api_key:
            self.logger.warning("沒有 ETHERSCAN_API_KEY，跳過轉帳查詢")
            return []

        target_address = self.exchange_wallets["Binance_14"]
        try:
            resp = _req.get(
                _ETHERSCAN_API,
                params={
                    "module":  "account",
                    "action":  "txlist",
                    "address": target_address,
                    "page":    1,
                    "offset":  30,
                    "sort":    "desc",
                    "apikey":  api_key,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "1":
                    transfers = []
                    for tx in data.get("result", []):
                        try:
                            value_eth = float(tx.get("value", 0)) / 1e18
                            if value_eth >= self.large_transfer_threshold:
                                transfers.append({
                                    "hash":      tx["hash"],
                                    "from":      tx["from"],
                                    "to":        tx["to"],
                                    "value_eth": value_eth,
                                    "timestamp": int(tx["timeStamp"]),
                                    "is_inflow": (
                                        tx["to"].lower() == target_address.lower()
                                    ),
                                })
                        except Exception:
                            continue
                    return transfers
        except Exception as e:
            self.logger.warning(f"取得轉帳失敗: {e}")
        return []

    # ─── Analyze ──────────────────────────────────────────────────────────────

    def analyze(self) -> SubReport:
        balances  = self.fetch_wallet_balances()
        transfers = self.fetch_recent_transfers()
        return self._dispatch(balances, transfers)

    def _dispatch(self, balances: dict, transfers: list) -> SubReport:
        if self.mode == "single_whale":
            return self._whale_analysis(balances, transfers)
        return self._aggregate_analysis(balances, transfers)

    # ─── Single Whale (小魏) ──────────────────────────────────────────────────

    def _whale_analysis(self, balances: dict, transfers: list) -> SubReport:
        """小魏的視角：單筆大額轉帳分析。"""
        signals:  list[tuple[str, float, str]] = []
        data_used: dict = {
            "transfers_count": len(transfers),
            "wallets_checked": list(balances.keys()),
        }

        whale_inflows  = [
            t for t in transfers if t["is_inflow"]  and t["value_eth"] >= self.whale_alert_threshold
        ]
        whale_outflows = [
            t for t in transfers if not t["is_inflow"] and t["value_eth"] >= self.whale_alert_threshold
        ]
        data_used["whale_inflows"]  = len(whale_inflows)
        data_used["whale_outflows"] = len(whale_outflows)

        # 流入 = 賣壓
        if whale_inflows:
            total_inflow = sum(t["value_eth"] for t in whale_inflows)
            data_used["total_whale_inflow_eth"] = total_inflow

            if total_inflow > 50000:
                signals.append(("bearish", 0.6, f"巨鯨流入交易所 {total_inflow:,.0f} ETH（強烈賣壓警告）"))
            elif total_inflow > 20000:
                signals.append(("bearish", 0.4, f"巨鯨流入交易所 {total_inflow:,.0f} ETH"))
            elif total_inflow > 5000:
                signals.append(("bearish", 0.2, f"中等流入 {total_inflow:,.0f} ETH"))

        # 流出 = 持有意願
        if whale_outflows:
            total_outflow = sum(t["value_eth"] for t in whale_outflows)
            data_used["total_whale_outflow_eth"] = total_outflow

            if total_outflow > 50000:
                signals.append(("bullish", 0.5, f"巨鯨從交易所提走 {total_outflow:,.0f} ETH"))
            elif total_outflow > 20000:
                signals.append(("bullish", 0.3, f"提走 {total_outflow:,.0f} ETH"))

        # 最近 5 筆的流向模式
        if len(transfers) >= 5:
            recent_5     = transfers[:5]
            inflow_count = sum(1 for t in recent_5 if t["is_inflow"])
            if inflow_count >= 4:
                signals.append(("bearish", 0.3, "近 5 筆大額交易 4+ 為流入"))
            elif inflow_count <= 1:
                signals.append(("bullish", 0.3, "近 5 筆大額交易多為流出"))

        return self._synthesize(signals, data_used)

    # ─── Aggregate Flow (蓮姐) ────────────────────────────────────────────────

    def _aggregate_analysis(self, balances: dict, transfers: list) -> SubReport:
        """蓮姐的視角：整體餘額趨勢分析。"""
        signals:  list[tuple[str, float, str]] = []
        data_used: dict = {
            "current_balances":    balances,
            "wallets_with_history": [],
        }

        # 1. 24h 餘額變化
        total_change_pct  = 0.0
        wallets_with_data = 0

        for name, history in self.balance_history.items():
            if len(history) < 2:
                continue

            current_balance = history[-1][1] if history[-1][1] else 0.0
            oldest_balance  = history[0][1]  if history[0][1]  else 0.0

            if oldest_balance == 0:
                continue

            change_pct = (current_balance - oldest_balance) / oldest_balance * 100
            data_used[f"{name}_change_pct"] = change_pct
            data_used["wallets_with_history"].append(name)
            total_change_pct  += change_pct
            wallets_with_data += 1

        if wallets_with_data > 0:
            avg_change = total_change_pct / wallets_with_data
            data_used["avg_balance_change_pct"] = avg_change

            if avg_change < -3:
                signals.append(("bullish", 0.5, f"交易所平均餘額 {avg_change:.1f}%（資金大量流出）"))
            elif avg_change < -1:
                signals.append(("bullish", 0.3, f"交易所平均餘額 {avg_change:.1f}%"))
            elif avg_change > 3:
                signals.append(("bearish", 0.5, f"交易所平均餘額 +{avg_change:.1f}%（資金湧入）"))
            elif avg_change > 1:
                signals.append(("bearish", 0.3, f"交易所平均餘額 +{avg_change:.1f}%"))

        # 2. 整體淨流向
        if transfers:
            total_inflow  = sum(t["value_eth"] for t in transfers if t["is_inflow"])
            total_outflow = sum(t["value_eth"] for t in transfers if not t["is_inflow"])
            net_flow      = total_inflow - total_outflow
            data_used["total_inflow_eth"]  = total_inflow
            data_used["total_outflow_eth"] = total_outflow
            data_used["net_flow_eth"]      = net_flow

            if net_flow > 30000:
                signals.append(("bearish", 0.4, f"24h 淨流入 {net_flow:,.0f} ETH"))
            elif net_flow < -30000:
                signals.append(("bullish", 0.4, f"24h 淨流出 {abs(net_flow):,.0f} ETH"))

        return self._synthesize(signals, data_used)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _synthesize(
        self,
        signals:  list[tuple[str, float, str]],
        data_used: dict,
    ) -> SubReport:
        if not signals:
            direction  = "neutral"
            confidence = 0.3
            reasoning  = "鏈上活動平穩，無顯著訊號"
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


# ─── OnChainSection ───────────────────────────────────────────────────────────

class OnChainSection:
    """小魏+蓮姐雙人組統籌（IO-03 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("IO-03-Section")

        self.xiaowei = OnChainAnalyst("single_whale",   gateway=self.gateway, bus=self.bus)
        self.lianjie = OnChainAnalyst("aggregate_flow", gateway=self.gateway, bus=self.bus)

        # 共用 balance_history：避免重複爬取
        self.lianjie.balance_history = self.xiaowei.balance_history

        self.debate_history: deque[DebateResult] = deque(maxlen=50)

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self) -> DebateResult:
        """共同取得一次資料，兩人各自分析，避免重複爬蟲。"""
        balances  = self.xiaowei.fetch_wallet_balances()
        transfers = self.xiaowei.fetch_recent_transfers()

        report_a = self.xiaowei._whale_analysis(balances, transfers)
        report_b = self.lianjie._aggregate_analysis(balances, transfers)

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"IO-03-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
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
        result = _engine_compare(report_a, report_b, "小魏", "蓮姐")
        if result["consensus_type"] == "dual_track":
            self.logger.warning(f"IO-03 雙人大分歧: {result['reasoning']}")
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
                f"方向分歧: 小魏={report_a.direction} vs 蓮姐={report_b.direction}"
            )
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 小魏={report_a.sub_confidence:.2f} "
                f"vs 蓮姐={report_b.sub_confidence:.2f}"
            )
        return None

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        latest = self.debate_history[-1] if self.debate_history else None
        agreed = sum(1 for d in self.debate_history if d.consensus_type == "agreed")
        return {
            "section":        "IO-03-Section",
            "debate_count":   len(self.debate_history),
            "latest_debate":  latest.to_dict() if latest else None,
            "consensus_rate": (
                agreed / len(self.debate_history) if self.debate_history else 0.0
            ),
        }
