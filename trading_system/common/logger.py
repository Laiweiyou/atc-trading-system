# -*- coding: utf-8 -*-
"""
ATC 日誌系統
- console: colorlog 彩色，INFO+
- file:    每日輪轉，DEBUG+，保留 30 天
- critical_events.log: JSON Lines，永久保留
"""
import json
import logging
import logging.handlers
import pathlib
from datetime import datetime, timezone

try:
    import colorlog
    _HAS_COLORLOG = True
except ImportError:
    _HAS_COLORLOG = False


# ─── Dynamic mode prefix formatter ────────────────────────────────────────────

class _ModeFormatter(logging.Formatter):
    """每次 format 時即時讀取 CURRENT_MODE，不在初始化時鎖定。"""

    def format(self, record: logging.LogRecord) -> str:
        from trading_system.common.config import CURRENT_MODE
        prefix = CURRENT_MODE.value
        self._style._fmt = (
            f"[{prefix}] %(asctime)s | %(levelname)-8s | role=%(role)s | %(message)s"
        )
        return super().format(record)


class _ModeColorFormatter(logging.Formatter):
    """彩色版（colorlog），動態模式前綴。"""

    _COLORS = {
        "DEBUG":    "cyan",
        "INFO":     "green",
        "WARNING":  "yellow",
        "ERROR":    "red",
        "CRITICAL": "bold_red",
    }

    def format(self, record: logging.LogRecord) -> str:
        from trading_system.common.config import CURRENT_MODE
        if not _HAS_COLORLOG:
            return _ModeFormatter(datefmt="%Y-%m-%d %H:%M:%S").format(record)

        prefix = CURRENT_MODE.value
        color  = self._COLORS.get(record.levelname, "white")
        fmt = (
            f"[{prefix}] %(asctime)s | %({color})s%(levelname)-8s%(reset)s"
            f" | role=%(role)s | %(message)s"
        )
        formatter = colorlog.ColoredFormatter(
            fmt,
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={color: color},
        )
        return formatter.format(record)


# ─── Old-log cleanup ──────────────────────────────────────────────────────────

def _cleanup_old_logs(log_dir: pathlib.Path, keep_days: int = 30) -> None:
    cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
    for f in log_dir.glob("atc_*.log.*"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


# ─── Public API ───────────────────────────────────────────────────────────────

def get_logger(role_name: str) -> logging.Logger:
    """
    回傳帶有 role 欄位的 Logger。
    首次呼叫時設定 handlers；後續呼叫直接回傳已存在的 logger。
    """
    from trading_system.common.config import LOGS_DIR

    logger = logging.getLogger(f"atc.{role_name}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # 為每個 LogRecord 自動附加 role 欄位
    logger.addFilter(_RoleFilter(role_name))

    # ── console handler ──
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    if _HAS_COLORLOG:
        ch.setFormatter(_ModeColorFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    else:
        ch.setFormatter(_ModeFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(ch)

    # ── file handler（daily rotation，保留 30 天）──
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / "atc_trading.log"
    fh = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=30, encoding="utf-8"
    )
    fh.suffix = "%Y-%m-%d"
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_ModeFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)

    _cleanup_old_logs(LOGS_DIR)
    return logger


def log_critical_event(
    role: str,
    event_type: str,
    details: dict,
) -> None:
    """將關鍵事件以 JSON Lines 格式附加至 reports/critical_events.log（永久保留）。"""
    from trading_system.common.config import REPORTS_DIR, CURRENT_MODE

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode":       CURRENT_MODE.value,
        "role":       role,
        "event_type": event_type,
        "details":    details,
    }
    crit_path = REPORTS_DIR / "critical_events.log"
    with open(crit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─── Internal ─────────────────────────────────────────────────────────────────

class _RoleFilter(logging.Filter):
    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role

    def filter(self, record: logging.LogRecord) -> bool:
        record.role = self.role
        return True
