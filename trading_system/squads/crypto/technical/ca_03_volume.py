# -*- coding: utf-8 -*-
"""ATC CA-03 小張+穎穎（量能分析 + 異常事件偵測）— 絕對 vs 情境雙人激辯組。"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.data_models import AnomalyEvent, DebateResult, SubReport
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class VolumeAnalyst:
    """通用量能分析員 — 小張和穎穎共用，差別在 mode。

    mode="absolute"    → 小張 CA-03a（絕對量化，快速反應）
    mode="contextual"  → 穎穎 CA-03b（時段調整，誤報少）
    """

    def __init__(self, mode: str, gateway=None, bus=None) -> None:
        assert mode in ("absolute", "contextual"), f"未知 mode: {mode}"
        self.mode    = mode
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()

        if mode == "absolute":
            self.role_name = "小張"
            self.role_code = "CA-03a"
        else:
            self.role_name = "穎穎"
            self.role_code = "CA-03b"

        self.logger = get_logger(self.role_name)

        self.flash_move_threshold   = 8.0   # %
        self.volume_spike_threshold = 4.0   # 倍（絕對）
        self.wide_range_threshold   = 10.0  # %

    # ─── Data fetch ───────────────────────────────────────────────────────────

    def fetch_klines(self, symbol: str = "ETHUSDT") -> dict:
        """取得 1H 和 1D K 線。"""
        result_1h = self.gateway.get_market_kline(symbol, "60", limit=48)
        result_1d = self.gateway.get_market_kline(symbol, "D",  limit=30)

        def _parse(result) -> list:
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
            except Exception:
                return []

        return {"1h": _parse(result_1h), "1d": _parse(result_1d)}

    # ─── Anomaly detection ────────────────────────────────────────────────────

    def detect_anomalies(self, klines: dict) -> list[AnomalyEvent]:
        if self.mode == "absolute":
            return self._detect_absolute(klines)
        return self._detect_contextual(klines)

    def _detect_absolute(self, klines: dict) -> list[AnomalyEvent]:
        """小張：用絕對閾值觸發異常。"""
        anomalies: list[AnomalyEvent] = []
        klines_1h = klines.get("1h", [])
        klines_1d = klines.get("1d", [])

        # FLASH_MOVE（最近 1H）
        if klines_1h:
            latest   = klines_1h[-1]
            change   = (latest["close"] - latest["open"]) / latest["open"] * 100
            if abs(change) >= self.flash_move_threshold:
                sev = self._calc_severity(abs(change), 8, 12, 20)
                anomalies.append(AnomalyEvent(
                    event_id      = f"FM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self.role_code}",
                    event_type    = "FLASH_MOVE",
                    symbol        = "ETHUSDT",
                    magnitude     = change,
                    severity      = sev,
                    timestamp     = datetime.now(),
                    triggered_alert = (sev >= 0.7),
                    direction     = "up" if change > 0 else "down",
                ))

        # VOLUME_SPIKE（最近 1H vs 前 24H 均量）
        if len(klines_1h) >= 25:
            latest_vol = klines_1h[-1]["volume"]
            avg_vol    = sum(k["volume"] for k in klines_1h[-25:-1]) / 24
            if avg_vol > 0:
                ratio = latest_vol / avg_vol
                if ratio >= self.volume_spike_threshold:
                    sev = self._calc_severity(ratio, 4, 6, 10)
                    anomalies.append(AnomalyEvent(
                        event_id      = f"VS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self.role_code}",
                        event_type    = "VOLUME_SPIKE",
                        symbol        = "ETHUSDT",
                        magnitude     = ratio,
                        severity      = sev,
                        timestamp     = datetime.now(),
                        triggered_alert = (sev >= 0.7),
                    ))

        # WIDE_RANGE（當日）
        if klines_1d:
            today     = klines_1d[-1]
            range_pct = (today["high"] - today["low"]) / today["open"] * 100
            if range_pct >= self.wide_range_threshold:
                sev = self._calc_severity(range_pct, 10, 15, 25)
                anomalies.append(AnomalyEvent(
                    event_id      = f"WR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self.role_code}",
                    event_type    = "WIDE_RANGE",
                    symbol        = "ETHUSDT",
                    magnitude     = range_pct,
                    severity      = sev,
                    timestamp     = datetime.now(),
                    triggered_alert = (sev >= 0.7),
                ))

        return anomalies

    def _detect_contextual(self, klines: dict) -> list[AnomalyEvent]:
        """穎穎：用同時段均量作基準，誤報更少。"""
        anomalies: list[AnomalyEvent] = []
        klines_1h = klines.get("1h", [])

        if len(klines_1h) < 2:
            return anomalies

        latest       = klines_1h[-1]
        current_hour = datetime.fromtimestamp(latest["timestamp"] / 1000).hour

        # 同時段歷史均量
        same_hour_volumes = [
            k["volume"] for k in klines_1h[:-1]
            if datetime.fromtimestamp(k["timestamp"] / 1000).hour == current_hour
        ]

        if same_hour_volumes:
            same_hour_avg = sum(same_hour_volumes) / len(same_hour_volumes)
            if same_hour_avg > 0:
                ratio = latest["volume"] / same_hour_avg
                if ratio >= 3:
                    sev = self._calc_severity(ratio, 3, 5, 8)
                    anomalies.append(AnomalyEvent(
                        event_id      = f"VS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self.role_code}",
                        event_type    = "VOLUME_SPIKE",
                        symbol        = "ETHUSDT",
                        magnitude     = ratio,
                        severity      = sev,
                        timestamp     = datetime.now(),
                        triggered_alert = (sev >= 0.7),
                    ))

        # FLASH_MOVE 與時段無關
        change = (latest["close"] - latest["open"]) / latest["open"] * 100
        if abs(change) >= self.flash_move_threshold:
            sev = self._calc_severity(abs(change), 8, 12, 20)
            anomalies.append(AnomalyEvent(
                event_id      = f"FM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self.role_code}",
                event_type    = "FLASH_MOVE",
                symbol        = "ETHUSDT",
                magnitude     = change,
                severity      = sev,
                timestamp     = datetime.now(),
                triggered_alert = (sev >= 0.7),
                direction     = "up" if change > 0 else "down",
            ))

        return anomalies

    # ─── Severity helper ──────────────────────────────────────────────────────

    def _calc_severity(
        self,
        value: float,
        low:   float,
        mid:   float,
        high:  float,
    ) -> float:
        """線性分段嚴重度 [0.5, 1.0]。"""
        if value < low:
            return 0.0
        if value < mid:
            return 0.5 + (value - low) / (mid - low) * 0.2
        if value < high:
            return 0.7 + (value - mid) / (high - mid) * 0.2
        return min(0.9 + (value - high) / high * 0.1, 1.0)

    # ─── Analyze ──────────────────────────────────────────────────────────────

    def analyze(self, symbol: str = "ETHUSDT") -> tuple[SubReport, list[AnomalyEvent]]:
        """回傳 (SubReport, anomalies)。"""
        klines = self.fetch_klines(symbol)

        if not klines.get("1h"):
            return SubReport(
                role_name      = self.role_name,
                role_code      = self.role_code,
                direction      = "neutral",
                sub_confidence = 0.1,
                reasoning      = "K 線資料不足",
                data_used      = {},
                timestamp      = datetime.now(),
                staleness_flag = True,
            ), []

        anomalies  = self.detect_anomalies(klines)
        klines_1h  = klines["1h"]
        signals: list[tuple[str, float, str]] = []

        # 量價健康判斷（五根短期 vs 前二十根）
        if len(klines_1h) >= 25:
            recent_5      = klines_1h[-5:]
            price_change  = (recent_5[-1]["close"] - recent_5[0]["open"]) / recent_5[0]["open"] * 100
            recent_vol    = sum(k["volume"] for k in recent_5) / 5
            older_vol     = sum(k["volume"] for k in klines_1h[-25:-5]) / 20

            if older_vol > 0:
                vol_ratio = recent_vol / older_vol
                if price_change > 1 and vol_ratio > 1.2:
                    signals.append(("bullish", 0.4, "量價齊揚（健康上漲）"))
                elif price_change > 1 and vol_ratio < 0.8:
                    signals.append(("bearish", 0.2, "量縮價漲（可能虛漲）"))
                elif price_change < -1 and vol_ratio > 1.2:
                    signals.append(("bearish", 0.4, "放量下跌（強勢空頭）"))
                elif price_change < -1 and vol_ratio < 0.8:
                    signals.append(("bullish", 0.2, "量縮下跌（可能止跌）"))

        # 異常事件影響方向
        for anomaly in anomalies:
            if anomaly.event_type == "FLASH_MOVE":
                if anomaly.direction == "up":
                    signals.append(("bearish", 0.2, f"急漲後可能回測 ({anomaly.magnitude:.1f}%)"))
                else:
                    signals.append(("bullish", 0.2, f"急跌後可能反彈 ({anomaly.magnitude:.1f}%)"))

        if not signals:
            direction  = "neutral"
            confidence = 0.3
            reasoning  = "量能訊號不顯著"
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

        if anomalies:
            reasoning += f" | 偵測到 {len(anomalies)} 個異常事件"

        report = SubReport(
            role_name      = self.role_name,
            role_code      = self.role_code,
            direction      = direction,
            sub_confidence = confidence,
            reasoning      = reasoning,
            data_used      = {
                "anomaly_count":   len(anomalies),
                "anomalies":       [a.to_dict() for a in anomalies],
                "kline_count_1h":  len(klines_1h),
            },
            timestamp      = datetime.now(),
            staleness_flag = False,
        )

        return report, anomalies


# ─── VolumeSection ────────────────────────────────────────────────────────────

class VolumeSection:
    """小張+穎穎雙人組統籌（CA-03 課）。"""

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("CA-03-Section")

        self.xiaozhang = VolumeAnalyst("absolute",    gateway=self.gateway, bus=self.bus)
        self.yingying  = VolumeAnalyst("contextual",  gateway=self.gateway, bus=self.bus)

        self.debate_history: deque[DebateResult] = deque(maxlen=50)
        self.published_anomaly_ids: set[str]     = set()

    # ─── Debate ───────────────────────────────────────────────────────────────

    def conduct_debate(self, symbol: str = "ETHUSDT") -> DebateResult:
        report_a, anomalies_a = self.xiaozhang.analyze(symbol)
        report_b, anomalies_b = self.yingying.analyze(symbol)

        self._publish_anomalies(anomalies_a, anomalies_b)

        consensus_type, final_direction, final_confidence, reasoning = \
            self._compare_reports(report_a, report_b)

        debate = DebateResult(
            debate_id          = f"CA-03-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
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

    def _publish_anomalies(
        self,
        anomalies_a: list[AnomalyEvent],
        anomalies_b: list[AnomalyEvent],
    ) -> None:
        """雙重確認加成 +0.1，避免重複發布。"""
        a_types = {(a.event_type, round(a.magnitude, 1)) for a in anomalies_a}
        b_types = {(a.event_type, round(a.magnitude, 1)) for a in anomalies_b}
        confirmed_keys = a_types & b_types

        for anomaly in anomalies_a:
            if anomaly.event_id in self.published_anomaly_ids:
                continue

            key = (anomaly.event_type, round(anomaly.magnitude, 1))
            if key in confirmed_keys:
                anomaly.severity = min(anomaly.severity + 0.1, 1.0)

            self.bus.publish("anomaly.detected", anomaly, sender="小張")
            self.published_anomaly_ids.add(anomaly.event_id)

            if anomaly.severity >= 0.7:
                self.logger.warning(
                    f"高嚴重度異常: {anomaly.event_type} sev={anomaly.severity:.2f}"
                )

    def _compare_reports(
        self,
        report_a: SubReport,
        report_b: SubReport,
    ) -> tuple[str, str, float, str]:
        """委派給通用雙人激辯引擎。"""
        from trading_system.common.debate_engine import compare_reports as _engine_compare
        result = _engine_compare(report_a, report_b, "小張", "穎穎")
        if result["consensus_type"] == "dual_track":
            self.logger.warning(f"CA-03 雙人大分歧: {result['reasoning']}")
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
            return f"方向分歧: 小張={report_a.direction} vs 穎穎={report_b.direction}"
        if abs(report_a.sub_confidence - report_b.sub_confidence) > 0.2:
            return (
                f"信心度差距: 小張={report_a.sub_confidence:.2f} "
                f"vs 穎穎={report_b.sub_confidence:.2f}"
            )
        return None
