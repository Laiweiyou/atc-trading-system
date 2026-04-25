# -*- coding: utf-8 -*-
import sys
import io
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
import feedparser
from trading_system.common.vader_enhanced import analyze_sentiment

USER_AGENT = "ATC Trading Research 1.0 (research@example.com)"
TIMEOUT = 20
SECTION = '=' * 65

FEEDS = [
    ("r/Bybit 全部新貼文",            "https://www.reddit.com/r/Bybit/new/.rss"),
    ("r/CryptoCurrency 搜尋 bybit",   "https://www.reddit.com/r/CryptoCurrency/search.rss?q=bybit&sort=new&t=day"),
    ("r/Bitcoin 熱門",                "https://www.reddit.com/r/Bitcoin/hot/.rss"),
]


def format_time(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6]).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                pass
    return "N/A"


def fetch_reddit_rss(url: str) -> tuple[int, object]:
    """回傳 (status_code, feed)；用 requests 帶 User-Agent，再交給 feedparser 解析。"""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        return resp.status_code, feedparser.parse(resp.content)
    except requests.RequestException as e:
        return 0, feedparser.parse(b"")


def test_feed(name: str, url: str) -> list[dict]:
    """
    抓取並印出 RSS 摘要，回傳前 5 篇貼文的 entry 清單（含 title/author/time）。
    """
    print(f"\n【{name}】")
    print(f"  URL: {url}")

    status, feed = fetch_reddit_rss(url)
    print(f"  HTTP 狀態碼  : {status if status else 'ERROR (連線失敗)'}")

    entries = feed.get("entries", [])
    print(f"  取得貼文數量 : {len(entries)}")

    if entries:
        first = entries[0]
        title  = first.get("title", "(無標題)").strip()
        author = first.get("author", first.get("dc_creator", "N/A"))
        pub    = format_time(first)
        print(f"  第一篇標題  : {title[:100]}")
        print(f"  第一篇作者  : {author}")
        print(f"  第一篇時間  : {pub}")
    else:
        print("  （無法取得貼文）")

    return [
        {
            "title":  e.get("title", "").strip(),
            "author": e.get("author", e.get("dc_creator", "N/A")),
            "time":   format_time(e),
        }
        for e in entries[:5]
    ]


def run_sentiment_block(feed_name: str, posts: list[dict]) -> None:
    """對前 5 篇貼文做情緒分析並印出結果、統計。"""
    if not posts:
        print("  （無貼文可分析）")
        return

    print(f"\n  ── 情緒分析：{feed_name} 前 {len(posts)} 篇 ──")
    scores: list[float] = []

    for i, post in enumerate(posts, 1):
        title = post["title"]
        result = analyze_sentiment(title)
        score  = result["score"]
        lbl    = result["label"]
        kws    = result["details"]["keywords_matched"]
        scores.append(score)

        print(f"\n  [{i}] {title[:80]}")
        print(f"       情緒分數: {score:+.4f}  |  判讀: {lbl}")
        if kws:
            print(f"       金融關鍵詞: {', '.join(set(kws))}")
        else:
            print(f"       金融關鍵詞: （無）")

    avg = sum(scores) / len(scores)
    pos = sum(1 for s in scores if s >= 0.05)
    neg = sum(1 for s in scores if s <= -0.05)
    neu = len(scores) - pos - neg

    print(f"\n  平均分數   : {avg:+.4f}")
    print(f"  情緒分佈   : {pos} 篇正面 / {neg} 篇負面 / {neu} 篇中性")


def main():
    print(SECTION)
    print("  Reddit RSS 抓取 + 增強版 VADER 情緒分析")
    print(f"  執行時間: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(SECTION)

    for i, (name, url) in enumerate(FEEDS):
        posts = test_feed(name, url)
        run_sentiment_block(name, posts)
        if i < len(FEEDS) - 1:
            print("\n  ── 等待 2 秒後繼續 ──")
            time.sleep(2)

    print(f"\n{SECTION}")
    print("  完成")
    print(SECTION)


if __name__ == "__main__":
    main()
