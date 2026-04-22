import os
from dataclasses import dataclass, field


@dataclass
class BybitConfig:
    api_key: str = field(default_factory=lambda: os.getenv("BYBIT_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BYBIT_API_SECRET", ""))
    testnet: bool = field(default_factory=lambda: os.getenv("BYBIT_TESTNET", "true").lower() == "true")

    @property
    def base_url(self) -> str:
        if self.testnet:
            return "https://api-testnet.bybit.com"
        return "https://api.bybit.com"

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


@dataclass
class TradingConfig:
    bybit: BybitConfig = field(default_factory=BybitConfig)
    default_symbol: str = "BTCUSDT"
    default_leverage: int = 1
    max_position_pct: float = 0.1  # max 10% of equity per position
    dry_run: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "true").lower() == "true")


# singleton
config = TradingConfig()


if __name__ == "__main__":
    print("=== Trading System Config ===")
    print(f"Testnet:        {config.bybit.testnet}")
    print(f"Base URL:       {config.bybit.base_url}")
    print(f"API configured: {config.bybit.is_configured()}")
    print(f"Dry run:        {config.dry_run}")
    print(f"Default symbol: {config.default_symbol}")
    print(f"Max position:   {config.max_position_pct * 100:.0f}%")
    print(f"Leverage:       {config.default_leverage}x")
