# -*- coding: utf-8 -*-
"""ATC API 閘道（DM-01 阿葉）— 所有 Bybit V5 API 呼叫的統一入口。"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
from collections import deque
from enum import Enum
from typing import Optional

import requests as _req

from trading_system.common.config import (
    BYBIT_BASE_URL, RECV_WINDOW, RATE_LIMIT, RATE_RESERVED, SCRAPER_TIMEOUT,
)
from trading_system.common.logger import get_logger


# ─── Priority ─────────────────────────────────────────────────────────────────

class Priority(Enum):
    CRITICAL = 1   # 下單、緊急平倉
    HIGH     = 2   # 持倉查詢、心跳
    MEDIUM   = 3   # K 線、資金費率
    LOW      = 4   # 歷史資料、背景監控


_PRIORITY_LIMITS: dict[Priority, int] = {
    Priority.CRITICAL: RATE_LIMIT,     # 120
    Priority.HIGH:     100,
    Priority.MEDIUM:   RATE_RESERVED,  # 80
    Priority.LOW:      60,
}

_MAX_WAIT_SEC = 5.0


# ─── APIGateway ───────────────────────────────────────────────────────────────

class APIGateway:
    def __init__(self) -> None:
        self.base_url          = BYBIT_BASE_URL
        self.api_key           = os.environ.get("BYBIT_API_KEY", "")
        self.api_secret        = os.environ.get("BYBIT_API_SECRET", "")
        self.rate_limit_per_min = RATE_LIMIT
        self.reserved_rate     = RATE_RESERVED
        self.request_history: deque[float] = deque(maxlen=200)
        self.logger            = get_logger("阿葉")

        self._total_requests   = 0
        self._by_priority      = {p.name: 0 for p in Priority}
        # (timestamp, priority_name, elapsed_ms, success)
        self._all_request_times: deque[tuple] = deque(maxlen=5000)
        self._error_times:       deque[float] = deque(maxlen=1000)

    # ── Rate limiting ────────────────────────────────────────────────────────

    def _can_send_request(self, priority: Priority) -> bool:
        now    = time.time()
        recent = sum(1 for t in self.request_history if now - t < 60)
        return recent < _PRIORITY_LIMITS[priority]

    def _wait_for_rate_limit(self, priority: Priority) -> None:
        deadline = time.time() + _MAX_WAIT_SEC
        while not self._can_send_request(priority):
            if time.time() >= deadline:
                raise RuntimeError(
                    f"速率限制：{priority.name} priority 等待 {_MAX_WAIT_SEC}s 後仍無法送出"
                )
            time.sleep(0.1)

    # ── Internal tracking ────────────────────────────────────────────────────

    def _record_request(self, priority: Priority, elapsed_ms: int,
                        success: bool = True) -> None:
        now = time.time()
        self.request_history.append(now)
        self._total_requests += 1
        self._by_priority[priority.name] += 1
        self._all_request_times.append((now, priority.name, elapsed_ms, success))
        if not success:
            self._error_times.append(now)

    # ── Authentication ───────────────────────────────────────────────────────

    def _build_auth_headers(self, method: str, params: Optional[dict]) -> dict:
        ts          = str(int(time.time() * 1000))
        recv_window = str(RECV_WINDOW)
        p           = params or {}

        if method.upper() == "GET":
            param_str = urllib.parse.urlencode(p)
        else:
            param_str = json.dumps(p, separators=(",", ":")) if p else ""

        sign_payload = ts + self.api_key + recv_window + param_str
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            sign_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-BAPI-API-KEY":      self.api_key,
            "X-BAPI-TIMESTAMP":    ts,
            "X-BAPI-SIGN":         signature,
            "X-BAPI-RECV-WINDOW":  recv_window,
            "Content-Type":        "application/json",
        }

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    # ── Core request ─────────────────────────────────────────────────────────

    def request(
        self,
        method:        str,
        endpoint:      str,
        params:        Optional[dict] = None,
        priority:      Priority       = Priority.MEDIUM,
        authenticated: bool           = False,
        retry_count:   int            = 2,
    ) -> dict:
        """
        統一請求方法。
        回傳: {"success": bool, "data": dict, "error": str, "elapsed_ms": int}
        """
        start = time.time()
        self._wait_for_rate_limit(priority)

        url     = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}

        if authenticated:
            if not self.is_configured():
                return {"success": False, "data": {}, "error": "API 未設定（缺少 key/secret）",
                        "elapsed_ms": 0}
            headers.update(self._build_auth_headers(method, params))

        last_error = ""
        for attempt in range(retry_count + 1):
            try:
                if method.upper() == "GET":
                    resp = _req.get(url, params=params, headers=headers,
                                    timeout=SCRAPER_TIMEOUT)
                else:
                    resp = _req.post(url, json=params, headers=headers,
                                     timeout=SCRAPER_TIMEOUT)

                try:
                    data = resp.json()
                except (ValueError, Exception):
                    data = {"retCode": -1,
                            "retMsg": f"HTTP {resp.status_code}: {resp.text[:120]}"}

                if data.get("retCode") == 0:
                    elapsed = int((time.time() - start) * 1000)
                    self._record_request(priority, elapsed, success=True)
                    return {
                        "success":    True,
                        "data":       data.get("result", {}),
                        "error":      "",
                        "elapsed_ms": elapsed,
                    }

                last_error = data.get("retMsg", f"retCode={data.get('retCode')}")
                self.logger.warning(
                    f"Bybit 錯誤 [{attempt+1}/{retry_count+1}]: {last_error} | {url}"
                )
                # 不重試驗證失敗
                if data.get("retCode") in (10003, 10004, 10006):
                    break

            except _req.exceptions.RequestException as exc:
                last_error = str(exc)
                self.logger.warning(
                    f"請求例外 [{attempt+1}/{retry_count+1}]: {exc}"
                )

            if attempt < retry_count:
                time.sleep(0.5 * (attempt + 1))

        elapsed = int((time.time() - start) * 1000)
        self._record_request(priority, elapsed, success=False)
        return {"success": False, "data": {}, "error": last_error, "elapsed_ms": elapsed}

    # ── Market data ──────────────────────────────────────────────────────────

    def get_server_time(self) -> dict:
        return self.request("GET", "/v5/market/time", priority=Priority.HIGH)

    def get_market_kline(self, symbol: str, interval: str, limit: int = 200) -> dict:
        return self.request("GET", "/v5/market/kline", params={
            "category": "spot", "symbol": symbol, "interval": interval, "limit": limit,
        })

    def get_funding_rate(self, symbol: str, limit: int = 48) -> dict:
        return self.request("GET", "/v5/market/funding/history", params={
            "category": "linear", "symbol": symbol, "limit": limit,
        })

    def get_open_interest(self, symbol: str, interval: str = "5min", limit: int = 48) -> dict:
        return self.request("GET", "/v5/market/open-interest", params={
            "category": "linear", "symbol": symbol, "intervalTime": interval, "limit": limit,
        })

    def get_account_ratio(self, symbol: str, period: str = "1h", limit: int = 24) -> dict:
        return self.request("GET", "/v5/market/account-ratio", params={
            "category": "linear", "symbol": symbol, "period": period, "limit": limit,
        })

    # ── Account / trading (authenticated) ────────────────────────────────────

    def get_account_balance(self) -> dict:
        return self.request("GET", "/v5/account/wallet-balance",
                            params={"accountType": "UNIFIED"},
                            authenticated=True)

    def get_positions(self, symbol: str = "ETHUSDT") -> dict:
        return self.request("GET", "/v5/position/list",
                            params={"category": "linear", "symbol": symbol},
                            authenticated=True)

    def place_order(
        self,
        symbol:     str,
        side:       str,
        order_type: str,
        qty:        str,
        price:      Optional[str] = None,
        stop_loss:  Optional[str] = None,
    ) -> dict:
        p: dict = {
            "category":  "spot",
            "symbol":    symbol,
            "side":      side,
            "orderType": order_type,
            "qty":       qty,
        }
        if price:
            p["price"] = price
        if stop_loss:
            p["stopLoss"] = stop_loss
        return self.request("POST", "/v5/order/create", params=p,
                            priority=Priority.CRITICAL, authenticated=True)

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        return self.request("POST", "/v5/order/cancel",
                            params={"category": "spot", "symbol": symbol, "orderId": order_id},
                            priority=Priority.CRITICAL, authenticated=True)

    # ── Stats & health ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        now      = time.time()
        last_min = [r for r in self._all_request_times if now - r[0] < 60]
        last_hr  = [r for r in self._all_request_times if now - r[0] < 3600]
        errors   = [t for t in self._error_times if now - t < 3600]
        times_ms = [r[2] for r in self._all_request_times]
        avg_ms   = round(sum(times_ms) / len(times_ms), 1) if times_ms else 0.0

        return {
            "total_requests":       self._total_requests,
            "requests_last_min":    len(last_min),
            "requests_last_hour":   len(last_hr),
            "current_rate_pct":     round(len(last_min) / self.rate_limit_per_min * 100, 1),
            "by_priority":          dict(self._by_priority),
            "errors_last_hour":     len(errors),
            "avg_response_time_ms": avg_ms,
        }

    def health_check(self) -> dict:
        result = self.get_server_time()
        if not result["success"]:
            return {"healthy": False, "reason": result["error"],
                    "elapsed_ms": result["elapsed_ms"]}

        server_sec = int(result["data"].get("timeSecond", 0))
        local_sec  = int(time.time())
        diff_ms    = abs(local_sec - server_sec) * 1000

        if diff_ms > 5000:
            return {"healthy": False,
                    "reason": f"時鐘偏差 {diff_ms}ms > 5000ms",
                    "time_diff_ms": diff_ms}

        return {"healthy": True, "time_diff_ms": diff_ms,
                "elapsed_ms": result["elapsed_ms"]}


# ─── Singleton ────────────────────────────────────────────────────────────────

_gateway_instance: Optional[APIGateway] = None


def get_gateway() -> APIGateway:
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = APIGateway()
    return _gateway_instance


def reset_gateway() -> None:
    """重設單例（測試用）。"""
    global _gateway_instance
    _gateway_instance = None
