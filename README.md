# ATC — Autonomous Trading Corporation

> **警告：本專案處於開發階段。請勿在無人監督的情況下執行真實交易。**

---

## 專案描述

ATC 是一套以「虛擬公司」組織架構驅動的自動加密貨幣交易系統。  
系統由多個 AI 代理人（Squads）協同運作，負責資料收集、情緒分析、歷史比對與交易決策。

---

## 當前階段：Phase 2 — 執行課 + 監控課（已完成）

Phase 2 的目標是建立交易執行子系統（EX）與績效/健康監控子系統（AU）。

---

## Phase 2 完成項目

### 執行課（EX Squad）

- [x] **EX-03 芬姐 `ConnectionMaintainer`** — 心跳延遲偵測（p99/平均/成功率）、延遲突波警告（>1.5× 近期平均）、持倉同步（check_positions / update_known_position）、失敗發送 EX_FAIL / ANOMALY_FLASH，71 項測試
- [x] **EX-01 小慧 `NormalOrderExecutor`** — DRY-RUN / LIVE 雙路執行、輸入驗證（position_size / symbol / stop_loss 方向）、滑點計算（bps）、執行統計追蹤，49 項測試
- [x] **EX-02 阿成 `EmergencyExecutor`** — 閃崩模式（idempotent）、全倉強制平倉（DRY-RUN 支援）、止損收緊（30% 距離方向）、訂閱 AU_RED / GA_CRITICAL 快報自動觸發，45 項測試
- [x] **宏哥 `OrderSectionManager`** — 統籌 EX-01/02/03、三態整體健康（healthy / degraded / critical）、SelfReview 廣播、emergency_dispatch 委派阿成，57 項測試

### 監控課（AU Squad）

- [x] **AU-01 阿康 `PerformanceMonitor`** — P&L 追蹤（日/週/總/已實現/未實現）、連敗計數（YELLOW≥5 / ORANGE≥8）、四級警戒（GREEN→YELLOW→ORANGE→RED）、每日自動重置，94 項測試
- [x] **AU-02 英姐 `SystemHealthMonitor`** — 角色存活三分類（active <60s / stale 60-300s / missing ≥300s）、訊息流量 by_channel、psutil 資源監控（graceful fallback）、DATA_OFFLINE / ANOMALY_FLASH 告警，39 項測試
- [x] **AU-03 君君 + 阿豪 `ExchangeHealthSection`**（**首個雙人激辯組**）— 同 class 雙 mode：君君（量化：API 延遲 / 錯誤率 / 心跳）、阿豪（質化：Reddit RSS + VADER 情緒）；小馬統籌 _compare_reports（agreed / discussed_agreed / dual_track 保守原則）、健康四態（healthy / degraded / suspicious / critical），73 項測試

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
│           ├── squad_config.yaml            # crypto 小隊設定（Stage 1, ETHUSDT）
│           ├── execution/
│           │   ├── ex_03_connection.py      # 芬姐：心跳 / 延遲 / 持倉同步
│           │   ├── ex_01_normal_order.py    # 小慧：常規下單（DRY-RUN / LIVE）
│           │   ├── ex_02_emergency.py       # 阿成：閃崩應變 / 強制平倉
│           │   └── order_section_manager.py # 宏哥：下單課主管
│           └── monitoring/
│               ├── au_01_performance.py     # 阿康：P&L / 警戒等級
│               ├── au_02_system_health.py   # 英姐：角色存活 / 訊息流 / 資源
│               └── au_03_exchange_health.py # 君君+阿豪+小馬：交易所健康雙人激辯
├── logs/                                    # 每日輪轉日誌（auto-created）
├── reports/                                 # critical_events.log（auto-created）
└── tests/
    ├── test_phase1_foundation.py    # Phase 1 config + logger（53 項）
    ├── test_data_models.py          # 10 個資料結構（86 項）
    ├── test_message_bus.py          # 訊息總線 + 快報（46 項）
    ├── test_phase1_step4.py         # feedback + kpi + snapshot（92 項）
    ├── test_phase1_step5.py         # API 閘道 + 小隊設定（65 項）
    ├── test_rss_feeds.py            # RSS Feed 健康檢查（14 個來源）
    ├── test_reddit_rss.py           # Reddit RSS 抓取 + 情緒分析
    ├── test_vader_enhanced.py       # 增強版 VADER 完整測試
    ├── test_scrapers.py             # 爬蟲模組測試（需 ETHERSCAN_API_KEY）
    ├── test_lexicon_loading.py      # 金融詞庫載入（22 項）
    ├── test_historical_events.py    # 歷史事件庫（22 項）
    ├── test_ex03_connection.py      # EX-03 芬姐（71 項）
    ├── test_ex01_normal_order.py    # EX-01 小慧（49 項）
    ├── test_ex02_emergency.py       # EX-02 阿成（45 項）
    ├── test_order_section_manager.py # 宏哥（57 項）
    ├── test_au01_performance.py     # AU-01 阿康（94 項）
    ├── test_au02_system_health.py   # AU-02 英姐（39 項）
    └── test_au03_exchange_health.py # AU-03 君君+阿豪（73 項）
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
pip install vaderSentiment feedparser requests beautifulsoup4 lxml colorlog pyyaml psutil

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

# Phase 2 驗證
python tests/test_ex03_connection.py      # EX-03 芬姐（71 項）
python tests/test_ex01_normal_order.py    # EX-01 小慧（49 項）
python tests/test_ex02_emergency.py       # EX-02 阿成（45 項）
python tests/test_order_section_manager.py # 宏哥（57 項）
python tests/test_au01_performance.py     # AU-01 阿康（94 項）
python tests/test_au02_system_health.py   # AU-02 英姐（39 項）
python tests/test_au03_exchange_health.py # AU-03 君君+阿豪（73 項，需網路）
```

---

## 免責聲明

本專案僅供研究與學習用途。加密貨幣交易涉及高度風險，過去的歷史模式不保證未來結果。  
作者不對任何因使用本系統而造成的財務損失負責。
