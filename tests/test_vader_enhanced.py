# -*- coding: utf-8 -*-
import sys
import io
import os
import re

# 確保 trading_system 可被 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from trading_system.common.vader_enhanced import analyze_sentiment, FINANCIAL_LEXICON

SECTION = '=' * 70

# 基本 VADER（無金融詞庫），做為對照基準
_base = SentimentIntensityAnalyzer()


def base_score(text: str) -> float:
    return _base.polarity_scores(text)['compound']


def label(score: float) -> str:
    if score >= 0.05:
        return 'positive'
    if score <= -0.05:
        return 'negative'
    return 'neutral'


def print_comparison(text: str) -> None:
    b = base_score(text)
    e = analyze_sentiment(text)
    delta = e['score'] - b
    sign = '+' if delta >= 0 else ''

    print(f"  句子   : {text}")
    print(f"  基本   : {b:+.4f}  ({label(b)})")
    print(f"  增強版 : {e['score']:+.4f}  ({e['label']})  "
          f"confidence={e['confidence']:.3f}")
    print(f"  差異   : {sign}{delta:.4f}")

    d = e['details']
    if d['keywords_matched']:
        print(f"  命中詞 : {', '.join(d['keywords_matched'])}")
    if d['reversal_triggered']:
        print(f"  [反轉] 語境反轉規則觸發 → 符號翻轉")
    if d['number_patterns_found']:
        print(f"  [數字] {', '.join(d['number_patterns_found'])}")
    print()


# ─── [1] 詞形擴充驗證 ─────────────────────────────────────────────────────────
print(SECTION)
print('  [1] 詞形擴充驗證 — 確認 FINANCIAL_LEXICON 覆蓋詞形變化')
print(SECTION)

check_forms = [
    ('surge',   ['surge', 'surges', 'surged', 'surging']),
    ('crash',   ['crash', 'crashes', 'crashed', 'crashing']),
    ('rally',   ['rally', 'rallies', 'rallied', 'rallying']),
    ('ban',     ['ban', 'bans', 'banned', 'banning']),
    ('approve', ['approve', 'approves', 'approved', 'approving']),
    ('hack',    ['hack', 'hacked', 'hacking']),
]

for base_word, forms in check_forms:
    results = []
    for f in forms:
        score = FINANCIAL_LEXICON.get(f)
        results.append(f"{f}({'OK' if score else 'MISS'})")
    print(f"  {base_word:12s}: {', '.join(results)}")
print()

# ─── [2] 原本的盲點測試（增強版 vs 基本 VADER）────────────────────────────────
print(SECTION)
print('  [2] 原始盲點句子 — 增強版 vs 基本 VADER')
print(SECTION)
print('  這些句子在基本 VADER 測試中表現不佳\n')

blind_spot_cases = [
    # 原本 neutral=0.00，surges 應為正面
    'Bitcoin surges to new all-time high as institutional adoption accelerates',
    # 原本 neutral=0.00，hack 應為強負面
    'Major exchange reports $100M hack, investigation ongoing',
    # 原本 neutral=0.00，tariffs 語境應為負面
    'Trump announces new tariffs on Chinese tech imports',
]
for s in blind_spot_cases:
    print_comparison(s)

# ─── [3] 語境反轉測試 ─────────────────────────────────────────────────────────
print(SECTION)
print('  [3] 語境反轉測試 — 反轉後語義應與基本 VADER 相反')
print(SECTION)
print('  "failed to ban" / "fears ease" 等應被翻轉為正面\n')

reversal_cases = [
    'SEC failed to ban crypto exchange',
    'Fears of crash ease as regulators approve ETF',
    'Bitcoin rallies despite crash in altcoins',
    'Recovery from the hack accelerates, exchange resumes operations',
]
for s in reversal_cases:
    print_comparison(s)

# ─── [4] 數字模式識別測試 ─────────────────────────────────────────────────────
print(SECTION)
print('  [4] 數字模式識別 — 百分比與高低點')
print(SECTION)
print('  基本 VADER 對純數字新聞幾乎無感，增強版應能識別漲跌\n')

number_cases = [
    'Bitcoin hits $77,500 up 3.5%',
    'Ethereum down 12% after network outage',
    'Crypto market gains 8% on ETF approval news',
    'BTC drops 25% in flash crash',
    'Bitcoin reaches all-time high above $100,000',
    'Altcoin hits 6-month low amid bearish sentiment',
]
for s in number_cases:
    print_comparison(s)

# ─── [5] 否定詞測試（重跑原本的否定句）──────────────────────────────────────
print(SECTION)
print('  [5] 否定詞 + 複合語境 — 重跑原始測試句')
print(SECTION)
print('  驗證增強版與基本版在否定語境的行為差異\n')

negation_cases = [
    'Fed did not raise interest rates',
    'SEC failed to ban crypto exchange',
    'Fears of crash ease as regulators approve ETF',
]
for s in negation_cases:
    print_comparison(s)

# ─── [6] 完整 8 句對比（原始盲點測試的全集）──────────────────────────────────
print(SECTION)
print('  [6] 原始 8 句完整對比')
print(SECTION)
print()

all_original = [
    'Bitcoin surges to new all-time high as institutional adoption accelerates',
    'SEC sues major crypto exchange for securities violations',
    'Fed maintains interest rates, markets react positively',
    'Ethereum network upgrade delayed, developers face criticism',
    'Trump announces new tariffs on Chinese tech imports',
    'Regulatory clarity on stablecoins boosts market confidence',
    'Major exchange reports $100M hack, investigation ongoing',
    'Whale moves 50000 ETH to exchange, sparks selling fears',
]
for s in all_original:
    print_comparison(s)

# ─── 總結 ────────────────────────────────────────────────────────────────────
print(SECTION)
print('  增強版 VADER 引擎測試完成')
print(f'  金融詞庫總詞條數: {len(FINANCIAL_LEXICON)}')
print(SECTION)
