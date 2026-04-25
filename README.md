# ATC — Autonomous Trading Corporation

> **警告：本專案處於開發階段。請勿在無人監督的情況下執行真實交易。**

---

## 專案描述

ATC 是一套以「虛擬公司」組織架構驅動的自動加密貨幣交易系統。  
系統由多個 AI 代理人（Squads）協同運作，負責資料收集、情緒分析、歷史比對與交易決策。

---

## 當前階段：Phase 0 — 基礎準備（已完成）

Phase 0 的目標是建立系統的感知層與知識底座，所有模組均可獨立執行與驗證。

---

## 技術棧

| 類別 | 工具 |
|------|------|
| 語言 | Python 3.10+ |
| 交易所 API | Bybit V5 REST API |
| 情緒分析 | VADER + 自訂金融詞庫 |
| 資料收集 | feedparser, requests |
| 鏈上資料 | Etherscan API（V2） |
| 市場資料 | CoinGecko API, Alternative.me FGI |

---

## 環境變數

執行前請設定以下系統環境變數（**請勿寫入程式碼或 .env 檔案**）：

```bash
BYBIT_API_KEY=你的_Bybit_API_Key
BYBIT_API_SECRET=你的_Bybit_API_Secret
ETHERSCAN_API_KEY=你的_Etherscan_API_Key

# 選填（預設 true）
BYBIT_TESTNET=true   # true = 測試網，false = 主網
DRY_RUN=true         # true = 只模擬，不下單
```

---

## 專案結構

```
atc-trading-system/
├── trading_system/
│   ├── common/
│   │   ├── config.py                # Bybit API 設定（讀環境變數）
│   │   ├── vader_enhanced.py        # 增強版 VADER 情緒分析引擎
│   │   └── historical_events_db.py  # 歷史事件庫存取介面
│   ├── data/
│   │   ├── financial_lexicon.json   # 金融詞庫設定檔（可熱更新）
│   │   └── historical_events.json   # 歷史事件庫（15 個典型事件）
│   └── squads/
│       └── crypto/                  # 加密貨幣交易小組（Phase 1 開發中）
└── tests/
    ├── test_rss_feeds.py            # RSS Feed 健康檢查（14 個來源）
    ├── test_reddit_rss.py           # Reddit RSS 抓取 + 情緒分析
    ├── test_vader_engine.py         # VADER 基礎引擎測試
    ├── test_vader_enhanced.py       # 增強版 VADER 完整測試
    ├── test_scrapers.py             # 爬蟲模組測試（需 ETHERSCAN_API_KEY）
    ├── test_lexicon_loading.py      # 金融詞庫載入測試
    └── test_historical_events.py    # 歷史事件庫測試
```

---

## Phase 0 完成項目

- [x] **Bybit V5 API 設定** — testnet/mainnet 切換、dry_run 保護
- [x] **RSS Feed 收集** — BBC, Reuters, CoinDesk, CoinTelegraph, SEC, CFTC 等 14 個來源
- [x] **Reddit RSS 抓取** — r/Bybit, r/CryptoCurrency, r/Bitcoin（含 User-Agent 繞過）
- [x] **增強版 VADER 情緒分析** — 金融詞庫注入、語境反轉規則、數字模式識別
- [x] **金融詞庫 JSON** — 36 個來源詞條（展開後 144 個）、支援熱更新與 fallback
- [x] **爬蟲模組** — CoinGecko 穩定幣市值、Alternative.me 恐懼貪婪指數、Etherscan 熱錢包餘額與大額交易
- [x] **歷史事件庫** — 15 個典型事件（地緣政治 / 央行政策 / 監管 / 加密原生 / 黑天鵝）

---

## 快速驗證

```bash
# 使用 Python 3.10+（需先安裝依賴：pip install vaderSentiment feedparser requests beautifulsoup4 lxml）

python tests/test_rss_feeds.py          # RSS Feed 健康檢查
python tests/test_reddit_rss.py         # Reddit RSS + 情緒分析
python tests/test_vader_enhanced.py     # VADER 增強版驗證
python tests/test_scrapers.py           # 爬蟲模組（需 ETHERSCAN_API_KEY）
python tests/test_lexicon_loading.py    # 詞庫載入
python tests/test_historical_events.py  # 歷史事件庫
```

---

## 免責聲明

本專案僅供研究與學習用途。加密貨幣交易涉及高度風險，過去的歷史模式不保證未來結果。  
作者不對任何因使用本系統而造成的財務損失負責。
