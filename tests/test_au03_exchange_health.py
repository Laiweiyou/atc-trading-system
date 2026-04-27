# -*- coding: utf-8 -*-
"""Tests for AU-03 君君/阿豪/小馬 ExchangeHealthAnalyst & ExchangeHealthSection."""
import io
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.squads.crypto.monitoring.au_03_exchange_health import (
    ExchangeHealthAnalyst,
    ExchangeHealthSection,
)
from trading_system.common.data_models import SubReport, DebateResult
from trading_system.common.flash_alert import reset_flash_state, _sent_alerts
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


def _fresh_gw(
    avg_latency_ms: float = 50.0,
    errors_last_hour: int = 0,
    requests_last_hour: int = 10,
    health_ok: bool = True,
) -> MagicMock:
    gw = MagicMock()
    gw.get_stats.return_value = {
        "avg_response_time_ms": avg_latency_ms,
        "errors_last_hour":     errors_last_hour,
        "requests_last_hour":   requests_last_hour,
    }
    gw.health_check.return_value = (
        {"healthy": True,  "time_diff_ms": 30}
        if health_ok
        else {"healthy": False, "reason": "timeout"}
    )
    return gw


def _make_subreport(direction: str, confidence: float, role: str = "TEST") -> SubReport:
    return SubReport(
        role_name      = role,
        role_code      = role,
        direction      = direction,
        sub_confidence = confidence,
        reasoning      = f"test {direction}",
        data_used      = {},
        timestamp      = datetime.now(),
        staleness_flag = False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 01 — 兩位分析員獨立工作
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 01 — 兩位分析員獨立工作')
print(SECTION)

gw = _fresh_gw()

junjun = ExchangeHealthAnalyst("quantitative", gateway=gw)
ahao   = ExchangeHealthAnalyst("qualitative",  gateway=gw)

check(junjun.role_name == "君君",   "君君 role_name")
check(junjun.role_code == "AU-03a", "君君 role_code")
check(ahao.role_name   == "阿豪",   "阿豪 role_name")
check(ahao.role_code   == "AU-03b", "阿豪 role_code")
check(junjun.mode == "quantitative", "君君 mode=quantitative")
check(ahao.mode   == "qualitative",  "阿豪 mode=qualitative")

# 量化分析的 analyze()
r_junjun = junjun.analyze()
check(isinstance(r_junjun, SubReport), "君君 analyze() 回傳 SubReport")
check(r_junjun.direction in ("bullish", "bearish", "neutral"), "君君 direction 合法")
check(0.0 <= r_junjun.sub_confidence <= 1.0, "君君 sub_confidence 在 [0,1]")
check(r_junjun.role_name == "君君", "君君 SubReport.role_name 正確")
check(len(junjun.analysis_history) == 1, "君君 analysis_history 記錄一筆")
check(junjun.last_analysis_time is not None, "君君 last_analysis_time 已更新")


# ─────────────────────────────────────────────────────────────────────────────
# Test 02 — 君君的量化分析（低延遲 vs 高延遲）
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 02 — 君君量化分析')
print(SECTION)

# 低延遲、零錯誤 → bullish 或 neutral
gw_good = _fresh_gw(avg_latency_ms=50, errors_last_hour=0, requests_last_hour=10)
analyst_good = ExchangeHealthAnalyst("quantitative", gateway=gw_good)
report_good  = analyst_good.analyze()

check(isinstance(report_good, SubReport), "低延遲場景回傳 SubReport")
check(report_good.direction in ("bullish", "neutral"), f"低延遲方向應為 bullish/neutral，得到 {report_good.direction}")
check("api_avg_latency_ms" in report_good.data_used, "data_used 含 api_avg_latency_ms")
check("api_error_rate" in report_good.data_used, "data_used 含 api_error_rate")
check("gateway_health" in report_good.data_used, "data_used 含 gateway_health")

# 高延遲（> 1000ms）→ bearish
gw_bad = _fresh_gw(avg_latency_ms=1500, errors_last_hour=0, requests_last_hour=10)
analyst_bad = ExchangeHealthAnalyst("quantitative", gateway=gw_bad)
report_bad  = analyst_bad.analyze()

check(isinstance(report_bad, SubReport), "高延遲場景回傳 SubReport")
check(report_bad.direction == "bearish", f"高延遲方向應為 bearish，得到 {report_bad.direction}")

# 高錯誤率（> 10%）→ bearish
gw_err = _fresh_gw(avg_latency_ms=100, errors_last_hour=20, requests_last_hour=100)
analyst_err = ExchangeHealthAnalyst("quantitative", gateway=gw_err)
report_err  = analyst_err.analyze()

check(report_err.direction == "bearish", f"高錯誤率方向應為 bearish，得到 {report_err.direction}")

# Gateway 健康檢查失敗 → bearish
gw_unhealthy = _fresh_gw(avg_latency_ms=50, health_ok=False)
analyst_unhealthy = ExchangeHealthAnalyst("quantitative", gateway=gw_unhealthy)
report_unhealthy  = analyst_unhealthy.analyze()

check(report_unhealthy.direction == "bearish", "Gateway 不健康應為 bearish")


# ─────────────────────────────────────────────────────────────────────────────
# Test 03 — 阿豪的質化分析（真實 Reddit RSS）
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 03 — 阿豪質化分析（真實 RSS）')
print(SECTION)

gw_ahao = _fresh_gw()
analyst_ahao = ExchangeHealthAnalyst("qualitative", gateway=gw_ahao)
report_ahao  = analyst_ahao.analyze()

check(isinstance(report_ahao, SubReport), "阿豪 analyze() 回傳 SubReport")
check(report_ahao.direction in ("bullish", "bearish", "neutral"), "阿豪 direction 合法")
check(0.0 <= report_ahao.sub_confidence <= 1.0, "阿豪 sub_confidence 在 [0,1]")
check(report_ahao.role_name == "阿豪", "阿豪 SubReport.role_name 正確")
check(report_ahao.role_code == "AU-03b", "阿豪 SubReport.role_code 正確")
check(len(analyst_ahao.analysis_history) == 1, "阿豪 analysis_history 記錄一筆")

print(f"  [INFO] 阿豪分析結果: direction={report_ahao.direction}, confidence={report_ahao.sub_confidence:.3f}")
print(f"  [INFO] 阿豪 data_used keys: {list(report_ahao.data_used.keys())}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 04 — 共識：方向一致 + 信心差 ≤ 0.2
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 04 — 共識（agreed）')
print(SECTION)

section = ExchangeHealthSection(gateway=_fresh_gw())

ra = _make_subreport("bullish", 0.5)
rb = _make_subreport("bullish", 0.6)

c_type, c_dir, c_conf, c_reason = section._compare_reports(ra, rb)

check(c_type == "agreed", f"consensus_type 應為 agreed，得到 {c_type}")
check(c_dir  == "bullish", f"final_direction 應為 bullish，得到 {c_dir}")
check(abs(c_conf - 0.55) < 1e-9, f"final_confidence 應為 0.55，得到 {c_conf}")
check(isinstance(c_reason, str) and len(c_reason) > 0, "reasoning 非空字串")


# ─────────────────────────────────────────────────────────────────────────────
# Test 05 — 小分歧：方向一致 + 信心差 > 0.2
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 05 — 小分歧（discussed_agreed）')
print(SECTION)

section5 = ExchangeHealthSection(gateway=_fresh_gw())

ra5 = _make_subreport("bearish", 0.3)
rb5 = _make_subreport("bearish", 0.8)

c_type5, c_dir5, c_conf5, _ = section5._compare_reports(ra5, rb5)

# 公式：(0.3^2 + 0.8^2) / (0.3 + 0.8) = (0.09 + 0.64) / 1.1 = 0.73 / 1.1
expected_conf5 = (0.3**2 + 0.8**2) / (0.3 + 0.8)

check(c_type5 == "discussed_agreed", f"consensus_type 應為 discussed_agreed，得到 {c_type5}")
check(c_dir5  == "bearish", f"final_direction 應為 bearish，得到 {c_dir5}")
check(abs(c_conf5 - expected_conf5) < 1e-9, f"final_confidence 應為 {expected_conf5:.4f}，得到 {c_conf5:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 06 — 大分歧：方向相反
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 06 — 大分歧（dual_track）')
print(SECTION)

section6 = ExchangeHealthSection(gateway=_fresh_gw())

ra6 = _make_subreport("bullish", 0.4)
rb6 = _make_subreport("bearish", 0.5)

c_type6, c_dir6, c_conf6, _ = section6._compare_reports(ra6, rb6)

check(c_type6 == "dual_track", f"consensus_type 應為 dual_track，得到 {c_type6}")
check(c_dir6  == "bearish", f"保守原則應取 bearish，得到 {c_dir6}")
check(abs(c_conf6 - 0.4) < 1e-9, f"final_confidence 應為 0.4，得到 {c_conf6}")

# 反向：bearish 0.4 vs bullish 0.5 → 保守取 bearish
ra6b = _make_subreport("bearish", 0.4)
rb6b = _make_subreport("bullish", 0.5)
_, c_dir6b, c_conf6b, _ = section6._compare_reports(ra6b, rb6b)
check(c_dir6b == "bearish", f"反向保守原則應取 bearish，得到 {c_dir6b}")
check(abs(c_conf6b - 0.32) < 1e-9, f"conf6b 應為 0.32，得到 {c_conf6b}")

# neutral vs bearish → bearish 勝
ra6c = _make_subreport("neutral", 0.5)
rb6c = _make_subreport("bearish", 0.4)
_, c_dir6c, _, _ = section6._compare_reports(ra6c, rb6c)
check(c_dir6c == "bearish", f"neutral vs bearish 應取 bearish，得到 {c_dir6c}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 07 — 完整激辯流程
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 07 — 完整激辯流程 conduct_debate()')
print(SECTION)

gw7 = _fresh_gw()
section7 = ExchangeHealthSection(gateway=gw7)

# Mock 兩位分析員的 analyze，避免真實 RSS
with patch.object(section7.junjun, 'analyze', return_value=_make_subreport("bullish", 0.5, "君君")):
    with patch.object(section7.ahao,   'analyze', return_value=_make_subreport("bullish", 0.6, "阿豪")):
        result7 = section7.conduct_debate()

check(isinstance(result7, DebateResult), "conduct_debate() 回傳 DebateResult")
check(result7.consensus_type == "agreed", f"consensus_type 應為 agreed，得到 {result7.consensus_type}")
check(result7.final_direction == "bullish", f"final_direction 應為 bullish，得到 {result7.final_direction}")
check(result7.debate_id.startswith("AU-03-"), f"debate_id 格式正確: {result7.debate_id}")
check(len(section7.debate_history) == 1, "debate_history 已記錄一筆")
check(result7.report_a.role_name == "君君", "report_a 來自君君")
check(result7.report_b.role_name == "阿豪", "report_b 來自阿豪")

# 確認 to_dict() 可序列化
d7 = result7.to_dict()
check(isinstance(d7, dict), "DebateResult.to_dict() 回傳 dict")
check("consensus_type" in d7, "to_dict() 含 consensus_type")

# 第二次激辯
with patch.object(section7.junjun, 'analyze', return_value=_make_subreport("bearish", 0.3)):
    with patch.object(section7.ahao, 'analyze', return_value=_make_subreport("bearish", 0.8)):
        result7b = section7.conduct_debate()

check(len(section7.debate_history) == 2, "第二次激辯後 debate_history 有 2 筆")
check(result7b.consensus_type == "discussed_agreed", f"第二次 consensus_type，得到 {result7b.consensus_type}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 08 — 健康狀態變化 → critical + FlashAlert
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 08 — 健康狀態變化與 FlashAlert')
print(SECTION)

reset_flash_state()
get_bus().clear()

gw8 = _fresh_gw()
section8 = ExchangeHealthSection(gateway=gw8)

# 第一次：bearish 0.75 → critical（confidence > 0.6）
before_count = len(_sent_alerts)
with patch.object(section8.junjun, 'analyze', return_value=_make_subreport("bearish", 0.75)):
    with patch.object(section8.ahao, 'analyze', return_value=_make_subreport("bearish", 0.75)):
        debate8 = section8.conduct_debate()

check(section8.last_health_status == "critical", f"健康狀態應為 critical，得到 {section8.last_health_status}")
check(len(_sent_alerts) > before_count, "critical 時應發送 FlashAlert")

# 確認 FlashAlert 類型為 DATA_OFFLINE
latest_alert = list(_sent_alerts.values())[-1]
check(latest_alert.alert_type == "DATA_OFFLINE", f"alert_type 應為 DATA_OFFLINE，得到 {latest_alert.alert_type}")
check(latest_alert.alert_level == "critical", f"alert_level 應為 critical，得到 {latest_alert.alert_level}")
check(latest_alert.requires_acknowledgment, "critical FlashAlert 需要確認")

# 第二次重複 critical → 不重複發送
count_after_first = len(_sent_alerts)
with patch.object(section8.junjun, 'analyze', return_value=_make_subreport("bearish", 0.75)):
    with patch.object(section8.ahao, 'analyze', return_value=_make_subreport("bearish", 0.75)):
        section8.conduct_debate()
check(len(_sent_alerts) == count_after_first, "相同狀態不重複發送 FlashAlert")

# suspicious（confidence 0.41-0.6）→ ANOMALY_FLASH
reset_flash_state()
gw8b = _fresh_gw()
section8b = ExchangeHealthSection(gateway=gw8b)

with patch.object(section8b.junjun, 'analyze', return_value=_make_subreport("bearish", 0.5)):
    with patch.object(section8b.ahao, 'analyze', return_value=_make_subreport("bearish", 0.5)):
        section8b.conduct_debate()

check(section8b.last_health_status == "suspicious", f"健康狀態應為 suspicious，得到 {section8b.last_health_status}")
sus_alert = list(_sent_alerts.values())[-1]
check(sus_alert.alert_type == "ANOMALY_FLASH", f"suspicious 應發 ANOMALY_FLASH，得到 {sus_alert.alert_type}")
check(not sus_alert.requires_acknowledgment, "suspicious 不需要確認")

# bearish 信心低（≤ 0.4）→ degraded，不發 FlashAlert
reset_flash_state()
gw8c = _fresh_gw()
section8c = ExchangeHealthSection(gateway=gw8c)

with patch.object(section8c.junjun, 'analyze', return_value=_make_subreport("bearish", 0.2)):
    with patch.object(section8c.ahao, 'analyze', return_value=_make_subreport("bearish", 0.2)):
        section8c.conduct_debate()

check(section8c.last_health_status == "degraded", f"低信心 bearish 應為 degraded，得到 {section8c.last_health_status}")
check(len(_sent_alerts) == 0, "degraded 不發 FlashAlert")


# ─────────────────────────────────────────────────────────────────────────────
# Test 09 — 共識率計算
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print('Test 09 — 共識率計算 _calculate_consensus_rate()')
print(SECTION)

reset_flash_state()
get_bus().clear()

gw9 = _fresh_gw()
section9 = ExchangeHealthSection(gateway=gw9)

check(section9._calculate_consensus_rate() == 0.0, "初始共識率為 0.0")

# 手動建立 10 筆 DebateResult：7 agreed + 3 dual_track
def _make_debate(c_type: str, direction: str = "bullish") -> DebateResult:
    ra = _make_subreport(direction, 0.5)
    rb = _make_subreport(direction, 0.5)
    return DebateResult(
        debate_id          = str(uuid.uuid4()),
        report_a           = ra,
        report_b           = rb,
        consensus_type     = c_type,
        final_direction    = direction,
        final_confidence   = 0.5,
        combined_reasoning = "test",
        timestamp          = datetime.now(),
    )

for _ in range(7):
    section9.debate_history.append(_make_debate("agreed"))
for _ in range(3):
    section9.debate_history.append(_make_debate("dual_track", "bearish"))

rate = section9._calculate_consensus_rate()
check(abs(rate - 0.7) < 1e-9, f"共識率應為 0.7，得到 {rate:.4f}")

# get_status() 結構
status9 = section9.get_status()
check("manager" in status9, "get_status() 含 manager")
check("exchange_health" in status9, "get_status() 含 exchange_health")
check("latest_debate" in status9, "get_status() 含 latest_debate")
check("debate_count" in status9, "get_status() 含 debate_count")
check("consensus_rate" in status9, "get_status() 含 consensus_rate")
check(status9["debate_count"] == 10, f"debate_count 應為 10，得到 {status9['debate_count']}")
check(abs(status9["consensus_rate"] - 0.7) < 1e-9, f"status consensus_rate 應為 0.7，得到 {status9['consensus_rate']}")

# 空 debate_history 的 get_status()
gw9b = _fresh_gw()
section9b = ExchangeHealthSection(gateway=gw9b)
status9b = section9b.get_status()
check(status9b["latest_debate"] is None, "無激辯時 latest_debate 為 None")
check(status9b["debate_count"] == 0, "無激辯時 debate_count 為 0")

# ─────────────────────────────────────────────────────────────────────────────
# 結果統計
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{SECTION}')
print(f'結果: {passed} passed, {failed} failed (共 {passed + failed} tests)')
print(SECTION)

if failed > 0:
    sys.exit(1)
