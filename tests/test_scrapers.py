# -*- coding: utf-8 -*-
"""
爬蟲原型測試
1. CoinGecko 穩定幣市值            (IO-02)
2. Alternative.me 恐懼貪婪指數      (IO-02)
3. Etherscan 路線 A：交易所熱錢包餘額  (IO-03)
4. Etherscan 路線 B：最近大額交易列表  (IO-03)
5. Etherscan 單一地址餘額           (IO-03, 原有)
"""
import sys
import io
import re
import time
import json
from datetime import datetime, timezone

import os

import requests
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ─── 共用設定 ─────────────────────────────────────────────────────────────────

UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)
HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
}
JSON_HEADERS = {
    'User-Agent': UA,
    'Accept': 'application/json',
}
TIMEOUT         = 15
PAUSE           = 3    # 主迴圈各爬蟲之間的間隔（秒）
ETHERSCAN_PAUSE = 5    # Etherscan 請求之間的間隔（免費版保守值）
SECTION         = '=' * 65
HUNDRED_M       = 100_000_000   # 1 億美元
WEI_PER_ETH     = 1e18

# 主要交易所熱錢包地址
EXCHANGE_WALLETS = {
    'Binance_14': '0x28C6c06298d514Db089934071355E5743bf21d60',
    'Binance_15': '0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549',
    'Bybit_Hot':  '0xf89d7b9c864f589bbF53a82105107622B35EaA40',
    'Coinbase_1': '0x71660c4005BA85c37ccec55d0C4493E66Fe775d3',
    'OKX_1':      '0x6cC5F688a315f3dC28A7781717a9A798a59fDA7b',
}

# 路線 B 用的監控地址（Binance 主熱錢包）
MONITOR_ADDRESS = '0x28C6c06298d514Db089934071355E5743bf21d60'


def ms(start: float) -> int:
    return round((time.time() - start) * 1000)


def short_addr(addr: str) -> str:
    return f'{addr[:6]}...{addr[-4:]}'


def print_json(d: dict) -> None:
    print(json.dumps(d, ensure_ascii=False, indent=2))


# ─── Scraper 1: CoinGecko 穩定幣市值 ─────────────────────────────────────────

def scrape_coingecko() -> dict:
    """優先用 CoinGecko 公開 API；失敗則爬網頁。"""
    api_url = (
        'https://api.coingecko.com/api/v3/coins/markets'
        '?vs_currency=usd&ids=tether,usd-coin'
        '&order=market_cap_desc&per_page=2&page=1&sparkline=false'
    )
    t0 = time.time()
    try:
        r = requests.get(api_url, headers=JSON_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        caps = {item['id']: item['market_cap'] for item in data}
        usdt = caps.get('tether', 0)
        usdc = caps.get('usd-coin', 0)
        return {
            'USDT_market_cap_億': round(usdt / HUNDRED_M, 1),
            'USDC_market_cap_億': round(usdc / HUNDRED_M, 1),
            'total_stablecoin_億': round((usdt + usdc) / HUNDRED_M, 1),
            'source': 'api',
            'response_time_ms': ms(t0),
        }
    except Exception as e:
        api_err = str(e)

    # 備案：網頁爬取
    results = {}
    t0 = time.time()
    for symbol, slug in {'USDT': 'tether', 'USDC': 'usd-coin'}.items():
        try:
            r = requests.get(
                f'https://www.coingecko.com/en/coins/{slug}',
                headers=HEADERS, timeout=TIMEOUT,
            )
            r.raise_for_status()
            text = BeautifulSoup(r.text, 'lxml').get_text(' ', strip=True)
            m = re.search(r'Market Cap[^\$]*\$([\d,]+(?:\.\d+)?)\s*([TBMK]?)', text, re.I)
            if m:
                val = float(m.group(1).replace(',', ''))
                mult = {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3}.get(m.group(2).upper(), 1)
                results[symbol] = val * mult
            else:
                results[symbol] = None
        except Exception:
            results[symbol] = None

    usdt = results.get('USDT') or 0
    usdc = results.get('USDC') or 0
    if usdt or usdc:
        return {
            'USDT_market_cap_億': round(usdt / HUNDRED_M, 1) if usdt else 'N/A',
            'USDC_market_cap_億': round(usdc / HUNDRED_M, 1) if usdc else 'N/A',
            'total_stablecoin_億': round((usdt + usdc) / HUNDRED_M, 1),
            'source': 'web_scrape',
            'response_time_ms': ms(t0),
        }
    return {
        'error': f'API 失敗: {api_err}；網頁爬取也失敗',
        'source': 'FAILED',
        'response_time_ms': ms(t0),
    }


# ─── Scraper 2: Alternative.me 恐懼貪婪指數 ──────────────────────────────────

def scrape_fgi() -> dict:
    url = 'https://api.alternative.me/fng/?limit=1'
    t0 = time.time()
    try:
        r = requests.get(url, headers=JSON_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        entry = r.json()['data'][0]
        dt = datetime.fromtimestamp(
            int(entry['timestamp']), tz=timezone.utc
        ).strftime('%Y-%m-%d %H:%M UTC')
        return {
            'fgi_value':          int(entry['value']),
            'fgi_classification': entry['value_classification'],
            'timestamp':          dt,
            'response_time_ms':   ms(t0),
        }
    except Exception as e:
        return {'error': str(e), 'source': 'FAILED', 'response_time_ms': ms(t0)}


# ─── Scraper 3 / 路線 A：交易所熱錢包餘額（網頁爬蟲） ────────────────────────

_ETH_MAX = 2_000_000   # ETH 總量 ~1.2億，交易所持倉超過 200 萬即異常


def _parse_eth_balance(html: str) -> float | None:
    """
    從 Etherscan 地址頁面 HTML 中擷取 ETH 餘額。
    三段式策略 + 上限 sanity check，避免誤判 token 餘額。
    """
    soup = BeautifulSoup(html, 'lxml')
    full = soup.get_text(' ', strip=True)

    # 策略 1：精確匹配 "ETH Balance" 標籤 → 緊跟的數值
    m = re.search(
        r'ETH\s+Balance\s*[:\s]*\$([\d,]+(?:\.\d+)?)|'   # "$X.XX" 美元格式（有時先顯示美元）
        r'ETH\s+Balance[^0-9]{0,30}?([\d,]+\.\d{4,})\s*ETH',  # "X.XXXX ETH" 格式
        full, re.I,
    )
    if m:
        raw = m.group(2) or m.group(1)
        if raw:
            val = float(raw.replace(',', ''))
            if val < _ETH_MAX:
                return val

    # 策略 2：已知 CSS 選擇器，但限定只在 "ETH" 字樣附近取值
    for sel in ('[data-highlight-target]', '#ContentPlaceHolder1_divSummary'):
        elem = soup.select_one(sel)
        if not elem:
            continue
        text = elem.get_text(' ', strip=True)
        for m in re.finditer(r'([\d,]+\.\d{4,})\s*ETH', text):
            val = float(m.group(1).replace(',', ''))
            if val < _ETH_MAX:
                return val

    # 策略 3：全頁掃描，限制合理範圍（0.001 ~ 2M ETH）
    for c in re.findall(r'([\d,]+\.\d{4,})\s*ETH', full):
        val = float(c.replace(',', ''))
        if 0.001 < val < _ETH_MAX:
            return val

    return None


def scrape_exchange_wallets() -> dict:
    """
    路線 A：依序爬取各大交易所熱錢包的 ETH 餘額。
    每個錢包之間等待 ETHERSCAN_PAUSE 秒，避免觸發 Etherscan 限流。
    """
    t0 = time.time()
    wallets: list[dict] = []
    success = 0

    for i, (name, address) in enumerate(EXCHANGE_WALLETS.items()):
        if i > 0:
            time.sleep(ETHERSCAN_PAUSE)

        url = f'https://etherscan.io/address/{address}'
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            balance = _parse_eth_balance(r.text)
            if balance is not None:
                wallets.append({
                    'exchange':     name,
                    'address':      short_addr(address),
                    'eth_balance':  balance,
                    'status':       'OK',
                })
                success += 1
                print(f'    {name:12s} {short_addr(address)}  {balance:>14,.2f} ETH')
            else:
                wallets.append({
                    'exchange': name,
                    'address':  short_addr(address),
                    'status':   'PARSE_FAILED',
                })
                print(f'    {name:12s} {short_addr(address)}  [解析失敗]')
        except Exception as e:
            wallets.append({
                'exchange': name,
                'address':  short_addr(address),
                'status':   f'ERROR: {e}',
            })
            print(f'    {name:12s} {short_addr(address)}  [請求失敗: {e}]')

    return {
        'wallets':          wallets,
        'success_count':    success,
        'total':            len(EXCHANGE_WALLETS),
        'source':           'etherscan_web',
        'response_time_ms': ms(t0),
    }


# ─── Scraper 4 / 路線 B：Etherscan API 最近大額交易 ──────────────────────────

def scrape_etherscan_txlist() -> dict:
    """
    路線 B：用 Etherscan txlist API 取最近 10 筆交易，
    篩選 value > 100 ETH 的大額轉帳。
    value 單位為 wei；100 ETH = 10^20 wei。
    """
    t0 = time.time()
    api_key = os.environ.get('ETHERSCAN_API_KEY')
    if not api_key:
        print('    [錯誤] 未設定環境變數 ETHERSCAN_API_KEY，路線 B 無法執行。')
        print('    請先執行：export ETHERSCAN_API_KEY=你的金鑰  (Linux/macOS)')
        print('    或：set ETHERSCAN_API_KEY=你的金鑰  (Windows CMD)')
        return {
            'address':          short_addr(MONITOR_ADDRESS),
            'error':            'ETHERSCAN_API_KEY 環境變數未設定',
            'source':           'FAILED',
            'response_time_ms': ms(t0),
        }
    # V2 API：https://docs.etherscan.io/v2-migration
    api_url = (
        'https://api.etherscan.io/v2/api'
        '?chainid=1'
        f'&module=account&action=txlist'
        f'&address={MONITOR_ADDRESS}'
        '&startblock=0&endblock=99999999'
        '&page=1&offset=10&sort=desc'
        f'&apikey={api_key}'
    )
    try:
        r = requests.get(api_url, headers=JSON_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        if data.get('status') != '1':
            return {
                'address':          short_addr(MONITOR_ADDRESS),
                'error':            f"{data.get('message','NOTOK')}: {data.get('result','')}",
                'source':           'FAILED',
                'response_time_ms': ms(t0),
            }

        txs = data['result']
        large_txs: list[dict] = []
        THRESHOLD_WEI = int(100 * WEI_PER_ETH)   # 100 ETH in wei

        for tx in txs:
            val_wei = int(tx.get('value', 0))
            eth_amt = val_wei / WEI_PER_ETH
            ts = int(tx.get('timeStamp', 0))
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            is_large = val_wei > THRESHOLD_WEI

            row = {
                'timestamp':  dt,
                'from':       short_addr(tx['from']),
                'to':         short_addr(tx['to']) if tx.get('to') else '(contract)',
                'eth_amount': round(eth_amt, 4),
                'large':      is_large,
            }
            if is_large:
                large_txs.append(row)
                print(f'    {dt}  {short_addr(tx["from"])} -> '
                      f'{short_addr(tx["to"]) if tx.get("to") else "(contract)"}  '
                      f'{eth_amt:>10,.2f} ETH  *** large ***')

        if not large_txs:
            print(f'    最近 {len(txs)} 筆交易中沒有 >100 ETH 的大額轉帳')

        return {
            'address':          short_addr(MONITOR_ADDRESS),
            'large_txs_100eth': large_txs,
            'large_tx_count':   len(large_txs),
            'total_fetched':    len(txs),
            'threshold':        '100 ETH',
            'source':           'etherscan_api',
            'response_time_ms': ms(t0),
        }

    except Exception as e:
        return {
            'address':          short_addr(MONITOR_ADDRESS),
            'error':            str(e),
            'source':           'FAILED',
            'response_time_ms': ms(t0),
        }


# ─── Scraper 5: Etherscan 單一地址餘額（原有，保留） ─────────────────────────

SINGLE_ADDRESS = '0x28C6c06298d514Db089934071355E5743bf21d60'


def scrape_etherscan_single() -> dict:
    """優先爬網頁；失敗則嘗試 Etherscan balance API。"""
    t0 = time.time()

    try:
        r = requests.get(
            f'https://etherscan.io/address/{SINGLE_ADDRESS}',
            headers=HEADERS, timeout=TIMEOUT,
        )
        r.raise_for_status()
        balance = _parse_eth_balance(r.text)
        if balance is not None:
            return {
                'address':          SINGLE_ADDRESS,
                'eth_balance':      balance,
                'source':           'etherscan_web',
                'response_time_ms': ms(t0),
            }
        web_err = f'HTTP {r.status_code}：解析不到餘額'
    except Exception as e:
        web_err = str(e)

    try:
        r = requests.get(
            'https://api.etherscan.io/api'
            f'?module=account&action=balance&address={SINGLE_ADDRESS}'
            '&tag=latest&apikey=YourApiKeyToken',
            headers=JSON_HEADERS, timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if data.get('status') == '1':
            eth = int(data['result']) / WEI_PER_ETH
            return {
                'address':          SINGLE_ADDRESS,
                'eth_balance':      round(eth, 4),
                'source':           'etherscan_api',
                'response_time_ms': ms(t0),
            }
        api_err = f"{data.get('message','NOTOK')}: {data.get('result','')}"
    except Exception as e:
        api_err = str(e)

    return {
        'address':          SINGLE_ADDRESS,
        'error':            f'網頁: {web_err} | API: {api_err}',
        'source':           'FAILED',
        'response_time_ms': ms(t0),
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

SCRAPERS = [
    ('CoinGecko 穩定幣市值',           scrape_coingecko),
    ('Alternative.me 恐懼貪婪指數',     scrape_fgi),
    ('Etherscan 路線A 交易所熱錢包餘額', scrape_exchange_wallets),
    ('Etherscan 路線B 最近大額交易',     scrape_etherscan_txlist),
    ('Etherscan 單一地址餘額',          scrape_etherscan_single),
]


def main() -> None:
    print(SECTION)
    print('  爬蟲原型測試')
    print(f'  執行時間: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}')
    print(SECTION)

    outcomes: list[tuple[str, bool, dict]] = []

    for i, (name, func) in enumerate(SCRAPERS, 1):
        print(f'\n[{i}] {name}')
        print('-' * 50)

        result = func()

        # 路線 A/B 在函數內已逐筆印出，只印 JSON summary；其餘完整印出
        if 'wallets' in result or 'large_txs_100eth' in result:
            # 只印非列表欄位的摘要
            summary = {k: v for k, v in result.items()
                       if k not in ('wallets', 'large_txs_100eth')}
            print()
            print_json(summary)
        else:
            print_json(result)

        source = result.get('source', '')
        ok = source not in ('FAILED',) and 'error' not in result
        outcomes.append((name, ok, result))

        if i < len(SCRAPERS):
            print(f'\n  ── 等待 {PAUSE} 秒後繼續 ──')
            time.sleep(PAUSE)

    # ─── 總結 ───────────────────────────────────────────────────────────────
    passed = [(n, r) for n, ok, r in outcomes if ok]
    failed = [(n, r) for n, ok, r in outcomes if not ok]

    print(f'\n{SECTION}')
    print(f'  總結：成功 {len(passed)} / {len(SCRAPERS)}')

    if passed:
        print('  成功：')
        for name, r in passed:
            extra = ''
            if 'success_count' in r:
                extra = f'  ← {r["success_count"]}/{r["total"]} 個錢包餘額讀取成功'
            elif 'total_fetched' in r:
                extra = (f'  ← 取得 {r["total_fetched"]} 筆交易，'
                         f'其中 {r["large_tx_count"]} 筆 >{r.get("threshold","100 ETH")}')
            elif 'eth_balance' in r:
                extra = f'  ← {r["eth_balance"]:,.2f} ETH'
            elif 'total_stablecoin_億' in r:
                extra = f'  ← 穩定幣總市值 {r["total_stablecoin_億"]} 億美元'
            elif 'fgi_value' in r:
                extra = f'  ← {r["fgi_value"]} ({r.get("fgi_classification","")})'
            print(f'    [OK] {name}  (source={r.get("source","")}){extra}')

    if failed:
        print('  失敗：')
        for name, r in failed:
            reason = r.get('error', r.get('reason', r.get('source', 'unknown')))
            print(f'    [--] {name}')
            print(f'         {str(reason)[:100]}')

    print(SECTION)


if __name__ == '__main__':
    main()
