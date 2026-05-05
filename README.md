# ATC — Autonomous Trading Corporation

> **警告：本專案處於開發階段。請勿在無人監督的情況下執行真實交易。**

---

## 專案描述

ATC 是一套以「虛擬公司」組織架構驅動的自動加密貨幣交易系統。  
系統由多個 AI 代理人（Squads）協同運作，負責資料收集、情緒分析、歷史比對與交易決策。

---

## 當前階段：Phase 4 — 策略層（決策層已完整通電 ✅）

Phase 4 的目標是建立策略層（Strategy Layer），銜接五個分析課的輸出，完成「分析 → 策略 → 風控 → 仲裁」完整決策鏈。

---

## Phase 4 完成項目

### 策略層（Strategy Layer）

- [x] **通用激辯引擎 `debate_engine.py`** — 抽取 9 個激辯組的公共邏輯（agreed / discussed_agreed / dual_track 保守原則），統一信心度計算（agreed 平均、discussed_agreed 二次加權、dual_track 最嚴乘以懲罰係數），減少 232 行重複代碼；48 項測試
- [x] **小蘇 `StrategyDirector`（策略長）** — 建快照 → 環境分類 → 複合評分（IO×0.3 / CA×0.4 / GA×0.2，TK 排除、stale 重新歸一化）→ 選策略 → 產出 `TradingProposal`；5 種環境（trending_bullish / trending_bearish / ranging / high_volatility / unclear）；訂閱 `strategy.request_proposal` + `anomaly.detected`；廣播 `proposal.submitted`；63 項測試
- [x] **怡姐 `RiskOfficer`（風控官）** — 敏敏（內部）+ 阿彭（外部）雙視角評估：內部檢查倉位上限 / 止損距離 / R/R 比率 / 複合信心度；外部檢查警戒等級 / 連敗次數 / 近期異常事件 / 環境類型；四態決策：APPROVED / MODIFIED-moderate（×0.7）/ MODIFIED-severe（×0.4，止損收緊 30%）/ REJECTED；訂閱 `proposal.submitted` + `au01.status_update` + `anomaly.detected`；廣播 `assessment.complete`；44 項測試
- [x] **老王 `Arbiter`（仲裁者）** — 決策鏈最後一關，暫存待審提案（TTL 600 秒自動清理）；三層判斷：① REJECTED → ABORT、② tempo=rest → ABORT、③ 倉位過小（< $20）→ ABORT、④ cautious + 信心 < 0.4 → WAIT、⑤ 傾向係數 < 0.4 且信心 < 0.5 → WAIT、⑥ 否則 → EXECUTE；自動傾向係數自我調節（0.3~0.7，樣本 < 5 時預設 0.5）；廣播 `decision.final`；40 項測試

---

## Phase 3 完成項目

### 資料管理課（DM Squad）

- [x] **DM-02 蓉蓉+小方 `DataQualitySection`**（雙人激辯組）— 蓉蓉（單筆即時品質）vs 小方（系統整體評估）；數值合理性、缺值率、時間戳連貫性、RSS/錢包月報健康，95 項測試
- [x] **DM-03 琪琪 `TimestampSynchronizer`** — 跨課時間戳同步、staleness 分級警告（YELLOW/RED）、freshness_grade 自動計算、SnapshotBundle 建構，72 項測試
- [x] **小蔡 `DataManagementSection`（DM 主管）** — 統籌 DM-02/03、整體健康評分（0-100）、FlashAlert 訂閱、run_cycle 每輪循環，52 項測試

### 市場情報課（IO Squad）

- [x] **IO-01 老徐+小曾 `CapitalFlowSection`**（雙人激辯組）— 老徐（歷史百分位橫向比較）vs 小曾（趨勢斜率縱向分析）；資金費率、OI、多空比，60 項測試
- [x] **IO-02 阿賴+珊珊 `SentimentSection`**（雙人激辯組）— 阿賴（機率型 FGI 量化）vs 珊珊（讀心型穩定幣情境）；Alternative.me FGI + CoinGecko 穩定幣市值，68 項測試
- [x] **IO-03 小魏+蓮姐 `OnChainSection`**（雙人激辯組）— 小魏（單筆鯨魚跟蹤狂）vs 蓮姐（整體交易所流向望遠鏡）；Etherscan V2 API，20 項測試
- [x] **婷姐 `IntelligenceSection`（IO 主管）** — 統籌 IO-01/02/03 三組激辯、CourseReport 整合、SelfReview 廣播，15 項測試

### 技術分析課（CA Squad）

- [x] **CA-01 阿盧+伶伶 `IndicatorSection`**（主從覆核結構）— 阿盧計算（RSI/MACD/BB/ATR）、伶伶品管覆核（上下界/一致性/趨勢方向），17 項測試
- [x] **CA-02 小林+慧慧 `StructureSection`**（雙人激辯組）— 小林（近期 100 根 1H）vs 慧慧（歷史 500 根 4H）；支撐壓力/趨勢結構/HH-HL 判斷，15 項測試
- [x] **CA-03 小張+穎穎 `VolumeSection`**（雙人激辯組）— 小張（絕對量化快速反應）vs 穎穎（時段調整誤報少）；成交量爆量偵測/AnomalyEvent 發布，14 項測試
- [x] **靜姐 `TechnicalSection`（CA 主管）** — 統籌 CA-01/02/03、CourseReport 整合、三態健康，15 項測試

### 國際情勢課（GA Squad）

- [x] **GA-01 阿蕭+芸芸 `NewsSection`**（雙人激辯組）— 阿蕭（24h 即時衝擊視角）vs 芸芸（結構性長期影響視角）；10 個 RSS 來源 + VADER 情緒，15 項測試
- [x] **GA-02 阿呂+萱萱 `RegulatorySection`**（雙人激辯組）— 阿呂（條文嚴格度解讀）vs 萱萱（執行脈絡判斷）；SEC/CFTC 監管事件分類，15 項測試
- [x] **琳姐 `GlobalAffairsSection`（GA 主管）** — 統籌 GA-01/02、GA_CRITICAL 快報發布、CourseReport 整合，10 項測試

### 節奏評估課（TK Squad）

- [x] **小施+華哥+老廖 `TempoSection`** — 小施（TK-01 節奏指標：波動率/量能活躍度/趨勢強度）、華哥（TK-02 節奏記憶：歷史模式/轉換偵測）、老廖（主管統籌）；整合輸出 CourseReport，10 項測試

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
│           ├── data_management/             # DM 課（Phase 3）
│           │   ├── dm_02_quality_check.py   # 蓉蓉+小方：資料品質雙人激辯
│           │   ├── dm_03_timestamp_sync.py  # 琪琪：跨課時間戳同步
│           │   └── data_management_section.py # 小蔡：DM 課主管
│           ├── intelligence/                # IO 課（Phase 3）
│           │   ├── io_01_capital_flow.py    # 老徐+小曾：資金流雙人激辯
│           │   ├── io_02_sentiment.py       # 阿賴+珊珊：情緒雙人激辯
│           │   ├── io_03_onchain.py         # 小魏+蓮姐：鏈上監控雙人激辯
│           │   └── intelligence_section.py  # 婷姐：IO 課主管
│           ├── technical/                   # CA 課（Phase 3）
│           │   ├── ca_01_indicators.py      # 阿盧+伶伶：指標計算+覆核
│           │   ├── ca_02_structure.py       # 小林+慧慧：市場結構雙人激辯
│           │   ├── ca_03_volume.py          # 小張+穎穎：量能分析雙人激辯
│           │   └── technical_section.py     # 靜姐：CA 課主管
│           ├── global_affairs/              # GA 課（Phase 3）
│           │   ├── ga_01_news.py            # 阿蕭+芸芸：新聞情緒雙人激辯
│           │   ├── ga_02_regulatory.py      # 阿呂+萱萱：監管分析雙人激辯
│           │   └── global_affairs_section.py # 琳姐：GA 課主管
│           ├── tempo/                       # TK 課（Phase 3）
│           │   ├── tk_01_tempo_indicators.py # 小施：節奏指標（波動率/量能/趨勢）
│           │   ├── tk_02_tempo_memory.py    # 華哥：節奏記憶（歷史模式/轉換偵測）
│           │   └── tempo_section.py         # 老廖：TK 課主管
│           ├── execution/
│           │   ├── ex_03_connection.py      # 芬姐：心跳 / 延遲 / 持倉同步
│           │   ├── ex_01_normal_order.py    # 小慧：常規下單（DRY-RUN / LIVE）
│           │   ├── ex_02_emergency.py       # 阿成：閃崩應變 / 強制平倉
│           │   └── order_section_manager.py # 宏哥：下單課主管
│           └── monitoring/
│               ├── au_01_performance.py     # 阿康：P&L / 警戒等級
│               ├── au_02_system_health.py   # 英姐：角色存活 / 訊息流 / 資源
│               └── au_03_exchange_health.py # 君君+阿豪+小馬：交易所健康雙人激辯
├── trading_system/
│   ├── common/
│   │   └── debate_engine.py             # 通用激辯引擎（9 組共用，Phase 4）
│   └── strategy/                        # 策略層（Phase 4）
│       ├── __init__.py
│       ├── strategy_director.py         # 小蘇：策略長
│       ├── risk_officer.py              # 怡姐：風控官
│       └── arbiter.py                   # 老王：仲裁者
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
    ├── test_au03_exchange_health.py # AU-03 君君+阿豪（73 項）
    ├── test_dm02_quality.py         # DM-02 蓉蓉+小方（95 項）
    ├── test_dm03_timestamp.py       # DM-03 琪琪（72 項）
    ├── test_dm_section.py           # DM 小蔡（52 項）
    ├── test_io01_capital_flow.py    # IO-01 老徐+小曾（60 項）
    ├── test_io02_sentiment.py       # IO-02 阿賴+珊珊（68 項）
    ├── test_io03_onchain.py         # IO-03 小魏+蓮姐（20 項）
    ├── test_io_section.py           # IO 婷姐（15 項）
    ├── test_ca01_indicators.py      # CA-01 阿盧+伶伶（17 項）
    ├── test_ca02_structure.py       # CA-02 小林+慧慧（15 項）
    ├── test_ca03_volume.py          # CA-03 小張+穎穎（14 項）
    ├── test_ca_section.py           # CA 靜姐（15 項）
    ├── test_ga01_news.py            # GA-01 阿蕭+芸芸（15 項）
    ├── test_ga02_regulatory.py      # GA-02 阿呂+萱萱（15 項）
    ├── test_ga_section.py           # GA 琳姐（10 項）
    ├── test_tk_section.py           # TK 小施+華哥+老廖（10 項）
    ├── test_debate_engine.py        # 通用激辯引擎（48 項）
    ├── test_strategy_director.py    # 小蘇 策略長（63 項）
    ├── test_risk_officer.py         # 怡姐 風控官（44 項）
    └── test_arbiter.py              # 老王 仲裁者（40 項）
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

# Phase 3 驗證
python tests/test_dm02_quality.py         # DM-02 蓉蓉+小方（95 項）
python tests/test_dm03_timestamp.py       # DM-03 琪琪（72 項）
python tests/test_dm_section.py           # DM 小蔡（52 項）
python tests/test_io01_capital_flow.py    # IO-01 老徐+小曾（60 項，需網路）
python tests/test_io02_sentiment.py       # IO-02 阿賴+珊珊（68 項，需網路）
python tests/test_io03_onchain.py         # IO-03 小魏+蓮姐（20 項，需 ETHERSCAN_API_KEY）
python tests/test_io_section.py           # IO 婷姐（15 項）
python tests/test_ca01_indicators.py      # CA-01 阿盧+伶伶（17 項）
python tests/test_ca02_structure.py       # CA-02 小林+慧慧（15 項）
python tests/test_ca03_volume.py          # CA-03 小張+穎穎（14 項）
python tests/test_ca_section.py           # CA 靜姐（15 項）
python tests/test_ga01_news.py            # GA-01 阿蕭+芸芸（15 項，需網路）
python tests/test_ga02_regulatory.py      # GA-02 阿呂+萱萱（15 項，需網路）
python tests/test_ga_section.py           # GA 琳姐（10 項）
python tests/test_tk_section.py           # TK 小施+華哥+老廖（10 項）

# Phase 4 驗證（決策層）
python tests/test_debate_engine.py        # 通用激辯引擎（48 項）
python tests/test_strategy_director.py    # 小蘇 策略長（63 項）
python tests/test_risk_officer.py         # 怡姐 風控官（44 項）
python tests/test_arbiter.py              # 老王 仲裁者（40 項）
```

---

## 免責聲明

本專案僅供研究與學習用途。加密貨幣交易涉及高度風險，過去的歷史模式不保證未來結果。  
作者不對任何因使用本系統而造成的財務損失負責。
