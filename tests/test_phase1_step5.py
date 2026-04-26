# -*- coding: utf-8 -*-
import sys
import io
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.common.api_gateway import (
    get_gateway, reset_gateway, APIGateway, Priority,
)
from trading_system.common.squad_config_loader import (
    load_squad_config, load_all_active_squads, SquadConfig,
)

SECTION = '=' * 65
passed = 0
failed = 0
HAS_KEY = bool(os.environ.get("BYBIT_API_KEY") and os.environ.get("BYBIT_API_SECRET"))


def check(condition: bool, msg: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f'  [PASS] {msg}')
    else:
        failed += 1
        print(f'  [FAIL] {msg}')


def skip(msg: str) -> None:
    print(f'  [SKIP] {msg}')


# ─── [1] APIGateway 單例 ──────────────────────────────────────────────────────

print(SECTION)
print('  [1] APIGateway 單例')
print(SECTION)

gw_a = get_gateway()
gw_b = get_gateway()
check(gw_a is gw_b, 'get_gateway() 多次呼叫回傳同一實例')

reset_gateway()
gw_c = get_gateway()
check(gw_a is not gw_c, 'reset_gateway() 後回傳新實例')
check(get_gateway() is gw_c, '再次呼叫 get_gateway() 回傳同一新實例')

gw = get_gateway()
check(gw.base_url == "https://api-demo.bybit.com", f'base_url 正確（{gw.base_url}）')
check(gw.rate_limit_per_min == 120, 'rate_limit_per_min == 120')
check(gw.reserved_rate == 80,       'reserved_rate == 80')
check(hasattr(gw, 'request_history'), 'request_history 存在')
print(f'  API 已設定: {gw.is_configured()}')

# ─── [2] health_check（真實 API）─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] health_check（真實 Bybit API）')
print(SECTION)

hc = gw.health_check()
print(f'  health_check 結果: {hc}')
check(isinstance(hc, dict), 'health_check() 回傳 dict')
check("healthy" in hc, 'health_check() 有 healthy 欄位')
check("elapsed_ms" in hc, 'health_check() 有 elapsed_ms 欄位')

if hc.get("healthy"):
    check(True, f'health_check healthy=True（時鐘偏差: {hc.get("time_diff_ms")}ms）')
    check(hc.get("time_diff_ms", 9999) < 5000, '時鐘偏差 < 5000ms')
else:
    check(False, f'health_check 失敗: {hc.get("reason")}')

# ─── [3] get_market_kline（真實 API）─────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] get_market_kline 真實查詢（共 3 次）')
print(SECTION)

# 第 1 次：1 小時 K 線
r1 = gw.get_market_kline("ETHUSDT", "60", limit=5)
check(r1["success"], f'ETHUSDT 1h K 線查詢成功（elapsed={r1["elapsed_ms"]}ms）')
if r1["success"]:
    kline_list = r1["data"].get("list", [])
    check(len(kline_list) > 0, f'K 線回傳 {len(kline_list)} 條資料')
    check(len(kline_list[0]) >= 6, f'K 線單條至少 6 個欄位（OHLCV+）: {len(kline_list[0])} 個')

time.sleep(0.3)

# 第 2 次：15 分鐘 K 線
r2 = gw.get_market_kline("ETHUSDT", "15", limit=3)
check(r2["success"], f'ETHUSDT 15m K 線查詢成功（elapsed={r2["elapsed_ms"]}ms）')

time.sleep(0.3)

# 第 3 次：1 分鐘 K 線
r3 = gw.get_market_kline("ETHUSDT", "1", limit=3)
check(r3["success"], f'ETHUSDT 1m K 線查詢成功（elapsed={r3["elapsed_ms"]}ms）')

# ─── [4] get_stats() 格式驗證 ─────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] get_stats() 格式與數值驗證')
print(SECTION)

stats = gw.get_stats()
print(f'  stats: {stats}')

required_keys = {"total_requests", "requests_last_min", "requests_last_hour",
                 "current_rate_pct", "by_priority", "errors_last_hour",
                 "avg_response_time_ms"}
check(required_keys.issubset(stats.keys()), '所有必要欄位都存在')
check(stats["total_requests"] >= 4, f'total_requests >= 4（health + 3 kline）: {stats["total_requests"]}')
check(stats["requests_last_min"] >= 1, f'requests_last_min >= 1: {stats["requests_last_min"]}')
check(0 <= stats["current_rate_pct"] <= 100, f'current_rate_pct 在 0~100 之間: {stats["current_rate_pct"]}')
check(isinstance(stats["by_priority"], dict), 'by_priority 為 dict')
check(all(p.name in stats["by_priority"] for p in Priority),
      '所有 Priority 都在 by_priority 中')
check(stats["avg_response_time_ms"] > 0, f'avg_response_time_ms > 0: {stats["avg_response_time_ms"]}ms')
check(stats["by_priority"]["HIGH"] >= 1, f'HIGH 優先級至少 1 次（health_check）: {stats["by_priority"]["HIGH"]}')
check(stats["by_priority"]["MEDIUM"] >= 3, f'MEDIUM 優先級至少 3 次（kline）: {stats["by_priority"]["MEDIUM"]}')

# ─── [5] 速率限制模擬（無真實 API）──────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] 速率限制模擬（直接注入假時間戳）')
print(SECTION)

# 清空 request_history，注入假時間戳
gw.request_history.clear()
now_ts = time.time()

# 61 個請求（超過 LOW 上限 60，但未超過 MEDIUM 80）
for _ in range(61):
    gw.request_history.append(now_ts - 10)

check(not gw._can_send_request(Priority.LOW),
      '61 requests in 60s → LOW(≤60) 超限回傳 False')
check(gw._can_send_request(Priority.MEDIUM),
      '61 requests → MEDIUM(≤80) 仍可送')
check(gw._can_send_request(Priority.HIGH),
      '61 requests → HIGH(≤100) 仍可送')
check(gw._can_send_request(Priority.CRITICAL),
      '61 requests → CRITICAL(≤120) 仍可送')

# 再加 20（總計 81）
for _ in range(20):
    gw.request_history.append(now_ts - 10)

check(not gw._can_send_request(Priority.MEDIUM),
      '81 requests → MEDIUM(≤80) 超限')
check(gw._can_send_request(Priority.HIGH),
      '81 requests → HIGH(≤100) 仍可送')

# 再加 20（總計 101）
for _ in range(20):
    gw.request_history.append(now_ts - 10)

check(not gw._can_send_request(Priority.HIGH),
      '101 requests → HIGH(≤100) 超限')
check(gw._can_send_request(Priority.CRITICAL),
      '101 requests → CRITICAL(≤120) 仍可送')

# 再加 20（總計 121）
for _ in range(20):
    gw.request_history.append(now_ts - 10)

check(not gw._can_send_request(Priority.CRITICAL),
      '121 requests → CRITICAL(≤120) 超限')

# 舊請求（> 60 秒前）不計入
gw.request_history.clear()
for _ in range(150):
    gw.request_history.append(now_ts - 65)  # 65 秒前，超出 60 秒窗口

check(gw._can_send_request(Priority.LOW),
      '150 個 >60s 的舊請求不計入速率限制')

# 清除人造資料
gw.request_history.clear()

# ─── [6] 無效端點錯誤處理 ──────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] 無效端點錯誤處理')
print(SECTION)

r_bad = gw.request("GET", "/v5/nonexistent-endpoint-xyz", retry_count=0)
print(f'  無效端點結果: success={r_bad["success"]}, error={r_bad["error"][:60]}')
check(r_bad["success"] == False, '無效端點 → success=False')
check(isinstance(r_bad["error"], str) and len(r_bad["error"]) > 0, '有 error 訊息')
check(r_bad["elapsed_ms"] >= 0, 'elapsed_ms 有值')

# 確認錯誤有計入 stats
stats2 = gw.get_stats()
check(stats2["errors_last_hour"] >= 1, f'錯誤計入 errors_last_hour: {stats2["errors_last_hour"]}')

# ─── [7] 已認證端點（需要 API Key）──────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] 已認證端點')
print(SECTION)

if HAS_KEY:
    bal = gw.get_account_balance()
    print(f'  get_account_balance: success={bal["success"]}, elapsed={bal["elapsed_ms"]}ms')
    check(isinstance(bal, dict) and "success" in bal, 'get_account_balance 回傳 dict')
    if not bal["success"]:
        print(f'  帳戶查詢失敗（可能無 UNIFIED 帳戶）: {bal["error"]}')
else:
    skip('無 BYBIT_API_KEY，跳過已認證端點測試')

# 無 key 時應優雅失敗
gw_nokey = APIGateway()
gw_nokey.api_key = ""
gw_nokey.api_secret = ""
r_nokey = gw_nokey.get_account_balance()
check(r_nokey["success"] == False, '無 API key 時 authenticated 請求回傳 success=False')
check("API 未設定" in r_nokey["error"], '無 API key 時有明確錯誤訊息')

# ─── [8] SquadConfig 載入 ─────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [8] SquadConfig 載入')
print(SECTION)

cfg = load_squad_config("crypto")
check(isinstance(cfg, SquadConfig), 'load_squad_config 回傳 SquadConfig')
check(cfg.squad_name == "crypto",              'squad_name == crypto')
check(cfg.market_type == "spot",               'market_type == spot')
check(cfg.exchange == "bybit",                 'exchange == bybit')
check(cfg.base_url == "https://api-demo.bybit.com", 'base_url 正確')
check(cfg.active == True,                      'active == True')
check("ETHUSDT" in cfg.target_symbols,         'target_symbols 含 ETHUSDT')
check(len(cfg.target_symbols) >= 1,            f'target_symbols 長度 ≥ 1: {cfg.target_symbols}')

# trading / risk / strategies 子欄位
check(cfg.trading.get("stage") == 1,                    'trading.stage == 1')
check(cfg.trading.get("initial_capital_usd") == 200,    'trading.initial_capital_usd == 200')
check(cfg.trading.get("max_position_usd") == 100,       'trading.max_position_usd == 100')
check(cfg.risk.get("max_daily_loss_pct") == 5,          'risk.max_daily_loss_pct == 5')
check(cfg.risk.get("max_drawdown_pct") == 10,           'risk.max_drawdown_pct == 10')
check(cfg.risk.get("red_loss_pct") == 5,                'risk.red_loss_pct == 5')
check("trend_following" in cfg.strategies,              'strategies 含 trend_following')
check("range_trading"   in cfg.strategies,              'strategies 含 range_trading')

# ─── [9] 不存在的 squad ──────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [9] 不存在的 squad')
print(SECTION)

try:
    load_squad_config("nonexistent_squad_xyz")
    check(False, '應拋出 FileNotFoundError')
except FileNotFoundError as e:
    check(True, f'FileNotFoundError 正確拋出: {str(e)[:50]}')
except Exception as e:
    check(False, f'拋出錯誤類型不對: {type(e).__name__}: {e}')

# ─── [10] load_all_active_squads ─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [10] load_all_active_squads')
print(SECTION)

active = load_all_active_squads()
check(isinstance(active, list), 'load_all_active_squads 回傳 list')
check(len(active) >= 1, f'至少 1 個 active squad（實際: {len(active)}）')

names = [s.squad_name for s in active]
check("crypto" in names, f'active squads 含 crypto: {names}')
check(all(s.active for s in active), '所有回傳的 squad 都是 active')

crypto_cfg = next(s for s in active if s.squad_name == "crypto")
check(crypto_cfg.exchange == "bybit", 'crypto squad exchange == bybit')
print(f'  Active squads: {names}')

# ─── 總結 ─────────────────────────────────────────────────────────────────────

total = passed + failed
print(f'\n{SECTION}')
print('  總結')
print(SECTION)
final_stats = gw.get_stats()
print(f'  API 呼叫統計  : total={final_stats["total_requests"]}, '
      f'avg_ms={final_stats["avg_response_time_ms"]}, '
      f'errors={final_stats["errors_last_hour"]}')
print(f'  by_priority   : {final_stats["by_priority"]}')
print(f'  測試結果      : {passed} / {total} 通過')
if failed == 0:
    print('  [全部通過]')
else:
    print(f'  [注意] {failed} 個測試失敗')
print(SECTION)
