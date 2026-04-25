# -*- coding: utf-8 -*-
import sys
import io
import os
import json
import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.common.vader_enhanced import (
    analyze_sentiment,
    load_lexicon_from_json,
    _build_hardcoded_lexicon,
    FINANCIAL_LEXICON,
    _LEXICON_JSON_PATH,
)

SECTION = '=' * 65

# ─── [1] JSON 結構驗證 ────────────────────────────────────────────────────────

print(SECTION)
print('  [1] JSON 設定檔結構驗證')
print(SECTION)

json_path = pathlib.Path(_LEXICON_JSON_PATH)
assert json_path.exists(), f"找不到 JSON 檔案：{json_path}"

with open(json_path, encoding='utf-8') as f:
    raw = json.load(f)

meta = raw['metadata']
print(f"  版本     : {meta['version']}")
print(f"  更新日期 : {meta['last_updated']}")
print(f"  說明     : {meta['description']}")
print()

WORD_SECTIONS = {'強負面', '中負面', '強正面', '中正面'}
total_source = 0

print(f"  {'類別':<12}  {'詞數':>4}  {'分數範圍'}")
print(f"  {'-'*12}  {'-'*4}  {'-'*20}")
for section, content in raw['lexicon'].items():
    words = content.get('words', {})
    # 非評分區段：words 是 list，或該 section 沒有 words 只有 patterns
    if not isinstance(words, dict) or not words:
        patterns = content.get('patterns', words if isinstance(words, list) else [])
        count = len(patterns) if isinstance(patterns, list) else '-'
        print(f"  {section:<12}  {str(count):>4}  （非評分區段）")
        continue
    wmin = min(words.values())
    wmax = max(words.values())
    print(f"  {section:<12}  {len(words):>4}  [{wmin:+.1f}, {wmax:+.1f}]")
    total_source += len(words)

print()
print(f"  來源詞條總數（展開前）: {total_source}")

# ─── [2] 詞庫展開驗證 ─────────────────────────────────────────────────────────

print()
print(SECTION)
print('  [2] 詞形展開驗證')
print(SECTION)

print(f"  展開後 FINANCIAL_LEXICON 詞條數 : {len(FINANCIAL_LEXICON)}")
fallback = _build_hardcoded_lexicon()
print(f"  Hardcoded 備援詞庫詞條數        : {len(fallback)}")
print()

# 確認關鍵詞形都有覆蓋
check_forms = [
    ('surge',        ['surge', 'surges', 'surged', 'surging'],       +3.0),
    ('crash',        ['crash', 'crashes', 'crashed', 'crashing'],     -3.5),
    ('rally',        ['rally', 'rallies', 'rallied', 'rallying'],     +2.5),
    ('ban',          ['ban', 'bans', 'banned', 'banning'],            -3.0),
    ('approve',      ['approve', 'approves', 'approved', 'approving'],+3.0),
    ('hack',         ['hack', 'hacked', 'hacking'],                   -4.0),
    ('bankruptcy',   ['bankruptcy', 'bankruptcies'],                  -4.0),
    ('breakthrough', ['breakthrough', 'breakthroughs'],               +3.5),
    ('ease',         ['ease', 'eases', 'eased', 'easing'],            +1.5),
    ('decline',      ['decline', 'declines', 'declined', 'declining'],-1.5),
]

all_pass = True
print(f"  {'基本詞':14s}  {'展開詞形 (score)'}")
print(f"  {'-'*14}  {'-'*45}")
for base_word, forms, expected_score in check_forms:
    statuses = []
    for f in forms:
        score = FINANCIAL_LEXICON.get(f)
        ok = score is not None
        statuses.append(f"{f}({'✓' if ok else '✗'})")
        if not ok:
            all_pass = False
    print(f"  {base_word:14s}  {', '.join(statuses)}")

print()
if all_pass:
    print('  [PASS] 所有指定詞形均已覆蓋')
else:
    print('  [WARN] 部分詞形未覆蓋，請檢查 JSON 詞庫')

# ─── [3] Fallback 機制驗證 ────────────────────────────────────────────────────

print()
print(SECTION)
print('  [3] Fallback 機制驗證')
print(SECTION)

import pathlib as _pl
bad_path = _pl.Path('/nonexistent/path/lexicon.json')

import warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always')
    fallback_result = load_lexicon_from_json(bad_path)

if caught and issubclass(caught[0].category, RuntimeWarning):
    print(f'  [PASS] 讀取失敗時正確發出 RuntimeWarning')
    print(f'         訊息: {str(caught[0].message)[:80]}')
else:
    print('  [WARN] 未偵測到預期的 RuntimeWarning')

print(f'  Fallback 詞庫詞條數: {len(fallback_result)}')
assert len(fallback_result) > 0, 'Fallback 詞庫不應為空'
print('  [PASS] Fallback 詞庫非空')

# ─── [4] 情緒分析行為驗證 ────────────────────────────────────────────────────

print()
print(SECTION)
print('  [4] 情緒分析行為驗證（比對預期方向）')
print(SECTION)
print()

TEST_CASES = [
    # (句子, 預期 label, 說明)
    ('Bitcoin surges to new all-time high as institutional adoption accelerates',
     'positive', '暴漲 + ATH → 強正面'),
    ('Major exchange reports $100M hack, investigation ongoing',
     'negative', 'hack → 強負面'),
    ('SEC failed to ban crypto exchange',
     'positive', '語境反轉：failed to ban → 正面'),
    ('Regulators rejected ban on crypto stablecoins',
     'positive', '語境反轉：rejected ban → 正面'),
    ('Bitcoin up 3.5%',
     'positive', '數字模式：up X% → 正面'),
    ('Ethereum down 12% after network outage',
     'negative', '數字模式：down X% → 負面'),
    ('Exchange collapse triggers $2B bankruptcy filing',
     'negative', 'collapse + bankruptcy → 強負面'),
    ('Ceasefire agreement boosts global market recovery',
     'positive', 'ceasefire + recovery → 正面'),
    ('CEO faces indictment charges as exchange faces collapse',
     'negative', '新詞庫：indictment + collapse → 強負面'),
    ('Regulators announce new sanctions and restrictions on crypto',
     'negative', 'sanctions + restrictions → 負面'),
]

passed = 0
failed_cases = []

for text, expected, note in TEST_CASES:
    result = analyze_sentiment(text)
    score  = result['score']
    lbl    = result['label']
    kws    = result['details']['keywords_matched']
    rev    = result['details']['reversal_triggered']
    nums   = result['details']['number_patterns_found']

    ok = (lbl == expected)
    status = 'PASS' if ok else 'FAIL'
    if ok:
        passed += 1
    else:
        failed_cases.append((text, expected, lbl, score))

    markers = []
    if rev:
        markers.append('↕反轉')
    if nums:
        markers.append(f'🔢{",".join(nums)}')
    if kws:
        markers.append(f'詞:{",".join(set(kws))}')
    marker_str = '  ' + ' '.join(markers) if markers else ''

    print(f'  [{status}] {score:+.4f} ({lbl:8s}) | {note}')
    if marker_str:
        print(f'         {marker_str.strip()}')

print()
print(f'  結果: {passed} / {len(TEST_CASES)} 通過')
if failed_cases:
    print('  失敗案例：')
    for text, exp, got, score in failed_cases:
        print(f'    預期={exp}, 實際={got}({score:+.4f})')
        print(f'    句子: {text[:80]}')

# ─── 總結 ─────────────────────────────────────────────────────────────────────

print()
print(SECTION)
print('  總結')
print(SECTION)
print(f'  JSON 路徑          : {_LEXICON_JSON_PATH}')
print(f'  來源詞條（展開前）  : {total_source}')
print(f'  展開後詞條          : {len(FINANCIAL_LEXICON)}')
print(f'  行為測試           : {passed} / {len(TEST_CASES)} 通過')
print(f'  {"[全部通過]" if passed == len(TEST_CASES) else "[部分失敗，請檢查]"}')
print(SECTION)
