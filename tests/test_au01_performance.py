# -*- coding: utf-8 -*-
import sys
import io
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.squads.crypto.monitoring.au_01_performance import PerformanceMonitor
from trading_system.common.data_models import ExecutionResult
from trading_system.common.flash_alert import (
    reset_flash_state, get_unacknowledged_critical,
)
from trading_system.common.message_bus import get_bus
import trading_system.common.config as _cfg

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

def make_gateway(balance: float = 200.0, api_ok: bool = True):
    gw = MagicMock()
    if api_ok:
        gw.get_account_balance.return_value = {
            "success": True,
            "data": {"list": [{"totalEquity": str(balance), "accountType": "UNIFIED"}]},
            "elapsed_ms": 40, "error": "",
        }
    else:
        gw.get_account_balance.return_value = {
            "success": False, "data": {}, "elapsed_ms": 0,
            "error": "API 未設定（缺少 key/secret）",
        }
    return gw


def make_monitor(balance: float = 200.0, api_ok: bool = True):
    gw  = make_gateway(balance, api_ok)
    mon = PerformanceMonitor(gateway=gw)
    return mon


def make_filled_result() -> ExecutionResult:
    return ExecutionResult(
        execution_id=str(uuid.uuid4()),
        decision_id=str(uuid.uuid4()),
        status="FILLED",
        timestamp=datetime.now(timezone.utc),
        executed_price=3500.0,
        executed_size=50.0,
        actual_slippage_pct=0.001,
        exchange_order_id="DRY-RUN-ORDER",
    )


def reset():
    reset_flash_state()
    get_bus().clear()


# ─── [1] 初始化 ────────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] 初始化與屬性')
print(SECTION)

reset()
mon = make_monitor()

check(mon.initial_capital_usd == _cfg.INITIAL_CAPITAL_USD, 'initial_capital_usd == 200')
check(mon.current_balance_usd is None,    'current_balance_usd 初始 None')
check(mon.last_balance_check is None,     'last_balance_check 初始 None')
check(mon.daily_pnl    == 0.0,            'daily_pnl 初始 0')
check(mon.weekly_pnl   == 0.0,            'weekly_pnl 初始 0')
check(mon.total_pnl    == 0.0,            'total_pnl 初始 0')
check(mon.realized_pnl == 0.0,            'realized_pnl 初始 0')
check(mon.unrealized_pnl == 0.0,          'unrealized_pnl 初始 0')
check(mon.total_trades   == 0,            'total_trades 初始 0')
check(mon.winning_trades == 0,            'winning_trades 初始 0')
check(mon.losing_trades  == 0,            'losing_trades 初始 0')
check(mon.consecutive_losses     == 0,    'consecutive_losses 初始 0')
check(mon.max_consecutive_losses == 0,    'max_consecutive_losses 初始 0')
check(mon.current_alert_level == "GREEN", 'current_alert_level 初始 GREEN')
check(mon.alert_level_changed_at is None, 'alert_level_changed_at 初始 None')

# ─── [2] 餘額查詢（API 成功）────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] update_balance（API 成功）')
print(SECTION)

reset()
mon = make_monitor(balance=205.5, api_ok=True)

ok = mon.update_balance()
check(ok == True,                          'update_balance 回傳 True（API 成功）')
check(mon.last_balance_check is not None, 'last_balance_check 已更新')
check(mon.current_balance_usd == 205.5,   f'current_balance_usd=205.5（實際: {mon.current_balance_usd}）')

# ─── [3] 餘額查詢（API 失敗 / DRY-RUN fallback）──────────────────────────────

print(f'\n{SECTION}')
print('  [3] update_balance（API 失敗 → fallback 到 initial_capital）')
print(SECTION)

reset()
mon = make_monitor(api_ok=False)

ok = mon.update_balance()
check(ok == False,                                      'update_balance 回傳 False（API 失敗）')
check(mon.last_balance_check is not None,              'last_balance_check 仍更新')
check(mon.current_balance_usd == mon.initial_capital_usd,
      f'fallback → current_balance={mon.current_balance_usd}')

# ─── [4] 損益更新（賺）──────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] update_pnl 獲利筆')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(+10.0, is_realized=True)

check(mon.winning_trades    == 1,    'winning_trades == 1')
check(mon.losing_trades     == 0,    'losing_trades == 0')
check(mon.consecutive_losses == 0,   'consecutive_losses == 0')
check(mon.daily_pnl   == 10.0,      f'daily_pnl == 10.0（實際: {mon.daily_pnl}）')
check(mon.total_pnl   == 10.0,      f'total_pnl == 10.0（實際: {mon.total_pnl}）')
check(mon.realized_pnl == 10.0,     f'realized_pnl == 10.0（實際: {mon.realized_pnl}）')
check(len(mon.recent_pnl_history) == 1, 'recent_pnl_history 有 1 筆')
check(mon.current_alert_level == "GREEN", '獲利後仍 GREEN')

# ─── [5] 損益更新（賠）與連敗計數 ────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] update_pnl 虧損連敗計數')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

for _ in range(3):
    mon.update_pnl(-0.5, is_realized=True)

check(mon.losing_trades       == 3,   'losing_trades == 3')
check(mon.consecutive_losses  == 3,   'consecutive_losses == 3')
check(mon.max_consecutive_losses == 3, 'max_consecutive_losses == 3')
check(mon.daily_pnl == -1.5,          f'daily_pnl == -1.5（實際: {mon.daily_pnl}）')

# ─── [6] 賺後重置連敗 ─────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] 獲利後 consecutive_losses 歸零')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(-1.0)
mon.update_pnl(-1.0)
mon.update_pnl(-1.0)
check(mon.consecutive_losses == 3, '連敗 3 次確認')
check(mon.max_consecutive_losses == 3, 'max_consecutive_losses == 3')

mon.update_pnl(+5.0)
check(mon.consecutive_losses == 0, '獲利後 consecutive_losses 歸零')
check(mon.max_consecutive_losses == 3, 'max_consecutive_losses 保留歷史最高（3）')

# ─── [7] 未實現損益更新 ───────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] update_pnl 未實現損益（is_realized=False）')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(-15.0, is_realized=False)
check(mon.unrealized_pnl == -15.0,  f'unrealized_pnl == -15.0（實際: {mon.unrealized_pnl}）')
check(mon.daily_pnl      == 0.0,    '未實現不影響 daily_pnl')
check(mon.total_pnl      == 0.0,    '未實現不影響 total_pnl')
check(mon.losing_trades  == 0,      '未實現不計入 losing_trades')

# 覆蓋更新
mon.update_pnl(-5.0, is_realized=False)
check(mon.unrealized_pnl == -5.0,   '未實現損益是覆蓋而非累加')

# ─── [8] 警戒升級 YELLOW（虧損 2%）──────────────────────────────────────────

print(f'\n{SECTION}')
print('  [8] 警戒升級 YELLOW（日損達 2%）')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0  # initial_capital = 200，2% = 4 USD

mon.update_pnl(-4.0)  # 2% 損失

check(mon.current_alert_level == "YELLOW",
      f'日損 2% → YELLOW（實際: {mon.current_alert_level}）')
check(mon.alert_level_changed_at is not None, 'alert_level_changed_at 已設定')

# 確認有 FlashAlert 發送（YELLOW → warning，不 require ack）
sent_msgs = get_bus().get_message_history("alert.flash")
check(len(sent_msgs) >= 1, 'YELLOW 升級發送了 FlashAlert')
if sent_msgs:
    payload = sent_msgs[-1].payload
    check(payload.get("alert_level") == "warning",
          f'YELLOW 快報 level=warning（實際: {payload.get("alert_level")}）')
    check(payload.get("requires_acknowledgment") == False,
          'YELLOW 快報不需 acknowledgment')

# ─── [9] 警戒升級 ORANGE（虧損 4%）──────────────────────────────────────────

print(f'\n{SECTION}')
print('  [9] 警戒升級 ORANGE（日損達 4%）')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(-8.0)  # 4% 損失（直接跳到 ORANGE）

check(mon.current_alert_level == "ORANGE",
      f'日損 4% → ORANGE（實際: {mon.current_alert_level}）')

unack = get_unacknowledged_critical()
check(len(unack) >= 1, 'ORANGE 升級發送了 critical FlashAlert（需 ack）')
if unack:
    check(unack[0].alert_type == "ANOMALY_FLASH",
          f'ORANGE 快報類型 ANOMALY_FLASH（實際: {unack[0].alert_type}）')

# ─── [10] 警戒升級 RED（虧損 5%）────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [10] 警戒升級 RED（日損達 5%）')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(-10.0)  # 5% 損失

check(mon.current_alert_level == "RED",
      f'日損 5% → RED（實際: {mon.current_alert_level}）')

unack = get_unacknowledged_critical()
check(len(unack) >= 1, 'RED 升級發送了 critical FlashAlert')
if unack:
    red_alert = unack[-1]
    check(red_alert.alert_type == "AU_RED",
          f'RED 快報類型 AU_RED（實際: {red_alert.alert_type}）')
    check(red_alert.target_recipients == ["全員"],
          f'RED 快報收件人 ["全員"]（實際: {red_alert.target_recipients}）')

# ─── [11] 警戒逐步升級（GREEN → YELLOW → ORANGE → RED）──────────────────────

print(f'\n{SECTION}')
print('  [11] 警戒逐步升級路徑')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(-4.0)   # 2% → YELLOW
check(mon.current_alert_level == "YELLOW", '→ YELLOW')

mon.update_pnl(-4.0)   # 累計 4% → ORANGE
check(mon.current_alert_level == "ORANGE", '→ ORANGE')

mon.update_pnl(-2.0)   # 累計 5% → RED
check(mon.current_alert_level == "RED",    '→ RED')

# ─── [12] 連敗觸發 YELLOW（損失 % 不足）──────────────────────────────────────

print(f'\n{SECTION}')
print('  [12] 連敗觸發 YELLOW（5 次連敗，損失 % < 2%）')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

# 每次 -0.1 USD = 0.05%，5 次共 0.25%，遠低於 YELLOW 門檻 2%
for i in range(5):
    mon.update_pnl(-0.1)

total_loss_pct = abs(mon.daily_pnl) / mon.initial_capital_usd * 100
check(total_loss_pct < _cfg.YELLOW_LOSS_PCT,
      f'損失 % = {total_loss_pct:.2f}% < {_cfg.YELLOW_LOSS_PCT}%（不達 YELLOW 門檻）')
check(mon.consecutive_losses == 5, 'consecutive_losses == 5')
check(mon.current_alert_level == "YELLOW",
      f'連敗 5 次觸發 YELLOW（實際: {mon.current_alert_level}）')

# ─── [13] 連敗觸發 ORANGE（8 次連敗）──────────────────────────────────────────

print(f'\n{SECTION}')
print('  [13] 連敗觸發 ORANGE（8 次連敗，損失 % < 4%）')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

for i in range(8):
    mon.update_pnl(-0.1)

total_loss_pct = abs(mon.daily_pnl) / mon.initial_capital_usd * 100
check(total_loss_pct < _cfg.ORANGE_LOSS_PCT,
      f'損失 % = {total_loss_pct:.2f}% < {_cfg.ORANGE_LOSS_PCT}%（不達 ORANGE 門檻）')
check(mon.consecutive_losses == 8, 'consecutive_losses == 8')
check(mon.current_alert_level == "ORANGE",
      f'連敗 8 次觸發 ORANGE（實際: {mon.current_alert_level}）')

# ─── [14] 訂閱執行結果：total_trades 增加 ────────────────────────────────────

print(f'\n{SECTION}')
print('  [14] bus 訂閱 execution.result → total_trades 增加')
print(SECTION)

reset()
mon = make_monitor()

before = mon.total_trades

# 發送 FILLED 結果
get_bus().publish("execution.result", payload=make_filled_result(), sender="EX-01")
check(mon.total_trades == before + 1, 'FILLED → total_trades 增加')

# 發送 FAILED 結果（不計入）
failed_result = ExecutionResult(
    execution_id=str(uuid.uuid4()),
    decision_id=str(uuid.uuid4()),
    status="FAILED",
    timestamp=datetime.now(timezone.utc),
    error_message="test",
)
get_bus().publish("execution.result", payload=failed_result, sender="EX-01")
check(mon.total_trades == before + 1, 'FAILED 不增加 total_trades')

# ─── [15] 績效報告結構 ────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [15] get_performance_report 結構與數值')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(+10.0)
mon.update_pnl(-3.0)
mon.update_pnl(-2.0)
mon.update_pnl(+5.0, is_realized=False)

report = mon.get_performance_report()
print(f'  report keys: {list(report.keys())}')

# 結構
check("balance"      in report, 'report 有 balance')
check("trade_stats"  in report, 'report 有 trade_stats')
check("alert_status" in report, 'report 有 alert_status')

# balance
b = report["balance"]
check(b["initial"]       == 200.0,  f'initial == 200（實際: {b["initial"]}）')
check(b["current"]       == 200.0,  f'current == 200（實際: {b["current"]}）')
check(abs(b["total_pnl"] - 5.0) < 0.001, f'total_pnl == 5.0（實際: {b["total_pnl"]}）')
check(abs(b["daily_pnl"] - 5.0) < 0.001, f'daily_pnl == 5.0（實際: {b["daily_pnl"]}）')
check(b["unrealized_pnl"] == 5.0, f'unrealized_pnl == 5.0（實際: {b["unrealized_pnl"]}）')

# trade_stats
ts = report["trade_stats"]
check(ts["total_trades"]   == 0,   f'total_trades == 0（bus 未觸發，直接呼叫 update_pnl）')
check(ts["winning_trades"] == 1,   f'winning_trades == 1（實際: {ts["winning_trades"]}）')
check(ts["losing_trades"]  == 2,   f'losing_trades == 2（實際: {ts["losing_trades"]}）')
check(abs(ts["win_rate"] - 1/3) < 0.001,
      f'win_rate ≈ 0.333（實際: {ts["win_rate"]}）')
check(ts["consecutive_losses"]     == 2,  f'最後兩筆均虧損 consecutive_losses == 2（實際: {ts["consecutive_losses"]}）')
check(ts["max_consecutive_losses"] == 2,  f'max_consecutive_losses == 2（實際: {ts["max_consecutive_losses"]}）')

# alert_status
al = report["alert_status"]
check(al["current_level"] in ("GREEN","YELLOW","ORANGE","RED"), '警戒等級值合法')
check("changed_at" in al,                                       'changed_at 欄位存在')
check("duration_at_current_level" in al,                        'duration 欄位存在')

# ─── [16] 每日重置 ────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [16] daily_reset：跨日重置')
print(SECTION)

reset()
mon = make_monitor()
mon.current_balance_usd = 200.0

mon.update_pnl(-4.0)  # 觸發 YELLOW
check(mon.daily_pnl == -4.0,              '重置前 daily_pnl == -4.0')
check(mon.current_alert_level == "YELLOW", '重置前 YELLOW')

# 偽裝 last_daily_reset 為昨天（觸發重置條件）
yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
mon.last_daily_reset = yesterday

did_reset = mon.daily_reset()
check(did_reset == True,        'daily_reset 回傳 True（確實重置）')
check(mon.daily_pnl == 0.0,    f'重置後 daily_pnl == 0（實際: {mon.daily_pnl}）')
check(mon.weekly_pnl == -4.0,  f'daily_pnl 轉入 weekly_pnl（實際: {mon.weekly_pnl}）')
# 連敗未達門檻（0）→ 警戒歸 GREEN
check(mon.current_alert_level == "GREEN",
      f'連敗 0 次 → 重置後 GREEN（實際: {mon.current_alert_level}）')

# 同一天再呼叫 daily_reset → 不重置
did_reset2 = mon.daily_reset()
check(did_reset2 == False, '同一天重複呼叫 daily_reset → False')
check(mon.daily_pnl == 0.0, 'daily_pnl 不變')

# ─── [17] run_cycle 間隔控制（餘額查詢每 5 分鐘）───────────────────────────

print(f'\n{SECTION}')
print('  [17] run_cycle：餘額查詢間隔控制')
print(SECTION)

reset()
mon = make_monitor(api_ok=True)

check(mon.last_balance_check is None, '初始 last_balance_check=None')

mon.run_cycle()
check(mon.last_balance_check is not None, '第一次 run_cycle → 觸發餘額查詢')

t1 = mon.last_balance_check
mon.run_cycle()
check(mon.last_balance_check == t1, '立即再次 run_cycle → 不重複查詢')

# 模擬 5 分鐘 + 1 秒後
mon.last_balance_check = time.time() - 301
t_before = mon.last_balance_check
mon.run_cycle()
check(mon.last_balance_check > t_before, '5 分鐘後 run_cycle → 再次觸發查詢')

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
