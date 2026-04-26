# -*- coding: utf-8 -*-
import sys
import io
import os
import json
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.common.message_bus import get_bus, Message, reset_bus
from trading_system.common.flash_alert import (
    FlashAlert, send_flash, acknowledge_alert,
    get_unacknowledged_critical, reset_flash_state,
)
from trading_system.common.config import REPORTS_DIR

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


# ─── [1] 全域單例 ─────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] 全域單例')
print(SECTION)

bus_a = get_bus()
bus_b = get_bus()
check(bus_a is bus_b, 'get_bus() 多次呼叫回傳同一實例')
check(isinstance(bus_a, type(bus_b)), 'get_bus() 回傳 MessageBus 實例')

reset_bus()
bus_c = get_bus()
check(bus_a is not bus_c, 'reset_bus() 後 get_bus() 回傳新實例')
check(get_bus() is bus_c, 'reset_bus() 後再次 get_bus() 仍是同一新實例')

# 以下測試都用 bus（共用單例）
bus = get_bus()
bus.clear()

# ─── [2] 基本 pub/sub ─────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] 基本 pub/sub')
print(SECTION)

bus.clear()
received: list[Message] = []

def yi_jie_callback(msg: Message) -> None:
    received.append(msg)

bus.subscribe("proposal.submitted", yi_jie_callback, "怡姐")
check("怡姐" in bus.get_subscribers("proposal.submitted"), '怡姐訂閱成功')

mid = bus.publish("proposal.submitted", {"symbol": "ETHUSDT", "direction": "long"}, "老蘇")
check(isinstance(mid, str) and len(mid) == 36, f'publish 回傳 UUID（{mid[:8]}...）')
check(len(received) == 1, '怡姐的 callback 被呼叫 1 次')
check(received[0].message_id == mid, 'callback 收到的 message_id 正確')
check(received[0].sender == "老蘇", 'sender 正確')
check(received[0].channel == "proposal.submitted", 'channel 正確')
check(isinstance(received[0].timestamp, datetime), 'timestamp 為 datetime')
check(received[0].payload["symbol"] == "ETHUSDT", 'payload 正確傳達')

# 重複訂閱同一 role 應被忽略
bus.subscribe("proposal.submitted", yi_jie_callback, "怡姐")
bus.publish("proposal.submitted", {}, "老蘇")
check(len(received) == 2, '重複訂閱 role 不會觸發雙次 callback')

# ─── [3] 多訂閱者 ─────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] 多訂閱者：順序與完整性')
print(SECTION)

bus.clear()
order: list[str] = []

bus.subscribe("decision.final", lambda m: order.append("怡姐"), "怡姐")
bus.subscribe("decision.final", lambda m: order.append("老王"), "老王")
bus.subscribe("decision.final", lambda m: order.append("老廖"), "老廖")

check(bus.get_subscribers("decision.final") == ["怡姐", "老王", "老廖"],
      'get_subscribers 回傳訂閱順序正確')

bus.publish("decision.final", {"decision": "EXECUTE"}, "仲裁系統")

check(len(order) == 3, '全部 3 個訂閱者都收到訊息')
check(order == ["怡姐", "老王", "老廖"], '訂閱者呼叫順序正確')

# 第二次發送，累計 6 次
bus.publish("decision.final", {"decision": "WAIT"}, "仲裁系統")
check(len(order) == 6, '第二次發送後累計 6 次呼叫')

# ─── [4] 取消訂閱 ─────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] 取消訂閱')
print(SECTION)

bus.clear()
unsub_received: list[Message] = []

bus.subscribe("assessment.complete", lambda m: unsub_received.append(m), "老蘇")
bus.publish("assessment.complete", "first", "怡姐")
check(len(unsub_received) == 1, '取消前收到 1 筆訊息')

removed = bus.unsubscribe("assessment.complete", "老蘇")
check(removed == True, 'unsubscribe 回傳 True')
check("老蘇" not in bus.get_subscribers("assessment.complete"), '老蘇已從訂閱清單移除')

bus.publish("assessment.complete", "second", "怡姐")
check(len(unsub_received) == 1, '取消後訊息不再送達')

not_found = bus.unsubscribe("assessment.complete", "不存在的角色")
check(not_found == False, 'unsubscribe 不存在 role 回傳 False')

# ─── [5] callback 例外處理 ───────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] callback 例外處理')
print(SECTION)

bus.clear()
good_received: list[Message] = []

class CaptureLogs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []
    def emit(self, record):
        self.records.append(record)

cap = CaptureLogs()
cap.setLevel(logging.ERROR)
logging.getLogger("atc.MessageBus").addHandler(cap)

def bad_callback(msg: Message) -> None:
    raise RuntimeError("故意拋例外，測試隔離性")

def good_callback(msg: Message) -> None:
    good_received.append(msg)

# 壞人先訂閱，好人後訂閱（確保壞人先被呼叫）
bus.subscribe("news.event", bad_callback, "壞人")
bus.subscribe("news.event", good_callback, "好人")

mid = bus.publish("news.event", "test_payload", "測試員")

check(len(good_received) == 1, '好人的 callback 仍正常收到訊息（例外不影響其他 subscriber）')
check(good_received[0].message_id == mid, '好人收到的 message_id 正確')
check(
    any("壞人" in r.getMessage() for r in cap.records),
    '例外已被 log（含 subscriber role 名稱）'
)

logging.getLogger("atc.MessageBus").removeHandler(cap)

# ─── [6] 訊息歷史（容量上限）────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] 訊息歷史：上限 1000 筆')
print(SECTION)

bus.clear()

# 記錄第 101 筆的 message_id（索引 100）
first_kept_id = None
last_id = None
for i in range(1100):
    mid = bus.publish("system.warning", f"payload_{i}", "壓力測試")
    if i == 100:
        first_kept_id = mid
    last_id = mid

history_all = bus.get_message_history("system.warning", limit=1000)
check(len(history_all) == 1000, f'history 保留 1000 筆（實際: {len(history_all)}）')
check(history_all[0].message_id == first_kept_id,
      '最舊一筆為第 101 條訊息（前 100 條已丟棄）')
check(history_all[-1].message_id == last_id, '最新一筆為第 1100 條')
check(history_all[-1].payload == "payload_1099", '最新一筆 payload 正確')

# 測試 limit 切片
recent10 = bus.get_message_history("system.warning", limit=10)
check(len(recent10) == 10, 'limit=10 回傳 10 筆')
check(recent10[-1].message_id == last_id, 'limit=10 最後一筆為最新訊息')

# 空 channel
empty_hist = bus.get_message_history("不存在的channel")
check(empty_hist == [], '不存在的 channel history 回傳空列表')

# ─── [7] 快報系統（FlashAlert）───────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] 快報系統')
print(SECTION)

bus.clear()
reset_flash_state()

# 統計呼叫前 critical_events.log 行數
crit_path = REPORTS_DIR / "critical_events.log"
before_lines = 0
if crit_path.is_file():
    with open(crit_path, encoding='utf-8') as f:
        before_lines = sum(1 for _ in f)

# 訂閱 alert.flash channel
flash_received: list[Message] = []
bus.subscribe("alert.flash", lambda m: flash_received.append(m), "怡姐")

# 7a: info 快報（不應寫入 critical_events.log）
alert_info = FlashAlert(
    alert_id="FA-TEST-001",
    alert_type="DATA_OFFLINE",
    alert_level="info",
    sender="小孫",
    target_recipients=["老蘇"],
    title="資料源暫時離線",
    message="CoinGecko API 回應緩慢",
    related_data={"source": "CoinGecko", "timeout": 15},
    timestamp=datetime.now(timezone.utc),
)
send_flash(alert_info)

after_info_lines = 0
if crit_path.is_file():
    with open(crit_path, encoding='utf-8') as f:
        after_info_lines = sum(1 for _ in f)

check(after_info_lines == before_lines, 'info 快報不寫入 critical_events.log')
check(len(flash_received) == 1, 'info 快報已廣播到 alert.flash channel')
check(flash_received[-1].payload["alert_id"] == "FA-TEST-001", 'payload alert_id 正確')

# 7b: critical 快報（應寫入 critical_events.log）
alert_crit = FlashAlert(
    alert_id="FA-TEST-002",
    alert_type="ANOMALY_FLASH",
    alert_level="critical",
    sender="琳姐",
    target_recipients=["怡姐", "老廖", "阿成"],
    title="閃崩偵測：ETH -4.2% in 5min",
    message="ETHUSDT 觸發閃崩閾值，建議暫停新倉",
    related_data={"symbol": "ETHUSDT", "magnitude": 4.2, "duration_sec": 300},
    timestamp=datetime.now(timezone.utc),
    requires_acknowledgment=True,
)
send_flash(alert_crit)

with open(crit_path, encoding='utf-8') as f:
    crit_lines = f.readlines()

check(len(crit_lines) == before_lines + 1, 'critical 快報寫入 critical_events.log（+1 行）')
check(len(flash_received) == 2, 'critical 快報也廣播到 alert.flash channel')

try:
    last_crit = json.loads(crit_lines[-1])
    check(last_crit["event_type"] == "FLASH_ANOMALY_FLASH", 'critical_events event_type 正確')
    check(last_crit["details"]["alert_id"] == "FA-TEST-002", 'critical_events alert_id 正確')
    check(last_crit["role"] == "琳姐", 'critical_events role 正確')
except json.JSONDecodeError as e:
    check(False, f'critical_events JSON 解析失敗: {e}')

# 7c: acknowledge_alert
check(get_unacknowledged_critical() == [alert_crit],
      '初始：FA-TEST-002 在未確認清單中')

result = acknowledge_alert("FA-TEST-002", "怡姐")
check(result == True, 'acknowledge_alert 回傳 True')

unacked = get_unacknowledged_critical()
check(alert_crit in unacked, '怡姐確認後，老廖/阿成未確認，仍在未確認清單')

acknowledge_alert("FA-TEST-002", "老廖")
acknowledge_alert("FA-TEST-002", "阿成")
check(get_unacknowledged_critical() == [],
      '全員確認後，未確認清單為空')

# 7d: 找不到的 alert_id
check(acknowledge_alert("不存在的ID", "某人") == False,
      'acknowledge_alert 找不到 alert 回傳 False')

# 7e: 不需要確認的 critical（不出現在未確認清單）
alert_no_ack = FlashAlert(
    alert_id="FA-TEST-003",
    alert_type="AU_RED",
    alert_level="critical",
    sender="監察官",
    target_recipients=["全員"],
    title="升級到 RED 警戒",
    message="當日虧損達警戒線",
    related_data={"loss_pct": 5.1},
    timestamp=datetime.now(timezone.utc),
    requires_acknowledgment=False,  # 不需要確認
)
send_flash(alert_no_ack)
check(alert_no_ack not in get_unacknowledged_critical(),
      'requires_acknowledgment=False 的 critical 不出現在未確認清單')

# ─── 總結 ─────────────────────────────────────────────────────────────────────

total = passed + failed
print(f'\n{SECTION}')
print('  總結')
print(SECTION)
print(f'  測試結果      : {passed} / {total} 通過')
if failed == 0:
    print('  [全部通過]')
else:
    print(f'  [注意] {failed} 個測試失敗')
print(SECTION)
