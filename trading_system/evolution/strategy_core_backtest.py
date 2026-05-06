# -*- coding: utf-8 -*-
"""ATC Strategy Core Backtest — 策略核心第一層回測。"""
from __future__ import annotations

import time

from trading_system.common.api_gateway import get_gateway
from trading_system.common.logger import get_logger


class StrategyCoreBacktest:
    role_name = "Strategy-Core-Backtest"

    def __init__(self, gateway=None) -> None:
        self.gateway = gateway or get_gateway()
        self.logger  = get_logger("BACKTEST")

        self.initial_capital:  float = 200.0
        self.max_position_usd: float = 100.0

        self.trades:      list = []
        self.equity_curve: list = []
        self.bh_curve:    list = []

    # ─── 資料取得 ─────────────────────────────────────────────────────────────

    def fetch_historical_klines(self, days: int = 180) -> list:
        """分批抓取歷史 1H K 線（目標 days*24 根）。"""
        target_count  = days * 24
        all_klines: list = []
        end_timestamp = None

        while len(all_klines) < target_count:
            params: dict = {"limit": 1000}
            if end_timestamp:
                params["end"] = end_timestamp

            result = self.gateway.request(
                "GET", "/v5/market/kline",
                params={
                    "category": "spot",
                    "symbol":   "ETHUSDT",
                    "interval": "60",
                    **params,
                },
            )

            if not result.get("success"):
                break

            raw = result["data"].get("list", [])
            if not raw:
                break

            batch = []
            for k in raw:
                batch.append({
                    "timestamp": int(k[0]),
                    "open":      float(k[1]),
                    "high":      float(k[2]),
                    "low":       float(k[3]),
                    "close":     float(k[4]),
                    "volume":    float(k[5]),
                })

            all_klines.extend(batch)

            oldest_ts = batch[-1]["timestamp"]
            if end_timestamp and oldest_ts >= end_timestamp:
                break
            end_timestamp = oldest_ts - 1

            time.sleep(0.3)

        all_klines.sort(key=lambda k: k["timestamp"])
        self.logger.info(f"取得 {len(all_klines)} 根 1H K 線（目標 {target_count} 根）")
        return all_klines

    # ─── 指標計算 ─────────────────────────────────────────────────────────────

    def calculate_indicators(self, klines: list, current_idx: int) -> dict | None:
        """計算當前 K 線的指標（基於前面的歷史）。"""
        if current_idx < 50:
            return None

        recent = klines[max(0, current_idx - 200): current_idx + 1]
        if len(recent) < 30:
            return None

        closes = [k["close"] for k in recent]
        highs  = [k["high"]  for k in recent]
        lows   = [k["low"]   for k in recent]

        # MA 20 / MA 50
        ma_20 = sum(closes[-20:]) / 20
        ma_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None

        # RSI 14
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            diff = closes[-i] - closes[-i - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0
        rsi = 50 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

        # ATR 14
        true_ranges = []
        for i in range(1, min(15, len(recent))):
            tr = max(
                highs[-i] - lows[-i],
                abs(highs[-i]  - closes[-i - 1]),
                abs(lows[-i]   - closes[-i - 1]),
            )
            true_ranges.append(tr)
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0

        ma_200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None

        return {
            "current_price": closes[-1],
            "ma_20":         ma_20,
            "ma_50":         ma_50,
            "ma_200":        ma_200,
            "rsi_14":        rsi,
            "atr_14":        atr,
        }

    # ─── 方向判斷 ─────────────────────────────────────────────────────────────

    def derive_direction(self, ind: dict | None, use_trend_filter: bool = False) -> tuple[str, float]:
        """放寬版方向判斷，可選 MA200 趨勢過濾。"""
        if not ind:
            return "neutral", 0

        signals: list[tuple[str, float]] = []

        # RSI（門檻放寬）
        if ind["rsi_14"] < 35:
            signals.append(("bullish", 0.4))
        elif ind["rsi_14"] < 45:
            signals.append(("bullish", 0.2))
        elif ind["rsi_14"] > 65:
            signals.append(("bearish", 0.4))
        elif ind["rsi_14"] > 55:
            signals.append(("bearish", 0.2))

        # MA 完美排列
        if ind["ma_50"] and ind["current_price"] > ind["ma_20"] > ind["ma_50"]:
            signals.append(("bullish", 0.4))
        elif ind["ma_50"] and ind["current_price"] < ind["ma_20"] < ind["ma_50"]:
            signals.append(("bearish", 0.4))

        # 價格 vs MA20 距離
        if ind["ma_20"]:
            ma20_dist = (ind["current_price"] - ind["ma_20"]) / ind["ma_20"]
            if ma20_dist > 0.005:
                signals.append(("bullish", 0.2))
            elif ma20_dist < -0.005:
                signals.append(("bearish", 0.2))

        # 趨勢過濾：只允許順 MA200 方向的訊號
        if use_trend_filter and ind.get("ma_200"):
            if ind["current_price"] > ind["ma_200"]:
                signals = [s for s in signals if s[0] == "bullish"]
            elif ind["current_price"] < ind["ma_200"]:
                signals = [s for s in signals if s[0] == "bearish"]

        if not signals:
            return "neutral", 0

        bullish_w = sum(w for d, w in signals if d == "bullish")
        bearish_w = sum(w for d, w in signals if d == "bearish")

        if bullish_w > bearish_w * 1.2:
            return "bullish", min(bullish_w, 0.95)
        elif bearish_w > bullish_w * 1.2:
            return "bearish", min(bearish_w, 0.95)
        return "neutral", 0

    # ─── 主回測 ───────────────────────────────────────────────────────────────

    def run_backtest(
        self,
        use_trend_filter: bool = False,
        profit_loss_ratio_target: str = "balanced",
        min_confidence: float = 0.3,
    ) -> dict:
        """執行完整回測。"""
        klines = self.fetch_historical_klines()

        if len(klines) < 100:
            return {"success": False, "reason": "歷史資料不足"}

        if profit_loss_ratio_target == "wide":
            sl_pct = 0.015
            tp_pct = 0.05
        else:
            sl_pct = 0.02
            tp_pct = 0.04

        capital  = self.initial_capital
        position = None

        bh_initial_price = klines[50]["close"]
        bh_amount_eth    = self.initial_capital / bh_initial_price

        for i in range(50, len(klines)):
            current_kline = klines[i]
            current_price = current_kline["close"]

            # 1. 檢查現有倉位是否觸發止損 / 止盈
            if position:
                if position["direction"] == "long":
                    if current_kline["low"] <= position["stop_loss"]:
                        pnl = (
                            (position["stop_loss"] - position["entry_price"])
                            / position["entry_price"]
                            * position["size_usd"]
                        )
                        capital += pnl
                        self.trades.append({
                            **position,
                            "exit_idx":    i,
                            "exit_price":  position["stop_loss"],
                            "pnl_usd":     pnl,
                            "exit_reason": "stop_loss",
                        })
                        position = None
                    elif current_kline["high"] >= position["take_profit"]:
                        pnl = (
                            (position["take_profit"] - position["entry_price"])
                            / position["entry_price"]
                            * position["size_usd"]
                        )
                        capital += pnl
                        self.trades.append({
                            **position,
                            "exit_idx":    i,
                            "exit_price":  position["take_profit"],
                            "pnl_usd":     pnl,
                            "exit_reason": "take_profit",
                        })
                        position = None
                else:  # short
                    if current_kline["high"] >= position["stop_loss"]:
                        pnl = (
                            (position["entry_price"] - position["stop_loss"])
                            / position["entry_price"]
                            * position["size_usd"]
                        )
                        capital += pnl
                        self.trades.append({
                            **position,
                            "exit_idx":    i,
                            "exit_price":  position["stop_loss"],
                            "pnl_usd":     pnl,
                            "exit_reason": "stop_loss",
                        })
                        position = None
                    elif current_kline["low"] <= position["take_profit"]:
                        pnl = (
                            (position["entry_price"] - position["take_profit"])
                            / position["entry_price"]
                            * position["size_usd"]
                        )
                        capital += pnl
                        self.trades.append({
                            **position,
                            "exit_idx":    i,
                            "exit_price":  position["take_profit"],
                            "pnl_usd":     pnl,
                            "exit_reason": "take_profit",
                        })
                        position = None

            # 2. 沒有倉位時，評估是否進場
            if not position:
                ind = self.calculate_indicators(klines, i)
                direction, confidence = self.derive_direction(ind, use_trend_filter)

                if direction != "neutral" and confidence > min_confidence:
                    size_usd = self.max_position_usd * confidence
                    if size_usd > capital:
                        size_usd = capital * 0.5

                    if direction == "bullish":
                        stop_loss   = current_price * (1 - sl_pct)
                        take_profit = current_price * (1 + tp_pct)
                        pos_dir     = "long"
                    else:
                        stop_loss   = current_price * (1 + sl_pct)
                        take_profit = current_price * (1 - tp_pct)
                        pos_dir     = "short"

                    position = {
                        "direction":   pos_dir,
                        "entry_price": current_price,
                        "size_usd":    size_usd,
                        "entry_idx":   i,
                        "stop_loss":   stop_loss,
                        "take_profit": take_profit,
                    }

            # 3. 記錄權益曲線
            current_equity = capital
            if position:
                if position["direction"] == "long":
                    unrealized = (
                        (current_price - position["entry_price"])
                        / position["entry_price"]
                        * position["size_usd"]
                    )
                else:
                    unrealized = (
                        (position["entry_price"] - current_price)
                        / position["entry_price"]
                        * position["size_usd"]
                    )
                current_equity = capital + unrealized

            self.equity_curve.append({
                "idx":       i,
                "timestamp": current_kline["timestamp"],
                "equity":    current_equity,
            })
            self.bh_curve.append({
                "idx":   i,
                "value": bh_amount_eth * current_price,
            })

        # 強制平倉最後的倉位（用最後收盤價）
        if position:
            final_price = klines[-1]["close"]
            if position["direction"] == "long":
                pnl = (
                    (final_price - position["entry_price"])
                    / position["entry_price"]
                    * position["size_usd"]
                )
            else:
                pnl = (
                    (position["entry_price"] - final_price)
                    / position["entry_price"]
                    * position["size_usd"]
                )
            capital += pnl
            self.trades.append({
                **position,
                "exit_idx":    len(klines) - 1,
                "exit_price":  final_price,
                "pnl_usd":     pnl,
                "exit_reason": "force_close",
            })

        return self.compute_results(capital, klines)

    # ─── 結果計算 ─────────────────────────────────────────────────────────────

    def compute_results(self, final_capital: float, klines: list) -> dict:
        """計算回測統計結果。"""
        total_pnl        = final_capital - self.initial_capital
        total_return_pct = total_pnl / self.initial_capital * 100

        wins   = [t for t in self.trades if t["pnl_usd"] > 0]
        losses = [t for t in self.trades if t["pnl_usd"] <= 0]

        win_rate         = len(wins) / len(self.trades) if self.trades else 0
        avg_win          = sum(t["pnl_usd"] for t in wins)   / len(wins)   if wins   else 0
        avg_loss         = abs(sum(t["pnl_usd"] for t in losses) / len(losses)) if losses else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        expected_value   = win_rate * profit_loss_ratio

        # 最大回撤
        max_drawdown = 0.0
        peak = self.initial_capital
        for point in self.equity_curve:
            if point["equity"] > peak:
                peak = point["equity"]
            dd = (peak - point["equity"]) / peak * 100
            if dd > max_drawdown:
                max_drawdown = dd

        # vs Buy & Hold
        bh_final      = self.bh_curve[-1]["value"] if self.bh_curve else self.initial_capital
        bh_return_pct = (bh_final - self.initial_capital) / self.initial_capital * 100
        diff_vs_bh    = total_return_pct - bh_return_pct

        positive_expectancy  = expected_value > 1
        acceptable_vs_bh     = diff_vs_bh > -5
        acceptable_drawdown  = max_drawdown < 15

        results = {
            "success":            True,
            "passed":             positive_expectancy,
            "total_trades":       len(self.trades),
            "wins":               len(wins),
            "losses":             len(losses),
            "win_rate":           win_rate,
            "avg_win_usd":        avg_win,
            "avg_loss_usd":       avg_loss,
            "profit_loss_ratio":  profit_loss_ratio,
            "expected_value":     expected_value,
            "total_pnl_usd":      total_pnl,
            "total_return_pct":   total_return_pct,
            "max_drawdown_pct":   max_drawdown,
            "bh_return_pct":      bh_return_pct,
            "diff_vs_bh_pct":     diff_vs_bh,
            "criteria": {
                "positive_expectancy": positive_expectancy,
                "acceptable_vs_bh":    acceptable_vs_bh,
                "acceptable_drawdown": acceptable_drawdown,
            },
        }
        self._print_summary(results)
        return results

    def _print_summary(self, r: dict) -> None:
        self.logger.info("=" * 50)
        self.logger.info("策略核心回測結果")
        self.logger.info("=" * 50)
        self.logger.info(f"總交易次數: {r['total_trades']}")
        self.logger.info(f"勝率: {r['win_rate']*100:.1f}%")
        self.logger.info(f"平均盈利: ${r['avg_win_usd']:.2f}")
        self.logger.info(f"平均虧損: ${r['avg_loss_usd']:.2f}")
        self.logger.info(f"盈虧比: {r['profit_loss_ratio']:.2f}")
        self.logger.info(f"期望值: {r['expected_value']:.2f}（必須 > 1 才算正期望值）")
        self.logger.info(f"總報酬: {r['total_return_pct']:+.2f}%")
        self.logger.info(f"vs Buy & Hold: {r['diff_vs_bh_pct']:+.2f}%")
        self.logger.info(f"最大回撤: {r['max_drawdown_pct']:.2f}%")
        self.logger.info(f"通過判定: {'通過' if r['passed'] else '不通過'}")
        self.logger.info("=" * 50)
