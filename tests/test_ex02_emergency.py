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

from trading_system.squads.crypto.execution.ex_02_emergency import EmergencyExecutor
from trading_system.squads.crypto.execution.ex_03_connection import ConnectionMaintainer
from trading_system.common.data_models import AnomalyEvent
from trading_system.common.flash_alert import (
    FlashAlert, send_flash, reset_flash_state, get_unacknowledged_critical,
)
from trading_system.common.message_bus import get_bus
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
    gw.get_market_kline.return_value = {
        "success": True,
        "data": {"list": [["ts", "o", "h", "l", str(price), "vol"]]},
        "elapsed_ms": 20, "error": "",
    }
    gw.get_server_time.return_value = {
        "success": True,
        "data": {"timeSecond": str(int(time.time()))},
        "elapsed_ms": 15, "error": "",
    }
    gw.get_positions.return_value = {
        "success": True,
        "data": {"list": []},
        "elapsed_ms": 20, "error": "",
    }
    gw.place_order.return_value = {
        "success": True,
        "data": {"orderId": "LIVE-EMER-001", "price": str(price)},
        "elapsed_ms": 40, "error": "",
    }
    return gw


def make_anomaly(
    event_type: str = "FLASH_MOVE",
    severity:   float = 0.8,
    symbol:     str   = "ETHUSDT",
) -> AnomalyEvent:
    return AnomalyEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        symbol=symbol,
        magnitude=5.5,
        severity=severity,
        timestamp=datetime.now(timezone.utc),
        triggered_alert=True,
        direction="down",
    )


def make_flash_alert(
    alert_type:  str = "AU_RED",
    alert_level: str = "critical",
    title:       str = "測試快報",
) -> FlashAlert:
    return FlashAlert(
        alert_id=str(uuid.uuid4()),
        alert_type=alert_type,
        alert_level=alert_level,
        sender="測試",
        title=title,
        message="測試訊息",
        target_recipients=["阿成"],
        related_data={},
        timestamp=datetime.now(timezone.utc),
        requires_acknowledgment=True,
    )


def make_executor(price: float = 3500.0):
    gw   = make_gateway(price)
    ex03 = ConnectionMaintainer(gateway=gw)
    ex02 = EmergencyExecutor(ex03_connection=ex03)
    ex02.gateway = gw
    return ex02, ex03


def reset():
    reset_flash_state()
    get_bus().clear()


def set_position(ex03, symbol: str, side: str, entry: float, stop: float, size: str = "0.1"):
    """便捷函式：直接設定 ex03 的已知持倉。"""
    ex03.known_positions[symbol] = {
        "symbol":      symbol,
        "side":        side,
        "entry_price": entry,
        "stop_loss":   stop,
        "size":        size,
    }


# ─── [1] 初始化 ────────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] 初始化與屬性')
print(SECTION)

reset()
ex02, ex03 = make_executor()

check(ex02.flash_crash_mode == False,       'flash_crash_mode 初始 False')
check(ex02.emergency_actions_count == 0,    'emergency_actions_count 初始 0')
check(len(ex02.emergency_history) == 0,     'emergency_history 初始空')
check(ex02.flash_mode_stop_tightening_pct == 30, '止損收緊比例 30%')
check(ex02.stop_loss_check_interval == 5,   'check 間隔 5 秒')

# ─── [2] FLASH_MOVE (severity=0.8) → 進入閃崩模式 ───────────────────────────

print(f'\n{SECTION}')
print('  [2] FLASH_MOVE (severity=0.8) → 閃崩模式 + FlashAlert')
print(SECTION)

reset()
ex02, ex03 = make_executor()
anomaly = make_anomaly("FLASH_MOVE", severity=0.8)

ex02.enter_flash_crash_mode(anomaly)

check(ex02.flash_crash_mode == True,                'flash_crash_mode == True')
check(ex02.emergency_actions_count == 1,            'emergency_actions_count == 1')
check(len(ex02.emergency_history) == 1,             'emergency_history 有 1 筆')
check(ex02.emergency_history[0]["type"] == "FLASH_CRASH_MODE_ENTER",
      'history type == FLASH_CRASH_MODE_ENTER')

unack = get_unacknowledged_critical()
check(len(unack) >= 1,                              'critical FlashAlert 已發送')
check(unack[0].alert_type == "ANOMALY_FLASH",       f'快報類型 ANOMALY_FLASH（實際: {unack[0].alert_type}）')
check("怡姐" in unack[0].target_recipients,         '收件人含 怡姐')
check("宏哥" in unack[0].target_recipients,         '收件人含 宏哥')

# ─── [3] FLASH_MOVE 透過 bus 觸發 ────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] bus publish anomaly → _on_anomaly 觸發閃崩模式')
print(SECTION)

reset()
ex02, ex03 = make_executor()
anomaly_bus = make_anomaly("FLASH_MOVE", severity=0.9)

get_bus().publish("anomaly.detected", payload=anomaly_bus, sender="CA-03")

check(ex02.flash_crash_mode == True, 'bus 觸發後 flash_crash_mode == True')

# ─── [4] 輕微 FLASH_MOVE (severity=0.5) → 不進入閃崩模式 ─────────────────────

print(f'\n{SECTION}')
print('  [4] 輕微 FLASH_MOVE (severity=0.5) → 不進入閃崩模式')
print(SECTION)

reset()
ex02, ex03 = make_executor()
mild_anomaly = make_anomaly("FLASH_MOVE", severity=0.5)

get_bus().publish("anomaly.detected", payload=mild_anomaly, sender="CA-03")

check(ex02.flash_crash_mode == False,          'severity=0.5 不觸發閃崩模式（門檻 0.7）')
check(ex02.emergency_actions_count == 0,       'emergency_actions_count 仍為 0')

# ─── [5] 重複進入閃崩模式 → 只執行一次 ──────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] 重複呼叫 enter_flash_crash_mode → 只執行一次')
print(SECTION)

reset()
ex02, ex03 = make_executor()
anomaly = make_anomaly()

ex02.enter_flash_crash_mode(anomaly)
first_count = ex02.emergency_actions_count

ex02.enter_flash_crash_mode(anomaly)  # 第二次呼叫應被忽略

check(ex02.emergency_actions_count == first_count, '重複觸發不增加 emergency_actions_count')
check(len(ex02.emergency_history) == 1,            'history 仍只有 1 筆')

# ─── [6] 退出閃崩模式 ─────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] exit_flash_crash_mode')
print(SECTION)

reset()
ex02, ex03 = make_executor()
ex02.enter_flash_crash_mode(make_anomaly())
check(ex02.flash_crash_mode == True,    '進入後 flash_crash_mode=True')

ex02.exit_flash_crash_mode()
check(ex02.flash_crash_mode == False,   '退出後 flash_crash_mode=False')

# 無閃崩模式時退出 → 不報錯
ex02.exit_flash_crash_mode()
check(ex02.flash_crash_mode == False,   '再次退出不出錯')

# ─── [7] 止損收緊計算（多單）────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] 閃崩模式：止損收緊計算（多單）')
print(SECTION)

reset()
ex02, ex03 = make_executor()
set_position(ex03, "ETHUSDT", side="Buy", entry=100.0, stop=95.0)

anomaly = make_anomaly("FLASH_MOVE", severity=0.8)
ex02.enter_flash_crash_mode(anomaly)

# 新止損 = 95 + (100-95)*0.30 = 96.5
new_stop = ex03.known_positions.get("ETHUSDT", {}).get("stop_loss", 0)
check(abs(new_stop - 96.5) < 0.001,
      f'多單新止損 = 96.5（實際: {new_stop}）')

# ─── [8] 止損收緊計算（空單）────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [8] 閃崩模式：止損收緊計算（空單）')
print(SECTION)

reset()
ex02, ex03 = make_executor()
# 空單：entry=100, stop=105（止損在上方）
set_position(ex03, "ETHUSDT", side="Sell", entry=100.0, stop=105.0)

ex02.enter_flash_crash_mode(make_anomaly())

# 新止損 = 105 - (105-100)*0.30 = 103.5
new_stop = ex03.known_positions.get("ETHUSDT", {}).get("stop_loss", 0)
check(abs(new_stop - 103.5) < 0.001,
      f'空單新止損 = 103.5（實際: {new_stop}）')

# ─── [9] 直接呼叫 _tighten_stop_loss ─────────────────────────────────────────

print(f'\n{SECTION}')
print('  [9] _tighten_stop_loss 直接呼叫')
print(SECTION)

reset()
ex02, ex03 = make_executor()

# 資訊完整 → 回傳新止損
pos = {"side": "Buy", "entry_price": 200.0, "stop_loss": 180.0, "size": "0.1"}
result = ex02._tighten_stop_loss("ETHUSDT", pos)
# new = 180 + (200-180)*0.3 = 186
check(abs(result - 186.0) < 0.001, f'_tighten_stop_loss 回傳 186.0（實際: {result}）')

# 資訊不足 → 回傳 None
result_none = ex02._tighten_stop_loss("ETHUSDT", {"side": "Buy"})
check(result_none is None, '資訊不足 → 回傳 None')

# ─── [10] AU_RED 警戒 → 緊急清倉 ─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [10] AU_RED 警戒 → 緊急清倉（有持倉）')
print(SECTION)

reset()
ex02, ex03 = make_executor()
set_position(ex03, "ETHUSDT", side="Buy", entry=3500.0, stop=3400.0)

# 透過 send_flash 觸發（payload 是 dict）
alert = make_flash_alert("AU_RED", "critical")
send_flash(alert)

check(ex02.emergency_actions_count >= 1,    'AU_RED → emergency_actions_count 增加')

# 確認 history 記錄了清倉
close_events = [e for e in ex02.emergency_history if e.get("type") == "EMERGENCY_CLOSE_ALL"]
check(len(close_events) >= 1,               'emergency_history 有 EMERGENCY_CLOSE_ALL 記錄')

# 確認清倉結果是 DRY_RUN_CLOSED
if close_events:
    closed = close_events[0].get("closed", [])
    check(len(closed) >= 1,                 '至少有 1 筆清倉記錄')
    if closed:
        check(closed[0]["status"] == "DRY_RUN_CLOSED",
              f'DRY-RUN 清倉 status=DRY_RUN_CLOSED（實際: {closed[0]["status"]}）')
        check(closed[0]["symbol"] == "ETHUSDT", '清倉 symbol=ETHUSDT')

# ─── [11] GA_CRITICAL 新聞 → 緊急清倉 ───────────────────────────────────────

print(f'\n{SECTION}')
print('  [11] GA_CRITICAL critical → 緊急清倉')
print(SECTION)

reset()
ex02, ex03 = make_executor()
set_position(ex03, "ETHUSDT", side="Buy", entry=3500.0, stop=3400.0)
set_position(ex03, "BTCUSDT", side="Sell", entry=60000.0, stop=61000.0)

ga_alert = make_flash_alert("GA_CRITICAL", "critical", title="央行緊急聲明")
send_flash(ga_alert)

check(ex02.emergency_actions_count >= 1,    'GA_CRITICAL → 觸發緊急清倉')
close_events = [e for e in ex02.emergency_history if e.get("type") == "EMERGENCY_CLOSE_ALL"]
check(len(close_events) >= 1,               '有 EMERGENCY_CLOSE_ALL 記錄')
if close_events:
    closed = close_events[0].get("closed", [])
    check(len(closed) == 2,                 f'2 個持倉被清倉（實際: {len(closed)}）')

# ─── [12] GA_CRITICAL 但非 critical 級別 → 不清倉 ────────────────────────────

print(f'\n{SECTION}')
print('  [12] GA_CRITICAL 但 alert_level=warning → 不觸發清倉')
print(SECTION)

reset()
ex02, ex03 = make_executor()
set_position(ex03, "ETHUSDT", side="Buy", entry=3500.0, stop=3400.0)
before_count = ex02.emergency_actions_count

warn_alert = make_flash_alert("GA_CRITICAL", "warning")
send_flash(warn_alert)

check(ex02.emergency_actions_count == before_count, 'GA_CRITICAL warning 不觸發清倉')

# ─── [13] 沒有持倉時的緊急清倉 ───────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [13] 空倉時緊急清倉 → 不報錯，不增加 actions_count')
print(SECTION)

reset()
ex02, ex03 = make_executor()
before_count = ex02.emergency_actions_count

ex02.emergency_close_all("測試：空倉清倉")

check(ex02.emergency_actions_count == before_count, '空倉時不增加 emergency_actions_count')

# ─── [14] check_stop_losses：接近止損（0.5%）→ WARNING 但不清倉 ───────────────

print(f'\n{SECTION}')
print('  [14] check_stop_losses：止損距離 0.5% → 只 log，不清倉')
print(SECTION)

reset()
# 設定 mock 價格 = 100.0，止損 = 99.5（多單 distance ≈ 0.5%）
gw_close = make_gateway(price=100.0)
ex03_close = ConnectionMaintainer(gateway=gw_close)
ex02_close = EmergencyExecutor(ex03_connection=ex03_close)
ex02_close.gateway = gw_close

set_position(ex03_close, "ETHUSDT", side="Buy", entry=101.0, stop=99.5)

before_count = ex02_close.emergency_actions_count
ex02_close.check_stop_losses()

# distance = (100 - 99.5) / 99.5 * 100 ≈ 0.5% → < 1% → WARNING，不清倉
check(ex02_close.emergency_actions_count == before_count,
      '止損距離 0.5% → 不觸發清倉（emergency_actions_count 不變）')

# ─── [15] check_stop_losses：止損觸發（distance ≤ 0）→ 平倉 ──────────────────

print(f'\n{SECTION}')
print('  [15] check_stop_losses：止損觸及 → 平倉')
print(SECTION)

reset()
# 價格 = 94，止損 = 95（多單已穿越止損）
gw_trig = make_gateway(price=94.0)
ex03_trig = ConnectionMaintainer(gateway=gw_trig)
ex02_trig = EmergencyExecutor(ex03_connection=ex03_trig)
ex02_trig.gateway = gw_trig

set_position(ex03_trig, "ETHUSDT", side="Buy", entry=100.0, stop=95.0)

ex02_trig.check_stop_losses()

# distance = (94 - 95) / 95 * 100 ≈ -1.05% → ≤ 0 → 觸發
check(ex02_trig.emergency_actions_count >= 1, '止損觸發 → emergency_actions_count 增加')
stop_events = [
    e for e in ex02_trig.emergency_history
    if e.get("type") == "STOP_LOSS_TRIGGERED"
]
check(len(stop_events) >= 1,                  'emergency_history 有 STOP_LOSS_TRIGGERED 記錄')
if stop_events:
    check(stop_events[0]["symbol"] == "ETHUSDT", 'STOP_LOSS_TRIGGERED 記錄 symbol 正確')

# ─── [16] run_cycle 間隔控制 ──────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [16] run_cycle：間隔控制（5 秒）')
print(SECTION)

reset()
gw_cyc = make_gateway(price=3500.0)
ex03_cyc = ConnectionMaintainer(gateway=gw_cyc)
ex02_cyc = EmergencyExecutor(ex03_connection=ex03_cyc)
ex02_cyc.gateway = gw_cyc

# 第一次：last_stop_loss_check=None → 立即執行
ex02_cyc.run_cycle()
check(ex02_cyc.last_stop_loss_check is not None, '第一次 run_cycle 更新 last_stop_loss_check')

t_first = ex02_cyc.last_stop_loss_check

# 第二次緊接著：不應再觸發
ex02_cyc.run_cycle()
check(ex02_cyc.last_stop_loss_check == t_first, '緊接著 run_cycle 不重複觸發')

# 模擬 6 秒後
ex02_cyc.last_stop_loss_check = time.time() - 6
t_before_third = ex02_cyc.last_stop_loss_check   # ≈ now - 6
ex02_cyc.run_cycle()
# 觸發後 last_stop_loss_check ≈ now >> t_before_third（t_before_third 是 6 秒前）
check(ex02_cyc.last_stop_loss_check > t_before_third,
      '6 秒後 run_cycle 再次觸發，時間戳更新')

# ─── [17] 訂閱整合測試 ───────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [17] 整合：同一 bus 上 EX-03 + EX-02 並存')
print(SECTION)

reset()
gw_int = make_gateway(price=3500.0)
ex03_int = ConnectionMaintainer(gateway=gw_int)
ex02_int = EmergencyExecutor(ex03_connection=ex03_int)
ex02_int.gateway = gw_int

# 設定持倉（直接寫入 known_positions）
set_position(ex03_int, "ETHUSDT", side="Buy", entry=3500.0, stop=3400.0)

# 透過 bus 發送嚴重 FLASH_MOVE
get_bus().publish("anomaly.detected",
                  payload=make_anomaly("FLASH_MOVE", severity=0.85),
                  sender="CA-03")

check(ex02_int.flash_crash_mode == True, '整合測試：bus 觸發閃崩模式')
check(ex02_int.emergency_actions_count >= 1, '整合測試：emergency_actions_count 增加')

# 止損應被收緊（多單 entry=3500, stop=3400 → 新止損 = 3400 + 100*0.3 = 3430）
new_s = ex03_int.known_positions.get("ETHUSDT", {}).get("stop_loss", 0)
check(abs(new_s - 3430.0) < 0.01,
      f'整合測試：持倉止損被收緊到 3430（實際: {new_s}）')

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
