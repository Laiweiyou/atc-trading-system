# -*- coding: utf-8 -*-
import sys
import io
import os
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.squads.crypto.execution.ex_03_connection import ConnectionMaintainer
from trading_system.common.flash_alert import reset_flash_state, get_unacknowledged_critical
from trading_system.common.message_bus import get_bus

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


def make_gateway(server_time_ok=True, latency_ms=50, positions=None):
    """建立一個 mock APIGateway。"""
    gw = MagicMock()
    if server_time_ok:
        gw.get_server_time.return_value = {
            "success": True,
            "data": {"timeSecond": str(int(time.time())), "timeNano": ""},
            "elapsed_ms": latency_ms,
            "error": "",
        }
    else:
        gw.get_server_time.return_value = {
            "success": False,
            "data": {},
            "elapsed_ms": latency_ms,
            "error": "timeout",
        }

    pos_list = positions if positions is not None else []
    gw.get_positions.return_value = {
        "success": True,
        "data": {"list": pos_list},
        "elapsed_ms": 30,
        "error": "",
    }
    return gw


def reset():
    reset_flash_state()
    get_bus().clear()


# ─── [1] 初始化 ────────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] 初始化與屬性')
print(SECTION)

reset()
gw = make_gateway()
cm = ConnectionMaintainer(gateway=gw)

check(cm.consecutive_failures == 0,     'consecutive_failures 初始為 0')
check(cm.last_heartbeat_time == 0.0,    'last_heartbeat_time 初始為 0.0')
check(cm.last_position_check == 0.0,    'last_position_check 初始為 0.0')
check(cm.known_positions == {},         'known_positions 初始為空 dict')
check(cm.position_sync_status == "unknown", 'position_sync_status 初始為 unknown')
check(cm.gateway is gw,                 'gateway 指向傳入的 mock')

# ─── [2] do_heartbeat 正常 ─────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] do_heartbeat 正常回傳')
print(SECTION)

reset()
gw = make_gateway(server_time_ok=True, latency_ms=40)
cm = ConnectionMaintainer(gateway=gw)

r = cm.do_heartbeat()
check(r["status"] == "ok",          f'心跳正常 status=ok（實際: {r["status"]}）')
check(isinstance(r["latency_ms"], int), 'latency_ms 為 int')
check(r["latency_ms"] >= 0,         f'latency_ms >= 0（實際: {r["latency_ms"]}）')
check(cm.consecutive_failures == 0, 'consecutive_failures 仍為 0')
check(cm.last_heartbeat_time > 0,   'last_heartbeat_time 已更新')
check(len(cm.heartbeat_history) == 1, '心跳歷史新增一筆')
check(cm.heartbeat_history[0]["success"] == True, '心跳記錄 success=True')

# ─── [3] do_heartbeat 失敗（< 3 次）─────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] do_heartbeat 失敗（< 3 次，status=failed）')
print(SECTION)

reset()
gw = make_gateway(server_time_ok=False)
cm = ConnectionMaintainer(gateway=gw)

r1 = cm.do_heartbeat()
check(r1["status"] == "failed",           '第 1 次失敗 → status=failed')
check(cm.consecutive_failures == 1,       'consecutive_failures == 1')

r2 = cm.do_heartbeat()
check(r2["status"] == "failed",           '第 2 次失敗 → status=failed')
check(cm.consecutive_failures == 2,       'consecutive_failures == 2')

# 尚未達 3 次，不應有 critical 快報
unack = get_unacknowledged_critical()
check(len(unack) == 0,                    '< 3 次失敗，無 critical 快報')

# ─── [4] do_heartbeat 連續 3 次失敗 → critical 快報 ──────────────────────────

print(f'\n{SECTION}')
print('  [4] 連續 3 次失敗 → status=critical + FlashAlert')
print(SECTION)

reset()
gw = make_gateway(server_time_ok=False)
cm = ConnectionMaintainer(gateway=gw)

cm.do_heartbeat()
cm.do_heartbeat()
r3 = cm.do_heartbeat()
check(r3["status"] == "critical",         '第 3 次失敗 → status=critical')
check(cm.consecutive_failures == 3,       'consecutive_failures == 3')

unack = get_unacknowledged_critical()
check(len(unack) >= 1,                    'critical 快報已發送')
check(unack[0].alert_type == "EX_FAIL",  f'快報類型 EX_FAIL（實際: {unack[0].alert_type}）')
check("宏哥" in unack[0].target_recipients, '快報收件人含 宏哥')
check("怡姐" in unack[0].target_recipients, '快報收件人含 怡姐')

# ─── [5] 連續失敗後恢復 → consecutive_failures 歸 0 ──────────────────────────

print(f'\n{SECTION}')
print('  [5] 失敗後恢復 → consecutive_failures 歸零')
print(SECTION)

reset()
gw = make_gateway(server_time_ok=False)
cm = ConnectionMaintainer(gateway=gw)
cm.do_heartbeat()  # fail×1
cm.do_heartbeat()  # fail×2

# 切換為成功
gw.get_server_time.return_value = {
    "success": True,
    "data": {"timeSecond": str(int(time.time()))},
    "elapsed_ms": 30, "error": "",
}
r_ok = cm.do_heartbeat()
check(r_ok["status"] in ("ok", "slow"),  f'恢復後 status in ok/slow（實際: {r_ok["status"]}）')
check(cm.consecutive_failures == 0,      '恢復後 consecutive_failures == 0')

# ─── [6] 延遲 spike 偵測 ──────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] 延遲 spike 偵測（status=slow）')
print(SECTION)

reset()
gw = make_gateway(server_time_ok=True)
cm = ConnectionMaintainer(gateway=gw)

# 注入 5 筆 100ms 的歷史（基準 = 100ms，spike 閾值 = 150ms）
for _ in range(5):
    cm.heartbeat_history.append({"latency_ms": 100, "success": True, "timestamp": time.time()})

# 模擬當前延遲 200ms（> 150ms → spike）
check(cm._check_latency_spike(200) == True,  '_check_latency_spike(200) → True（100ms × 1.5 = 150ms）')
check(cm._check_latency_spike(149) == False, '_check_latency_spike(149) → False（≤ 150ms）')
check(cm._check_latency_spike(150) == False, '_check_latency_spike(150) → False（不超過閾值）')

# 少於 5 筆時不偵測 spike
cm2 = ConnectionMaintainer(gateway=gw)
for _ in range(4):
    cm2.heartbeat_history.append({"latency_ms": 10, "success": True, "timestamp": time.time()})
check(cm2._check_latency_spike(9999) == False, '< 5 筆歷史 → 不偵測 spike（回傳 False）')

# 心跳回傳 slow
gw2 = make_gateway(server_time_ok=True, latency_ms=200)
cm3 = ConnectionMaintainer(gateway=gw2)
for _ in range(5):
    cm3.heartbeat_history.append({"latency_ms": 100, "success": True, "timestamp": time.time()})
r_slow = cm3.do_heartbeat()
check(r_slow["status"] == "slow", f'大延遲心跳 → status=slow（實際: {r_slow["status"]}）')

# ─── [7] check_positions 首次初始化 ──────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] check_positions 首次呼叫 → initialized')
print(SECTION)

reset()
pos_list = [{"symbol": "ETHUSDT", "size": "0.1", "side": "Buy"}]
gw = make_gateway(positions=pos_list)
cm = ConnectionMaintainer(gateway=gw)

r = cm.check_positions()
check(r["status"] == "initialized",             'check_positions 首次 → initialized')
check(len(r["discrepancies"]) == 0,             '首次無差異')
check(cm._positions_initialized == True,        '_positions_initialized == True')
check("ETHUSDT" in cm.known_positions,          'ETHUSDT 已存入 known_positions')
check(cm.position_sync_status == "synced",      'position_sync_status == synced')
check(cm.last_position_check > 0,               'last_position_check 已更新')
# 首次初始化不發 critical 快報
unack = get_unacknowledged_critical()
check(len(unack) == 0,                          '首次初始化不發 critical 快報')

# ─── [8] check_positions 同步正常 ────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [8] check_positions 再次呼叫 → synced')
print(SECTION)

r2 = cm.check_positions()  # 持倉未變
check(r2["status"] == "synced",   '第 2 次呼叫持倉不變 → synced')
check(len(r2["discrepancies"]) == 0, '無差異')

# ─── [9] check_positions 偵測差異 ────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [9] check_positions 持倉差異 → discrepancy + FlashAlert')
print(SECTION)

reset()
pos_list_init = [{"symbol": "ETHUSDT", "size": "0.1", "side": "Buy"}]
gw = make_gateway(positions=pos_list_init)
cm = ConnectionMaintainer(gateway=gw)
cm.check_positions()  # 初始化

# 手動竄改本地持倉，模擬差異
cm.known_positions["ETHUSDT"] = {"symbol": "ETHUSDT", "size": "0.5", "side": "Buy"}

r_disc = cm.check_positions()
check(r_disc["status"] == "discrepancy",       '持倉差異 → discrepancy')
check(len(r_disc["discrepancies"]) >= 1,       '有差異記錄')
check(r_disc["discrepancies"][0]["symbol"] == "ETHUSDT", '差異 symbol=ETHUSDT')
check(cm.position_sync_status == "discrepancy", 'position_sync_status == discrepancy')

unack = get_unacknowledged_critical()
check(len(unack) >= 1,                         '持倉差異 critical 快報已發送')
check(unack[0].alert_type == "ANOMALY_FLASH",  f'快報類型 ANOMALY_FLASH（實際: {unack[0].alert_type}）')

# ─── [10] check_positions API 錯誤 ───────────────────────────────────────────

print(f'\n{SECTION}')
print('  [10] check_positions API 錯誤 → api_error')
print(SECTION)

reset()
gw_err = MagicMock()
gw_err.get_positions.return_value = {
    "success": False, "data": {}, "elapsed_ms": 50, "error": "network error"
}
gw_err.get_server_time.return_value = {
    "success": True, "data": {"timeSecond": str(int(time.time()))},
    "elapsed_ms": 30, "error": ""
}
cm_err = ConnectionMaintainer(gateway=gw_err)
r_err = cm_err.check_positions()
check(r_err["status"] == "api_error",            'API 錯誤 → api_error')
check(len(r_err["discrepancies"]) == 0,          'API 錯誤時無差異')
check(cm_err.position_sync_status == "api_error", 'position_sync_status == api_error')

# ─── [11] update_known_position ──────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [11] update_known_position')
print(SECTION)

reset()
gw = make_gateway()
cm = ConnectionMaintainer(gateway=gw)

cm.update_known_position("ETHUSDT", {"symbol": "ETHUSDT", "size": "0.2", "side": "Buy"})
check("ETHUSDT" in cm.known_positions,                    'ETHUSDT 已加入 known_positions')
check(cm.known_positions["ETHUSDT"]["size"] == "0.2",    '持倉 size 正確')

cm.update_known_position("ETHUSDT", {"symbol": "ETHUSDT", "size": "0.5", "side": "Sell"})
check(cm.known_positions["ETHUSDT"]["size"] == "0.5",    '更新後 size 變為 0.5')

# ─── [12] get_health_status ──────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [12] get_health_status 格式與數值')
print(SECTION)

reset()
gw = make_gateway(server_time_ok=True)
cm = ConnectionMaintainer(gateway=gw)

# 未心跳時
hs0 = cm.get_health_status()
check("avg_latency_ms" in hs0,              'avg_latency_ms 欄位存在')
check("p99_latency_ms" in hs0,             'p99_latency_ms 欄位存在')
check("success_rate" in hs0,               'success_rate 欄位存在')
check("consecutive_failures" in hs0,       'consecutive_failures 欄位存在')
check("last_heartbeat_age_seconds" in hs0, 'last_heartbeat_age_seconds 欄位存在')
check("position_sync_status" in hs0,       'position_sync_status 欄位存在')
check(hs0["last_heartbeat_age_seconds"] == -1, '未心跳時 age == -1')
check(hs0["success_rate"] == 1.0,          '無歷史時 success_rate == 1.0')

# 注入一些心跳歷史
for ms in [50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 200]:
    cm.heartbeat_history.append({"latency_ms": ms, "success": True, "timestamp": time.time()})
# 一筆失敗
cm.heartbeat_history.append({"latency_ms": 0, "success": False, "timestamp": time.time()})

hs1 = cm.get_health_status()
check(hs1["avg_latency_ms"] > 0,          f'avg_latency_ms > 0（實際: {hs1["avg_latency_ms"]}）')
check(hs1["p99_latency_ms"] > 0,         f'p99_latency_ms > 0（實際: {hs1["p99_latency_ms"]}）')
check(0 < hs1["success_rate"] < 1.0,     f'success_rate 在 0~1 之間（實際: {hs1["success_rate"]}）')
print(f'  avg_latency={hs1["avg_latency_ms"]}ms, '
      f'p99={hs1["p99_latency_ms"]}ms, '
      f'success_rate={hs1["success_rate"]}')

# 心跳一次後 age >= 0
cm.do_heartbeat()
hs2 = cm.get_health_status()
check(hs2["last_heartbeat_age_seconds"] >= 0, '心跳後 age >= 0')

# ─── [13] run_cycle 觸發邏輯 ─────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [13] run_cycle 觸發邏輯')
print(SECTION)

reset()
gw = make_gateway(server_time_ok=True, positions=[])
cm = ConnectionMaintainer(gateway=gw)

# 剛初始化（last_heartbeat_time=0, last_position_check=0）→ 兩者都應觸發
result = cm.run_cycle()
check(result["heartbeat"] is not None,  'last_heartbeat_time=0 → 心跳觸發')
check(result["positions"] is not None,  'last_position_check=0 → 持倉檢查觸發')

# 剛觸發後立即再次 run_cycle → 不應再觸發
result2 = cm.run_cycle()
check(result2["heartbeat"] is None,   '剛完成心跳 → 下次 run_cycle 不再觸發')
check(result2["positions"] is None,   '剛完成持倉檢查 → 下次 run_cycle 不再觸發')

# 模擬 31 秒後 → 心跳再次觸發
cm.last_heartbeat_time = time.time() - 31
result3 = cm.run_cycle()
check(result3["heartbeat"] is not None, '31 秒後 → 心跳再次觸發')
check(result3["positions"] is None,     '31 秒後 → 持倉檢查不觸發（< 60s）')

# 模擬 61 秒後 → 持倉檢查再次觸發
cm.last_position_check = time.time() - 61
result4 = cm.run_cycle()
check(result4["positions"] is not None, '61 秒後 → 持倉檢查再次觸發')

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
