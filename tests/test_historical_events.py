# -*- coding: utf-8 -*-
import sys
import io
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from collections import Counter
from trading_system.common.historical_events_db import (
    load_events,
    find_similar,
    compute_avg_reaction,
    add_event,
    _DB_PATH,
)

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

# ─── [1] 載入測試 ─────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] 事件庫載入測試')
print(SECTION)

events = load_events()
print(f'  事件總數: {len(events)}')
check(len(events) == 15, f'事件數量正確（15 個）')

# 各類別分佈
cat_counts = Counter(e['category'] for e in events)
sub_counts = Counter(e['subcategory'] for e in events)

print(f'\n  類別分佈：')
for cat, cnt in sorted(cat_counts.items()):
    print(f'    {cat:<22s}  {cnt} 個')

print(f'\n  次分類分佈：')
for sub, cnt in sorted(sub_counts.items()):
    print(f'    {sub:<30s}  {cnt} 個')

check(cat_counts['GEOPOLITICAL'] == 3,    'GEOPOLITICAL 3 個')
check(cat_counts['ECONOMIC'] == 3,        'ECONOMIC 3 個')
check(cat_counts['REGULATORY'] == 4,      'REGULATORY 4 個')
check(cat_counts['CRYPTO_NATIVE'] == 3,   'CRYPTO_NATIVE 3 個')
check(cat_counts['BLACK_SWAN'] == 2,      'BLACK_SWAN 2 個')

# 確認每個事件都有必要欄位
required_fields = {'event_id', 'date', 'category', 'subcategory',
                   'description', 'key_entities', 'btc_reaction', 'eth_reaction',
                   'recovery_days', 'max_drawdown_during_event',
                   'novelty', 'escalation', 'reversibility'}
incomplete = [e['event_id'] for e in events if not required_fields.issubset(e.keys())]
check(len(incomplete) == 0, f'所有事件欄位完整（缺欄位事件: {incomplete}）')

# ─── [2] find_similar 查詢測試 ────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] find_similar 查詢測試')
print(SECTION)

# 2a: 地緣政治軍事衝突（category.subcategory 格式）
print('\n  查詢: GEOPOLITICAL.military_conflict  limit=3')
results = find_similar('GEOPOLITICAL.military_conflict', limit=3)
for r in results:
    print(f'    {r["event_id"]}  {r["date"]}  {r["description"][:55]}...')
check(len(results) == 3, 'military_conflict 找到 3 個事件')

# 2b: ETF 審批（subcategory 格式）
print('\n  查詢: etf_approval  limit=5')
results_etf = find_similar('etf_approval', limit=5)
for r in results_etf:
    print(f'    {r["event_id"]}  {r["date"]}  {r["subcategory"]}')
check(len(results_etf) == 2, 'etf_approval 找到 2 個事件')

# 2c: category 格式 + 實體加權
print('\n  查詢: REGULATORY + entities=[SEC, BlackRock]  limit=3')
results_reg = find_similar('REGULATORY', entities=['SEC', 'BlackRock'], limit=3)
for r in results_reg:
    entities_hit = [e for e in r.get('key_entities', []) if e in ('SEC', 'BlackRock')]
    print(f'    {r["event_id"]}  {r["date"]}  命中實體: {entities_hit}')
check(len(results_reg) >= 2, 'REGULATORY + 實體加權找到 ≥ 2 個事件')
# 首個結果應該是 ETF 事件（同時命中 SEC + BlackRock）
check(
    any('BlackRock' in r.get('key_entities', []) for r in results_reg[:2]),
    '最前結果包含 BlackRock 相關事件'
)

# 2d: 加密原生類（category 格式）
print('\n  查詢: CRYPTO_NATIVE  limit=5')
results_cn = find_similar('CRYPTO_NATIVE', limit=5)
for r in results_cn:
    print(f'    {r["event_id"]}  {r["date"]}  {r["subcategory"]}')
check(len(results_cn) == 3, 'CRYPTO_NATIVE 找到 3 個事件')

# 2e: 黑天鵝
print('\n  查詢: BLACK_SWAN  limit=5')
results_bs = find_similar('BLACK_SWAN', limit=5)
for r in results_bs:
    print(f'    {r["event_id"]}  {r["date"]}  {r["description"][:55]}...')
check(len(results_bs) == 2, 'BLACK_SWAN 找到 2 個事件')

# ─── [3] compute_avg_reaction 測試 ────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] compute_avg_reaction 平均反應計算')
print(SECTION)

def print_avg(label: str, avg: dict) -> None:
    br = avg['btc_reaction']
    er = avg['eth_reaction']
    print(f'\n  【{label}】  ({avg["event_count"]} 個事件)')
    print(f'    BTC  24h: {br["24h_change_pct"]:+.2f}%  '
          f'48h: {br["48h_change_pct"]:+.2f}%  '
          f'7d: {br["7d_change_pct"]:+.2f}%')
    print(f'    ETH  24h: {er["24h_change_pct"]:+.2f}%  '
          f'48h: {er["48h_change_pct"]:+.2f}%  '
          f'7d: {er["7d_change_pct"]:+.2f}%')
    print(f'    回復天數: {avg["avg_recovery_days"]} 天  '
          f'最大回撤: {avg["avg_max_drawdown"]}%')

# 地緣政治
geo_events = [e for e in events if e['category'] == 'GEOPOLITICAL']
avg_geo = compute_avg_reaction(geo_events)
print_avg('GEOPOLITICAL', avg_geo)
check(avg_geo['btc_reaction']['24h_change_pct'] < 0, 'GEOPOLITICAL 平均 BTC 24h 為負')

# 黑天鵝
bs_events = [e for e in events if e['category'] == 'BLACK_SWAN']
avg_bs = compute_avg_reaction(bs_events)
print_avg('BLACK_SWAN', avg_bs)
check(avg_bs['btc_reaction']['24h_change_pct'] < -10, 'BLACK_SWAN 平均 BTC 24h 跌逾 10%')

# 監管
reg_events = [e for e in events if e['category'] == 'REGULATORY']
avg_reg = compute_avg_reaction(reg_events)
print_avg('REGULATORY', avg_reg)

# 加密原生（只看負面事件）
cn_neg = [e for e in events
          if e['category'] == 'CRYPTO_NATIVE'
          and e['btc_reaction']['24h_change_pct'] < 0]
avg_cn_neg = compute_avg_reaction(cn_neg)
print_avg('CRYPTO_NATIVE (負面)', avg_cn_neg)
check(avg_cn_neg['avg_max_drawdown'] < -20, 'CRYPTO_NATIVE 負面事件平均回撤 < -20%')

# 全部事件
avg_all = compute_avg_reaction(events)
print_avg('全部事件', avg_all)
check(avg_all['event_count'] == 15, 'compute_avg_reaction 正確計算 15 個事件')

# 空列表
avg_empty = compute_avg_reaction([])
check(avg_empty == {'event_count': 0}, 'compute_avg_reaction 空列表回傳 {event_count: 0}')

# ─── [4] add_event 測試 ────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] add_event 新增 / 驗證 / 還原測試')
print(SECTION)

# 備份原始資料
with open(_DB_PATH, encoding='utf-8') as f:
    _original = json.load(f)

test_event = {
    "event_id": "EVT-20260425-TEST",
    "date": "2026-04-25",
    "category": "REGULATORY",
    "subcategory": "test",
    "description": "測試用虛擬事件，系統自動還原",
    "key_entities": ["TEST"],
    "btc_reaction": {"24h_change_pct": 0.0, "48h_change_pct": 0.0, "7d_change_pct": 0.0},
    "eth_reaction": {"24h_change_pct": 0.0, "48h_change_pct": 0.0, "7d_change_pct": 0.0},
    "recovery_days": 0,
    "max_drawdown_during_event": 0.0,
    "novelty": "first",
    "escalation": "維持",
    "reversibility": "reversible",
    "estimated": True
}

try:
    add_event(test_event)
    events_after = load_events()
    check(len(events_after) == 16, f'新增後事件數為 16（實際: {len(events_after)}）')

    # 重複 event_id 應拒絕
    try:
        add_event(test_event)
        check(False, '重複 event_id 應拋出 ValueError')
    except ValueError as e:
        check(True, f'重複 event_id 正確拒絕: {str(e)[:40]}')

    # 缺少必要欄位應拒絕
    try:
        add_event({"event_id": "EVT-MISSING", "date": "2026-01-01"})
        check(False, '缺少必要欄位應拋出 ValueError')
    except ValueError as e:
        check(True, f'缺少欄位正確拒絕: {str(e)[:50]}')

finally:
    # 還原原始資料
    with open(_DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(_original, f, ensure_ascii=False, indent=2)
    restored = load_events()
    check(len(restored) == 15, f'資料還原至 15 個事件（實際: {len(restored)}）')

# ─── 總結 ─────────────────────────────────────────────────────────────────────

total = passed + failed
print(f'\n{SECTION}')
print('  總結')
print(SECTION)
print(f'  事件庫路徑    : {_DB_PATH}')
print(f'  事件總數      : {len(load_events())}')
print(f'  各類別        : {dict(sorted(cat_counts.items()))}')
print(f'  測試結果      : {passed} / {total} 通過')
if failed == 0:
    print('  [全部通過]')
else:
    print(f'  [注意] {failed} 個測試失敗')
print(SECTION)
