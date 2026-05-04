# -*- coding: utf-8 -*-
"""ATC 小蘇（策略長）— 整合四課 CourseReport，產出 TradingProposal。"""
from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime
from typing import Optional

from trading_system.common.api_gateway import get_gateway
from trading_system.common.config import MAX_POSITION_USD
from trading_system.common.data_models import SnapshotBundle, TradingProposal
from trading_system.common.logger import get_logger
from trading_system.common.message_bus import get_bus


class StrategyDirector:
    role_name = "小蘇"
    role_code = "Strategy-Director"

    # ─── 環境 → 策略映射 ──────────────────────────────────────────────────────
    _ENV_STRATEGY: dict[str, str] = {
        "trending_bullish":  "trend_following",
        "trending_bearish":  "trend_following",
        "ranging":           "range_trading",
    }

    # ─── 策略 → 止損/止盈百分比 ───────────────────────────────────────────────
    _STRATEGY_PARAMS: dict[str, tuple[float, float]] = {
        "trend_following": (2.0, 4.0),  # stop_loss%, take_profit%
        "range_trading":   (1.0, 2.0),
    }

    def __init__(self, gateway=None, bus=None) -> None:
        self.gateway = gateway or get_gateway()
        self.bus     = bus or get_bus()
        self.logger  = get_logger("小蘇")

        from trading_system.common.snapshot_builder import get_snapshot_builder
        self.snapshot_builder = get_snapshot_builder()

        # 課別權重（架構文件 v4.1）
        self.weights: dict[str, float] = {
            "io": 0.30,
            "ca": 0.40,
            "ga": 0.20,
            "tk": 0.10,
        }

        self.proposal_interval  = 300   # 秒
        self.last_proposal_time: Optional[float] = None

        self.proposals_produced = 0
        self.recent_proposals: deque[TradingProposal] = deque(maxlen=50)

        self.bus.subscribe("strategy.request_proposal", self._on_request,  role="小蘇")
        self.bus.subscribe("anomaly.detected",           self._on_anomaly, role="小蘇")

    # ─── Bus callbacks ────────────────────────────────────────────────────────

    def _on_request(self, message) -> None:
        self.produce_proposal()

    def _on_anomaly(self, message) -> None:
        anomaly = message.payload
        if hasattr(anomaly, "severity") and anomaly.severity >= 0.7:
            self.logger.warning("異常觸發提案重新評估")
            self.produce_proposal(triggered_by="anomaly")

    # ─── 主流程 ───────────────────────────────────────────────────────────────

    def produce_proposal(self, triggered_by: str = "scheduled") -> Optional[TradingProposal]:
        """建快照 → 環境分類 → 計算分數 → 選策略 → 產出提案。"""
        snapshot = self.snapshot_builder.build_snapshot()

        if not self._is_snapshot_usable(snapshot):
            self.logger.warning("快照資料不足，跳過此次提案")
            return None

        environment = self._classify_environment(snapshot)
        composite_score, direction = self._compute_composite_score(snapshot)

        if not self._should_trade(snapshot, composite_score, environment):
            self.logger.info(
                f"當前不適合交易: env={environment}, score={composite_score:.2f}"
            )
            return None

        strategy = self._select_strategy(environment, direction)
        if strategy is None:
            self.logger.info("無匹配策略")
            return None

        proposal = self._build_proposal(
            snapshot, environment, direction, composite_score, strategy
        )
        if proposal is None:
            return None

        self.bus.publish("proposal.submitted", proposal, sender="小蘇")
        self.proposals_produced += 1
        self.recent_proposals.append(proposal)
        self.last_proposal_time = time.time()

        self.logger.info(
            f"提案: {direction} {proposal.symbol} @ {proposal.entry_price}, "
            f"size={proposal.position_size_usd:.1f}, env={environment}"
        )
        return proposal

    # ─── 快照可用性 ───────────────────────────────────────────────────────────

    def _is_snapshot_usable(self, snapshot: SnapshotBundle) -> bool:
        if not snapshot.io_report or not snapshot.ca_report:
            return False
        if snapshot.overall_data_quality == "degraded":
            return False
        return True

    # ─── 環境分類 ─────────────────────────────────────────────────────────────

    def _classify_environment(self, snapshot: SnapshotBundle) -> str:
        io_dir  = snapshot.io_report.course_direction  if snapshot.io_report  else "neutral"
        io_conf = snapshot.io_report.course_confidence if snapshot.io_report  else 0.0
        ca_dir  = snapshot.ca_report.course_direction  if snapshot.ca_report  else "neutral"
        ca_conf = snapshot.ca_report.course_confidence if snapshot.ca_report  else 0.0
        tk_dir  = snapshot.tk_report.course_direction  if snapshot.tk_report  else "neutral"

        # TK course_direction → tempo
        tempo = {"bullish": "active", "neutral": "cautious", "bearish": "rest"}.get(
            tk_dir, "cautious"
        )

        # 異常事件數
        anomaly_count = 0
        if snapshot.ca_report and snapshot.ca_report.data_health:
            anomaly_count = snapshot.ca_report.data_health.get("anomaly_events_count", 0)

        if tempo == "rest" or anomaly_count >= 2:
            return "high_volatility"

        if io_dir == ca_dir and io_dir != "neutral":
            avg_conf = (io_conf + ca_conf) / 2
            if avg_conf >= 0.5:
                return "trending_bullish" if io_dir == "bullish" else "trending_bearish"

        if (io_dir == "neutral" or io_conf < 0.4) and (ca_dir == "neutral" or ca_conf < 0.4):
            return "ranging"

        return "unclear"

    # ─── Composite score ──────────────────────────────────────────────────────

    def _compute_composite_score(self, snapshot: SnapshotBundle) -> tuple[float, str]:
        _dir_val = {"bullish": 1, "bearish": -1, "neutral": 0}

        scores: list[tuple[str, float, float]] = []
        active_weights: dict[str, float] = {}

        for key, attr in [("io", "io_report"), ("ca", "ca_report"), ("ga", "ga_report")]:
            report = getattr(snapshot, attr)
            if report is None:
                continue
            if report.freshness_grade == "stale":
                continue
            scores.append((key, _dir_val[report.course_direction], report.course_confidence))
            active_weights[key] = self.weights[key]

        if not scores:
            return 0.0, "neutral"

        total_w = sum(active_weights.values())
        norm    = {k: v / total_w for k, v in active_weights.items()}

        composite = sum(
            dir_val * conf * norm[key]
            for key, dir_val, conf in scores
        )

        if composite > 0.15:
            direction = "bullish"
        elif composite < -0.15:
            direction = "bearish"
        else:
            direction = "neutral"

        return composite, direction

    # ─── 交易可行性 ───────────────────────────────────────────────────────────

    def _should_trade(
        self, snapshot: SnapshotBundle, composite_score: float, environment: str
    ) -> bool:
        if environment in ("high_volatility", "unclear"):
            return False
        if abs(composite_score) < 0.2:
            return False
        if snapshot.tk_report and snapshot.tk_report.course_direction == "bearish":
            return False
        return True

    # ─── 策略選擇 ─────────────────────────────────────────────────────────────

    def _select_strategy(self, environment: str, direction: str) -> Optional[dict]:
        strategy_name = self._ENV_STRATEGY.get(environment)
        if strategy_name is None:
            return None
        return {"name": strategy_name, "description": {"trend_following": "趨勢跟隨",
                                                        "range_trading":   "區間交易"}[strategy_name]}

    # ─── 提案建構 ─────────────────────────────────────────────────────────────

    def _build_proposal(
        self,
        snapshot: SnapshotBundle,
        environment: str,
        direction: str,
        composite_score: float,
        strategy: dict,
    ) -> Optional[TradingProposal]:
        kline = self.gateway.get_market_kline("ETHUSDT", "1", limit=1)
        if not kline.get("success"):
            self.logger.warning("無法取得當前價格，跳過提案建構")
            return None
        try:
            current_price = float(kline["data"]["list"][0][4])
        except (KeyError, IndexError, TypeError, ValueError):
            self.logger.warning("K 線資料格式異常，跳過提案建構")
            return None

        # 倉位計算
        base_size = MAX_POSITION_USD * abs(composite_score)
        tk_factor = 1.0
        if snapshot.tk_report:
            tk_factor = {"bullish": 1.0, "neutral": 0.5, "bearish": 0.0}.get(
                snapshot.tk_report.course_direction, 0.5
            )
        position_size_usd = base_size * tk_factor

        # 止損止盈
        sl_pct, tp_pct = self._STRATEGY_PARAMS[strategy["name"]]
        if direction == "bullish":
            side        = "long"
            stop_loss   = current_price * (1 - sl_pct / 100)
            take_profit = current_price * (1 + tp_pct / 100)
        else:
            side        = "short"
            stop_loss   = current_price * (1 + sl_pct / 100)
            take_profit = current_price * (1 - tp_pct / 100)

        return TradingProposal(
            proposal_id          = str(uuid.uuid4()),
            symbol               = "ETHUSDT",
            direction            = side,
            entry_type           = "market",
            entry_price          = current_price,
            position_size_usd    = position_size_usd,
            leverage             = 1,
            stop_loss            = stop_loss,
            take_profit          = take_profit,
            composite_score      = composite_score,
            direction_confidence = abs(composite_score),
            environment_type     = environment,
            selected_strategy    = strategy["name"],
            reasoning            = self._build_reasoning(snapshot, environment, composite_score),
            based_on_snapshot    = snapshot.snapshot_id,
            timestamp            = datetime.now(),
        )

    def _build_reasoning(
        self, snapshot: SnapshotBundle, environment: str, composite_score: float
    ) -> str:
        parts = [
            f"環境: {environment}",
            f"composite: {composite_score:+.2f}",
            f"IO: {snapshot.io_report.course_direction if snapshot.io_report else 'N/A'}",
            f"CA: {snapshot.ca_report.course_direction if snapshot.ca_report else 'N/A'}",
            f"GA: {snapshot.ga_report.course_direction if snapshot.ga_report else 'N/A'}",
            f"TK: {snapshot.tk_report.course_direction if snapshot.tk_report else 'N/A'}",
        ]
        return " | ".join(parts)

    # ─── 週期觸發 ─────────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        now = time.time()
        if (self.last_proposal_time is None
                or now - self.last_proposal_time >= self.proposal_interval):
            self.produce_proposal()

    # ─── 狀態查詢 ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "role":              self.role_name,
            "proposals_produced": self.proposals_produced,
            "weights":           self.weights,
            "last_proposal_time": self.last_proposal_time,
        }
