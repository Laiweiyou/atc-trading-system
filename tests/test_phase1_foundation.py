# -*- coding: utf-8 -*-
import sys
import io
import os
import json
import logging
import pathlib
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SECTION = '=' * 65
passed = 0
failed = 0


def check(condition: bool, msg: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f'  [PASS] {msg}')
    else:
        failed += 1
        print(f'  [FAIL] {msg}')


# ─── [1] RunMode ──────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] RunMode 枚舉測試')
print(SECTION)

from trading_system.common.config import RunMode, CURRENT_MODE

check(RunMode.DRY_RUN.value   == "DRY-RUN",   'DRY_RUN.value == "DRY-RUN"')
check(RunMode.LIVE_DEMO.value == "LIVE-DEMO",  'LIVE_DEMO.value == "LIVE-DEMO"')
check(RunMode.LIVE_REAL.value == "LIVE-REAL",  'LIVE_REAL.value == "LIVE-REAL"')
check(isinstance(CURRENT_MODE, RunMode),        'CURRENT_MODE 是 RunMode 實例')
check(CURRENT_MODE == RunMode.DRY_RUN,          '預設 CURRENT_MODE 為 DRY_RUN')
print(f'  CURRENT_MODE = {CURRENT_MODE.value}')

# 透過環境變數切換
os.environ['ATC_RUN_MODE'] = 'LIVE_DEMO'
import importlib
import trading_system.common.config as _cfg
importlib.reload(_cfg)
check(_cfg._parse_run_mode().value == "LIVE-DEMO", 'ATC_RUN_MODE=LIVE_DEMO 解析正確')

os.environ['ATC_RUN_MODE'] = 'INVALID_XYZ'
check(_cfg._parse_run_mode().value == "DRY-RUN",   '無效 ATC_RUN_MODE fallback 至 DRY_RUN')

# 還原
os.environ.pop('ATC_RUN_MODE', None)
importlib.reload(_cfg)

# ─── [2] 路徑常數 ─────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] 路徑常數與目錄建立測試')
print(SECTION)

from trading_system.common.config import PROJECT_ROOT, DATA_DIR, LOGS_DIR, REPORTS_DIR

check(PROJECT_ROOT.is_dir(),  f'PROJECT_ROOT 存在: {PROJECT_ROOT}')
check(DATA_DIR.is_dir(),      f'DATA_DIR 存在: {DATA_DIR}')
check(LOGS_DIR.is_dir(),      f'LOGS_DIR 自動建立: {LOGS_DIR}')
check(REPORTS_DIR.is_dir(),   f'REPORTS_DIR 自動建立: {REPORTS_DIR}')
check((DATA_DIR / "historical_events.json").is_file(), 'historical_events.json 可見')
check((DATA_DIR / "financial_lexicon.json").is_file(), 'financial_lexicon.json 可見')

# ─── [3] Bybit / 爬蟲 / 交易 / 警示常數 ─────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] 常數值驗證')
print(SECTION)

from trading_system.common.config import (
    BYBIT_BASE_URL, RECV_WINDOW, RATE_LIMIT, RATE_RESERVED,
    RSS_USER_AGENT, SCRAPER_TIMEOUT, SCRAPER_MIN_INTERVAL,
    TARGET_SYMBOL, STAGE, INITIAL_CAPITAL_USD, MAX_POSITION_USD,
    MAX_DAILY_LOSS_PCT, MAX_DRAWDOWN_PCT,
    YELLOW_LOSS_PCT, ORANGE_LOSS_PCT, RED_LOSS_PCT,
)

check(BYBIT_BASE_URL == "https://api-demo.bybit.com", 'BYBIT_BASE_URL 正確')
check(RECV_WINDOW == 5000,    'RECV_WINDOW == 5000')
check(RATE_LIMIT  == 120,     'RATE_LIMIT  == 120')
check(RATE_RESERVED == 80,    'RATE_RESERVED == 80')
check("ATC-TradingBot" in RSS_USER_AGENT, 'RSS_USER_AGENT 含 ATC-TradingBot')
check(SCRAPER_TIMEOUT == 15,  'SCRAPER_TIMEOUT == 15')
check(SCRAPER_MIN_INTERVAL == 5, 'SCRAPER_MIN_INTERVAL == 5')
check(TARGET_SYMBOL == "ETHUSDT",        'TARGET_SYMBOL == ETHUSDT')
check(STAGE == 1,                        'STAGE == 1')
check(INITIAL_CAPITAL_USD == 200.0,      'INITIAL_CAPITAL_USD == 200')
check(MAX_POSITION_USD    == 100.0,      'MAX_POSITION_USD == 100')
check(MAX_DAILY_LOSS_PCT  == 5.0,        'MAX_DAILY_LOSS_PCT == 5')
check(MAX_DRAWDOWN_PCT    == 10.0,       'MAX_DRAWDOWN_PCT == 10')
check(YELLOW_LOSS_PCT == 2.0, 'YELLOW_LOSS_PCT == 2')
check(ORANGE_LOSS_PCT == 4.0, 'ORANGE_LOSS_PCT == 4')
check(RED_LOSS_PCT    == 5.0, 'RED_LOSS_PCT == 5')
check(YELLOW_LOSS_PCT < ORANGE_LOSS_PCT < RED_LOSS_PCT, '警示閾值遞增正確')

# ─── [4] 向下相容（舊 dataclass）─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] 向下相容：BybitConfig / TradingConfig / config singleton')
print(SECTION)

from trading_system.common.config import BybitConfig, TradingConfig, config

check(isinstance(config, TradingConfig),          'config 是 TradingConfig 實例')
check(isinstance(config.bybit, BybitConfig),      'config.bybit 是 BybitConfig 實例')
check(config.dry_run == True,                     'config.dry_run 預設 True')
check(config.default_symbol == "BTCUSDT",         'config.default_symbol == BTCUSDT')
check(config.bybit.base_url.startswith("https"),  'BybitConfig.base_url 回傳 HTTPS URL')

# ─── [5] get_logger 基本功能 ──────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] get_logger 功能測試')
print(SECTION)

from trading_system.common.logger import get_logger

logger_a = get_logger("老蘇")
logger_b = get_logger("老蘇")  # 第二次呼叫應回傳同一 logger
check(logger_a is logger_b, '同名 role 回傳同一 logger 實例')
check(logger_a.level == logging.DEBUG, 'logger level 為 DEBUG')

# 驗證 handlers 類型
handler_types = {type(h).__name__ for h in logger_a.handlers}
check("StreamHandler" in handler_types, '有 StreamHandler（console）')
check("TimedRotatingFileHandler" in handler_types, '有 TimedRotatingFileHandler（file）')

# 發送一條 INFO 訊息（不應拋出例外）
try:
    logger_a.info("Phase 1 foundation test log entry")
    check(True, 'logger.info() 執行無例外')
except Exception as e:
    check(False, f'logger.info() 拋出例外: {e}')

# 確認 log 檔案被建立
log_file = LOGS_DIR / "atc_trading.log"
check(log_file.is_file(), f'log 檔案已建立: {log_file.name}')

# ─── [6] 格式化驗證（role 欄位 + 模式前綴）────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] 日誌格式驗證')
print(SECTION)

# 用 MemoryHandler 捕捉訊息
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []
    def emit(self, record):
        self.records.append(record)

cap = _Capture()
cap.setLevel(logging.DEBUG)
logger_c = get_logger("測試員")
logger_c.addHandler(cap)
logger_c.debug("capture test message")

check(len(cap.records) >= 1, '捕捉到至少 1 條 LogRecord')
if cap.records:
    rec = cap.records[-1]
    check(rec.role == "測試員",    f'record.role == 測試員（實際: {rec.role}）')
    check(rec.levelname == "DEBUG", 'record.levelname == DEBUG')

# 格式化後的字串應含模式前綴
from trading_system.common.logger import _ModeFormatter
fmt = _ModeFormatter(datefmt="%Y-%m-%d %H:%M:%S")
if cap.records:
    formatted = fmt.format(cap.records[-1])
    check("[DRY-RUN]" in formatted, f'格式化輸出含 [DRY-RUN]（前 60 字: {formatted[:60]}）')
    check("role=測試員" in formatted, '格式化輸出含 role=測試員')

# ─── [7] log_critical_event ───────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] log_critical_event 測試')
print(SECTION)

from trading_system.common.logger import log_critical_event

crit_path = REPORTS_DIR / "critical_events.log"
# 記錄呼叫前的行數
before_lines = 0
if crit_path.is_file():
    with open(crit_path, encoding='utf-8') as f:
        before_lines = sum(1 for _ in f)

log_critical_event(
    role="測試員",
    event_type="UNIT_TEST",
    details={"msg": "Phase 1 foundation test", "value": 42},
)

check(crit_path.is_file(), f'critical_events.log 已建立: {crit_path}')

with open(crit_path, encoding='utf-8') as f:
    lines = f.readlines()

check(len(lines) == before_lines + 1, f'新增 1 行（共 {len(lines)} 行）')

try:
    last_record = json.loads(lines[-1])
    check(last_record["role"]       == "測試員",   'JSON 欄位 role 正確')
    check(last_record["event_type"] == "UNIT_TEST", 'JSON 欄位 event_type 正確')
    check(last_record["mode"]       == "DRY-RUN",   'JSON 欄位 mode 正確')
    check("timestamp" in last_record,               'JSON 含 timestamp 欄位')
    check(last_record["details"]["value"] == 42,    'JSON details.value == 42')
    print(f'  記錄預覽: {lines[-1].strip()[:80]}...')
except json.JSONDecodeError as e:
    check(False, f'JSON 解析失敗: {e}')

# ─── 總結 ─────────────────────────────────────────────────────────────────────

total = passed + failed
print(f'\n{SECTION}')
print('  總結')
print(SECTION)
print(f'  測試結果      : {passed} / {total} 通過')
if failed == 0:
    print('  [全部通過]')
else:
    print(f'  [注意] {failed} 個測試失敗')
print(SECTION)
