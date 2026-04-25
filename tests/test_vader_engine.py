# -*- coding: utf-8 -*-
import sys
import io
import requests
import feedparser
import urllib.request
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

USER_AGENT = "ATC Trading System 1.0 (research@example.com)"

FINANCIAL_LEXICON = {
    # 強負面
    "crash":      -3.5,
    "collapse":   -3.5,
    "plunge":     -3.0,
    "hack":       -4.0,
    "exploit":    -3.5,
    "ban":        -3.0,
    "sanctions":  -2.5,
    "lawsuit":    -2.5,
    "crackdown":  -3.0,
    "indictment": -3.5,
    "bankruptcy": -4.0,
    # 強正面
    "approve":      +3.0,
    "adopt":        +2.5,
    "surge":        +3.0,
    "rally":        +2.5,
    "breakthrough": +3.5,
    "partnership":  +2.5,
    "bullish":      +2.5,
    # 加密專有
    "hodl":    +1.5,
    "fud":     -2.0,
    "rekt":    -3.0,
    "moon":    +2.0,
    "halving": +1.5,
    "depeg":   -3.0,
}

TEST_SENTENCES = [
    "Bitcoin surges to new all-time high as institutional adoption accelerates",
    "SEC sues major crypto exchange for securities violations",
    "Fed maintains interest rates, markets react positively",
    "Ethereum network upgrade delayed, developers face criticism",
    "Trump announces new tariffs on Chinese tech imports",
    "Regulatory clarity on stablecoins boosts market confidence",
    "Major exchange reports $100M hack, investigation ongoing",
    "Whale moves 50000 ETH to exchange, sparks selling fears",
]

NEGATION_SENTENCES = [
    "Fed did not raise interest rates",
    "SEC failed to ban crypto exchange",
    "Fears of crash ease as regulators approve ETF",
]

SECTION = "=" * 65


def label(score: float) -> str:
    if score >= 0.05:
        return "positive"
    if score <= -0.05:
        return "negative"
    return "neutral"


def print_scores(sentences: list[str], analyzer: SentimentIntensityAnalyzer,
                 show_delta: bool = False,
                 baseline: dict[str, float] | None = None) -> dict[str, float]:
    scores = {}
    for sent in sentences:
        vs = analyzer.polarity_scores(sent)
        c = vs["compound"]
        scores[sent] = c
        delta_str = ""
        if show_delta and baseline and sent in baseline:
            delta = c - baseline[sent]
            sign = "+" if delta >= 0 else ""
            delta_str = f"  delta={sign}{delta:+.3f}"
        print(f"  句子  : {sent}")
        print(f"  分數  : compound={c:+.4f}  ({label(c)}){delta_str}")
        print(f"  detail: pos={vs['pos']:.3f}  neu={vs['neu']:.3f}  neg={vs['neg']:.3f}")
        print()
    return scores


# ─── 第一區塊：基本 VADER（無金融詞庫）────────────────────────────────────────
print(SECTION)
print("  [1] 基本 VADER — 無金融詞庫")
print(SECTION)

base_analyzer = SentimentIntensityAnalyzer()
baseline_scores = print_scores(TEST_SENTENCES, base_analyzer)

# ─── 第二區塊：加入金融詞庫後比較 ────────────────────────────────────────────
print(SECTION)
print("  [2] 加入金融詞庫後 — 分數比較")
print(SECTION)
print(f"  詞庫大小：{len(FINANCIAL_LEXICON)} 個詞條加入 VADER lexicon\n")

fin_analyzer = SentimentIntensityAnalyzer()
fin_analyzer.lexicon.update(FINANCIAL_LEXICON)
print_scores(TEST_SENTENCES, fin_analyzer, show_delta=True, baseline=baseline_scores)

# ─── 第三區塊：否定詞處理 ────────────────────────────────────────────────────
print(SECTION)
print("  [3] 否定詞處理測試")
print(SECTION)
print("  驗證 VADER 能正確處理 not / failed / ease 等否定/緩和語境\n")

neg_analyzer = SentimentIntensityAnalyzer()
neg_analyzer.lexicon.update(FINANCIAL_LEXICON)
print_scores(NEGATION_SENTENCES, neg_analyzer)

# ─── 第四區塊：真實 RSS 新聞標題 ─────────────────────────────────────────────
print(SECTION)
print("  [4] 真實新聞標題 — CoinDesk RSS (前 5 篇) + 金融詞庫")
print(SECTION)

COINDESK_RSS = "https://www.coindesk.com/arc/outboundfeeds/rss/"

try:
    resp = requests.get(
        COINDESK_RSS,
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True,
        timeout=20,
    )
    feed = feedparser.parse(resp.content)
    entries = feed.get("entries", [])[:5]
    if not entries:
        print("  [WARN] 無法取得 CoinDesk 文章，跳過此區塊\n")
    else:
        rss_analyzer = SentimentIntensityAnalyzer()
        rss_analyzer.lexicon.update(FINANCIAL_LEXICON)
        for i, entry in enumerate(entries, 1):
            title = entry.get("title", "(無標題)").strip()
            vs = rss_analyzer.polarity_scores(title)
            c = vs["compound"]
            print(f"  [{i}] {title}")
            print(f"      compound={c:+.4f}  ({label(c)})  "
                  f"pos={vs['pos']:.3f}  neu={vs['neu']:.3f}  neg={vs['neg']:.3f}")
            print()
except Exception as e:
    print(f"  [ERROR] 抓取 CoinDesk RSS 失敗: {e}\n")

print(SECTION)
print("  VADER 情緒分析引擎測試完成")
print(SECTION)
