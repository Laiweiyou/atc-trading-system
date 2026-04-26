# -*- coding: utf-8 -*-
import sys
import io
import os
import json
import dataclasses
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.common.data_models import (
    SubReport, DebateResult, CourseReport, SnapshotBundle,
    TradingProposal, RiskAssessment, ArbiterDecision,
    ExecutionResult, AnomalyEvent, NewsEvent,
)

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


def no_datetimes(d) -> bool:
    """遞迴確認 dict 中無 datetime 物件（全已序列化為字串）。"""
    if isinstance(d, dict):
        return all(no_datetimes(v) for v in d.values())
    if isinstance(d, list):
        return all(no_datetimes(i) for i in d)
    return not isinstance(d, datetime)


def json_size(d: dict) -> int:
    return len(json.dumps(d, ensure_ascii=False))


TS  = datetime(2026, 4, 26, 8, 30, 0, tzinfo=timezone.utc)
TS2 = datetime(2026, 4, 26, 9, 0, 0, tzinfo=timezone.utc)

# ─── [1] SubReport ────────────────────────────────────────────────────────────

print(SECTION)
print('  [1] SubReport')
print(SECTION)

sr = SubReport(
    role_name="老徐",
    role_code="IO-01a",
    direction="bullish",
    sub_confidence=0.72,
    reasoning="鏈上淨流入增加，恐懼指數回升",
    data_used={"onchain": True, "fgi": 42},
    timestamp=TS,
    staleness_flag=False,
)

d = sr.to_dict()
check(isinstance(d, dict), 'to_dict() 回傳 dict')
check(no_datetimes(d), 'to_dict() 無 datetime 物件')
check(isinstance(d["timestamp"], str), 'timestamp 已序列化為字串')
check("T" in d["timestamp"], 'timestamp 為 ISO 格式')

try:
    json.dumps(d)
    check(True, 'to_dict() JSON 可序列化')
except Exception as e:
    check(False, f'to_dict() JSON 序列化失敗: {e}')

sr2 = SubReport.from_dict(d)
check(sr2 == sr, 'from_dict(to_dict()) 完整還原')
check(isinstance(sr2.timestamp, datetime), 'from_dict 後 timestamp 為 datetime')
check(sr2.staleness_flag == False, 'staleness_flag 預設值保留')
check(len(dataclasses.fields(sr)) == 8, f'SubReport 欄位數 8（實際: {len(dataclasses.fields(sr))}）')
print(f'  欄位數: {len(dataclasses.fields(sr))}  JSON 大小: {json_size(d)} bytes')

# ─── [2] DebateResult ─────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] DebateResult（巢狀 SubReport）')
print(SECTION)

sr_b = SubReport(
    role_name="小曾",
    role_code="IO-01b",
    direction="neutral",
    sub_confidence=0.55,
    reasoning="短期訊號混雜，觀望為主",
    data_used={"rss": 14, "reddit_score": -0.1},
    timestamp=TS,
)

dr = DebateResult(
    debate_id="IO-01-20260426-001",
    report_a=sr,
    report_b=sr_b,
    consensus_type="discussed_agreed",
    final_direction="bullish",
    final_confidence=0.65,
    combined_reasoning="老徐鏈上數據偏多，小曾情緒中性，綜合取偏多",
    timestamp=TS,
    key_disagreement="短期情緒分歧",
)

d = dr.to_dict()
check(isinstance(d, dict), 'DebateResult.to_dict() 回傳 dict')
check(no_datetimes(d), 'DebateResult 全樹無 datetime 物件')
check(isinstance(d["report_a"], dict), 'report_a 已序列化為 dict')
check(d["report_a"]["role_name"] == "老徐", 'report_a.role_name 正確')
check(isinstance(d["report_a"]["timestamp"], str), 'report_a.timestamp 為字串')

try:
    json.dumps(d)
    check(True, 'DebateResult JSON 可序列化')
except Exception as e:
    check(False, f'DebateResult JSON 序列化失敗: {e}')

dr2 = DebateResult.from_dict(d)
check(dr2 == dr, 'DebateResult from_dict(to_dict()) 完整還原')
check(isinstance(dr2.report_a, SubReport), 'from_dict 後 report_a 為 SubReport')
check(dr2.key_disagreement == "短期情緒分歧", 'key_disagreement 保留')

# Optional None
dr_no_dis = DebateResult(
    debate_id="IO-01-20260426-002",
    report_a=sr, report_b=sr_b,
    consensus_type="agreed",
    final_direction="neutral",
    final_confidence=0.6,
    combined_reasoning="雙方一致中性",
    timestamp=TS,
)
d_no = dr_no_dis.to_dict()
check(d_no["key_disagreement"] is None, 'key_disagreement=None 正確序列化')
dr_no2 = DebateResult.from_dict(d_no)
check(dr_no2.key_disagreement is None, 'key_disagreement=None 正確還原')
print(f'  欄位數: {len(dataclasses.fields(dr))}  JSON 大小: {json_size(d)} bytes')

# ─── [3] CourseReport ─────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] CourseReport（巢狀 List[DebateResult]）')
print(SECTION)

sr_c = SubReport("婷姐A", "IO-02a", "bullish", 0.8, "宏觀偏多", {}, TS)
sr_d = SubReport("婷姐B", "IO-02b", "bullish", 0.75, "技術面支撐", {}, TS)
dr2_list = [
    dr,
    DebateResult("IO-02-20260426-001", sr_c, sr_d, "agreed",
                 "bullish", 0.77, "雙組皆偏多", TS),
]

cr = CourseReport(
    course_name="市場情報課",
    course_code="IO",
    manager_name="婷姐",
    debate_results=dr2_list,
    course_direction="bullish",
    course_confidence=0.71,
    freshness_grade="recent",
    data_health={"rss": "ok", "onchain": "ok", "fgi": "ok"},
    flash_alerts=["ETH 突破 2400", "BTC 鏈上淨流入創月高"],
    self_review={"completeness": 0.9, "flags": []},
    timestamp=TS,
)

d = cr.to_dict()
check(isinstance(d, dict), 'CourseReport.to_dict() 回傳 dict')
check(no_datetimes(d), 'CourseReport 全樹無 datetime 物件')
check(isinstance(d["debate_results"], list), 'debate_results 序列化為 list')
check(len(d["debate_results"]) == 2, 'debate_results 長度 == 2')
check(isinstance(d["debate_results"][0]["report_a"], dict),
      'debate_results[0].report_a 已序列化')

try:
    json.dumps(d)
    check(True, 'CourseReport JSON 可序列化')
except Exception as e:
    check(False, f'CourseReport JSON 序列化失敗: {e}')

cr2 = CourseReport.from_dict(d)
check(cr2 == cr, 'CourseReport from_dict(to_dict()) 完整還原')
check(len(cr2.debate_results) == 2, 'debate_results 長度保留')
check(isinstance(cr2.debate_results[0], DebateResult), 'from_dict 後 debate_results[0] 為 DebateResult')
check(cr2.debate_results[0].report_a.role_name == "老徐", '深層巢狀 role_name 保留')
print(f'  欄位數: {len(dataclasses.fields(cr))}  JSON 大小: {json_size(d)} bytes')

# ─── [4] SnapshotBundle ───────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] SnapshotBundle（Optional CourseReport）')
print(SECTION)

sb = SnapshotBundle(
    snapshot_id="SNAP-20260426-0830",
    snapshot_time=TS,
    overall_data_quality="good",
    io_report=cr,
    ca_report=None,
    ga_report=None,
    tk_report=None,
)

d = sb.to_dict()
check(isinstance(d, dict), 'SnapshotBundle.to_dict() 回傳 dict')
check(no_datetimes(d), 'SnapshotBundle 全樹無 datetime 物件')
check(d["ca_report"] is None, 'ca_report=None 序列化為 None')
check(isinstance(d["io_report"], dict), 'io_report 序列化為 dict')

try:
    json.dumps(d)
    check(True, 'SnapshotBundle JSON 可序列化')
except Exception as e:
    check(False, f'SnapshotBundle JSON 序列化失敗: {e}')

sb2 = SnapshotBundle.from_dict(d)
check(sb2 == sb, 'SnapshotBundle from_dict(to_dict()) 完整還原')
check(isinstance(sb2.io_report, CourseReport), 'from_dict 後 io_report 為 CourseReport')
check(sb2.ca_report is None, 'ca_report=None 正確還原')
check(sb.timestamp == TS, 'SnapshotBundle.timestamp property 回傳 snapshot_time')
print(f'  欄位數: {len(dataclasses.fields(sb))}  JSON 大小: {json_size(d)} bytes')

# ─── [5] TradingProposal ──────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] TradingProposal')
print(SECTION)

tp = TradingProposal(
    proposal_id="PROP-20260426-001",
    symbol="ETHUSDT",
    direction="long",
    entry_type="limit",
    position_size_usd=80.0,
    stop_loss=2200.0,
    composite_score=0.68,
    direction_confidence=0.71,
    environment_type="trending_bullish",
    selected_strategy="breakout_entry",
    reasoning="IO 課情報偏多，技術面突破確認",
    based_on_snapshot="SNAP-20260426-0830",
    timestamp=TS,
    leverage=1,
    entry_price=2380.0,
    take_profit=2520.0,
)

d = tp.to_dict()
check(isinstance(d, dict), 'TradingProposal.to_dict() 回傳 dict')
check(no_datetimes(d), '無 datetime 物件')
check(d["leverage"] == 1, 'leverage 預設值 1')
check(d["entry_price"] == 2380.0, 'entry_price 正確')

try:
    json.dumps(d)
    check(True, 'TradingProposal JSON 可序列化')
except Exception as e:
    check(False, f'TradingProposal JSON 序列化失敗: {e}')

tp2 = TradingProposal.from_dict(d)
check(tp2 == tp, 'TradingProposal from_dict(to_dict()) 完整還原')

# market order（entry_price=None）
tp_mkt = TradingProposal(
    proposal_id="PROP-20260426-002", symbol="ETHUSDT",
    direction="long", entry_type="market",
    position_size_usd=50.0, stop_loss=2200.0,
    composite_score=0.6, direction_confidence=0.65,
    environment_type="choppy", selected_strategy="pullback",
    reasoning="市價進場", based_on_snapshot="SNAP-20260426-0830",
    timestamp=TS,
)
check(TradingProposal.from_dict(tp_mkt.to_dict()).entry_price is None,
      'entry_price=None 正確還原')
print(f'  欄位數: {len(dataclasses.fields(tp))}  JSON 大小: {json_size(d)} bytes')

# ─── [6] RiskAssessment ───────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] RiskAssessment')
print(SECTION)

ra = RiskAssessment(
    assessment_id="RISK-20260426-001",
    proposal_id="PROP-20260426-001",
    decision="APPROVED",
    reasoning="倉位合規，止損設置合理",
    reverse_analysis_internal="若跌破 2300，止損可能不足",
    reverse_analysis_external="宏觀環境尚穩，外部風險可控",
    timestamp=TS,
)

d = ra.to_dict()
check(isinstance(d, dict), 'RiskAssessment.to_dict() 回傳 dict')
check(no_datetimes(d), '無 datetime 物件')
check(d["modified_position_size"] is None, 'modified_position_size=None')
check(d["rejection_reason"] is None, 'rejection_reason=None')

try:
    json.dumps(d)
    check(True, 'RiskAssessment JSON 可序列化')
except Exception as e:
    check(False, f'RiskAssessment JSON 序列化失敗: {e}')

ra2 = RiskAssessment.from_dict(d)
check(ra2 == ra, 'RiskAssessment from_dict(to_dict()) 完整還原')

# MODIFIED 情境
ra_mod = RiskAssessment(
    assessment_id="RISK-20260426-002",
    proposal_id="PROP-20260426-001",
    decision="MODIFIED",
    reasoning="倉位縮減至安全範圍",
    reverse_analysis_internal="敏敏：下行風險仍存",
    reverse_analysis_external="阿彭：外部流動性充足",
    timestamp=TS,
    modified_position_size=50.0,
    modified_stop_loss=2250.0,
)
ra_mod2 = RiskAssessment.from_dict(ra_mod.to_dict())
check(ra_mod2.modified_position_size == 50.0, 'MODIFIED: modified_position_size 還原')
check(ra_mod2.modified_stop_loss == 2250.0, 'MODIFIED: modified_stop_loss 還原')
print(f'  欄位數: {len(dataclasses.fields(ra))}  JSON 大小: {json_size(d)} bytes')

# ─── [7] ArbiterDecision ──────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [7] ArbiterDecision')
print(SECTION)

ad = ArbiterDecision(
    decision_id="ARB-20260426-001",
    proposal_id="PROP-20260426-001",
    assessment_id="RISK-20260426-001",
    final_decision="EXECUTE",
    tempo_factor=0.85,
    tendency_coefficient=0.72,
    reasoning="多頭動能確認，節奏適合入場",
    timestamp=TS,
)

d = ad.to_dict()
check(isinstance(d, dict), 'ArbiterDecision.to_dict() 回傳 dict')
check(no_datetimes(d), '無 datetime 物件')

try:
    json.dumps(d)
    check(True, 'ArbiterDecision JSON 可序列化')
except Exception as e:
    check(False, f'ArbiterDecision JSON 序列化失敗: {e}')

ad2 = ArbiterDecision.from_dict(d)
check(ad2 == ad, 'ArbiterDecision from_dict(to_dict()) 完整還原')
check(ad2.tempo_factor == 0.85, 'tempo_factor 精度保留')
print(f'  欄位數: {len(dataclasses.fields(ad))}  JSON 大小: {json_size(d)} bytes')

# ─── [8] ExecutionResult ──────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [8] ExecutionResult')
print(SECTION)

er = ExecutionResult(
    execution_id="EXEC-20260426-001",
    decision_id="ARB-20260426-001",
    status="FILLED",
    timestamp=TS2,
    executed_price=2381.5,
    executed_size=0.0336,
    actual_slippage_pct=0.063,
    exchange_order_id="bybit-ord-123456",
)

d = er.to_dict()
check(isinstance(d, dict), 'ExecutionResult.to_dict() 回傳 dict')
check(no_datetimes(d), '無 datetime 物件')
check(d["error_message"] is None, 'error_message=None 正確')

try:
    json.dumps(d)
    check(True, 'ExecutionResult JSON 可序列化')
except Exception as e:
    check(False, f'ExecutionResult JSON 序列化失敗: {e}')

er2 = ExecutionResult.from_dict(d)
check(er2 == er, 'ExecutionResult from_dict(to_dict()) 完整還原')
check(er2.executed_price == 2381.5, 'executed_price 精度保留')

# FAILED 情境（全 Optional 為 None）
er_fail = ExecutionResult(
    execution_id="EXEC-20260426-002",
    decision_id="ARB-20260426-001",
    status="FAILED",
    timestamp=TS2,
    error_message="網路逾時，下單失敗",
)
er_fail2 = ExecutionResult.from_dict(er_fail.to_dict())
check(er_fail2.executed_price is None, 'FAILED: executed_price=None 還原')
check(er_fail2.error_message == "網路逾時，下單失敗", 'FAILED: error_message 還原')
print(f'  欄位數: {len(dataclasses.fields(er))}  JSON 大小: {json_size(d)} bytes')

# ─── [9] AnomalyEvent ─────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [9] AnomalyEvent')
print(SECTION)

ae = AnomalyEvent(
    event_id="ANOM-20260426-001",
    event_type="FLASH_MOVE",
    symbol="ETHUSDT",
    magnitude=4.2,
    severity=0.85,
    timestamp=TS,
    triggered_alert=True,
    direction="up",
)

d = ae.to_dict()
check(isinstance(d, dict), 'AnomalyEvent.to_dict() 回傳 dict')
check(no_datetimes(d), '無 datetime 物件')
check(d["direction"] == "up", 'direction 正確')

try:
    json.dumps(d)
    check(True, 'AnomalyEvent JSON 可序列化')
except Exception as e:
    check(False, f'AnomalyEvent JSON 序列化失敗: {e}')

ae2 = AnomalyEvent.from_dict(d)
check(ae2 == ae, 'AnomalyEvent from_dict(to_dict()) 完整還原')
check(ae2.triggered_alert == True, 'triggered_alert 保留')

ae_no_dir = AnomalyEvent(
    event_id="ANOM-20260426-002", event_type="VOLUME_SPIKE",
    symbol="BTCUSDT", magnitude=3.5, severity=0.7,
    timestamp=TS, triggered_alert=False,
)
check(AnomalyEvent.from_dict(ae_no_dir.to_dict()).direction is None,
      'direction=None 正確還原')
print(f'  欄位數: {len(dataclasses.fields(ae))}  JSON 大小: {json_size(d)} bytes')

# ─── [10] NewsEvent ───────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [10] NewsEvent')
print(SECTION)

ne = NewsEvent(
    event_id="NEWS-20260426-001",
    event_type="GEOPOLITICAL.sanctions",
    headline="US Treasury imposes new crypto sanctions",
    summary="新制裁令針對加密混幣器服務，短期利空",
    source_count=5,
    cross_validated=True,
    vader_sentiment=-0.62,
    vader_confidence=0.78,
    entities=["US Treasury", "OFAC", "Tornado Cash"],
    first_seen=TS,
    latest_update=TS2,
    secondary_type="REGULATORY",
    is_key_figure_statement=False,
)

d = ne.to_dict()
check(isinstance(d, dict), 'NewsEvent.to_dict() 回傳 dict')
check(no_datetimes(d), '無 datetime 物件')
check(isinstance(d["first_seen"], str), 'first_seen 序列化為字串')
check(isinstance(d["latest_update"], str), 'latest_update 序列化為字串')
check(d["figure_name"] is None, 'figure_name=None 正確')
check(isinstance(d["entities"], list) and len(d["entities"]) == 3, 'entities list 保留')

try:
    json.dumps(d)
    check(True, 'NewsEvent JSON 可序列化')
except Exception as e:
    check(False, f'NewsEvent JSON 序列化失敗: {e}')

ne2 = NewsEvent.from_dict(d)
check(ne2 == ne, 'NewsEvent from_dict(to_dict()) 完整還原')
check(ne2.entities == ["US Treasury", "OFAC", "Tornado Cash"], 'entities 保留')
check(ne.timestamp == TS, 'NewsEvent.timestamp property 回傳 first_seen')

ne_fig = NewsEvent(
    event_id="NEWS-20260426-002",
    event_type="REGULATORY",
    headline="SEC Chair signals ETF review",
    summary="SEC 主席表態重新審視現貨 ETF 申請",
    source_count=3, cross_validated=True,
    vader_sentiment=0.45, vader_confidence=0.7,
    entities=["SEC", "BlackRock"],
    first_seen=TS, latest_update=TS,
    is_key_figure_statement=True,
    figure_name="SEC Chair",
)
ne_fig2 = NewsEvent.from_dict(ne_fig.to_dict())
check(ne_fig2.is_key_figure_statement == True, 'is_key_figure_statement=True 還原')
check(ne_fig2.figure_name == "SEC Chair", 'figure_name 還原')
print(f'  欄位數: {len(dataclasses.fields(ne))}  JSON 大小: {json_size(d)} bytes')

# ─── 總結 ─────────────────────────────────────────────────────────────────────

total = passed + failed
print(f'\n{SECTION}')
print('  總結')
print(SECTION)

models = [
    ("SubReport",       sr),
    ("DebateResult",    dr),
    ("CourseReport",    cr),
    ("SnapshotBundle",  sb),
    ("TradingProposal", tp),
    ("RiskAssessment",  ra),
    ("ArbiterDecision", ad),
    ("ExecutionResult", er),
    ("AnomalyEvent",    ae),
    ("NewsEvent",       ne),
]
print(f'  {"Model":<20s}  {"欄位數":>4s}  {"JSON(bytes)":>10s}')
print(f'  {"-"*20}  {"-"*4}  {"-"*10}')
for name, obj in models:
    fc = len(dataclasses.fields(obj))
    sz = json_size(obj.to_dict())
    print(f'  {name:<20s}  {fc:>4d}  {sz:>10d}')

print(f'\n  測試結果      : {passed} / {total} 通過')
if failed == 0:
    print('  [全部通過]')
else:
    print(f'  [注意] {failed} 個測試失敗')
print(SECTION)
