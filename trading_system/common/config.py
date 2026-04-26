# -*- coding: utf-8 -*-
import os
import pathlib
from dataclasses import dataclass, field
from enum import Enum


# ─── RunMode ──────────────────────────────────────────────────────────────────

class RunMode(Enum):
    DRY_RUN   = "DRY-RUN"
    LIVE_DEMO = "LIVE-DEMO"
    LIVE_REAL = "LIVE-REAL"


def _parse_run_mode() -> RunMode:
    raw = os.getenv("ATC_RUN_MODE", "DRY_RUN").upper().replace("-", "_")
    try:
        return RunMode[raw]
    except KeyError:
        return RunMode.DRY_RUN


CURRENT_MODE: RunMode = _parse_run_mode()

# ─── Paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT: pathlib.Path = pathlib.Path(__file__).parent.parent.parent
DATA_DIR:     pathlib.Path = PROJECT_ROOT / "trading_system" / "data"
LOGS_DIR:     pathlib.Path = PROJECT_ROOT / "logs"
REPORTS_DIR:  pathlib.Path = PROJECT_ROOT / "reports"

for _d in (LOGS_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ─── Bybit ────────────────────────────────────────────────────────────────────

BYBIT_BASE_URL  = "https://api-demo.bybit.com"
RECV_WINDOW     = 5000
RATE_LIMIT      = 120   # requests / minute (Bybit V5 limit)
RATE_RESERVED   = 80    # safe operating cap

# ─── Data Sources ─────────────────────────────────────────────────────────────

RSS_USER_AGENT     = "ATC-TradingBot/1.0 (+https://github.com/Laiweiyou/atc-trading-system)"
SCRAPER_USER_AGENT = RSS_USER_AGENT
SCRAPER_TIMEOUT    = 15   # seconds
SCRAPER_MIN_INTERVAL = 5  # seconds between requests

# ─── Trading ──────────────────────────────────────────────────────────────────

TARGET_SYMBOL       = "ETHUSDT"
STAGE               = 1
INITIAL_CAPITAL_USD = 200.0
MAX_POSITION_USD    = 100.0
MAX_DAILY_LOSS_PCT  = 5.0   # % of initial capital
MAX_DRAWDOWN_PCT    = 10.0  # % of initial capital

# ─── Alert Thresholds ─────────────────────────────────────────────────────────

YELLOW_LOSS_PCT = 2.0
ORANGE_LOSS_PCT = 4.0
RED_LOSS_PCT    = 5.0

# ─── Legacy Dataclasses (kept for Phase 0 compatibility) ──────────────────────

@dataclass
class BybitConfig:
    api_key:    str  = field(default_factory=lambda: os.getenv("BYBIT_API_KEY", ""))
    api_secret: str  = field(default_factory=lambda: os.getenv("BYBIT_API_SECRET", ""))
    testnet:    bool = field(default_factory=lambda: os.getenv("BYBIT_TESTNET", "true").lower() == "true")

    @property
    def base_url(self) -> str:
        if self.testnet:
            return "https://api-testnet.bybit.com"
        return "https://api.bybit.com"

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


@dataclass
class TradingConfig:
    bybit:           BybitConfig = field(default_factory=BybitConfig)
    default_symbol:  str         = "BTCUSDT"
    default_leverage: int        = 1
    max_position_pct: float      = 0.1
    dry_run:         bool        = field(default_factory=lambda: os.getenv("DRY_RUN", "true").lower() == "true")


config = TradingConfig()


if __name__ == "__main__":
    print("=== ATC Config ===")
    print(f"RunMode:        {CURRENT_MODE.value}")
    print(f"PROJECT_ROOT:   {PROJECT_ROOT}")
    print(f"LOGS_DIR:       {LOGS_DIR}")
    print(f"REPORTS_DIR:    {REPORTS_DIR}")
    print(f"TARGET_SYMBOL:  {TARGET_SYMBOL}")
    print(f"INITIAL_CAPITAL:{INITIAL_CAPITAL_USD} USD")
