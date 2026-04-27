# -*- coding: utf-8 -*-
import sys
import io
import os
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from trading_system.squads.crypto.execution.order_section_manager import OrderSectionManager
from trading_system.squads.crypto.execution.ex_01_normal_order import NormalOrderExecutor
from trading_system.squads.crypto.execution.ex_02_emergency import EmergencyExecutor
from trading_system.squads.crypto.execution.ex_03_connection import ConnectionMaintainer
from trading_system.common.data_models import (
    ArbiterDecision, ExecutionResult, TradingProposal,
)
from trading_system.common.feedback_models import SelfReview
from trading_system.common.flash_alert import reset_flash_state
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


# ─── 工廠函式 ─────────────────────────────────────────────────────────────────

def make_gateway(price: float = 3500.0):
    gw = MagicMock()
    gw.get_market_kline.return_value = {
        "success": True,
        "data": {"list": [["ts", "o", "h", "l", str(price), "vol"]]},
        "elapsed_ms": 20, "error": "",
    }
    gw.get_server_time.return_value = {
        "success": True,
        "data": {"timeSecond": str(int(time.time()))},
        "elapsed_ms": 15, "error": "",
    }
    gw.get_positions.return_value = {
        "success": True, "data": {"list": []}, "elapsed_ms": 20, "error": "",
    }
    return gw


def make_execution_result(
    status: str = "FILLED",
    slippage_pct: float = 0.0,
    error_msg: str = None,
) -> ExecutionResult:
    return ExecutionResult(
        execution_id=str(uuid.uuid4()),
        decision_id=str(uuid.uuid4()),
        status=status,
        timestamp=datetime.now(timezone.utc),
        executed_price=3500.0 if status == "FILLED" else None,
        executed_size=50.0 if status == "FILLED" else None,
        actual_slippage_pct=slippage_pct if status == "FILLED" else None,
        exchange_order_id="DRY-RUN-ORDER" if status == "FILLED" else None,
        error_message=error_msg,
    )


def make_arbiter_decision(final_decision: str = "EXECUTE") -> ArbiterDecision:
    return ArbiterDecision(
        decision_id=str(uuid.uuid4()),
        proposal_id=str(uuid.uuid4()),
        assessment_id=str(uuid.uuid4()),
        final_decision=final_decision,
        tempo_factor=1.0,
        tendency_coefficient=0.8,
        reasoning="測試",
        timestamp=datetime.now(timezone.utc),
    )


def make_proposal(symbol: str = "ETHUSDT") -> TradingProposal:
    return TradingProposal(
        proposal_id=str(uuid.uuid4()),
        symbol=symbol,
        direction="long",
        entry_type="market",
        position_size_usd=50.0,
        stop_loss=3400.0,
        composite_score=75.0,
        direction_confidence=0.75,
        environment_type="trending",
        selected_strategy="trend_following",
        reasoning="測試",
        based_on_snapshot=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
    )


def make_team(price: float = 3500.0):
    """建立完整的四人組（芬姐 + 小慧 + 阿成 + 宏哥）。"""
    gw   = make_gateway(price)
    ex03 = ConnectionMaintainer(gateway=gw)
    ex01 = NormalOrderExecutor(ex03_connection=ex03, target_symbols=["ETHUSDT"])
    ex02 = EmergencyExecutor(ex03_connection=ex03)
    ex01.gateway = gw
    ex02.gateway = gw
    mgr  = OrderSectionManager(ex01=ex01, ex02=ex02, ex03=ex03)
    return mgr, ex01, ex02, ex03


def reset():
    reset_flash_state()
    get_bus().clear()


# ─── [1] 初始化與屬性 ─────────────────────────────────────────────────────────

print(SECTION)
print('  [1] 初始化與屬性')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

check(mgr.ex01 is ex01,  '宏哥持有 ex01 引用')
check(mgr.ex02 is ex02,  '宏哥持有 ex02 引用')
check(mgr.ex03 is ex03,  '宏哥持有 ex03 引用')
check(mgr.section_stats["execution_results_observed"] == 0, 'observed 初始 0')
check(mgr.section_stats["successful_executions"]    == 0,   'successful 初始 0')
check(mgr.section_stats["failed_executions"]        == 0,   'failed 初始 0')
check(len(mgr.recent_results) == 0,                          'recent_results 初始空')

# ─── [2] get_section_status 結構完整 ─────────────────────────────────────────

print(f'\n{SECTION}')
print('  [2] get_section_status 回傳結構')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

status = mgr.get_section_status()
print(f'  overall_health: {status["overall_health"]}')

check("manager"           in status, '有 manager 欄位')
check("section_stats"     in status, '有 section_stats 欄位')
check("connection_health" in status, '有 connection_health 欄位')
check("normal_executor"   in status, '有 normal_executor 欄位')
check("emergency_executor" in status, '有 emergency_executor 欄位')
check("overall_health"    in status, '有 overall_health 欄位')
check(status["manager"] == "宏哥",   'manager == 宏哥')
check(isinstance(status["connection_health"], dict), 'connection_health 為 dict')
check("flash_crash_mode" in status["emergency_executor"],
      'emergency_executor 有 flash_crash_mode')
check(status["overall_health"] in ("healthy", "degraded", "critical"),
      f'overall_health 值合法（實際: {status["overall_health"]}）')

# ─── [3] 觀察執行結果（成功）─────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [3] 觀察執行結果（FILLED）')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

result_ok = make_execution_result("FILLED", slippage_pct=0.001)
get_bus().publish("execution.result", payload=result_ok, sender="EX-01")

check(mgr.section_stats["execution_results_observed"] == 1,
      'observed == 1')
check(mgr.section_stats["successful_executions"] == 1,
      'successful_executions == 1')
check(mgr.section_stats["failed_executions"] == 0,
      'failed_executions == 0')
check(len(mgr.recent_results) == 1, 'recent_results 有 1 筆')

# ─── [4] 觀察執行結果（失敗）─────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [4] 觀察執行結果（FAILED）')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

result_fail = make_execution_result("FAILED", error_msg="倉位超限")
get_bus().publish("execution.result", payload=result_fail, sender="EX-01")

check(mgr.section_stats["execution_results_observed"] == 1,
      'observed == 1')
check(mgr.section_stats["failed_executions"] == 1,
      'failed_executions == 1')
check(mgr.section_stats["successful_executions"] == 0,
      'successful_executions == 0')

# ─── [5] 平均滑價計算（移動平均）─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [5] 平均滑價計算（3 筆：5/10/15 bps）')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

# actual_slippage_pct = bps/100（EX-01 設計）：5bps=0.05, 10bps=0.10, 15bps=0.15
for pct in [0.05, 0.10, 0.15]:
    r = make_execution_result("FILLED", slippage_pct=pct)
    get_bus().publish("execution.result", payload=r, sender="EX-01")

avg = mgr.section_stats["average_slippage_bps"]
print(f'  average_slippage_bps = {avg}')
check(abs(avg - 10.0) < 0.01, f'平均滑價 = 10 bps（實際: {avg}）')
check(mgr.section_stats["successful_executions"] == 3, 'successful_executions == 3')

# ─── [6] overall_health：healthy ─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [6] overall_health：正常狀態 → healthy')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

# 5 筆 FILLED（成功率 100%，非閃崩，連線 OK）
for _ in range(5):
    r = make_execution_result("FILLED", slippage_pct=0.001)
    get_bus().publish("execution.result", payload=r, sender="EX-01")

health = mgr.get_section_status()["overall_health"]
check(health == "healthy", f'正常狀態 → healthy（實際: {health}）')

# ─── [7] overall_health：連線不健康 → critical ────────────────────────────────

print(f'\n{SECTION}')
print('  [7] overall_health：連線不健康 → critical')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

# 直接設定 ex03 的 consecutive_failures ≥ 3
ex03.consecutive_failures = 3
health = mgr.get_section_status()["overall_health"]
check(health == "critical", f'consecutive_failures=3 → critical（實際: {health}）')

# ─── [8] overall_health：閃崩模式 → degraded ─────────────────────────────────

print(f'\n{SECTION}')
print('  [8] overall_health：閃崩模式中 → degraded')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

ex02.flash_crash_mode = True
health = mgr.get_section_status()["overall_health"]
check(health == "degraded", f'閃崩模式 → degraded（實際: {health}）')

# ─── [9] overall_health：成功率 < 80% → degraded ─────────────────────────────

print(f'\n{SECTION}')
print('  [9] overall_health：成功率不足 → degraded')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

# 2 成功 + 4 失敗 = 33% 成功率（< 80%）
for _ in range(2):
    get_bus().publish("execution.result",
                      payload=make_execution_result("FILLED"), sender="EX-01")
for _ in range(4):
    get_bus().publish("execution.result",
                      payload=make_execution_result("FAILED", error_msg="test"),
                      sender="EX-01")

health = mgr.get_section_status()["overall_health"]
check(health == "degraded", f'成功率 33% → degraded（實際: {health}）')

# ─── [10] produce_self_review ─────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [10] produce_self_review 產出')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

# 讓有一些執行記錄
get_bus().publish("execution.result",
                  payload=make_execution_result("FILLED"), sender="EX-01")

review = mgr.produce_self_review()

check(isinstance(review, SelfReview),           'produce_self_review 回傳 SelfReview')
check(review.role_name == "宏哥",               f'role_name == 宏哥（實際: {review.role_name}）')
check(review.role_code == "EX-Manager",         f'role_code == EX-Manager（實際: {review.role_code}）')
check(review.work_type == "執行部統籌",         f'work_type == 執行部統籌')
check("section_health" in review.my_call,        'my_call 含 section_health')
check(isinstance(review.confidence_at_time, float), 'confidence_at_time 為 float')
check(0 < review.confidence_at_time <= 1.0,     f'confidence 在 0~1（實際: {review.confidence_at_time}）')
check("connection_health" in review.data_used,   'data_used 含 connection_health')
check("section_stats" in review.data_used,       'data_used 含 section_stats')
check(review.review_id is not None,              'review_id 自動生成')

# 確認透過 bus 廣播 feedback.submitted
feedback_msgs = get_bus().get_message_history("feedback.submitted")
check(len(feedback_msgs) >= 1,                   'feedback.submitted 已廣播至 bus')
check(feedback_msgs[-1].sender == "EX-Manager",  'sender == EX-Manager')

# ─── [11] self_review confidence 對應 health ──────────────────────────────────

print(f'\n{SECTION}')
print('  [11] self_review confidence 對應 overall_health')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()
review_healthy = mgr.produce_self_review()
check(review_healthy.confidence_at_time == 1.0,
      f'healthy → confidence=1.0（實際: {review_healthy.confidence_at_time}）')

reset()
mgr2, ex01_2, ex02_2, ex03_2 = make_team()
ex02_2.flash_crash_mode = True
review_degraded = mgr2.produce_self_review()
check(review_degraded.confidence_at_time == 0.5,
      f'degraded → confidence=0.5（實際: {review_degraded.confidence_at_time}）')

reset()
mgr3, ex01_3, ex02_3, ex03_3 = make_team()
ex03_3.consecutive_failures = 5
review_critical = mgr3.produce_self_review()
check(review_critical.confidence_at_time == 0.3,
      f'critical → confidence=0.3（實際: {review_critical.confidence_at_time}）')

# ─── [12] emergency_dispatch ──────────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [12] emergency_dispatch → 觸發阿成緊急清倉')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

# 設定一個持倉
ex03.known_positions["ETHUSDT"] = {
    "symbol": "ETHUSDT", "side": "Buy", "entry_price": 3500.0,
    "stop_loss": 3400.0, "size": "0.1",
}

before_count = ex02.emergency_actions_count
mgr.emergency_dispatch("ORANGE 警戒測試")

check(ex02.emergency_actions_count > before_count,
      'emergency_dispatch → 阿成 emergency_actions_count 增加')

close_events = [e for e in ex02.emergency_history if e.get("type") == "EMERGENCY_CLOSE_ALL"]
check(len(close_events) >= 1, '阿成 emergency_history 有清倉記錄')
if close_events:
    check("ORANGE" in close_events[-1].get("reason", ""),
          f'清倉原因含 ORANGE（實際: {close_events[-1].get("reason", "")}）')

# ─── [13] 整合測試：完整下單流程 ─────────────────────────────────────────────

print(f'\n{SECTION}')
print('  [13] 整合：bus 發送 ArbiterDecision → 小慧執行 → 宏哥觀察')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

before_observed = mgr.section_stats["execution_results_observed"]

decision  = make_arbiter_decision("EXECUTE")
proposal  = make_proposal("ETHUSDT")

# 透過 bus 觸發小慧下單（她訂閱了 decision.final）
get_bus().publish(
    "decision.final",
    payload={"decision": decision, "proposal": proposal},
    sender="老王",
)

# 小慧下單後會 publish "execution.result"，宏哥會觀察到
check(mgr.section_stats["execution_results_observed"] > before_observed,
      '整合：宏哥觀察到執行結果（execution.result）')
check(mgr.section_stats["successful_executions"] >= 1,
      '整合：successful_executions 增加')

# 確認小慧的統計也更新了
check(ex01.execution_count >= 1, '小慧 execution_count 增加')

# 確認芬姐知道持倉
check("ETHUSDT" in ex03.known_positions, '芬姐 known_positions 含 ETHUSDT')

# 宏哥狀態查詢
final_status = mgr.get_section_status()
check(final_status["section_stats"]["execution_results_observed"] >= 1,
      '最終 get_section_status 反映最新執行結果')

# ─── [14] 多筆混合結果的統計正確性 ───────────────────────────────────────────

print(f'\n{SECTION}')
print('  [14] 多筆混合結果：統計一致性')
print(SECTION)

reset()
mgr, ex01, ex02, ex03 = make_team()

n_success = 7
n_fail    = 3
for _ in range(n_success):
    get_bus().publish("execution.result",
                      payload=make_execution_result("FILLED", 0.001), sender="EX-01")
for _ in range(n_fail):
    get_bus().publish("execution.result",
                      payload=make_execution_result("FAILED", error_msg="err"),
                      sender="EX-01")

s = mgr.section_stats
check(s["execution_results_observed"] == n_success + n_fail,
      f'observed == {n_success + n_fail}（實際: {s["execution_results_observed"]}）')
check(s["successful_executions"] == n_success,
      f'successful == {n_success}（實際: {s["successful_executions"]}）')
check(s["failed_executions"] == n_fail,
      f'failed == {n_fail}（實際: {s["failed_executions"]}）')
expected_rate = round(n_success / (n_success + n_fail), 4)
actual_rate   = round(s["successful_executions"] / s["execution_results_observed"], 4)
check(actual_rate == expected_rate,
      f'成功率 = {expected_rate}（實際: {actual_rate}）')

# ─── 總結 ──────────────────────────────────────────────────────────────────────

total = passed + failed
print(f'\n{SECTION}')
print('  總結')
print(SECTION)
print(f'  測試結果：{passed} / {total} 通過')
if failed == 0:
    print('  [全部通過]')
else:
    print(f'  [注意] {failed} 個測試失敗')
print(SECTION)
