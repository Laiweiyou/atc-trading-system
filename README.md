# ATC — Autonomous Trading Corporation

> **警告：本專案處於開發階段。請勿在無人監督的情況下執行真實交易。**

---

## 專案描述

ATC 是一套以「虛擬公司」組織架構驅動的自動加密貨幣交易系統。  
系統由多個 AI 代理人（Squads）協同運作，負責資料收集、情緒分析、歷史比對與交易決策。

---

## 當前階段：Phase 1 — 核心基礎建設（已完成）

Phase 1 的目標是建立系統的基礎設施層，包含設定管理、日誌系統、資料模型、訊息總線與 API 閘道。

---

## Phase 1 完成項目

- [x] **config.py 擴充** — RunMode enum、路徑常數自動建立、Bybit/爬蟲/交易/警示閾值常數
- [x] **logger.py** — colorlog 彩色 console、每日輪轉檔案、`log_critical_event` JSON Lines 永久記錄
- [x] **data_models.py** — 10 個核心資料結構（SubReport→DebateResult→CourseReport→SnapshotBundle→TradingProposal→RiskAssessment→ArbiterDecision→ExecutionResult→AnomalyEvent→NewsEvent），全部支援 `to_dict()` / `from_dict()`
- [x] **message_bus.py** — 同步 pub/sub，deque(maxlen=1000) 歷史，callback 例外隔離，全域單例
- [x] **flash_alert.py** — 五種快報類型、三級告警、critical 永久記錄、acknowledgment 追蹤
- [x] **feedback_models.py** — SelfReview（UUID 自動產生、mark_correct/incorrect/partial）+ ReviewBatch（加權正確率計算）
- [x] **kpi_models.py** — KPIDefinition / KPIRecord / PerformanceGrade，S/A/B/C/D 評級規則（D 級降權 ×0.5）
- [x] **snapshot_builder.py** — 跨課時間同步機制，freshness_grade（real_time/recent/delayed/stale），overall_data_quality 自動計算
- [x] **api_gateway.py** — 四優先級速率限制（120/100/80/60 req/min），HMAC-SHA256 簽名，retry with backoff，完整統計
- [x] **squad_config_loader.py** — YAML 設定載入，trading/risk/strategies 子欄位存取
- [x] **squads/crypto/squad_config.yaml** — crypto 小隊設定（Stage 1，ETHUSDT 現貨，200 USDT）

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
| 日誌 | colorlog（彩色終端）+ TimedRotatingFileHandler |
| 設定 | pyyaml（小隊設定）|
| 訊息傳遞 | 內建同步 pub/sub（MessageBus）|

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
│   │   ├── config.py                # RunMode enum、路徑、常數（讀環境變數）
│   │   ├── logger.py                # colorlog + 每日輪轉 + critical_events.log
│   │   ├── data_models.py           # 10 個核心資料結構（dataclass + to/from_dict）
│   │   ├── message_bus.py           # 同步 pub/sub 訊息總線
│   │   ├── flash_alert.py           # 快報系統（5 種類型、3 級告警）
│   │   ├── feedback_models.py       # SelfReview + ReviewBatch
│   │   ├── kpi_models.py            # KPI 定義/紀錄/績效評級
│   │   ├── snapshot_builder.py      # 跨課快照建構（時間同步）
│   │   ├── api_gateway.py           # Bybit API 閘道（速率限制 + 簽名 + 重試）
│   │   ├── squad_config_loader.py   # YAML 小隊設定載入器
│   │   ├── vader_enhanced.py        # 增強版 VADER 情緒分析引擎
│   │   └── historical_events_db.py  # 歷史事件庫存取介面
│   ├── data/
│   │   ├── financial_lexicon.json   # 金融詞庫設定檔（可熱更新）
│   │   └── historical_events.json   # 歷史事件庫（15 個典型事件）
│   └── squads/
│       └── crypto/
│           └── squad_config.yaml    # crypto 小隊設定（Stage 1, ETHUSDT）
├── logs/                            # 每日輪轉日誌（auto-created）
├── reports/                         # critical_events.log（auto-created）
└── tests/
    ├── test_phase1_foundation.py    # Phase 1 config + logger 測試（53 項）
    ├── test_data_models.py          # 10 個資料結構完整測試（86 項）
    ├── test_message_bus.py          # MessageBus + FlashAlert 測試（46 項）
    ├── test_phase1_step4.py         # feedback + kpi + snapshot 測試（92 項）
    ├── test_phase1_step5.py         # APIGateway + SquadConfig 測試（65 項）
    ├── test_rss_feeds.py            # RSS Feed 健康檢查（14 個來源）
    ├── test_reddit_rss.py           # Reddit RSS 抓取 + 情緒分析
    ├── test_vader_enhanced.py       # 增強版 VADER 完整測試
    ├── test_scrapers.py             # 爬蟲模組測試（需 ETHERSCAN_API_KEY）
    ├── test_lexicon_loading.py      # 金融詞庫載入測試（22 項）
    └── test_historical_events.py    # 歷史事件庫測試（22 項）
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
# 依賴安裝
pip install vaderSentiment feedparser requests beautifulsoup4 lxml colorlog pyyaml

# Phase 0 驗證
python tests/test_rss_feeds.py          # RSS Feed 健康檢查
python tests/test_reddit_rss.py         # Reddit RSS + 情緒分析
python tests/test_vader_enhanced.py     # VADER 增強版驗證
python tests/test_scrapers.py           # 爬蟲模組（需 ETHERSCAN_API_KEY）
python tests/test_lexicon_loading.py    # 詞庫載入（22 項）
python tests/test_historical_events.py  # 歷史事件庫（22 項）

# Phase 1 驗證
python tests/test_phase1_foundation.py  # config + logger（53 項）
python tests/test_data_models.py        # 10 個資料結構（86 項）
python tests/test_message_bus.py        # 訊息總線 + 快報（46 項）
python tests/test_phase1_step4.py       # feedback + kpi + snapshot（92 項）
python tests/test_phase1_step5.py       # API 閘道 + 小隊設定（65 項，需網路）
```

---

## 免責聲明

本專案僅供研究與學習用途。加密貨幣交易涉及高度風險，過去的歷史模式不保證未來結果。  
作者不對任何因使用本系統而造成的財務損失負責。
