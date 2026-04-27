# -*- coding: utf-8 -*-
"""ATC EX-03 芬姐（連線維護員）— 心跳檢測、持倉同步、連線健康管理。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

from trading_system.common.api_gateway import APIGateway, get_gateway
from trading_system.common.flash_alert import FlashAlert, send_flash
from trading_system.common.logger import get_logger

_ROLE_NAME = "芬姐"
_ROLE_CODE  = "EX-03"

# 心跳每 30 秒觸發一次，持倉同步每 60 秒一次
_HEARTBEAT_INTERVAL_SEC  = 30
_POSITION_INTERVAL_SEC   = 60

# 連線品質參數
_SPIKE_MULTIPLIER         = 1.5   # 當前延遲 > 5 期平均 × 1.5 → 視為 spike
_SPIKE_WINDOW             = 5     # 用最近 N 筆計算基準平均
_CONSECUTIVE_FAIL_ALERT   = 3     # 連續失敗 N 次 → critical 快報


class ConnectionMaintainer:
    """
    EX-03 芬姐：維護與交易所的連線品質，並監控持倉一致性。

    職責：
      - 定時心跳：量測延遲、偵測 spike、連續失敗告警
      - 持倉同步：比對 known_positions 與交易所回傳，發現差異即告警
      - 提供 get_health_status() 供其他模組查詢連線狀態
    """

    def __init__(self, gateway: Optional[APIGateway] = None) -> None:
        self.gateway: APIGateway = gateway or get_gateway()
        self.logger = get_logger(_ROLE_NAME)

        # 心跳歷史 (latency_ms, success, timestamp)
        self.heartbeat_history: deque[dict] = deque(maxlen=500)

        self.consecutive_failures: int = 0
        self.last_heartbeat_time: float = 0.0
        self.last_position_check: float = 0.0

        # 已知持倉 {symbol: position_data_dict}
        self.known_positions: Dict[str, dict] = {}
        self._positions_initialized: bool = False
        self.position_sync_status: str = "unknown"

    # ─── Heartbeat ────────────────────────────────────────────────────────────

    def do_heartbeat(self) -> dict:
        """
        向交易所發送一次 get_server_time()，記錄延遲並評估連線品質。

        回傳 {"status": "ok"|"slow"|"critical"|"failed", "latency_ms": int}
        """
        result = self.gateway.get_server_time()
        # 優先使用 API gateway 回報的 elapsed_ms（更準確且 mock 友好）
        latency_ms = result.get("elapsed_ms", 0)
        now_ts = time.time()
        self.last_heartbeat_time = now_ts

        if not result["success"]:
            self.consecutive_failures += 1
            self.heartbeat_history.append({
                "latency_ms": latency_ms, "success": False, "timestamp": now_ts,
            })
            self.logger.warning(
                f"心跳失敗（連續第 {self.consecutive_failures} 次）: {result.get('error', '')}"
            )

            if self.consecutive_failures >= _CONSECUTIVE_FAIL_ALERT:
                self._send_critical_alert(
                    f"心跳連續失敗 {self.consecutive_failures} 次，交易所連線異常"
                )
                return {"status": "critical", "latency_ms": latency_ms}

            return {"status": "failed", "latency_ms": latency_ms}

        # 成功
        self.consecutive_failures = 0
        self.heartbeat_history.append({
            "latency_ms": latency_ms, "success": True, "timestamp": now_ts,
        })

        is_spike = self._check_latency_spike(latency_ms)
        if is_spike:
            self.logger.warning(f"延遲 spike 偵測：{latency_ms}ms")
            return {"status": "slow", "latency_ms": latency_ms}

        self.logger.debug(f"心跳正常：{latency_ms}ms")
        return {"status": "ok", "latency_ms": latency_ms}

    def _check_latency_spike(self, current_ms: int) -> bool:
        """若最近 _SPIKE_WINDOW 筆成功心跳的平均延遲 × _SPIKE_MULTIPLIER < current_ms → True。"""
        recent_ok = [
            h["latency_ms"] for h in self.heartbeat_history
            if h["success"]
        ]
        # 需要至少 _SPIKE_WINDOW 筆才計算基準
        if len(recent_ok) < _SPIKE_WINDOW:
            return False
        baseline = sum(recent_ok[-_SPIKE_WINDOW:]) / _SPIKE_WINDOW
        return current_ms > baseline * _SPIKE_MULTIPLIER

    def _send_critical_alert(self, message: str) -> None:
        alert = FlashAlert(
            alert_id=str(uuid.uuid4()),
            alert_type="EX_FAIL",
            alert_level="critical",
            sender=_ROLE_CODE,
            title="交易所連線異常",
            message=message,
            target_recipients=["宏哥", "怡姐"],
            related_data={"consecutive_failures": self.consecutive_failures},
            timestamp=datetime.now(timezone.utc),
            requires_acknowledgment=True,
        )
        send_flash(alert)
        self.logger.critical(f"[{_ROLE_CODE}] CRITICAL 快報已發送：{message}")

    # ─── Position Sync ────────────────────────────────────────────────────────

    def check_positions(self) -> dict:
        """
        向交易所查詢最新持倉，與 known_positions 比對。

        首次呼叫：初始化 known_positions，回傳 status="initialized"。
        後續呼叫：比對差異，有差異則發送 FlashAlert 給宏哥/怡姐。

        回傳 {"status": "synced"|"discrepancy"|"initialized"|"api_error",
              "exchange_positions": list, "discrepancies": list}
        """
        self.last_position_check = time.time()
        result = self.gateway.get_positions()

        if not result["success"]:
            self.position_sync_status = "api_error"
            self.logger.warning(f"持倉查詢失敗：{result.get('error', '')}")
            return {"status": "api_error", "exchange_positions": [], "discrepancies": []}

        exchange_list: List[dict] = result["data"].get("list", [])

        if not self._positions_initialized:
            # 首次初始化
            self.known_positions = {
                pos["symbol"]: pos for pos in exchange_list
            }
            self._positions_initialized = True
            self.position_sync_status = "synced"
            self.logger.info(f"持倉初始化完成，共 {len(self.known_positions)} 個持倉")
            return {
                "status": "initialized",
                "exchange_positions": exchange_list,
                "discrepancies": [],
            }

        # 比對差異
        discrepancies: List[dict] = []
        exchange_map = {pos["symbol"]: pos for pos in exchange_list}
        all_symbols = set(self.known_positions) | set(exchange_map)

        for symbol in all_symbols:
            known = self.known_positions.get(symbol)
            exchange = exchange_map.get(symbol)
            if known != exchange:
                discrepancies.append({
                    "symbol":   symbol,
                    "known":    known,
                    "exchange": exchange,
                })

        if discrepancies:
            self.position_sync_status = "discrepancy"
            self.logger.warning(f"持倉不一致：{len(discrepancies)} 個差異")
            self._send_position_alert(discrepancies)
            return {
                "status": "discrepancy",
                "exchange_positions": exchange_list,
                "discrepancies": discrepancies,
            }

        self.position_sync_status = "synced"
        self.logger.debug("持倉同步正常")
        return {"status": "synced", "exchange_positions": exchange_list, "discrepancies": []}

    def _send_position_alert(self, discrepancies: List[dict]) -> None:
        symbols = [d["symbol"] for d in discrepancies]
        alert = FlashAlert(
            alert_id=str(uuid.uuid4()),
            alert_type="ANOMALY_FLASH",
            alert_level="critical",
            sender=_ROLE_CODE,
            title="持倉不一致警告",
            message=f"偵測到 {len(discrepancies)} 個持倉差異：{symbols}",
            target_recipients=["宏哥", "怡姐"],
            related_data={"discrepancies": discrepancies},
            timestamp=datetime.now(timezone.utc),
            requires_acknowledgment=True,
        )
        send_flash(alert)

    def update_known_position(self, symbol: str, position_data: dict) -> None:
        """執行器下單後呼叫，同步更新本地已知持倉。"""
        self.known_positions[symbol] = position_data
        self.logger.debug(f"已知持倉更新：{symbol} → {position_data}")

    # ─── Health Status ────────────────────────────────────────────────────────

    def get_health_status(self) -> dict:
        """
        回傳連線健康摘要：
          avg_latency_ms        — 最近 10 筆成功心跳的平均延遲
          p99_latency_ms        — 全部成功心跳的 P99 延遲
          success_rate          — 全部心跳的成功率（0.0~1.0）
          consecutive_failures  — 目前連續失敗次數
          last_heartbeat_age_seconds — 距離上次心跳的秒數（-1 = 從未心跳）
          position_sync_status  — "synced"|"discrepancy"|"api_error"|"unknown"
        """
        all_hb = list(self.heartbeat_history)
        ok_ms  = [h["latency_ms"] for h in all_hb if h["success"]]
        total  = len(all_hb)

        # avg（最近 10）
        recent_ok = ok_ms[-10:] if len(ok_ms) >= 10 else ok_ms
        avg_latency = round(sum(recent_ok) / len(recent_ok), 1) if recent_ok else 0.0

        # P99（全部）
        if ok_ms:
            sorted_ms = sorted(ok_ms)
            idx = max(0, int(len(sorted_ms) * 0.99) - 1)
            p99_latency = sorted_ms[idx]
        else:
            p99_latency = 0

        success_rate = round(len(ok_ms) / total, 4) if total > 0 else 1.0

        if self.last_heartbeat_time > 0:
            age_sec = round(time.time() - self.last_heartbeat_time, 1)
        else:
            age_sec = -1

        return {
            "avg_latency_ms":           avg_latency,
            "p99_latency_ms":           p99_latency,
            "success_rate":             success_rate,
            "consecutive_failures":     self.consecutive_failures,
            "last_heartbeat_age_seconds": age_sec,
            "position_sync_status":     self.position_sync_status,
        }

    # ─── Run Cycle ────────────────────────────────────────────────────────────

    def run_cycle(self) -> dict:
        """
        主循環驅動：距上次心跳 ≥ 30s → 執行 do_heartbeat()
                    距上次持倉檢查 ≥ 60s → 執行 check_positions()

        回傳 {"heartbeat": dict|None, "positions": dict|None}
        """
        now = time.time()
        hb_result  = None
        pos_result = None

        if now - self.last_heartbeat_time >= _HEARTBEAT_INTERVAL_SEC:
            hb_result = self.do_heartbeat()

        if now - self.last_position_check >= _POSITION_INTERVAL_SEC:
            pos_result = self.check_positions()

        return {"heartbeat": hb_result, "positions": pos_result}
