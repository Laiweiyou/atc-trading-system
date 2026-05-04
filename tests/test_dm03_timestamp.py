# -*- coding: utf-8 -*-
"""Tests for DM-03 琪琪 TimestampSynchronizer."""
import io
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.squads.crypto.data_management.dm_03_timestamp_sync import (
    TimestampSynchronizer,
)
from trading_system.common.data_models import SnapshotBundle
from trading_system.common.flash_alert import reset_flash_state, _sent_alerts
from trading_system.common.message_bus import get_bus
from trading_system.common.snapshot_builder import reset_snapshot_builder

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


def _fresh_sync() -> TimestampSynchronizer:
    """清乾淨所有單例再建立新的 TimestampSynchronizer。"""
    reset_snapshot_builder()   # 清 SnapshotBuilder 單例並取消其訂閱
    get_bus().clear()          # 清所有 bus 狀態
    reset_flash_state()        # 清 FlashAlert 狀態
    from unittest.mock import MagicMock
    gw = MagicMock()
    return TimestampSynchronizer(gateway=gw)


# ─────────────────────────────────────────────────────────────────────────────
# Test 01 — 初始化
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 01 — 初始化')
print(SECTION)

sync1 = _fresh_sync()
bus1  = get_bus()

check(sync1.role_name == "琪琪",    "role_name 正確")
check(sync1.role_code == "DM-03",   "role_code 正確")
check(sync1.snapshot_count == 0,    "snapshot_count 初始為 0")
check(len(sync1.staleness_warnings) == 0, "staleness_warnings 初始為空")

# last_report_times 全部為 None
check(all(v is None for v in sync1.last_report_times.values()), "所有 last_report_times 初始為 None")
check(set(sync1.last_report_times.keys()) == {"io", "ca", "ga", "tk"}, "last_report_times 包含 4 個課")

# 已訂閱 4 個 report.* channels
for course in ["io", "ca", "ga", "tk"]:
    subscribers = bus1.get_subscribers(f"report.{course}")
    check("DM-03" in subscribers, f"已訂閱 report.{course}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 02 — 接收報告
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 02 — 接收報告更新時間戳')
print(SECTION)

sync2 = _fresh_sync()
bus2  = get_bus()

check(sync2.last_report_times["io"] is None, "io 初始為 None")

t_before = time.time()
bus2.publish("report.io", {"payload": "test"}, sender="IO-Course")
t_after = time.time()

check(sync2.last_report_times["io"] is not None, "io 發布後時間戳已更新")
check(t_before <= sync2.last_report_times["io"] <= t_after, "io 時間戳在合理範圍內")

# ca 尚未收到
check(sync2.last_report_times["ca"] is None, "ca 仍為 None")

# 發送多個課的報告
for course in ["ca", "ga", "tk"]:
    bus2.publish(f"report.{course}", {"payload": "test"}, sender="COURSE")

check(all(v is not None for v in sync2.last_report_times.values()), "4 個課都有時間戳")

# 重複發送 io → 時間戳應更新
old_io_ts = sync2.last_report_times["io"]
time.sleep(0.01)
bus2.publish("report.io", {"payload": "update"}, sender="IO-Course")
check(sync2.last_report_times["io"] >= old_io_ts, "重複發送 io，時間戳應 ≥ 舊值")


# ─────────────────────────────────────────────────────────────────────────────
# Test 03 — 建造快照
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 03 — 建造快照 build_snapshot()')
print(SECTION)

sync3 = _fresh_sync()
bus3  = get_bus()

# 模擬 4 個課都發送報告
for course in ["io", "ca", "ga", "tk"]:
    bus3.publish(f"report.{course}", {"data": "ok"}, sender="COURSE")

check(all(v is not None for v in sync3.last_report_times.values()), "4 課都已報告")

snap = sync3.build_snapshot()

check(isinstance(snap, SnapshotBundle),     "build_snapshot() 回傳 SnapshotBundle")
check(sync3.snapshot_count == 1,            "snapshot_count 遞增到 1")
check(snap.snapshot_id.startswith("SNAP-"), "snapshot_id 格式正確")
check(isinstance(snap.snapshot_time, datetime), "snapshot_time 為 datetime")

# 再建一次 → count=2
snap2 = sync3.build_snapshot()
check(sync3.snapshot_count == 2, "第二次 build_snapshot，count=2")
check(isinstance(snap2, SnapshotBundle),    "第二次回傳 SnapshotBundle")


# ─────────────────────────────────────────────────────────────────────────────
# Test 04 — 新鮮度判斷
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 04 — 新鮮度判斷 get_freshness_summary()')
print(SECTION)

sync4 = _fresh_sync()

# io expected = 300s，閾值：real_time < 90s, recent 90-300s, delayed 300-600s, stale ≥ 600s

# 4a. 剛剛收到 → real_time
sync4.last_report_times["io"] = time.time()
s4 = sync4.get_freshness_summary()
check(s4["io"]["freshness_grade"] == "real_time",
      f"剛收到應為 real_time，得到 {s4['io']['freshness_grade']}")
check(s4["io"]["status"] == "ok",
      f"real_time 狀態應為 ok，得到 {s4['io']['status']}")

# 4b. 200 秒前 → recent（90 < 200 < 300）
sync4.last_report_times["io"] = time.time() - 200
s4b = sync4.get_freshness_summary()
check(s4b["io"]["freshness_grade"] == "recent",
      f"200s 前應為 recent，得到 {s4b['io']['freshness_grade']}")
check(s4b["io"]["status"] == "ok", "recent 狀態應為 ok")

# 4c. 400 秒前 → delayed（300 < 400 < 600）
sync4.last_report_times["io"] = time.time() - 400
s4c = sync4.get_freshness_summary()
check(s4c["io"]["freshness_grade"] == "delayed",
      f"400s 前應為 delayed，得到 {s4c['io']['freshness_grade']}")
check(s4c["io"]["status"] == "warning", "delayed 狀態應為 warning")

# 4d. 700 秒前 → stale（700 > 600）
sync4.last_report_times["io"] = time.time() - 700
s4d = sync4.get_freshness_summary()
check(s4d["io"]["freshness_grade"] == "stale",
      f"700s 前應為 stale，得到 {s4d['io']['freshness_grade']}")
check(s4d["io"]["status"] == "warning", "stale 狀態應為 warning")

# 4e. expected_seconds 欄位
check(s4d["io"]["expected_seconds"] == 300, "expected_seconds 為 300")
check(isinstance(s4d["io"]["elapsed_seconds"], float), "elapsed_seconds 為 float")

# 4f. ca expected = 60s
sync4.last_report_times["ca"] = time.time() - 10
s4f = sync4.get_freshness_summary()
check(s4f["ca"]["freshness_grade"] == "real_time",
      f"ca 10s 前應為 real_time，得到 {s4f['ca']['freshness_grade']}")

sync4.last_report_times["ca"] = time.time() - 50
s4g = sync4.get_freshness_summary()
check(s4g["ca"]["freshness_grade"] == "recent",
      f"ca 50s 前(>60*0.3=18s) 應為 recent，得到 {s4g['ca']['freshness_grade']}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 05 — 過時警告（warning）
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 05 — 過時警告（warning）')
print(SECTION)

sync5 = _fresh_sync()

# ca expected=60s，warning 閾值 = 60*2 = 120s
# 設為 130s 前 → 超過 2 倍但未超 3 倍
sync5.last_report_times["ca"] = time.time() - 130

check(len(sync5.staleness_warnings) == 0, "初始無警告")

sync5._check_staleness()

check(len(sync5.staleness_warnings) == 1, "觸發一筆 staleness_warning")

w = sync5.staleness_warnings[0]
check(w["course"] == "ca",        "警告課別為 ca")
check(w["severity"] == "warning", f"severity 應為 warning，得到 {w['severity']}")
check(w["expected_seconds"] == 60, "expected_seconds 正確")
check(w["elapsed_seconds"] >= 130, "elapsed_seconds ≥ 130")

# warning 不應發 FlashAlert
check(len(_sent_alerts) == 0, "warning 等級不發 FlashAlert")


# ─────────────────────────────────────────────────────────────────────────────
# Test 06 — 過時警告（critical）→ FlashAlert
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 06 — 過時警告（critical）+ FlashAlert')
print(SECTION)

sync6 = _fresh_sync()

# ca expected=60s，critical 閾值 = 60*3 = 180s
# 設為 200s 前 → 超過 3 倍
sync6.last_report_times["ca"] = time.time() - 200
before_alerts = len(_sent_alerts)

sync6._check_staleness()

check(len(sync6.staleness_warnings) == 1, "觸發一筆 critical staleness_warning")
wc = sync6.staleness_warnings[0]
check(wc["severity"] == "critical", f"severity 應為 critical，得到 {wc['severity']}")

# 應發送 FlashAlert
check(len(_sent_alerts) > before_alerts, "critical 應發送 FlashAlert")
latest_alert = list(_sent_alerts.values())[-1]
check(latest_alert.alert_type == "DATA_OFFLINE",  f"alert_type 應為 DATA_OFFLINE，得到 {latest_alert.alert_type}")
check(latest_alert.alert_level == "critical",     f"alert_level 應為 critical，得到 {latest_alert.alert_level}")
check(latest_alert.requires_acknowledgment,       "critical FlashAlert 需要確認")
check("小蔡" in latest_alert.target_recipients,  "recipients 含 '小蔡'")
check("老蘇" in latest_alert.target_recipients,  "recipients 含 '老蘇'")
check("ca" in latest_alert.title,                "title 含課別 'ca'")

# build_snapshot 也會觸發 _check_staleness
sync6b = _fresh_sync()
sync6b.last_report_times["io"] = time.time() - 1000   # io: 1000s > 300*3=900s → critical
before6b = len(_sent_alerts)
sync6b.build_snapshot()
check(len(_sent_alerts) > before6b, "build_snapshot 也觸發 critical FlashAlert")


# ─────────────────────────────────────────────────────────────────────────────
# Test 07 — 重複警告防止（60 秒內不重複）
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 07 — 重複警告防止')
print(SECTION)

sync7 = _fresh_sync()
sync7.last_report_times["ca"] = time.time() - 200   # critical

sync7._check_staleness()
count_after_first = len(sync7.staleness_warnings)
check(count_after_first == 1, "第一次觸發：staleness_warnings 有 1 筆")

# 立即再次觸發（同一秒內）
sync7._check_staleness()
check(len(sync7.staleness_warnings) == count_after_first, "60s 內重複觸發不增加警告")

# 還有 ga, tk, io 都沒有 last_report_times（None）→ 也不應加警告
check(all(
    sync7.last_report_times[c] is None for c in ["ga", "tk", "io"]
), "其他課仍為 None，不觸發警告")

# 模擬多個課同時過時（不同課各自獨立計數）
sync7b = _fresh_sync()
sync7b.last_report_times["ca"] = time.time() - 200  # critical
sync7b.last_report_times["io"] = time.time() - 1000  # critical (>300*3=900)
sync7b._check_staleness()
check(len(sync7b.staleness_warnings) == 2, "兩個課同時過時，各自一筆警告")


# ─────────────────────────────────────────────────────────────────────────────
# Test 08 — 從未收到報告
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 08 — 從未收到報告時的新鮮度')
print(SECTION)

sync8 = _fresh_sync()

# 不發任何訊息，直接查詢
s8 = sync8.get_freshness_summary()

check(len(s8) == 4, "回傳 4 個課的摘要")
for course in ["io", "ca", "ga", "tk"]:
    check(s8[course]["status"] == "no_data",
          f"{course} 無資料，status='no_data'，得到 {s8[course]['status']}")
    check(s8[course]["elapsed_seconds"] is None,
          f"{course} elapsed_seconds 應為 None")
    check(s8[course]["freshness_grade"] == "stale",
          f"{course} 預設 freshness_grade='stale'")

# _check_staleness 不應對 None 觸發警告
sync8._check_staleness()
check(len(sync8.staleness_warnings) == 0, "last_time=None 不觸發過時警告")


# ─────────────────────────────────────────────────────────────────────────────
# Test 09 — 完整流程 + get_stats
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 09 — 完整流程與 get_stats()')
print(SECTION)

sync9 = _fresh_sync()
bus9  = get_bus()

# 各課依序發送報告
for course in ["io", "ca", "ga", "tk"]:
    bus9.publish(f"report.{course}", {"ok": True}, sender="COURSE")

# 建造 3 次快照
for _ in range(3):
    snap = sync9.build_snapshot()
    check(isinstance(snap, SnapshotBundle), "build_snapshot 回傳 SnapshotBundle")

check(sync9.snapshot_count == 3, f"snapshot_count 應為 3，得到 {sync9.snapshot_count}")

# get_stats 結構
stats = sync9.get_stats()
check("snapshots_built" in stats,          "get_stats 含 snapshots_built")
check("staleness_warnings_total" in stats, "get_stats 含 staleness_warnings_total")
check("current_freshness" in stats,        "get_stats 含 current_freshness")

check(stats["snapshots_built"] == 3,       f"snapshots_built=3，得到 {stats['snapshots_built']}")
check(stats["staleness_warnings_total"] == 0, "正常運作無警告")

freshness = stats["current_freshness"]
check(len(freshness) == 4, "freshness 包含 4 個課")
for course in ["io", "ca", "ga", "tk"]:
    grade = freshness[course]["freshness_grade"]
    check(grade in ("real_time", "recent"),
          f"{course} 剛更新應為 real_time/recent，得到 {grade}")

# expected_intervals 驗證
check(sync9.expected_intervals["io"] == 300,  "io expected_interval=300")
check(sync9.expected_intervals["ca"] == 60,   "ca expected_interval=60")
check(sync9.expected_intervals["ga"] == 1080, "ga expected_interval=1080")
check(sync9.expected_intervals["tk"] == 600,  "tk expected_interval=600")


# ─────────────────────────────────────────────────────────────────────────────
# 結果統計
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print(f'結果: {passed} passed, {failed} failed (共 {passed + failed} tests)')
print(SECTION)

if failed > 0:
    sys.exit(1)
