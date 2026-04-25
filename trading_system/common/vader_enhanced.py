# -*- coding: utf-8 -*-
"""
增強版 VADER 情緒分析引擎
- 金融詞庫（從 JSON 設定檔載入，含詞形擴充）
- 語境反轉規則
- 數字模式識別
"""
import json
import pathlib
import re
import warnings
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_LEXICON_JSON_PATH = pathlib.Path(__file__).parent.parent / "data" / "financial_lexicon.json"

# ─── 詞形擴充 ─────────────────────────────────────────────────────────────────

def _expand_word_forms(word: str, score: float) -> dict[str, float]:
    """
    根據詞尾規則產生最多 4 種變化 (base / +s / +ed / +ing)。
    規則優先順序：
      1. 結尾 'e'          → +s, drop-e+d, drop-e+ing   (surge→surges/surged/surging)
      2. 結尾 'y'          → -y+ies, -y+ied, +ing        (rally→rallies/rallied/rallying)
      3. 結尾 sh/ch/x      → +es, +ed, +ing              (crash→crashes/crashed/crashing)
      4. CVC (輔母輔) 結尾  → +s, double+ed, double+ing   (ban→bans/banned/banning)
      5. 其他              → +s, +ed, +ing               (adopt→adopts/adopted/adopting)
    """
    forms: dict[str, float] = {word: score}

    if word.endswith('e'):
        forms[word + 's'] = score
        forms[word[:-1] + 'ed'] = score
        forms[word[:-1] + 'ing'] = score

    elif word.endswith('y'):
        forms[word[:-1] + 'ies'] = score
        forms[word[:-1] + 'ied'] = score
        forms[word + 'ing'] = score

    elif word.endswith(('sh', 'ch', 'x')):
        forms[word + 'es'] = score
        forms[word + 'ed'] = score
        forms[word + 'ing'] = score

    elif (len(word) >= 3
          and word[-1] not in 'aeiouwy'
          and word[-2] in 'aeiou'
          and word[-3] not in 'aeiou'):
        # Consonant-Vowel-Consonant：最後一個輔音加倍
        forms[word + 's'] = score
        forms[word + word[-1] + 'ed'] = score
        forms[word + word[-1] + 'ing'] = score

    else:
        forms[word + 's'] = score
        forms[word + 'ed'] = score
        forms[word + 'ing'] = score

    return forms


# ─── Hardcoded 備援詞庫 ────────────────────────────────────────────────────────

_BASE_WORDS_HARDCODED: dict[str, float] = {
    'surge':        +3.0,
    'crash':        -3.5,
    'plunge':       -3.0,
    'rally':        +2.5,
    'approve':      +3.0,
    'ban':          -3.0,
    'adopt':        +2.5,
    'reject':       -2.5,
    'hack':         -4.0,
    'exploit':      -3.5,
    'breakthrough': +3.5,
    'collapse':     -3.5,
    'boom':         +3.0,
    'crackdown':    -3.0,
}

_CRYPTO_SLANG_HARDCODED: dict[str, float] = {
    'hodl':       +1.5,
    'fud':        -2.0,
    'rekt':       -3.0,
    'moon':       +2.0,
    'mooning':    +2.0,
    'depeg':      -3.0,
    'halving':    +1.5,
    'hacked':     -4.0,
    'hacking':    -4.0,
    'lawsuit':    -2.5,
    'sued':       -2.5,
    'sanction':   -2.5,
    'sanctions':  -2.5,
    'sanctioned': -2.5,
}


def _build_hardcoded_lexicon() -> dict[str, float]:
    lexicon: dict[str, float] = {}
    for w, s in _BASE_WORDS_HARDCODED.items():
        lexicon.update(_expand_word_forms(w, s))
    lexicon.update(_CRYPTO_SLANG_HARDCODED)
    return lexicon


# ─── JSON 詞庫載入 ─────────────────────────────────────────────────────────────

_SKIP_SECTIONS = {'否定詞', '數字模式', '語境反轉模式'}


def load_lexicon_from_json(path: pathlib.Path = _LEXICON_JSON_PATH) -> dict[str, float]:
    """
    從 financial_lexicon.json 讀取詞庫並展開詞形變化。
    忽略 否定詞 / 數字模式 / 語境反轉模式 區段（另有硬編碼處理）。
    JSON 讀取失敗時自動回退至 hardcoded 備援詞庫。
    """
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)

        lexicon: dict[str, float] = {}
        for section, content in data['lexicon'].items():
            if section in _SKIP_SECTIONS:
                continue
            words = content.get('words', {})
            if not isinstance(words, dict):
                continue
            for word, score in words.items():
                lexicon.update(_expand_word_forms(word, float(score)))

        if not lexicon:
            raise ValueError("載入後詞庫為空")

        return lexicon

    except Exception as exc:
        warnings.warn(
            f"[vader_enhanced] 無法從 {path} 讀取詞庫（{exc}），使用 hardcoded 備援。",
            RuntimeWarning,
            stacklevel=2,
        )
        return _build_hardcoded_lexicon()


# ─── 詞庫初始化 ───────────────────────────────────────────────────────────────

FINANCIAL_LEXICON: dict[str, float] = load_lexicon_from_json()

# 初始化 VADER 並注入金融詞庫
_analyzer = SentimentIntensityAnalyzer()
_analyzer.lexicon.update(FINANCIAL_LEXICON)

# ─── 語境反轉規則 ──────────────────────────────────────────────────────────────

_REVERSAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'failed\s+to\s+(ban|stop|block|reject|halt)',  re.I), 'REVERSE_NEG'),
    (re.compile(r'rejected\s+(ban|sanctions|restrictions)',      re.I), 'REVERSE_NEG'),
    (re.compile(r'fears?\s+ease',                               re.I), 'REVERSE_NEG'),
    (re.compile(r'concerns?\s+fade',                            re.I), 'REVERSE_NEG'),
    (re.compile(r'recovery\s+from',                             re.I), 'REVERSE_NEG'),
    (re.compile(r'despite\s+(crash|plunge|sell.?off)',          re.I), 'REVERSE_NEG'),
]


def context_reversal(text: str) -> str | None:
    """偵測到語境反轉模式時回傳類型字串，否則回傳 None。"""
    for pattern, reversal_type in _REVERSAL_PATTERNS:
        if pattern.search(text):
            return reversal_type
    return None


# ─── 數字模式識別 ──────────────────────────────────────────────────────────────

# (compiled_pattern, label, sign_or_flat)
# sign_or_flat > 1.0 表示 flat 分數；否則為方向乘數（配合 pct/10 計算）
_NUMBER_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r'\bup\s+(\d+(?:\.\d+)?)%',     re.I), 'up_pct',         'pct+'),
    (re.compile(r'\bdown\s+(\d+(?:\.\d+)?)%',   re.I), 'down_pct',       'pct-'),
    (re.compile(r'\bgains?\s+(\d+(?:\.\d+)?)%', re.I), 'gain_pct',       'pct+'),
    (re.compile(r'\bdrops?\s+(\d+(?:\.\d+)?)%', re.I), 'drop_pct',       'pct-'),
    (re.compile(r'all.?time\s+high',             re.I), 'ath',            'flat+0.8'),
    (re.compile(r'all.?time\s+low',              re.I), 'atl',            'flat-0.8'),
    (re.compile(r'\d+.?month\s+high',            re.I), 'nth_month_high', 'flat+0.5'),
    (re.compile(r'\d+.?month\s+low',             re.I), 'nth_month_low',  'flat-0.5'),
]


def number_pattern_score(text: str) -> tuple[float, list[str]]:
    """
    掃描數字模式，回傳 (合計分數, 命中描述清單)。
    合計分數已 clamp 至 [-1, +1]。
    """
    total = 0.0
    matched: list[str] = []

    for pattern, name, mode in _NUMBER_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue

        if mode.startswith('pct'):
            pct = float(m.group(1))
            contrib = (1 if mode == 'pct+' else -1) * min(pct / 10.0, 1.0)
        else:
            contrib = float(mode.replace('flat', ''))

        total += contrib
        matched.append(f"{name}({contrib:+.2f})")

    return max(-1.0, min(1.0, total)), matched


# ─── 主函數 ────────────────────────────────────────────────────────────────────

def label(score: float) -> str:
    if score >= 0.05:
        return "positive"
    if score <= -0.05:
        return "negative"
    return "neutral"


def analyze_sentiment(text: str) -> dict:
    """
    整合 VADER + 金融詞庫 + 語境反轉 + 數字模式，回傳：
    {
        score:      float [-1, +1],
        label:      str   positive / negative / neutral,
        confidence: float [0, 1],
        details: {
            vader_base_score:      float,
            keywords_matched:      list[str],
            reversal_triggered:    bool,
            number_patterns_found: list[str],
        }
    }
    """
    # a) VADER（已含金融詞庫）
    vs = _analyzer.polarity_scores(text)
    vader_base = vs['compound']

    # b) 命中的金融關鍵詞
    words = re.findall(r"[a-z']+", text.lower())
    keywords = [w for w in words if w in FINANCIAL_LEXICON]

    # c) 語境反轉
    reversal = context_reversal(text)
    score = -vader_base if reversal else vader_base

    # d) 數字模式加成（權重 0.4，不完全覆蓋 VADER 結果）
    num_score, num_patterns = number_pattern_score(text)
    score += num_score * 0.4

    # e) clamp 至 [-1, +1]
    score = max(-1.0, min(1.0, score))

    return {
        'score':      round(score, 4),
        'label':      label(score),
        'confidence': round(abs(score), 4),
        'details': {
            'vader_base_score':      vader_base,
            'keywords_matched':      keywords,
            'reversal_triggered':    reversal is not None,
            'number_patterns_found': num_patterns,
        },
    }
