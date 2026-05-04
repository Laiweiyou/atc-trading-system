# -*- coding: utf-8 -*-
"""ATC DM-02 蓉蓉+小方（資料品質守門員）— 雙人激辯組。"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus

_ROLE_SECTION = "DM-02-Section"


# ─── DataQualityAnalyst ───────────────────────────────────────────────────────

class DataQualityAnalyst:
    """
    通用品質檢查員 — 蓉蓉和小方共用，差別在 mode。

    mode="single_point" → 蓉蓉 DM-02a（單點異常型）
    mode="systemic"     → 小方 DM-02b（系統性異常型）
    """

    # 數據合理性範圍
    VALID_RANGES: dict[str, tuple] = {
        "eth_price":        (100, 100_000),
        "btc_price":        (1_000, 200_000),
        "funding_rate":     (-0.005, 0.005),
        "rsi":              (0, 100),
        "fgi":              (0, 100),
        "stablecoin_mcap":  (10_000_000_000, 1_000_000_000_000),
    }

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("single_point", "systemic"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "single_point":
            self.role_name = "蓉蓉"
            self.role_code = "DM-02a"
        else:
            self.role_name = "小方"
            self.role_code = "DM-02b"

        self.logger  = get_logger(self.role_name)
        self.history: deque[SubReport] = deque(maxlen=200)

    # ─── Public ───────────────────────────────────────────────────────────────

    def check_data(self, data_packet: dict) -> SubReport:
        if self.mode == "single_point":
            return self._single_point_check(data_packet)
        return self._systemic_check(data_packet)

    # ─── Single-Point (蓉蓉) ──────────────────────────────────────────────────

    def _single_point_check(self, data: dict) -> SubReport:
        """蓉蓉的視角：單筆數據逐欄位檢查。"""
        issues:   list[str] = []
        data_used = {"checked_fields": list(data.keys())}

        # 1. 數值合理性
        for field, value in data.items():
            if field in self.VALID_RANGES and isinstance(value, (int, float)):
                low, high = self.VALID_RANGES[field]
                if not (low <= value <= high):
                    issues.append(
                        f"{field}={value} 超出合理範圍 [{low}, {high}]"
                    )

        # 2. 時間戳檢查
        if "timestamp" in data:
            try:
                ts = data["timestamp"]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_seconds = (datetime.now(ts.tzinfo) - ts).total_seconds()
                if age_seconds < 0:
                    issues.append(f"時間戳在未來 {age_seconds:.0f}s")
                elif age_seconds > 600:
                    issues.append(f"資料過時 {age_seconds:.0f}s")
            except Exception as e:
                issues.append(f"時間戳格式錯誤: {e}")

        # 3. 連續性檢查（和 data["previous"] 比對）
        if self.history and "previous" in data:
            previous = data.get("previous", {})
            for field, current_val in data.items():
                if (
                    isinstance(current_val, (int, float))
                    and field in previous
                    and isinstance(previous[field], (int, float))
                ):
                    prev_val = previous[field]
                    if prev_val and abs(current_val - prev_val) / abs(prev_val) > 0.5:
                        issues.append(f"{field} 跳變 {prev_val} → {current_val}")

        # 綜合判斷
        if not issues:
            direction  = "bullish"
            confidence = 0.8
            reasoning  = "所有單點檢查通過"
        elif len(issues) == 1:
            direction  = "neutral"
            confidence = 0.5
            reasoning  = issues[0]
        else:
            direction  = "bearish"
            confidence = min(0.4 + len(issues) * 0.1, 0.95)
            reasoning  = "; ".join(issues)

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
        self.history.append(report)
        return report

    # ─── Systemic (小方) ──────────────────────────────────────────────────────

    def _systemic_check(self, data: dict) -> SubReport:
        """小方的視角：系統性多指標組合檢查。"""
        issues:   list[str] = []
        data_used: dict      = {"checked_systems": []}

        # 1. 多指標組合異常
        anomaly_count = 0
        normal_count  = 0
        for field, value in data.items():
            if field in self.VALID_RANGES and isinstance(value, (int, float)):
                low, high = self.VALID_RANGES[field]
                if low <= value <= high:
                    normal_count += 1
                else:
                    anomaly_count += 1

        if normal_count > 0 and anomaly_count == 1:
            issues.append(
                "單一欄位異常但其他正常，可能是真實事件而非系統錯誤"
            )
        elif anomaly_count >= 2:
            issues.append(
                f"{anomaly_count} 個欄位同時異常，疑似系統性問題"
            )

        # 2. RSS 健康記憶
        if "rss_status" in data:
            offline_count = sum(1 for v in data["rss_status"].values() if not v)
            data_used["rss_offline_count"] = offline_count
            if offline_count >= 3:
                issues.append(
                    f"{offline_count} 個 RSS 失效，疑似網路或 IP 被擋"
                )

        # 3. 爬蟲健康
        if "scraper_status" in data:
            failed = [k for k, v in data["scraper_status"].items() if not v]
            data_used["failed_scrapers"] = failed
            if len(failed) >= 2:
                issues.append(f"多個爬蟲失敗: {failed}")

        # 綜合判斷
        if not issues:
            direction  = "bullish"
            confidence = 0.7
            reasoning  = "系統性檢查未發現異常"
        else:
            direction  = "bearish"
            confidence = min(0.4 + len(issues) * 0.15, 0.95)
            reasoning  = "; ".join(issues)

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
        self.history.append(report)
        return report

    # ─── Maintenance (小方 only) ──────────────────────────────────────────────

    def daily_health_check_rss(self) -> dict:
        """每日驗證所有 RSS 是否可解析（僅 systemic 模式）。"""
        if self.mode != "systemic":
            return {}

        rss_urls = {
            "BBC World":          "https://feeds.bbci.co.uk/news/world/rss.xml",
            "Al Jazeera":         "https://www.aljazeera.com/xml/rss/all.xml",
            "CNBC World":         "https://www.cnbc.com/id/100727362/device/rss/rss.html",
            "BBC Business":       "https://feeds.bbci.co.uk/news/business/rss.xml",
            "NPR":                "https://feeds.npr.org/1001/rss.xml",
            "CoinDesk":           "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "CoinTelegraph":      "https://cointelegraph.com/rss",
            "Foreign Affairs":    "https://foreignaffairs.com/rss.xml",
            "Geopolitical Futures": "https://geopoliticalfutures.com/feed",
        }

        import feedparser
        results: dict[str, bool] = {}
        for name, url in rss_urls.items():
            try:
                feed          = feedparser.parse(url)
                results[name] = len(feed.entries) > 0
            except Exception:
                results[name] = False

        offline = [n for n, ok in results.items() if not ok]
        if offline:
            self.logger.warning(
                f"RSS 健康檢查：{len(offline)} 個失效 — {offline}"
            )

        return results

    def monthly_wallet_check(self, wallets: dict) -> dict:
        """每月驗證熱錢包活躍度（僅 systemic 模式）。"""
        if self.mode != "systemic":
            return {}

        results: dict[str, dict] = {}
        for name, _address in wallets.items():
            results[name] = {"active": True, "needs_verification": False}
        return results


# ─── DataQualitySection ───────────────────────────────────────────────────────

class DataQualitySection:
    """DM-02 資料品質課統籌（主管為小蔡 DM-Manager，此處為課級操作介面）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger(_ROLE_SECTION)

        self.rongrong = DataQualityAnalyst(
            "single_point", gateway=self.gateway, bus=self.bus
        )
        self.xiaofang = DataQualityAnalyst(
            "systemic", gateway=self.gateway, bus=self.bus
        )

        self.debate_history: deque[DebateResult] = deque(maxlen=50)

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self, data_packet: dict) -> DebateResult:
        report_a = self.rongrong.check_data(data_packet)
        report_b = self.xiaofang.check_data(data_packet)

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"DM-02-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
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
        result = _engine_compare(report_a, report_b, "蓉蓉", "小方")
        if result["consensus_type"] == "dual_track":
            self.logger.warning(f"DM-02 雙人大分歧: {result['reasoning']}")
        return (
            result["consensus_type"],
            result["final_direction"],
            result["final_confidence"],
            result["reasoning"],
        )

    def _identify_disagreement(
        self, report_a: SubReport, report_b: SubReport
    ) -> Optional[str]:
        if report_a.direction != report_b.direction:
            return (
                f"方向分歧: 蓉蓉={report_a.direction} vs 小方={report_b.direction}"
            )
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 蓉蓉={report_a.sub_confidence:.2f} "
                f"vs 小方={report_b.sub_confidence:.2f}"
            )
        return None

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        latest = self.debate_history[-1] if self.debate_history else None
        agreed = sum(
            1 for d in self.debate_history if d.consensus_type == "agreed"
        )
        return {
            "section":       _ROLE_SECTION,
            "debate_count":  len(self.debate_history),
            "latest_debate": latest.to_dict() if latest else None,
            "consensus_rate": (
                agreed / len(self.debate_history) if self.debate_history else 0.0
            ),
        }
