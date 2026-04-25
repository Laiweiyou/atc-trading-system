# -*- coding: utf-8 -*-
"""
歷史事件庫存取介面
GA-01b 歷史比對使用
"""
import json
import pathlib
from datetime import datetime, timezone

_DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "historical_events.json"

VALID_CATEGORIES = {"GEOPOLITICAL", "REGULATORY", "ECONOMIC", "CRYPTO_NATIVE", "BLACK_SWAN"}


def load_events(path: pathlib.Path = _DB_PATH) -> list[dict]:
    """載入事件庫，回傳事件列表。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("events", [])


def find_similar(
    event_type: str,
    entities: list[str] | None = None,
    limit: int = 3,
    path: pathlib.Path = _DB_PATH,
) -> list[dict]:
    """
    根據類別 / 次分類 / 實體搜尋相似歷史事件。

    event_type 格式：
      - "GEOPOLITICAL"                    → 只比對 category（+2 分）
      - "GEOPOLITICAL.military_conflict"  → 比對 category + subcategory（+2 + 3 分）
      - "etf_approval"                    → 只比對 subcategory（+3 分）

    entities: 相關實體清單，每命中一個 +1 分。
    回傳得分最高的前 limit 個事件（同分時優先最近事件）。
    """
    events = load_events(path)

    if "." in event_type:
        target_cat, target_sub = event_type.split(".", 1)
    elif event_type.upper() in VALID_CATEGORIES:
        target_cat, target_sub = event_type.upper(), None
    else:
        target_cat, target_sub = None, event_type

    scored: list[tuple[int, dict]] = []
    for event in events:
        score = 0

        if target_cat and event.get("category", "").upper() == target_cat.upper():
            score += 2
        if target_sub and event.get("subcategory", "").lower() == target_sub.lower():
            score += 3
        if entities:
            ev_entities = {e.lower() for e in event.get("key_entities", [])}
            for entity in entities:
                if entity.lower() in ev_entities:
                    score += 1

        if score > 0:
            scored.append((score, event))

    # 主排序：score 降序；次排序：日期降序（最近事件優先）
    scored.sort(key=lambda x: (x[0], x[1]["date"]), reverse=True)

    return [event for _, event in scored[:limit]]


def compute_avg_reaction(events: list[dict]) -> dict:
    """
    計算多個事件的平均市場反應。

    回傳：
    {
      btc_reaction: {24h/48h/7d_change_pct},
      eth_reaction: {24h/48h/7d_change_pct},
      avg_recovery_days:  float | None,
      avg_max_drawdown:   float | None,
      event_count:        int,
    }
    """
    if not events:
        return {"event_count": 0}

    keys = ["24h_change_pct", "48h_change_pct", "7d_change_pct"]
    btc_vals: dict[str, list[float]] = {k: [] for k in keys}
    eth_vals: dict[str, list[float]] = {k: [] for k in keys}
    recovery_list: list[float] = []
    drawdown_list: list[float] = []

    for ev in events:
        for k in keys:
            v = ev.get("btc_reaction", {}).get(k)
            if v is not None:
                btc_vals[k].append(float(v))
            v = ev.get("eth_reaction", {}).get(k)
            if v is not None:
                eth_vals[k].append(float(v))
        rd = ev.get("recovery_days")
        if rd is not None:
            recovery_list.append(float(rd))
        dd = ev.get("max_drawdown_during_event")
        if dd is not None:
            drawdown_list.append(float(dd))

    def avg(lst: list[float]) -> float | None:
        return round(sum(lst) / len(lst), 2) if lst else None

    return {
        "btc_reaction": {k: avg(btc_vals[k]) for k in keys},
        "eth_reaction": {k: avg(eth_vals[k]) for k in keys},
        "avg_recovery_days": avg(recovery_list),
        "avg_max_drawdown":  avg(drawdown_list),
        "event_count": len(events),
    }


def add_event(
    event_data: dict,
    path: pathlib.Path = _DB_PATH,
) -> None:
    """
    新增事件至事件庫並更新 metadata。
    event_data 至少需包含：event_id, date, category, description。
    重複 event_id 會拋出 ValueError。
    """
    required = {"event_id", "date", "category", "description"}
    missing = required - set(event_data.keys())
    if missing:
        raise ValueError(f"事件缺少必要欄位：{missing}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    existing_ids = {e["event_id"] for e in data.get("events", [])}
    if event_data["event_id"] in existing_ids:
        raise ValueError(f"event_id 已存在：{event_data['event_id']}")

    data["events"].append(event_data)
    data["metadata"]["event_count"] = len(data["events"])
    data["metadata"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
