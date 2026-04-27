# -*- coding: utf-8 -*-
"""ATC EX-01 小慧（常規下單員）— 接收仲裁決策，精準執行現貨下單。"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import List, Optional

import trading_system.common.config as _cfg
from trading_system.common.config import RunMode, MAX_POSITION_USD
from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import ArbiterDecision, ExecutionResult, TradingProposal
from trading_system.common.message_bus import get_bus
from trading_system.common.logger import get_logger

_ROLE_NAME = "小慧"
_ROLE_CODE  = "EX-01"


class NormalOrderExecutor:
    """
    EX-01 小慧：精準穩定的執行者。

    接收 message_bus "decision.final" 頻道的仲裁決策（payload 格式：
        {"decision": ArbiterDecision, "proposal": TradingProposal}）
    執行下單後發布 ExecutionResult 到 "execution.result"，
    並通知 EX-03 芬姐更新已知持倉。
    """

    def __init__(self, ex03_connection, target_symbols: Optional[List[str]] = None) -> None:
        self.gateway    = get_gateway()
        self.bus        = get_bus()
        self.logger     = get_logger(_ROLE_NAME)
        self.ex03       = ex03_connection
        self._target_symbols: List[str] = target_symbols or ["ETHUSDT"]

        self.bus.subscribe("decision.final", self._on_decision_received, role=_ROLE_CODE)

        self.execution_count:    int   = 0
        self.successful_count:   int   = 0
        self.failed_count:       int   = 0
        self.total_slippage_bps: float = 0.0
        self.execution_history: deque[ExecutionResult] = deque(maxlen=200)

    # ─── Message Bus Callback ─────────────────────────────────────────────────

    def _on_decision_received(self, message) -> None:
        payload = message.payload

        if isinstance(payload, dict):
            decision: ArbiterDecision = payload.get("decision")
            proposal: TradingProposal = payload.get("proposal")
        else:
            # payload が直接 ArbiterDecision の場合（proposal なし → 執行不可）
            decision = payload
            proposal = None

        if decision is None:
            return

        if decision.final_decision == "EXECUTE":
            if proposal is None:
                self.logger.error("收到 EXECUTE 決策但缺少 proposal，無法執行")
                return
            self.execute_decision(decision, proposal)
        elif decision.final_decision == "WAIT":
            self.logger.info(f"老王要求等待: {decision.reasoning}")
        elif decision.final_decision == "ABORT":
            self.logger.warning(f"老王取消執行: {decision.reasoning}")

    # ─── Core Execution ───────────────────────────────────────────────────────

    def execute_decision(
        self,
        decision: ArbiterDecision,
        proposal: TradingProposal,
    ) -> ExecutionResult:
        """
        執行單一仲裁決策。統計計數無論成功失敗都更新。
        """
        # 1. 驗證
        validation = self._validate_decision(decision, proposal)
        if not validation["valid"]:
            result = self._create_failed_result(decision, validation["reason"])
        elif _cfg.CURRENT_MODE == RunMode.DRY_RUN:
            # 2. DRY-RUN：模擬執行
            result = self._dry_run_execute(decision, proposal)
        else:
            # 3. 真實下單
            result = self._live_execute(decision, proposal)

        # 統計
        self.execution_count += 1
        self.execution_history.append(result)
        if result.status == "FILLED":
            self.successful_count += 1
            self.total_slippage_bps += (result.actual_slippage_pct or 0.0) * 100
        else:
            self.failed_count += 1

        return result

    # ─── Validation ──────────────────────────────────────────────────────────

    def _validate_decision(self, decision: ArbiterDecision, proposal: TradingProposal) -> dict:
        """執行前健康檢查，回傳 {"valid": bool, "reason": str}。"""
        if proposal.position_size_usd <= 0:
            return {"valid": False, "reason": "position_size_usd 必須 > 0"}

        if proposal.position_size_usd > MAX_POSITION_USD:
            return {"valid": False,
                    "reason": f"position_size_usd {proposal.position_size_usd} 超過上限 {MAX_POSITION_USD}"}

        if proposal.symbol not in self._target_symbols:
            return {"valid": False,
                    "reason": f"symbol {proposal.symbol} 不在允許清單 {self._target_symbols}"}

        # 止損合理性（僅在有入場價時驗證）
        if proposal.entry_price is not None and proposal.stop_loss is not None:
            if proposal.direction == "long" and proposal.stop_loss >= proposal.entry_price:
                return {"valid": False,
                        "reason": f"多單止損 {proposal.stop_loss} 應 < 入場價 {proposal.entry_price}"}
            if proposal.direction == "short" and proposal.stop_loss <= proposal.entry_price:
                return {"valid": False,
                        "reason": f"空單止損 {proposal.stop_loss} 應 > 入場價 {proposal.entry_price}"}

        return {"valid": True, "reason": ""}

    # ─── DRY-RUN ─────────────────────────────────────────────────────────────

    def _dry_run_execute(
        self,
        decision: ArbiterDecision,
        proposal: TradingProposal,
    ) -> ExecutionResult:
        """模擬執行，不真實下單。使用市價作為成交價，假設零滑價。"""
        market_price = self._get_current_price(proposal.symbol)
        side = "Buy" if proposal.direction == "long" else "Sell"

        result = ExecutionResult(
            execution_id=f"DRY-{uuid.uuid4()}",
            decision_id=decision.decision_id,
            status="FILLED",
            timestamp=datetime.now(timezone.utc),
            executed_price=market_price,
            executed_size=proposal.position_size_usd,
            actual_slippage_pct=0.0,
            exchange_order_id="DRY-RUN-ORDER",
        )

        self.ex03.update_known_position(proposal.symbol, {
            "symbol":      proposal.symbol,
            "size":        str(proposal.position_size_usd),
            "entry_price": str(market_price),
            "side":        side,
        })

        self.logger.info(
            f"[DRY-RUN] 模擬下單: {side} {proposal.position_size_usd} "
            f"{proposal.symbol} @ {market_price}"
        )
        self.bus.publish("execution.result", result, sender=_ROLE_CODE)
        return result

    # ─── Live Execution ───────────────────────────────────────────────────────

    def _live_execute(
        self,
        decision: ArbiterDecision,
        proposal: TradingProposal,
    ) -> ExecutionResult:
        """真實下單（僅在 LIVE-DEMO / LIVE-REAL 模式執行）。"""
        side       = "Buy" if proposal.direction == "long" else "Sell"
        order_type = "Market" if proposal.entry_type == "market" else "Limit"
        market_price = self._get_current_price(proposal.symbol)

        order_result = self.gateway.place_order(
            symbol=proposal.symbol,
            side=side,
            order_type=order_type,
            qty=str(proposal.position_size_usd),
            price=str(proposal.entry_price) if order_type == "Limit" and proposal.entry_price else None,
            stop_loss=str(proposal.stop_loss) if proposal.stop_loss else None,
        )

        if order_result["success"]:
            executed_price = float(order_result["data"].get("price") or market_price)
            slippage_bps   = self._calc_slippage(market_price, executed_price, side)
            order_id       = order_result["data"].get("orderId", "")

            self.ex03.update_known_position(proposal.symbol, {
                "symbol":      proposal.symbol,
                "size":        str(proposal.position_size_usd),
                "entry_price": str(executed_price),
                "side":        side,
            })

            result = ExecutionResult(
                execution_id=str(uuid.uuid4()),
                decision_id=decision.decision_id,
                status="FILLED",
                timestamp=datetime.now(timezone.utc),
                executed_price=executed_price,
                executed_size=proposal.position_size_usd,
                actual_slippage_pct=slippage_bps / 100,
                exchange_order_id=order_id,
            )
        else:
            result = self._create_failed_result(decision, order_result.get("error", "unknown"))

        self.bus.publish("execution.result", result, sender=_ROLE_CODE)
        return result

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _get_current_price(self, symbol: str) -> float:
        """取得最新市價（1 分 K 線最後一根的 close price）。"""
        kline = self.gateway.get_market_kline(symbol, "1", limit=1)
        if kline["success"]:
            try:
                return float(kline["data"]["list"][0][4])
            except (IndexError, KeyError, ValueError):
                return 0.0
        return 0.0

    def _calc_slippage(self, market_price: float, executed_price: float, side: str) -> float:
        """計算不利滑價（basis points，正值代表不利於策略）。"""
        if market_price == 0:
            return 0.0
        if side == "Buy":
            slippage_pct = (executed_price - market_price) / market_price
        else:
            slippage_pct = (market_price - executed_price) / market_price
        return slippage_pct * 10000

    def _create_failed_result(
        self,
        decision: ArbiterDecision,
        reason: str,
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id=str(uuid.uuid4()),
            decision_id=decision.decision_id,
            status="FAILED",
            timestamp=datetime.now(timezone.utc),
            error_message=reason,
        )

    # ─── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        recent_failures = [
            r.to_dict()
            for r in self.execution_history
            if r.status == "FAILED"
        ][-5:]
        return {
            "total_executions": self.execution_count,
            "success_rate":     round(self.successful_count / max(1, self.execution_count), 4),
            "avg_slippage_bps": round(self.total_slippage_bps / max(1, self.successful_count), 2),
            "recent_failures":  recent_failures,
        }
