# -*- coding: utf-8 -*-
import sys
import io
import os
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.squads.crypto.execution.ex_01_normal_order import NormalOrderExecutor
from trading_system.squads.crypto.execution.ex_03_connection import ConnectionMaintainer
from trading_system.common.data_models import ArbiterDecision, ExecutionResult, TradingProposal
from trading_system.common.message_bus import get_bus
from trading_system.common.flash_alert import reset_flash_state
import trading_system.common.config as _cfg
from trading_system.common.config import RunMode

SECTION = '=' * 65
passed = 0
failed = 0


def check(condition: bool, msg: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f'  [PASS] {msg}')
    else:
        failed += 1
        print(f'  [FAIL] {msg}')


# ─── 工廠函式 ─────────────────────────────────────────────────────────────────

def make_gateway(price: float = 3500.0):
    gw = MagicMock()
    kline_data = [["ts", "open", "high", "low", str(price), "volume"]]
    gw.get_market_kline.return_value = {
        "success": True,
        "data": {"list": kline_data},
        "elapsed_ms": 30,
        "error": "",
    }
    gw.get_server_time.return_value = {
        "success": True,
        "data": {"timeSecond": str(int(time.time()))},
        "elapsed_ms": 20,
        "error": "",
    }
    gw.get_positions.return_value = {
        "success": True,
        "data": {"list": []},
        "elapsed_ms": 25,
        "error": "",
    }
    gw.place_order.return_value = {
        "success": True,
        "data": {"orderId": "LIVE-123", "price": str(price)},
        "elapsed_ms": 50,
        "error": "",
    }
    return gw


def make_decision(final_decision: str = "EXECUTE", reasoning: str = "測試") -> ArbiterDecision:
    return ArbiterDecision(
        decision_id=str(uuid.uuid4()),
        proposal_id=str(uuid.uuid4()),
        assessment_id=str(uuid.uuid4()),
        final_decision=final_decision,
        tempo_factor=1.0,
        tendency_coefficient=0.8,
        reasoning=reasoning,
        timestamp=datetime.now(timezone.utc),
    )


def make_proposal(
    symbol: str = "ETHUSDT",
    direction: str = "long",
    entry_type: str = "market",
    position_size_usd: float = 50.0,
    stop_loss: float = 3400.0,
    entry_price: float = None,
    take_profit: float = None,
) -> TradingProposal:
    return TradingProposal(
        proposal_id=str(uuid.uuid4()),
        symbol=symbol,
        direction=direction,
        entry_type=entry_type,
        position_size_usd=position_size_usd,
        stop_loss=stop_loss,
        composite_score=75.0,
        direction_confidence=0.75,
        environment_type="trending",
        selected_strategy="trend_following",
        reasoning="測試",
        based_on_snapshot=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        entry_price=entry_price,
        take_profit=take_profit,
    )


def make_executor(price: float = 3500.0, target_symbols=None):
    gw = make_gateway(price)
    ex03 = ConnectionMaintainer(gateway=gw)
    executor = NormalOrderExecutor(
        ex03_connection=ex03,
        target_symbols=target_symbols or ["ETHUSDT"],
    )
    # patch executor.gateway to use same mock
    executor.gateway = gw
    return executor, ex03


def reset():
    reset_flash_state()
    get_bus().clear()


# ─── [1] 初始化 ────────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] 初始化與屬性')
print(SECTION)

reset()
executor, ex03 = make_executor()

check(executor.execution_count == 0,       'execution_count 初始為 0')
check(executor.successful_count == 0,      'successful_count 初始為 0')
check(executor.failed_count == 0,          'failed_count 初始為 0')
check(executor.total_slippage_bps == 0.0,  'total_slippage_bps 初始為 0.0')
check(len(executor.execution_history) == 0, 'execution_history 初始為空')
check("ETHUSDT" in executor._target_symbols, 'target_symbols 含 ETHUSDT')

# ─── [2] DRY-RUN 模式下單 ─────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] DRY-RUN 模式執行（市場多單）')
print(SECTION)

reset()
check(_cfg.CURRENT_MODE == RunMode.DRY_RUN, '確認當前為 DRY-RUN 模式')

executor, ex03 = make_executor(price=3500.0)
decision  = make_decision("EXECUTE")
proposal  = make_proposal(direction="long", position_size_usd=50.0, stop_loss=3400.0)

result = executor.execute_decision(decision, proposal)

check(isinstance(result, ExecutionResult),  '回傳 ExecutionResult 實例')
check(result.status == "FILLED",            f'status=FILLED（實際: {result.status}）')
check(result.executed_price == 3500.0,      f'executed_price=3500.0（實際: {result.executed_price}）')
check(result.executed_price > 0,            'executed_price > 0')
check(result.execution_id.startswith("DRY-"), f'execution_id 以 DRY- 開頭（實際: {result.execution_id[:10]}）')
check(result.decision_id == decision.decision_id, 'decision_id 正確')
check(result.actual_slippage_pct == 0.0,    'DRY-RUN 滑價 == 0')
check(result.exchange_order_id == "DRY-RUN-ORDER", 'exchange_order_id == DRY-RUN-ORDER')

# 確認芬姐的 known_positions 被更新
check("ETHUSDT" in ex03.known_positions,    '芬姐 known_positions 已含 ETHUSDT')

# 確認 execution.result 被廣播
bus_msgs = get_bus().get_message_history("execution.result")
check(len(bus_msgs) >= 1,                   'execution.result 已廣播至 bus')

# 統計更新
check(executor.execution_count == 1,        'execution_count == 1')
check(executor.successful_count == 1,       'successful_count == 1')
check(executor.failed_count == 0,           'failed_count == 0')

# ─── [3] 訂閱機制 ─────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] 訂閱機制：bus 發送 EXECUTE 決策')
print(SECTION)

reset()
executor, ex03 = make_executor(price=3600.0)
decision  = make_decision("EXECUTE")
proposal  = make_proposal(direction="long", position_size_usd=40.0, stop_loss=3500.0)

before_count = executor.execution_count

# 透過 bus 發送（payload 格式符合 executor 期望）
get_bus().publish(
    "decision.final",
    payload={"decision": decision, "proposal": proposal},
    sender="老王",
)

# callback 應同步觸發
check(executor.execution_count == before_count + 1,
      'bus 發送後 callback 同步觸發，execution_count 增加')

bus_results = get_bus().get_message_history("execution.result")
check(len(bus_results) >= 1, 'execution.result 已廣播')

# ─── [4] WAIT 決策 ────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] WAIT 決策：不執行下單')
print(SECTION)

reset()
executor, ex03 = make_executor()
before_count = executor.execution_count

decision_wait = make_decision("WAIT", reasoning="市場不明朗，等待")
get_bus().publish(
    "decision.final",
    payload={"decision": decision_wait, "proposal": make_proposal()},
    sender="老王",
)

check(executor.execution_count == before_count, 'WAIT 不增加 execution_count')
bus_results = get_bus().get_message_history("execution.result")
check(len(bus_results) == 0, 'WAIT 不廣播 execution.result')

# ─── [5] ABORT 決策 ───────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] ABORT 決策：不執行下單')
print(SECTION)

reset()
executor, ex03 = make_executor()
before_count = executor.execution_count

decision_abort = make_decision("ABORT", reasoning="風控攔截")
get_bus().publish(
    "decision.final",
    payload={"decision": decision_abort, "proposal": make_proposal()},
    sender="老王",
)

check(executor.execution_count == before_count, 'ABORT 不增加 execution_count')

# ─── [6] 止損不合理驗證（多單 stop_loss >= entry_price）────────────────────────

print(f'\n{SECTION}')
print('  [6] 驗證失敗：多單止損 >= 入場價')
print(SECTION)

reset()
executor, ex03 = make_executor()

# Limit 單有 entry_price，止損不合理
bad_proposal = make_proposal(
    direction="long",
    entry_type="limit",
    entry_price=3500.0,
    stop_loss=3600.0,   # 止損 > 入場價 → 不合理
    position_size_usd=50.0,
)
result = executor.execute_decision(make_decision(), bad_proposal)

check(result.status == "FAILED",        f'止損不合理 → FAILED（實際: {result.status}）')
check(result.error_message is not None, '有 error_message')
check("止損" in result.error_message or "stop_loss" in result.error_message.lower(),
      f'error_message 提及止損（實際: {result.error_message}）')
check(executor.failed_count == 1,       'failed_count == 1')
check(executor.execution_count == 1,    'execution_count 仍計入')

# ─── [7] 空單止損不合理 ──────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] 驗證失敗：空單止損 <= 入場價')
print(SECTION)

reset()
executor, ex03 = make_executor()

bad_proposal_short = make_proposal(
    direction="short",
    entry_type="limit",
    entry_price=3500.0,
    stop_loss=3400.0,   # 止損 < 入場價 → 空單不合理
    position_size_usd=50.0,
)
result = executor.execute_decision(make_decision(), bad_proposal_short)
check(result.status == "FAILED", f'空單止損不合理 → FAILED（實際: {result.status}）')

# ─── [8] 倉位超限 ─────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [8] 驗證失敗：position_size_usd 超過 MAX_POSITION_USD')
print(SECTION)

reset()
executor, ex03 = make_executor()

from trading_system.common.config import MAX_POSITION_USD
oversized = make_proposal(position_size_usd=MAX_POSITION_USD + 1.0)
result = executor.execute_decision(make_decision(), oversized)

check(result.status == "FAILED",        f'超限 → FAILED（實際: {result.status}）')
check(str(MAX_POSITION_USD) in result.error_message or "超過" in result.error_message,
      f'error_message 含限額資訊（實際: {result.error_message}）')

# ─── [9] symbol 不在允許清單 ──────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [9] 驗證失敗：symbol 不在 target_symbols')
print(SECTION)

reset()
executor, ex03 = make_executor()

bad_symbol = make_proposal(symbol="BTCUSDT")
result = executor.execute_decision(make_decision(), bad_symbol)
check(result.status == "FAILED", f'BTCUSDT 不在允許清單 → FAILED（實際: {result.status}）')
check("BTCUSDT" in result.error_message, f'error 含 symbol 資訊（實際: {result.error_message}）')

# ─── [10] 混合結果統計（3 成功 + 2 失敗）─────────────────────────────────────

print(f'\n{SECTION}')
print('  [10] 統計功能：混合執行結果')
print(SECTION)

reset()
executor, ex03 = make_executor(price=3500.0)

# 3 筆成功
for _ in range(3):
    proposal = make_proposal(direction="long", stop_loss=3400.0)
    executor.execute_decision(make_decision(), proposal)

# 2 筆失敗（倉位超限）
for _ in range(2):
    bad = make_proposal(position_size_usd=MAX_POSITION_USD + 10.0)
    executor.execute_decision(make_decision(), bad)

stats = executor.get_stats()
print(f'  stats: {stats}')

check(stats["total_executions"] == 5,          f'total_executions == 5（實際: {stats["total_executions"]}）')
check(stats["success_rate"] == 0.6,            f'success_rate == 0.6（實際: {stats["success_rate"]}）')
check(isinstance(stats["avg_slippage_bps"], float), 'avg_slippage_bps 為 float')
check(isinstance(stats["recent_failures"], list),  'recent_failures 為 list')
check(len(stats["recent_failures"]) == 2,      f'recent_failures 共 2 筆（實際: {len(stats["recent_failures"])}）')
check(stats["recent_failures"][0]["status"] == "FAILED", 'recent_failures 狀態正確')

# ─── [11] 滑價計算 ────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [11] _calc_slippage 計算')
print(SECTION)

reset()
executor, ex03 = make_executor()

# 多單：executed > market → 正值滑價
bps = executor._calc_slippage(100.0, 100.5, "Buy")
check(abs(bps - 50.0) < 0.01, f'Buy slippage(100, 100.5) == 50 bps（實際: {bps}）')

# 賣單：executed < market → 正值滑價
bps_sell = executor._calc_slippage(100.0, 99.5, "Sell")
check(abs(bps_sell - 50.0) < 0.01, f'Sell slippage(100, 99.5) == 50 bps（實際: {bps_sell}）')

# 零滑價
bps_zero = executor._calc_slippage(100.0, 100.0, "Buy")
check(bps_zero == 0.0, f'零滑價 == 0 bps（實際: {bps_zero}）')

# market_price=0 時回傳 0（避免除以零）
bps_div0 = executor._calc_slippage(0.0, 100.0, "Buy")
check(bps_div0 == 0.0, f'market_price=0 時回傳 0（實際: {bps_div0}）')

# ─── [12] DRY-RUN 空單 ────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [12] DRY-RUN 空單（short）')
print(SECTION)

reset()
executor, ex03 = make_executor(price=3500.0)

proposal_short = make_proposal(
    direction="short",
    entry_type="limit",
    entry_price=3600.0,
    stop_loss=3700.0,  # 空單止損 > 入場價 ✓
    position_size_usd=30.0,
)
result = executor.execute_decision(make_decision(), proposal_short)

check(result.status == "FILLED",           f'空單 DRY-RUN 成功（實際: {result.status}）')
check(result.execution_id.startswith("DRY-"), '空單 execution_id 以 DRY- 開頭')
check(ex03.known_positions.get("ETHUSDT", {}).get("side") == "Sell",
      '芬姐知道空單 side=Sell')

# ─── [13] position_size = 0 驗證 ─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [13] 驗證失敗：position_size_usd = 0')
print(SECTION)

reset()
executor, ex03 = make_executor()
zero_size = make_proposal(position_size_usd=0.0)
result = executor.execute_decision(make_decision(), zero_size)
check(result.status == "FAILED", f'position_size=0 → FAILED（實際: {result.status}）')

# ─── 總結 ──────────────────────────────────────────────────────────────────────

total = passed + failed
print(f'\n{SECTION}')
print('  總結')
print(SECTION)
print(f'  測試結果：{passed} / {total} 通過')
if failed == 0:
    print('  [全部通過]')
else:
    print(f'  [注意] {failed} 個測試失敗')
print(SECTION)
