# -*- coding: utf-8 -*-
"""ATC Hindsight Engine（事後驗證引擎）— 回填 SelfReview.hindsight_correct。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.feedback_models import SelfReview
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class HindsightEngine:
    role_name = "Hindsight Engine"
    role_code = "HINDSIGHT"

    # ─── 各角色驗證時間窗口（小時）───────────────────────────────────────────────
    VERIFICATION_WINDOWS: dict[str, int] = {
        # 短期（4h）
        "CA-01": 4, "CA-02": 4, "CA-03": 4,
        "EX-01": 4, "EX-02": 4, "EX-03": 4,
        "Risk-Officer": 4,
        # 中期（12h）
        "IO-01": 12, "IO-02": 12, "IO-03": 12,
        "AU-01": 12, "AU-02": 12, "AU-03": 12,
        "DM-02": 12, "DM-03": 12,
        "DM-Manager": 12, "IO-Manager": 12, "CA-Manager": 12,
        # 長期（24h）
        "GA-01": 24, "GA-02": 24, "GA-Manager": 24,
        # 節奏（8h）
        "TK-01": 8, "TK-02": 8, "TK-Manager": 8,
        # 決策層（8h）
        "Strategy-Director": 8, "Arbiter": 8,
    }
    DEFAULT_WINDOW_HOURS: int = 6

    # ─── 判斷門檻 ─────────────────────────────────────────────────────────────
    _STRONG_MOVE_PCT  = 0.5   # bullish/bearish 強方向門檻
    _NEUTRAL_BAND_PCT = 1.0   # neutral 允許的最大波動

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("HINDSIGHT")

        # key: review_id → {"review", "verify_at", "window_hours", "submitted_at"}
        self.pending_reviews: dict[str, dict] = {}

        # 統計
        self.reviews_received         = 0
        self.reviews_verified         = 0
        self.correct_count            = 0
        self.incorrect_count          = 0
        self.partial_count            = 0
        self.unverified_due_to_data   = 0

        self.bus.subscribe("feedback.submitted", self._on_review_submitted, role="HINDSIGHT")

    # ─── Bus callback ─────────────────────────────────────────────────────────

    def _on_review_submitted(self, message) -> None:
        review = message.payload
        if not isinstance(review, SelfReview):
            return

        window_hours = self.VERIFICATION_WINDOWS.get(
            review.role_code, self.DEFAULT_WINDOW_HOURS
        )
        verify_at = review.timestamp + timedelta(hours=window_hours)

        self.pending_reviews[review.review_id] = {
            "review":       review,
            "verify_at":    verify_at,
            "window_hours": window_hours,
            "submitted_at": time.time(),
        }
        self.reviews_received += 1

    # ─── 主驗證循環 ───────────────────────────────────────────────────────────

    def run_verification_cycle(self) -> int:
        """掃描到期的 reviews 並驗證；回傳本次驗證筆數。"""
        now         = datetime.now()
        to_verify   = [
            (rid, entry)
            for rid, entry in list(self.pending_reviews.items())
            if now >= entry["verify_at"]
        ]

        for rid, entry in to_verify:
            self._verify_review(entry["review"], entry["window_hours"])
            del self.pending_reviews[rid]

        return len(to_verify)

    # ─── 單筆驗證 ─────────────────────────────────────────────────────────────

    def _verify_review(self, review: SelfReview, window_hours: int) -> None:
        start_ts_ms = int(review.timestamp.timestamp() * 1000)
        end_ts_ms   = int(
            (review.timestamp + timedelta(hours=window_hours)).timestamp() * 1000
        )

        price_start, price_end = self._fetch_price_range(start_ts_ms, end_ts_ms)

        if price_start is None or price_end is None:
            self.unverified_due_to_data += 1
            review.hindsight_correct = "unverified"
            review.hindsight_notes   = "歷史價格資料不足"
            return

        change_pct = (price_end - price_start) / price_start * 100

        direction = self._parse_direction(review.my_call)
        if direction is None:
            review.hindsight_correct = "unverified"
            review.hindsight_notes   = "無法解析 my_call 方向"
            return

        result, notes = self._judge(direction, change_pct)
        review._mark(result, "HINDSIGHT_ENGINE", notes)

        self.reviews_verified += 1
        if result == "correct":
            self.correct_count += 1
        elif result == "incorrect":
            self.incorrect_count += 1
        else:
            self.partial_count += 1

        self.bus.publish("hindsight.verified", review, sender="HINDSIGHT")

    # ─── 方向解析 ─────────────────────────────────────────────────────────────

    def _parse_direction(self, my_call: str) -> Optional[str]:
        text = (my_call or "").lower()
        if "bullish" in text:
            return "bullish"
        if "bearish" in text:
            return "bearish"
        if "neutral" in text:
            return "neutral"
        return None

    # ─── 判定邏輯 ─────────────────────────────────────────────────────────────

    def _judge(self, direction: str, change_pct: float) -> tuple[str, str]:
        if direction == "bullish":
            if change_pct > self._STRONG_MOVE_PCT:
                return "correct",        f"bullish 判斷正確，實際漲 {change_pct:.2f}%"
            elif change_pct > 0:
                return "partial_correct", f"方向對但漲幅小 {change_pct:.2f}%"
            else:
                return "incorrect",      f"預期漲但實際 {change_pct:.2f}%"

        elif direction == "bearish":
            if change_pct < -self._STRONG_MOVE_PCT:
                return "correct",        f"bearish 判斷正確，實際跌 {change_pct:.2f}%"
            elif change_pct < 0:
                return "partial_correct", f"方向對但跌幅小 {change_pct:.2f}%"
            else:
                return "incorrect",      f"預期跌但實際 {change_pct:.2f}%"

        else:  # neutral
            if abs(change_pct) < self._NEUTRAL_BAND_PCT:
                return "correct",   f"neutral 判斷正確，實際變化 {change_pct:.2f}%"
            else:
                return "incorrect", f"預期持平但實際變化 {change_pct:.2f}%"

    # ─── 價格取得 ─────────────────────────────────────────────────────────────

    def _fetch_price_range(
        self, start_ts_ms: int, end_ts_ms: int
    ) -> tuple[Optional[float], Optional[float]]:
        """從 Bybit 1H K 線取得時間窗口的開始與結束價格。"""
        result = self.gateway.get_market_kline("ETHUSDT", "60", limit=200)
        if not result.get("success"):
            return None, None

        try:
            klines = list(reversed(result["data"].get("list", [])))
            price_start: Optional[float] = None
            price_end:   Optional[float] = None

            for k in klines:
                k_ts  = int(k[0])
                close = float(k[4])

                if price_start is None and k_ts >= start_ts_ms:
                    price_start = close
                if k_ts <= end_ts_ms:
                    price_end = close

            return price_start, price_end
        except Exception as exc:
            self.logger.warning(f"解析 K 線失敗: {exc}")
            return None, None

    # ─── 角色準確率查詢 ───────────────────────────────────────────────────────

    def get_role_accuracy(self, role_code: str) -> dict:
        """從 hindsight.verified 歷史計算某角色的加權準確率。"""
        history = self.bus.get_message_history("hindsight.verified", limit=500)

        role_reviews = [
            msg.payload for msg in history
            if hasattr(msg.payload, "role_code") and msg.payload.role_code == role_code
        ]

        if not role_reviews:
            return {"role_code": role_code, "verified_count": 0}

        correct   = sum(1 for r in role_reviews if r.hindsight_correct == "correct")
        partial   = sum(1 for r in role_reviews if r.hindsight_correct == "partial_correct")
        incorrect = sum(1 for r in role_reviews if r.hindsight_correct == "incorrect")
        total     = correct + partial + incorrect

        if total == 0:
            return {"role_code": role_code, "verified_count": 0}

        return {
            "role_code":       role_code,
            "verified_count":  total,
            "correct_rate":    correct  / total,
            "partial_rate":    partial  / total,
            "incorrect_rate":  incorrect / total,
            "weighted_score":  (correct + partial * 0.5) / total,
        }

    # ─── 統計查詢 ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        verified = max(1, self.reviews_verified)
        return {
            "reviews_received":       self.reviews_received,
            "reviews_verified":       self.reviews_verified,
            "pending_count":          len(self.pending_reviews),
            "correct_count":          self.correct_count,
            "partial_count":          self.partial_count,
            "incorrect_count":        self.incorrect_count,
            "unverified_due_to_data": self.unverified_due_to_data,
            "overall_accuracy":       (self.correct_count + self.partial_count * 0.5) / verified,
        }
