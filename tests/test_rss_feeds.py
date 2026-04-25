# -*- coding: utf-8 -*-
import sys
import io
import feedparser
import requests
import time
import urllib.request
from datetime import datetime

# 強制 stdout 使用 UTF-8，避免 Windows cp950 編碼錯誤
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

USER_AGENT = "ATC Trading System 1.0 (research@example.com)"

# SEC 需要更明確的聯絡資訊格式（EDGAR 政策）
SEC_USER_AGENT = "ATC Trading Research contact@example.com"

FEEDS = [
    # 第一層：國際通訊社
    (1,  "BBC World",              "https://feeds.bbci.co.uk/news/world/rss.xml"),
    (2,  "Al Jazeera",             "https://www.aljazeera.com/xml/rss/all.xml"),
    (3,  "Reuters (Google News)",  "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com"),
    (4,  "AP News (Google News)",  "https://news.google.com/rss/search?q=when:24h+allinurl:apnews.com"),
    # 第二層：財經國際新聞
    (5,  "CNBC World",             "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    (6,  "BBC Business",           "https://feeds.bbci.co.uk/news/business/rss.xml"),
    (7,  "NPR",                    "https://feeds.npr.org/1001/rss.xml"),
    (8,  "Bloomberg (Google News)","https://news.google.com/rss/search?q=when:24h+allinurl:bloomberg.com"),
    # 第三層：地緣政治深度
    (9,  "Foreign Affairs",        "https://foreignaffairs.com/rss.xml"),
    (10, "Geopolitical Futures",   "https://geopoliticalfutures.com/feed"),
    # 第四層：加密貨幣專門
    (11, "CoinDesk",               "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    (12, "CoinTelegraph",          "https://cointelegraph.com/rss"),
    # 監管專用（美國）
    # SEC: 直接 Atom feed，需 EDGAR 格式 User-Agent
    (13, "SEC.gov (8-K)",          "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=40&output=atom"),
    # CFTC: 官網有 bot 保護，改用 Google News 7 天視窗抓 cftc.gov 新聞
    (14, "CFTC (Google News)",     "https://news.google.com/rss/search?q=when:7d+site:cftc.gov"),
]

TIMEOUT = 20

# 需要用 requests 取得內容再給 feedparser（#11 CoinDesk 308 重導向；#13 SEC 403 防護）
REQUESTS_FEEDS = {11, 13}


def fetch_via_requests(url: str, ua: str = USER_AGENT) -> tuple[int, bytes]:
    """回傳 (status_code, content)；失敗時 status=0, content=b''。"""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": ua},
            allow_redirects=True,
            timeout=TIMEOUT,
        )
        return resp.status_code, resp.content
    except requests.RequestException:
        return 0, b""


def fetch_via_urllib(url: str) -> tuple[int, bytes]:
    """回傳 (status_code, content)；失敗時 status=0, content=b''。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def format_time(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6]).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                pass
    return "N/A"


def test_feed(num: int, name: str, url: str) -> bool:
    print(f"\n[{num:02d}] {name}")
    print(f"     URL: {url}")

    if num in REQUESTS_FEEDS:
        ua = SEC_USER_AGENT if num == 13 else USER_AGENT
        status, content = fetch_via_requests(url, ua=ua)
        feed = feedparser.parse(content)
    else:
        status, content = fetch_via_urllib(url)
        feed = feedparser.parse(content) if content else feedparser.parse(url)

    status_str = str(status) if status else "ERROR (連線失敗)"
    print(f"     HTTP 狀態碼  : {status_str}")

    bozo = feed.get("bozo", True)
    bozo_exc = feed.get("bozo_exception", None)
    if bozo and bozo_exc:
        exc_name = type(bozo_exc).__name__
        print(f"     解析狀態    : [WARN] bozo=True ({exc_name}: {bozo_exc})")
    elif not bozo:
        print("     解析狀態    : [OK] 正常")
    else:
        print("     解析狀態    : [WARN] bozo=True (但可繼續)")

    entries = feed.get("entries", [])
    print(f"     文章數量    : {len(entries)}")

    if entries:
        title = entries[0].get("title", "(無標題)").strip()
        print(f"     第一篇標題  : {title[:100]}")
        pub = format_time(entries[0])
        print(f"     最新發布時間: {pub}")
        success = True
    else:
        print("     第一篇標題  : (無法取得文章)")
        print("     最新發布時間: N/A")
        success = False

    return success and (status in (200, 0) or status < 400)


def main():
    print("=" * 65)
    print("  RSS Feed 健康檢查")
    print(f"  執行時間: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 65)

    results = []
    for num, name, url in FEEDS:
        ok = test_feed(num, name, url)
        results.append((num, name, ok))
        time.sleep(0.5)

    passed = [r for r in results if r[2]]
    failed = [r for r in results if not r[2]]
    total = len(FEEDS)

    print("\n" + "=" * 65)
    print(f"  總結：成功 {len(passed)} / {total}")
    if failed:
        print(f"  失敗的 RSS ({len(failed)} 個)：")
        for num, name, _ in failed:
            print(f"    [{num:02d}] {name}")
    else:
        print("  所有 RSS Feed 均正常！")
    print("=" * 65)


if __name__ == "__main__":
    main()
