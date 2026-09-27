"""逆变器管理业务规则：状态流转、字段校验与筛选口径都收在这里。

排行榜、设备详情、评分读回共用同一份数据来源：设备指标取自逆变器台账，
评分按逆变器编号入账（一台设备只保留最新一条），排行缓存按电站分键、
评分一旦写入立即整体失效，切换电站不会带出上一座电站的残留评分。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "inverter"
REQUIRED_FIELDS = ["逆变器编号", "逆变器型号", "额定功率"]
STATUS_ORDER = ["运行", "待机", "告警", "停机", "维修中"]
ACTION_RULES = {"停机检查": "停机", "复位告警": "待机", "恢复运行": "运行"}
NEGATIVE_ACTIONS = []

ALL_STATIONS_KEY = "__all__"  # 排行缓存里“全部电站”使用的键

# 预置评分：让排行榜首次进入就有内容；按逆变器编号关联，与台账口径一致。
SCORE_SEEDS: list[dict[str, Any]] = [
    {"逆变器编号": "INVE-0002", "评分": 88.5, "评语": "告警偏多，持续关注", "评分人": "值班管理员", "评分时间": "2026-09-26 10:30:00"},
    {"逆变器编号": "INVE-0005", "评分": 93, "评语": "运行平稳", "评分人": "值班管理员", "评分时间": "2026-09-26 10:32:00"},
    {"逆变器编号": "INVE-0007", "评分": 95, "评语": "标杆设备", "评分人": "值班管理员", "评分时间": "2026-09-26 10:35:00"},
]


class InverterService:
    def __init__(self) -> None:
        # 评分账簿：键是逆变器编号，一台设备任何时候只有一条最新评分。
        self._scores: dict[str, dict[str, Any]] = {
            str(row["逆变器编号"]): dict(row) for row in SCORE_SEEDS
        }
        # 排行缓存：按电站分键；评分写入后整体清空，避免切换电站时残留旧评分。
        self._ranking_cache: dict[str, list[dict[str, Any]]] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("逆变器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        self._ranking_cache.clear()  # 台账变了，排行缓存一并失效
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"逆变器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于逆变器管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["运行状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._ranking_cache.clear()  # 运行状态进排行，缓存同步失效
        return entry, f"逆变器已{action}"

    def stations(self) -> list[str]:
        """电站切换器的选项：从台账里按出现顺序去重，排行与详情都用这份清单。"""
        seen: list[str] = []
        for row in store.rows(MODULE):
            station = str(row.get("所属电站") or "").strip()
            if station and station not in seen:
                seen.append(station)
        return seen

    def ranking(self, station: str | None = None) -> list[dict[str, Any]]:
        """逆变器排行榜：按电站分键缓存；返回副本，调用方改不动缓存本体。"""
        key = station or ALL_STATIONS_KEY
        if key not in self._ranking_cache:
            self._ranking_cache[key] = self._build_ranking(station)
        return [dict(row) for row in self._ranking_cache[key]]

    def device_detail(self, code: str) -> dict[str, Any] | None:
        """设备详情：按逆变器编号从台账取指标、从评分账簿取最新评分，与排行同源。"""
        row = self._find_by_code(code)
        if row is None:
            return None
        return self._merge(row, detail=True)

    def save_score(
        self,
        code: str,
        score: Any,
        remark: str = "",
        operator: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """评分写入：按逆变器编号覆盖入账，随后从同一来源读回，保证三处口径一致。"""
        row = self._find_by_code(code)
        if row is None:
            return None, f"逆变器 {code} 不存在或已归档"
        try:
            value = float(score)
        except (TypeError, ValueError):
            return None, "评分需为 0-100 的数字"
        if not 0 <= value <= 100:
            return None, "评分需在 0-100 之间"
        device_code = str(row["逆变器编号"])
        self._scores[device_code] = {
            "逆变器编号": device_code,
            "评分": value,
            "评语": remark,
            "评分人": operator or "值班管理员",
            "评分时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._ranking_cache.clear()  # 评分变了，所有电站的排行缓存一并失效
        return self.device_detail(device_code), "评分已保存"

    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        target = str(code or "").strip()
        for row in store.rows(MODULE):
            if str(row.get("逆变器编号") or "").strip() == target:
                return row
        return None

    def _merge(self, row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
        """台账指标 + 最新评分合并成一行：排行、详情、评分读回都走这一个入口。"""
        code = str(row.get("逆变器编号") or "")
        score = self._scores.get(code) or {}
        merged: dict[str, Any] = {
            "逆变器编号": code,
            "逆变器型号": row.get("逆变器型号"),
            "所属电站": row.get("所属电站"),
            "运行时长": row.get("运行时长"),
            "告警次数": row.get("告警次数"),
            "运行状态": row.get("运行状态") or row.get("status"),
            "评分": score.get("评分"),
            "评语": score.get("评语"),
            "评分人": score.get("评分人"),
            "评分时间": score.get("评分时间"),
        }
        if detail:
            merged["id"] = row.get("id")
            merged["额定功率"] = row.get("额定功率")
            merged["投产日期"] = row.get("投产日期")
        return merged

    def _build_ranking(self, station: str | None) -> list[dict[str, Any]]:
        rows = [
            row for row in store.rows(MODULE)
            if not station or str(row.get("所属电站") or "") == station
        ]
        merged = [self._merge(row) for row in rows]
        merged.sort(key=lambda item: (
            item["评分"] is None,  # 未评分的排最后
            -(item["评分"] or 0),
            item["告警次数"] if isinstance(item["告警次数"], (int, float)) else 0,
            item["逆变器编号"],
        ))
        for index, item in enumerate(merged, start=1):
            item["名次"] = index
        return merged
