# -*- coding: utf-8 -*-
import sys
import io
import os
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.common.feedback_models import SelfReview, ReviewBatch
from trading_system.common.kpi_models import (
    KPIDefinition, KPIRecord, PerformanceGrade,
    compute_performance_grade, GRADE_SYSTEM_IMPACT, GRADE_THRESHOLDS,
)
from trading_system.common.snapshot_builder import (
    get_snapshot_builder, reset_snapshot_builder, SnapshotBuilder,
)
from trading_system.common.data_models import (
    CourseReport, DebateResult, SubReport,
)
from trading_system.common.message_bus import get_bus, reset_bus

SECTION = '=' * 65
passed = 0
failed = 0
NOW = datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc)


def check(condition: bool, msg: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f'  [PASS] {msg}')
    else:
        failed += 1
        print(f'  [FAIL] {msg}')


# ─── 共用 helper ──────────────────────────────────────────────────────────────

def _make_sub(name, code, ts=NOW) -> SubReport:
    return SubReport(
        role_name=name, role_code=code,
        direction="bullish", sub_confidence=0.7,
        reasoning="測試", data_used={}, timestamp=ts,
    )


def _make_debate(code, ts=NOW) -> DebateResult:
    return DebateResult(
        debate_id=f"{code}-DEB",
        report_a=_make_sub(f"{code}a", f"{code}a"),
        report_b=_make_sub(f"{code}b", f"{code}b"),
        consensus_type="agreed",
        final_direction="bullish",
        final_confidence=0.7,
        combined_reasoning="測試",
        timestamp=ts,
    )


def _make_course(code: str, manager: str, ts: datetime = NOW) -> CourseReport:
    return CourseReport(
        course_name=f"{code} 課",
        course_code=code,
        manager_name=manager,
        debate_results=[_make_debate(code, ts)],
        course_direction="bullish",
        course_confidence=0.7,
        freshness_grade="real_time",
        data_health={"status": "ok"},
        flash_alerts=[],
        self_review={"completeness": 0.9},
        timestamp=ts,
    )


# ─── [1] SelfReview 基本建立 ──────────────────────────────────────────────────

print(SECTION)
print('  [1] SelfReview 基本建立')
print(SECTION)

sr = SelfReview(
    role_name="老徐",
    role_code="IO-01a",
    work_type="資金流分析",
    timestamp=NOW,
    my_call="看多，ETH 淨流入持續",
    confidence_at_time=0.72,
    reasoning="鏈上資料顯示大戶持續買入",
    data_used={"etherscan": True, "onchain_vol": 1200},
)

check(isinstance(sr.review_id, str) and len(sr.review_id) == 36, 'review_id 自動產生 UUID')
check(sr.is_verified() == False, '初始 is_verified() == False')
check(sr.hindsight_correct is None, 'hindsight_correct 初始為 None')
check(sr.hindsight_verifier is None, 'hindsight_verifier 初始為 None')

# ─── [2] SelfReview 驗證方法 ──────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] SelfReview 驗證方法')
print(SECTION)

sr.mark_correct("華華", "方向正確，ETH 24h +3.2%")
check(sr.hindsight_correct == "correct", 'mark_correct → hindsight_correct == correct')
check(sr.is_verified() == True, 'mark_correct 後 is_verified() == True')
check(sr.hindsight_verifier == "華華", 'hindsight_verifier == 華華')
check(sr.hindsight_notes == "方向正確，ETH 24h +3.2%", 'hindsight_notes 正確')
check(isinstance(sr.hindsight_verified_at, datetime), 'hindsight_verified_at 為 datetime')

sr2 = SelfReview(
    role_name="小曾", role_code="IO-01b", work_type="情緒分析",
    timestamp=NOW, my_call="中性", confidence_at_time=0.55,
    reasoning="RSS 情緒混合", data_used={},
)
sr2.mark_incorrect("阿銘", "市場實際強勢反彈")
check(sr2.hindsight_correct == "incorrect", 'mark_incorrect 正確')
check(sr2.is_verified() == True, 'mark_incorrect 後 is_verified() == True')

sr3 = SelfReview(
    role_name="老蘇", role_code="IO-02a", work_type="宏觀分析",
    timestamp=NOW, my_call="偏多但幅度有限", confidence_at_time=0.6,
    reasoning="Fed 暗示暫緩升息", data_used={},
)
sr3.mark_partial("華華", "方向正確但幅度低估")
check(sr3.hindsight_correct == "partial_correct", 'mark_partial 正確')

# ─── [3] SelfReview to_dict / from_dict ──────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] SelfReview 序列化')
print(SECTION)

d = sr.to_dict()
check(isinstance(d, dict), 'to_dict() 回傳 dict')
check(isinstance(d["timestamp"], str), 'timestamp 序列化為字串')
check(isinstance(d["hindsight_verified_at"], str), 'hindsight_verified_at 序列化為字串')

try:
    json.dumps(d)
    check(True, 'JSON 可序列化')
except Exception as e:
    check(False, f'JSON 序列化失敗: {e}')

sr_rt = SelfReview.from_dict(d)
check(sr_rt.role_name == "老徐", 'from_dict role_name 正確')
check(sr_rt.hindsight_correct == "correct", 'from_dict hindsight_correct 正確')
check(isinstance(sr_rt.hindsight_verified_at, datetime), 'from_dict hindsight_verified_at 為 datetime')
check(sr_rt.review_id == sr.review_id, 'from_dict review_id 保留')
check(sr_rt.is_verified() == True, 'from_dict 後 is_verified() == True')

# 未驗證的 review
sr_unv = SelfReview(
    role_name="測試員", role_code="TEST", work_type="test",
    timestamp=NOW, my_call="不知道", confidence_at_time=0.5,
    reasoning="隨機", data_used={},
)
d_unv = sr_unv.to_dict()
check(d_unv["hindsight_verified_at"] is None, '未驗證 hindsight_verified_at 為 None')
sr_unv2 = SelfReview.from_dict(d_unv)
check(sr_unv2.hindsight_verified_at is None, 'from_dict 後 None 保留')
check(sr_unv2.is_verified() == False, 'from_dict 後 is_verified() == False')

# ─── [4] ReviewBatch ──────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] ReviewBatch')
print(SECTION)

sr_a = SelfReview("老徐", "IO-01a", "資金流", NOW, "看多", 0.7, "鏈上多", {})
sr_b = SelfReview("老徐", "IO-01a", "宏觀", NOW, "看多", 0.65, "Fed偏鴿", {})
sr_c = SelfReview("小曾", "IO-01b", "情緒", NOW, "中性", 0.5, "RSS混合", {})
sr_d = SelfReview("婷姐", "IO-02a", "匯總", NOW, "看多", 0.75, "IO整體偏多", {})

sr_a.mark_correct("華華", "")
sr_b.mark_partial("阿銘", "部分正確")
sr_c.mark_incorrect("華華", "實際偏多")
# sr_d 未驗證

batch = ReviewBatch(
    batch_id="BATCH-IO-20260426",
    course_code="IO",
    period_start=NOW,
    period_end=NOW + timedelta(hours=8),
    reviews=[sr_a, sr_b, sr_c, sr_d],
)

徐_reviews = batch.get_by_role("老徐")
check(len(徐_reviews) == 2, 'get_by_role("老徐") 找到 2 筆')
check(all(r.role_name == "老徐" for r in 徐_reviews), 'get_by_role 結果全部為老徐')

unverified = batch.get_unverified()
check(len(unverified) == 1, 'get_unverified() 找到 1 筆')
check(unverified[0].role_name == "婷姐", '未驗證的是婷姐')

# accuracy: sr_a=correct(1.0), sr_b=partial(0.5), sr_c=incorrect(0.0) → 1.5/3 = 0.5
acc = batch.calculate_accuracy()
check(abs(acc - 0.5) < 1e-6, f'calculate_accuracy() == 0.5（實際: {acc}）')

# to_dict / from_dict
d = batch.to_dict()
check(isinstance(d["reviews"], list), 'batch.to_dict() reviews 為 list')
try:
    json.dumps(d)
    check(True, 'ReviewBatch JSON 可序列化')
except Exception as e:
    check(False, f'ReviewBatch JSON 序列化失敗: {e}')

batch2 = ReviewBatch.from_dict(d)
check(len(batch2.reviews) == 4, 'from_dict 後 reviews 長度保留')
check(batch2.calculate_accuracy() == acc, 'from_dict 後 calculate_accuracy 結果一致')
check(batch2.get_unverified()[0].role_name == "婷姐", 'from_dict 後 get_unverified 結果一致')

# ─── [5] KPIDefinition ────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] KPIDefinition')
print(SECTION)

kpi_def = KPIDefinition(
    kpi_id="KPI-IO01a-01",
    role_name="老徐",
    kpi_name="資金流偵測準確率",
    target_value=0.70,
    target_direction="greater_than",
    measurement_period="weekly",
    description="每週資金流方向判斷正確率 ≥ 70%",
)

check(kpi_def.check_achieved(0.75) == True,  'actual=0.75 ≥ 0.70 → achieved')
check(kpi_def.check_achieved(0.70) == True,  'actual=0.70 ≥ 0.70 → achieved（含等於）')
check(kpi_def.check_achieved(0.65) == False, 'actual=0.65 < 0.70 → not achieved')

kpi_lt = KPIDefinition(
    kpi_id="KPI-EX-01", role_name="阿成",
    kpi_name="滑點率", target_value=0.10,
    target_direction="less_than", measurement_period="weekly",
    description="滑點率 ≤ 0.10%",
)
check(kpi_lt.check_achieved(0.08) == True,  'less_than: 0.08 ≤ 0.10 → achieved')
check(kpi_lt.check_achieved(0.12) == False, 'less_than: 0.12 > 0.10 → not achieved')

d = kpi_def.to_dict()
kpi_def2 = KPIDefinition.from_dict(d)
check(kpi_def2.kpi_name == "資金流偵測準確率", 'KPIDefinition round-trip kpi_name')
check(kpi_def2.target_value == 0.70, 'KPIDefinition round-trip target_value')

# ─── [6] KPIRecord ────────────────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] KPIRecord')
print(SECTION)

rec_ok = KPIRecord(
    record_id="REC-IO01a-W17",
    kpi_id="KPI-IO01a-01",
    role_name="老徐",
    period="2026-W17",
    actual_value=0.78,
    target_value=0.70,
    achieved=True,
    timestamp=NOW,
    notes="本週 7/9 正確，表現良好",
)
rec_fail = KPIRecord(
    record_id="REC-IO01a-W16",
    kpi_id="KPI-IO01a-01",
    role_name="老徐",
    period="2026-W16",
    actual_value=0.62,
    target_value=0.70,
    achieved=False,
    timestamp=NOW,
    notes="受假訊息干擾，準確率偏低",
)

check(rec_ok.achieved == True, 'rec_ok.achieved == True')
check(rec_fail.achieved == False, 'rec_fail.achieved == False')

d = rec_ok.to_dict()
check(isinstance(d["timestamp"], str), 'KPIRecord timestamp 序列化為字串')
rec_ok2 = KPIRecord.from_dict(d)
check(rec_ok2.actual_value == 0.78, 'KPIRecord round-trip actual_value')
check(isinstance(rec_ok2.timestamp, datetime), 'from_dict timestamp 為 datetime')
check(rec_ok2.achieved == True, 'from_dict achieved 保留')

# ─── [7] compute_performance_grade / PerformanceGrade ────────────────────────

print(f'\n{SECTION}')
print('  [7] compute_performance_grade 與評級規則')
print(SECTION)

# 全 KPI 達標 + hindsight 高 → S
recs_s = [KPIRecord(f"R{i}", "K1", "老徐", "2026-W17", 0.8, 0.7, True, NOW, "") for i in range(5)]
pg_s = compute_performance_grade("PG-S", "老徐", "2026-W17", recs_s, 0.80)
check(pg_s.grade == "S", f'全達標 + hindsight=0.80 → S（實際: {pg_s.grade}）')
check(pg_s.kpi_achievement_rate == 1.0, 'kpi_achievement_rate == 1.0')
check(pg_s.system_impact["weight_multiplier"] == 1.2, 'S 等級 weight_multiplier == 1.2')

# 多數達標 → A
recs_a = (
    [KPIRecord(f"R{i}", "K1", "老徐", "W17", 0.8, 0.7, True, NOW, "") for i in range(5)] +  # 5 passed
    [KPIRecord(f"R{i+5}", "K1", "老徐", "W17", 0.6, 0.7, False, NOW, "") for i in range(1)]  # 1 failed
)  # 5/6 = 0.833...
pg_a = compute_performance_grade("PG-A", "老蘇", "2026-W17", recs_a, 0.72)
# score = 0.8333 * 70 + 0.72 * 30 = 58.33 + 21.6 = 79.93 → C? Hmm
# Hmm, that's not A. Let me check...
# Actually: 5/6 = 0.8333, hindsight=0.72
# score = 0.8333*70 + 0.72*30 = 58.33+21.6 = 79.93 → score < 80 → NOT A → B?
# B check: score>=70 ✓, rate>=0.5 ✓, hindsight>0.55 ✓ → B
# Hmm. Let me use values that clearly reach A grade.
print(f'  A 預備測試: score={pg_a.overall_score}, grade={pg_a.grade}')

# Clear A: 6/6 achieved but hindsight=0.72 → score=70+21.6=91.6 → S (hindsight<0.75?)
# No: 6/6=1.0, hindsight=0.72 → S check: hindsight>0.75? 0.72 > 0.75? No → not S
# A check: score=91.6>=80 ✓, rate=1.0>=0.7 ✓, hindsight=0.72>0.65 ✓ → A ✓
recs_a2 = [KPIRecord(f"RA{i}", "K1", "老王", "W17", 0.8, 0.7, True, NOW, "") for i in range(6)]
pg_a2 = compute_performance_grade("PG-A2", "老王", "2026-W17", recs_a2, 0.72)
check(pg_a2.grade == "A",
      f'kpi=1.0, hindsight=0.72(>0.65, not>0.75) → A（實際: {pg_a2.grade}, score={pg_a2.overall_score}）')
check(pg_a2.system_impact["weight_multiplier"] == 1.1, 'A 等級 weight_multiplier == 1.1')

# B: kpi 達標 5/7 ≈ 0.714, hindsight=0.6 → score=0.714*70+0.6*30=49.98+18=67.98 → C
# Need score ≥ 70. Let me try kpi=4/5=0.8, hindsight=0.6 → 56+18=74 → B
recs_b = (
    [KPIRecord(f"RB{i}", "K1", "婷姐", "W17", 0.8, 0.7, True, NOW, "") for i in range(4)] +
    [KPIRecord(f"RB{i+4}", "K1", "婷姐", "W17", 0.6, 0.7, False, NOW, "") for i in range(1)]
)  # 4/5=0.8
pg_b = compute_performance_grade("PG-B", "婷姐", "2026-W17", recs_b, 0.60)
check(pg_b.grade == "B",
      f'kpi=0.8, hindsight=0.6(>0.55,not>0.65) → B（實際: {pg_b.grade}, score={pg_b.overall_score}）')
check(pg_b.system_impact["weight_multiplier"] == 1.0, 'B 等級 weight_multiplier == 1.0')

# C: score 60~69, fails B conditions
recs_c = (
    [KPIRecord(f"RC{i}", "K1", "小孫", "W17", 0.8, 0.7, True, NOW, "") for i in range(3)] +
    [KPIRecord(f"RC{i+3}", "K1", "小孫", "W17", 0.5, 0.7, False, NOW, "") for i in range(1)]
)  # 3/4=0.75 kpi, hindsight=0.5 (not > 0.55) → B fails → C
pg_c = compute_performance_grade("PG-C", "小孫", "2026-W17", recs_c, 0.50)
check(pg_c.grade == "C",
      f'kpi=0.75, hindsight=0.5(≤0.55) → C（實際: {pg_c.grade}, score={pg_c.overall_score}）')
check(pg_c.system_impact["weight_multiplier"] == 0.8, 'C 等級 weight_multiplier == 0.8')

# D: score < 60
recs_d = [KPIRecord(f"RD{i}", "K1", "阿成", "W17", 0.5, 0.7, False, NOW, "") for i in range(5)]
pg_d = compute_performance_grade("PG-D", "阿成", "2026-W17", recs_d, 0.20)
check(pg_d.grade == "D",
      f'kpi=0, hindsight=0.2 → D（實際: {pg_d.grade}, score={pg_d.overall_score}）')
check(pg_d.system_impact["weight_multiplier"] == 0.5, 'D 等級 weight_multiplier == 0.5')

# PerformanceGrade to_dict / from_dict
d = pg_s.to_dict()
try:
    json.dumps(d)
    check(True, 'PerformanceGrade JSON 可序列化')
except Exception as e:
    check(False, f'PerformanceGrade JSON 序列化失敗: {e}')
pg_s2 = PerformanceGrade.from_dict(d)
check(pg_s2.grade == "S", 'PerformanceGrade round-trip grade 正確')
check(len(pg_s2.kpi_records) == 5, 'PerformanceGrade round-trip kpi_records 長度')
check(pg_s2.system_impact["weight_multiplier"] == 1.2, 'PerformanceGrade round-trip system_impact')

# ─── [8] SnapshotBuilder 基本功能 ─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [8] SnapshotBuilder — 基本功能')
print(SECTION)

# 重設 bus 和 snapshot builder
reset_snapshot_builder()
reset_bus()
bus = get_bus()
builder = get_snapshot_builder()

# 確認 builder 已訂閱所有 report channels
for ch in ("report.io", "report.ca", "report.ga", "report.tk"):
    check("SnapshotBuilder" in bus.get_subscribers(ch),
          f'SnapshotBuilder 已訂閱 {ch}')

# 發送 4 份課級報告
io_r = _make_course("IO", "婷姐")
ca_r = _make_course("CA", "琳姐")
ga_r = _make_course("GA", "小孫")
tk_r = _make_course("TK", "老廖")

bus.publish("report.io", io_r, "婷姐")
bus.publish("report.ca", ca_r, "琳姐")
bus.publish("report.ga", ga_r, "小孫")
bus.publish("report.tk", tk_r, "老廖")

check(len(builder._latest) == 4, f'快取中有 4 份報告（實際: {len(builder._latest)}）')
check("IO" in builder._latest, 'IO 報告已快取')
check("GA" in builder._latest, 'GA 報告已快取')

# build_snapshot：4 份都在
snap = builder.build_snapshot()
check(snap.io_report is not None, 'SnapshotBundle.io_report 不為 None')
check(snap.ca_report is not None, 'SnapshotBundle.ca_report 不為 None')
check(snap.ga_report is not None, 'SnapshotBundle.ga_report 不為 None')
check(snap.tk_report is not None, 'SnapshotBundle.tk_report 不為 None')
check(snap.snapshot_id.startswith("SNAP-"), 'snapshot_id 格式正確')

# ─── [9] SnapshotBuilder freshness 計算 ───────────────────────────────────────

print(f'\n{SECTION}')
print('  [9] SnapshotBuilder — freshness 計算')
print(SECTION)

sb = SnapshotBuilder  # 使用靜態方法

now = datetime.now(timezone.utc)
check(sb.get_freshness_grade(now - timedelta(seconds=30),  now) == "real_time",
      '30 秒前 → real_time')
check(sb.get_freshness_grade(now - timedelta(minutes=5),   now) == "recent",
      '5 分鐘前 → recent')
check(sb.get_freshness_grade(now - timedelta(minutes=30),  now) == "delayed",
      '30 分鐘前 → delayed')
check(sb.get_freshness_grade(now - timedelta(minutes=90),  now) == "stale",
      '90 分鐘前 → stale')
check(sb.get_freshness_grade(now - timedelta(seconds=59),  now) == "real_time",
      '59 秒前 → real_time（邊界）')
check(sb.get_freshness_grade(now - timedelta(seconds=60),  now) == "recent",
      '60 秒前 → recent（邊界）')
check(sb.get_freshness_grade(now - timedelta(seconds=899), now) == "recent",
      '899 秒前 → recent（upper 邊界 -1s）')
check(sb.get_freshness_grade(now - timedelta(minutes=15), now) == "delayed",
      '15 分鐘（900 秒）前 → delayed（恰好在邊界，< 900 為 False）')

# 模擬 30 分鐘前的報告
old_ts = now - timedelta(minutes=30)
builder._latest["IO"] = _make_course("IO", "婷姐", old_ts)
snap2 = builder.build_snapshot()
check(snap2.io_report.freshness_grade == "delayed",
      '30 分鐘前的 IO 報告 → freshness_grade == delayed')
check(snap2.ca_report.freshness_grade == "real_time",
      '剛發送的 CA 報告 → freshness_grade == real_time')

# Naive datetime 也能正確處理
naive_ts = now.replace(tzinfo=None) - timedelta(minutes=30)
grade = SnapshotBuilder.get_freshness_grade(naive_ts, now)
check(grade == "delayed", 'naive datetime 也能正確計算 freshness_grade')

# ─── [10] SnapshotBuilder overall_data_quality ────────────────────────────────

print(f'\n{SECTION}')
print('  [10] SnapshotBuilder — overall_data_quality')
print(SECTION)

# good：全部 real_time/recent
r_good = [_make_course(c, "mgr") for c in ("IO", "CA", "GA", "TK")]
for r in r_good:
    r.freshness_grade = "real_time"
check(SnapshotBuilder.get_overall_quality(r_good) == "good",
      '全部 real_time → good')

r_recent = [_make_course(c, "mgr") for c in ("IO", "CA", "GA", "TK")]
for r in r_recent:
    r.freshness_grade = "recent"
check(SnapshotBuilder.get_overall_quality(r_recent) == "good",
      '全部 recent → good')

# acceptable：剛好 1 份 delayed
r_acc = [_make_course(c, "mgr") for c in ("IO", "CA", "GA", "TK")]
for r in r_acc:
    r.freshness_grade = "recent"
r_acc[0].freshness_grade = "delayed"
check(SnapshotBuilder.get_overall_quality(r_acc) == "acceptable",
      '1 份 delayed → acceptable')

# degraded：2 份 delayed
r_2d = [_make_course(c, "mgr") for c in ("IO", "CA", "GA", "TK")]
for r in r_2d:
    r.freshness_grade = "recent"
r_2d[0].freshness_grade = "delayed"
r_2d[1].freshness_grade = "delayed"
check(SnapshotBuilder.get_overall_quality(r_2d) == "degraded",
      '2 份 delayed → degraded')

# degraded：有 stale
r_stale = [_make_course(c, "mgr") for c in ("IO", "CA", "GA", "TK")]
for r in r_stale:
    r.freshness_grade = "recent"
r_stale[2].freshness_grade = "stale"
check(SnapshotBuilder.get_overall_quality(r_stale) == "degraded",
      '1 份 stale → degraded')

# degraded：缺報告
r_miss = [_make_course(c, "mgr") for c in ("IO", "CA", "GA")]
r_miss_with_none = r_miss + [None]
check(SnapshotBuilder.get_overall_quality(r_miss_with_none) == "degraded",
      '缺 1 份報告 → degraded')

# 驗證 build_snapshot 中的 overall_data_quality（IO 是 30min 前，其他 real_time）
check(snap2.overall_data_quality == "acceptable",
      'IO delayed + 其他 real_time → overall_data_quality == acceptable')

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
