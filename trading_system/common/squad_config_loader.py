# -*- coding: utf-8 -*-
"""ATC 小隊設定載入器。"""
from __future__ import annotations

import dataclasses
from typing import List

try:
    import yaml
except ImportError as e:
    raise ImportError("需要 pyyaml：pip install pyyaml") from e

from trading_system.common.config import PROJECT_ROOT

_SQUADS_DIR = PROJECT_ROOT / "trading_system" / "squads"


# ─── SquadConfig ──────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SquadConfig:
    squad_name:     str
    market_type:    str
    target_symbols: List[str]
    exchange:       str
    base_url:       str
    active:         bool
    config_data:    dict   # 完整 YAML 資料（含 trading/risk/strategies 等）

    @property
    def trading(self) -> dict:
        return self.config_data.get("trading", {})

    @property
    def risk(self) -> dict:
        return self.config_data.get("risk", {})

    @property
    def strategies(self) -> List[str]:
        return self.config_data.get("strategies", [])


# ─── Loader ───────────────────────────────────────────────────────────────────

def load_squad_config(squad_name: str) -> SquadConfig:
    """
    從 trading_system/squads/{squad_name}/squad_config.yaml 載入設定。
    若檔案不存在拋 FileNotFoundError。
    """
    config_path = _SQUADS_DIR / squad_name / "squad_config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"找不到小隊設定檔：{config_path}"
        )

    with open(config_path, encoding="utf-8") as f:
        data: dict = yaml.safe_load(f)

    return SquadConfig(
        squad_name=data["squad_name"],
        market_type=data["market_type"],
        target_symbols=data.get("target_symbols", []),
        exchange=data["exchange"],
        base_url=data["base_url"],
        active=bool(data.get("active", False)),
        config_data=data,
    )


def load_all_active_squads() -> List[SquadConfig]:
    """
    掃描 squads 目錄，載入所有 active=True 的小隊設定。
    無法解析的設定檔會被跳過（不中斷）。
    """
    result: List[SquadConfig] = []
    if not _SQUADS_DIR.is_dir():
        return result

    for squad_dir in sorted(_SQUADS_DIR.iterdir()):
        if not squad_dir.is_dir():
            continue
        config_file = squad_dir / "squad_config.yaml"
        if not config_file.is_file():
            continue
        try:
            cfg = load_squad_config(squad_dir.name)
            if cfg.active:
                result.append(cfg)
        except Exception:
            pass

    return result
