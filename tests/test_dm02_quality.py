# -*- coding: utf-8 -*-
"""Tests for DM-02 蓉蓉+小方 DataQualityAnalyst & DataQualitySection."""
import io
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.squads.crypto.data_management.dm_02_quality_check import (
    DataQualityAnalyst,
    DataQualitySection,
)
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.message_bus import get_bus

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


def _make_gw() -> MagicMock:
    gw = MagicMock()
    gw.get_stats.return_value = {"avg_response_time_ms": 50, "errors_last_hour": 0}
    return gw


def _make_section() -> DataQualitySection:
    get_bus().clear()
    return DataQualitySection(gateway=_make_gw())


def _old_ts(seconds: int = 700) -> str:
    """回傳 seconds 秒前的 UTC ISO 字串。"""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _future_ts(seconds: int = 60) -> str:
    """回傳 seconds 秒後的 UTC ISO 字串。"""
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Test 01 — 兩位分析員獨立工作
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 01 — 兩位分析員獨立工作')
print(SECTION)

get_bus().clear()
rongrong = DataQualityAnalyst("single_point", gateway=_make_gw())
xiaofang = DataQualityAnalyst("systemic",     gateway=_make_gw())

check(rongrong.role_name == "蓉蓉",        "蓉蓉 role_name")
check(rongrong.role_code == "DM-02a",      "蓉蓉 role_code")
check(rongrong.mode      == "single_point", "蓉蓉 mode=single_point")
check(xiaofang.role_name == "小方",         "小方 role_name")
check(xiaofang.role_code == "DM-02b",      "小方 role_code")
check(xiaofang.mode      == "systemic",     "小方 mode=systemic")

# 各自獨立呼叫 check_data
r_rr = rongrong.check_data({"eth_price": 3000, "rsi": 50})
r_xf = xiaofang.check_data({"eth_price": 3000, "rsi": 50})

check(isinstance(r_rr, SubReport),        "蓉蓉 check_data() 回傳 SubReport")
check(r_rr.role_name == "蓉蓉",           "蓉蓉 SubReport.role_name 正確")
check(r_rr.role_code == "DM-02a",         "蓉蓉 SubReport.role_code 正確")
check(isinstance(r_xf, SubReport),        "小方 check_data() 回傳 SubReport")
check(r_xf.role_name == "小方",           "小方 SubReport.role_name 正確")
check(r_xf.role_code == "DM-02b",         "小方 SubReport.role_code 正確")
check(len(rongrong.history) == 1,         "蓉蓉 history 記錄一筆")
check(len(xiaofang.history) == 1,         "小方 history 記錄一筆")

# mode 保護
try:
    DataQualityAnalyst("invalid_mode")
    check(False, "非法 mode 應拋出 AssertionError")
except AssertionError:
    check(True, "非法 mode 拋出 AssertionError")


# ─────────────────────────────────────────────────────────────────────────────
# Test 02 — 蓉蓉的單點檢查
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 02 — 蓉蓉單點檢查')
print(SECTION)

get_bus().clear()
rr = DataQualityAnalyst("single_point", gateway=_make_gw())

# 2a. 正常資料 → bullish
data_ok = {"eth_price": 3000, "rsi": 60, "fgi": 45, "funding_rate": 0.0001}
r_ok = rr.check_data(data_ok)
check(r_ok.direction == "bullish",   f"正常資料應為 bullish，得到 {r_ok.direction}")
check(r_ok.sub_confidence == 0.8,    f"正常資料信心應為 0.8，得到 {r_ok.sub_confidence}")
check("checked_fields" in r_ok.data_used, "data_used 含 checked_fields")

# 2b. 一個欄位異常 → neutral
data_one_bad = {"eth_price": 3000, "rsi": 150}  # rsi > 100
r_one = rr.check_data(data_one_bad)
check(r_one.direction == "neutral",  f"一個欄位異常應為 neutral，得到 {r_one.direction}")
check(r_one.sub_confidence == 0.5,   f"一個異常信心應為 0.5，得到 {r_one.sub_confidence}")
check("rsi" in r_one.reasoning,      "reasoning 含異常欄位名")

# 2c. 多個欄位異常 → bearish
data_multi_bad = {"eth_price": 50, "rsi": 150}  # 兩個都超出
r_multi = rr.check_data(data_multi_bad)
check(r_multi.direction == "bearish", f"多個欄位異常應為 bearish，得到 {r_multi.direction}")
check(r_multi.sub_confidence >= 0.5,  f"多個異常信心 ≥ 0.5，得到 {r_multi.sub_confidence}")

expected_conf_multi = min(0.4 + 2 * 0.1, 0.95)
check(
    abs(r_multi.sub_confidence - expected_conf_multi) < 1e-9,
    f"信心公式正確 ({expected_conf_multi:.2f})，得到 {r_multi.sub_confidence:.2f}"
)

# 2d. 時間戳在未來 → neutral
data_future_ts = {"eth_price": 3000, "timestamp": _future_ts(60)}
r_future = rr.check_data(data_future_ts)
check(r_future.direction in ("neutral", "bearish"), "未來時間戳應為 neutral/bearish")
check("未來" in r_future.reasoning, "reasoning 含 '未來'")

# 2e. 資料過時（700 秒）→ neutral
data_old_ts = {"eth_price": 3000, "timestamp": _old_ts(700)}
r_old = rr.check_data(data_old_ts)
check(r_old.direction in ("neutral", "bearish"), "過時資料應為 neutral/bearish")
check("過時" in r_old.reasoning, "reasoning 含 '過時'")

# 2f. 新鮮時間戳（60 秒）→ 不加 issue
data_fresh_ts = {"eth_price": 3000, "timestamp": _old_ts(60)}
r_fresh = rr.check_data(data_fresh_ts)
check(r_fresh.direction == "bullish", "新鮮時間戳不應加 issue")

# 2g. 連續性跳變（需先有 history）
rr2 = DataQualityAnalyst("single_point", gateway=_make_gw())
rr2.check_data({"eth_price": 3000})  # 先建立 history
data_jump = {"eth_price": 6000, "previous": {"eth_price": 3000}}  # 100% 漲幅 > 50%
r_jump = rr2.check_data(data_jump)
check("跳變" in r_jump.reasoning, f"連續性跳變應出現在 reasoning: {r_jump.reasoning}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 03 — 小方的系統性檢查
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 03 — 小方系統性檢查')
print(SECTION)

get_bus().clear()
xf = DataQualityAnalyst("systemic", gateway=_make_gw())

# 3a. 所有正常 → bullish
data_sys_ok = {"eth_price": 3000, "rsi": 60, "fgi": 50}
r_sys_ok = xf.check_data(data_sys_ok)
check(r_sys_ok.direction == "bullish",  f"系統正常應為 bullish，得到 {r_sys_ok.direction}")
check(r_sys_ok.sub_confidence == 0.7,   f"正常信心應為 0.7，得到 {r_sys_ok.sub_confidence}")

# 3b. 單一欄位異常 + 其他正常 → bearish + "可能是真實事件"
data_one_sys = {"eth_price": 50, "rsi": 50, "fgi": 50}   # eth_price out, others ok
r_one_sys = xf.check_data(data_one_sys)
check(r_one_sys.direction == "bearish",      f"單異常應為 bearish，得到 {r_one_sys.direction}")
check("真實事件" in r_one_sys.reasoning,     "reasoning 含 '真實事件'")
expected_one_sys_conf = min(0.4 + 1 * 0.15, 0.95)
check(
    abs(r_one_sys.sub_confidence - expected_one_sys_conf) < 1e-9,
    f"單異常信心 {expected_one_sys_conf:.2f}，得到 {r_one_sys.sub_confidence:.2f}"
)

# 3c. 多個欄位同時異常 → bearish + "系統性問題"
data_multi_sys = {"eth_price": 50, "rsi": 150, "fgi": 50}  # 2 anomalies, 1 normal
r_multi_sys = xf.check_data(data_multi_sys)
check(r_multi_sys.direction == "bearish",      f"多異常應為 bearish，得到 {r_multi_sys.direction}")
check("系統性問題" in r_multi_sys.reasoning,   "reasoning 含 '系統性問題'")

# 3d. RSS 健康（3個以上失效）
data_rss = {
    "rss_status": {
        "BBC World": False,
        "CoinDesk":  False,
        "NPR":       False,
        "Others":    True,
    }
}
r_rss = xf.check_data(data_rss)
check(r_rss.direction == "bearish",        f"RSS 3 個失效應為 bearish，得到 {r_rss.direction}")
check("RSS 失效" in r_rss.reasoning,       "reasoning 含 'RSS 失效'")
check("rss_offline_count" in r_rss.data_used, "data_used 含 rss_offline_count")
check(r_rss.data_used["rss_offline_count"] == 3, "離線計數為 3")

# 3e. RSS 健康（2個失效，不超門檻）
data_rss_ok = {"rss_status": {"BBC World": False, "CoinDesk": False, "NPR": True}}
r_rss_ok = xf.check_data(data_rss_ok)
check(r_rss_ok.direction == "bullish",     "RSS 2 個失效不超門檻，應為 bullish")

# 3f. 爬蟲健康（2個以上失效）
data_scraper = {
    "scraper_status": {
        "CoinGecko": False,
        "Etherscan": False,
        "FGI":       True,
    }
}
r_scraper = xf.check_data(data_scraper)
check(r_scraper.direction == "bearish",    f"爬蟲 2 失效應為 bearish，得到 {r_scraper.direction}")
check("爬蟲失敗" in r_scraper.reasoning,   "reasoning 含 '爬蟲失敗'")
check("failed_scrapers" in r_scraper.data_used, "data_used 含 failed_scrapers")


# ─────────────────────────────────────────────────────────────────────────────
# Test 04 — 共識（agreed）
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 04 — 共識（agreed）')
print(SECTION)

section4 = _make_section()

# 兩人都說資料健康（bullish）→ agreed
# 蓉蓉: 0.8, 小方: 0.7 → conf_diff=0.1 ≤ 0.2 → agreed, final=0.75
data_healthy = {"eth_price": 3000, "rsi": 60, "fgi": 50, "funding_rate": 0.0001}
debate4 = section4.conduct_debate(data_healthy)

check(isinstance(debate4, DebateResult),      "conduct_debate 回傳 DebateResult")
check(debate4.consensus_type == "agreed",     f"兩人看好資料應 agreed，得到 {debate4.consensus_type}")
check(debate4.final_direction == "bullish",   f"最終方向應 bullish，得到 {debate4.final_direction}")
check(abs(debate4.final_confidence - 0.75) < 1e-9,
      f"最終信心應 0.75，得到 {debate4.final_confidence}")
check(debate4.report_a.role_name == "蓉蓉",   "report_a 來自蓉蓉")
check(debate4.report_b.role_name == "小方",   "report_b 來自小方")
check(debate4.key_disagreement is None,       "無分歧時 key_disagreement 為 None")
check(len(section4.debate_history) == 1,      "debate_history 記錄一筆")

# to_dict() 可序列化
d4 = debate4.to_dict()
check(isinstance(d4, dict),                   "to_dict() 回傳 dict")
check(debate4.debate_id.startswith("DM-02-"), "debate_id 格式正確")


# ─────────────────────────────────────────────────────────────────────────────
# Test 05 — 大分歧（dual_track）→ 保守原則
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 05 — 大分歧（dual_track）')
print(SECTION)

section5 = _make_section()

# 情境：funding_rate 超範圍 + 時間戳過時
#   蓉蓉：2 issues（field out of range + timestamp old）→ bearish, conf=0.6
#   小方：anomaly_count=1, normal_count=0（無其他 valid_range 欄位）
#         → 兩個條件都不觸發 → 0 issues → bullish, conf=0.7
data_disagree = {
    "funding_rate": -0.01,           # 超出 [-0.005, 0.005]
    "timestamp":    _old_ts(700),    # 過時 700 秒
}
debate5 = section5.conduct_debate(data_disagree)

check(debate5.consensus_type == "dual_track",  f"方向分歧應為 dual_track，得到 {debate5.consensus_type}")
check(debate5.final_direction == "bearish",    f"保守原則應取 bearish，得到 {debate5.final_direction}")

# 蓉蓉 bearish conf: min(0.4 + 2*0.1, 0.95) = 0.6 → final = 0.6 * 0.8 = 0.48
expected_rr_conf = min(0.4 + 2 * 0.1, 0.95)
expected_final   = expected_rr_conf * 0.8
check(
    abs(debate5.final_confidence - expected_final) < 1e-9,
    f"final_confidence 應為 {expected_final:.3f}，得到 {debate5.final_confidence:.3f}"
)
check(debate5.key_disagreement is not None,   "大分歧時 key_disagreement 非 None")
check("蓉蓉" in debate5.combined_reasoning,   "combined_reasoning 含 '蓉蓉'")
check("小方" in debate5.combined_reasoning,   "combined_reasoning 含 '小方'")

# 直接測試 _compare_reports 的各種場景
# discussed_agreed（同向但信心差 > 0.2）
from trading_system.common.data_models import SubReport
def _sr(direction, confidence, role="TEST"):
    return SubReport(
        role_name=role, role_code=role, direction=direction,
        sub_confidence=confidence, reasoning="test", data_used={},
        timestamp=datetime.now(), staleness_flag=False,
    )

section5b = _make_section()
ra_da = _sr("bearish", 0.3)
rb_da = _sr("bearish", 0.8)
ct, cd, cc, _ = section5b._compare_reports(ra_da, rb_da)
expected_cc = (0.3**2 + 0.8**2) / (0.3 + 0.8)
check(ct == "discussed_agreed", f"信心差 > 0.2 應為 discussed_agreed，得到 {ct}")
check(cd == "bearish",          f"同向取 bearish，得到 {cd}")
check(abs(cc - expected_cc) < 1e-9, f"加權信心公式正確 {expected_cc:.4f}，得到 {cc:.4f}")

# neutral vs bearish → bearish 勝（保守）
ra_nb = _sr("neutral", 0.5)
rb_nb = _sr("bearish", 0.4)
ct_nb, cd_nb, cc_nb, _ = section5b._compare_reports(ra_nb, rb_nb)
check(ct_nb == "dual_track", "neutral vs bearish 應為 dual_track")
check(cd_nb == "bearish",    "保守原則取 bearish")


# ─────────────────────────────────────────────────────────────────────────────
# Test 06 — RSS 健康檢查（小方專屬）
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 06 — RSS 健康檢查（daily_health_check_rss）')
print(SECTION)

get_bus().clear()
xf6 = DataQualityAnalyst("systemic", gateway=_make_gw())
rss_result = xf6.daily_health_check_rss()

check(isinstance(rss_result, dict),       "daily_health_check_rss 回傳 dict")
check(len(rss_result) > 0,               "結果非空（有 RSS 來源）")
check(all(isinstance(v, bool) for v in rss_result.values()),
      "所有 RSS 結果為 bool 型別")
check("BBC World" in rss_result,         "包含 BBC World")
check("CoinDesk"  in rss_result,         "包含 CoinDesk")
check("CoinTelegraph" in rss_result,     "包含 CoinTelegraph")

# 確認至少一半可以解析（或全部都是 bool 結果）
parsed = sum(1 for v in rss_result.values() if v)
print(f"  [INFO] RSS 健康: {parsed}/{len(rss_result)} 可解析")

# 蓉蓉呼叫 daily_health_check_rss 應回傳空 dict
rr6 = DataQualityAnalyst("single_point", gateway=_make_gw())
result_rr = rr6.daily_health_check_rss()
check(result_rr == {},   "蓉蓉呼叫 daily_health_check_rss 應回傳 {}")

# monthly_wallet_check 也只有小方有效
wallets = {"wallet_A": "0xABC...", "wallet_B": "0xDEF..."}
check(rr6.monthly_wallet_check(wallets) == {},  "蓉蓉 monthly_wallet_check 回傳 {}")
wc_result = xf6.monthly_wallet_check(wallets)
check(isinstance(wc_result, dict),   "小方 monthly_wallet_check 回傳 dict")
check(len(wc_result) == 2,           "包含兩個錢包結果")


# ─────────────────────────────────────────────────────────────────────────────
# Test 07 — 完整激辯流程與 get_status
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 07 — 完整激辯流程與 get_status')
print(SECTION)

section7 = _make_section()

# 初始狀態
status0 = section7.get_status()
check(status0["debate_count"] == 0,     "初始 debate_count=0")
check(status0["latest_debate"] is None, "初始 latest_debate=None")
check(status0["consensus_rate"] == 0.0, "初始 consensus_rate=0.0")

# 第一次激辯（正常資料 → agreed）
debate7a = section7.conduct_debate({"eth_price": 3000, "rsi": 50, "fgi": 45})
check(debate7a.consensus_type == "agreed",   "第一次激辯：正常資料 agreed")
check(len(section7.debate_history) == 1,     "debate_history 一筆")

# 第二次激辯（多個欄位異常，兩人都 bearish → agreed 或 discussed_agreed）
debate7b = section7.conduct_debate({"eth_price": 50, "rsi": 150, "fgi": -5})
check(debate7b.final_direction == "bearish", f"多異常最終應為 bearish，得到 {debate7b.final_direction}")
check(len(section7.debate_history) == 2,     "debate_history 兩筆")

# 第三次激辯（dual_track）
debate7c = section7.conduct_debate({"funding_rate": -0.01, "timestamp": _old_ts(800)})
check(debate7c.consensus_type == "dual_track", "第三次激辯：dual_track")
check(len(section7.debate_history) == 3,       "debate_history 三筆")

# get_status 最終狀態
status_final = section7.get_status()
check(status_final["debate_count"] == 3,           "debate_count=3")
check(status_final["latest_debate"] is not None,   "latest_debate 非 None")
check(isinstance(status_final["consensus_rate"], float), "consensus_rate 為 float")
agreed_count = sum(1 for d in section7.debate_history if d.consensus_type == "agreed")
expected_rate = agreed_count / 3
check(
    abs(status_final["consensus_rate"] - expected_rate) < 1e-9,
    f"consensus_rate 正確（{expected_rate:.4f}），得到 {status_final['consensus_rate']:.4f}"
)

# _identify_disagreement
section7b = _make_section()
ra_id = _sr("bearish", 0.6, "蓉蓉")
rb_id = _sr("bullish", 0.6, "小方")
disagree = section7b._identify_disagreement(ra_id, rb_id)
check(disagree is not None,         "方向分歧時 _identify_disagreement 非 None")
check("蓉蓉" in (disagree or ""),    "_identify_disagreement 含 '蓉蓉'")

ra_agree = _sr("bearish", 0.8, "蓉蓉")
rb_agree = _sr("bearish", 0.8, "小方")
no_disagree = section7b._identify_disagreement(ra_agree, rb_agree)
check(no_disagree is None,          "無分歧時 _identify_disagreement 為 None")


# ─────────────────────────────────────────────────────────────────────────────
# 結果統計
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print(f'結果: {passed} passed, {failed} failed (共 {passed + failed} tests)')
print(SECTION)

if failed > 0:
    sys.exit(1)
