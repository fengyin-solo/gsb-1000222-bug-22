"""逆变器管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "inverter"
REQUIRED_FIELDS = ["逆变器编号", "逆变器型号", "额定功率"]
STATUS_ORDER = ["运行", "待机", "告警", "停机", "维修中"]
ACTION_RULES = {"停机检查": "停机", "复位告警": "待机", "恢复运行": "运行"}
NEGATIVE_ACTIONS = []

# 评分只按逆变器编号落一份，排行、详情、读回都从这里取，避免两套设备关联各存一份。
SCORE_BUCKET = "inverter_scores"


class InverterService:
    def __init__(self) -> None:
        # 排行缓存按电站分键；任何评分写入或设备变更都会整体失效，切换电站不会读到残留评分。
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
        self._ranking_cache.clear()
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
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._ranking_cache.clear()
        return entry, f"逆变器已{action}"

    # ---- 排行榜 / 详情 / 评分：三个入口共用同一份按逆变器编号索引的数据 ----

    def list_plants(self) -> list[str]:
        """电站切换下拉的选项，直接来自逆变器行的所属电站，不另存一份。"""
        plants = {str(row.get("所属电站") or "").strip() for row in store.rows(MODULE)}
        return sorted(plant for plant in plants if plant)

    def ranking(self, plant: str | None = None) -> list[dict[str, Any]]:
        """排行缓存按电站分键；缓存 miss 时从设备行与评分公司现算，保证不残留其他电站的评分。"""
        key = (plant or "").strip()
        cached = self._ranking_cache.get(key)
        if cached is not None:
            return [dict(item) for item in cached]
        rows = store.rows(MODULE)
        if key:
            rows = [row for row in rows if str(row.get("所属电站") or "").strip() == key]
        items = [self._snapshot(row) for row in rows]
        items.sort(key=self._rank_key)
        self._ranking_cache[key] = [dict(item) for item in items]
        return items

    def device_detail(self, device_no: str) -> dict[str, Any] | None:
        """详情只认逆变器编号，绕开排行缓存直接读设备行与评分桶，与排行看到的一致。"""
        row = self._find_by_device_no(device_no)
        if row is None:
            return None
        return self._snapshot(row)

    def save_score(
        self,
        device_no: str,
        score: float,
        remark: str = "",
        operator: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """评分按逆变器编号覆盖写入：同一设备永远只保留一份最新评分，并立即失效排行缓存。"""
        row = self._find_by_device_no(device_no)
        if row is None:
            return None, f"逆变器 {device_no} 不存在或已归档"
        if not 0 <= score <= 100:
            return None, "评分需在 0-100 之间"
        key = str(row.get("逆变器编号"))
        store.bucket(SCORE_BUCKET)[key] = {
            "逆变器编号": key,
            "评分": round(float(score), 1),
            "评分备注": remark.strip(),
            "评分人": operator.strip(),
            "评分时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._ranking_cache.clear()
        # 读回与排行、详情走同一个 _snapshot，三处看到的告警次数、运行时长、评分必然一致。
        return self._snapshot(row), "评分已保存"

    def _find_by_device_no(self, device_no: str) -> dict[str, Any] | None:
        key = (device_no or "").strip()
        for row in store.rows(MODULE):
            if str(row.get("逆变器编号") or "").strip() == key:
                return row
        return None

    def _snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        """排行、详情、评分读回共用的设备视图：基础字段取自设备行，评分取自评分桶。"""
        device_no = str(row.get("逆变器编号") or "").strip()
        score = store.bucket(SCORE_BUCKET).get(device_no) or {}
        return {
            "逆变器编号": device_no,
            "逆变器型号": row.get("逆变器型号"),
            "额定功率": row.get("额定功率"),
            "所属电站": row.get("所属电站"),
            "投产日期": row.get("投产日期"),
            "运行时长": row.get("运行时长"),
            "告警次数": row.get("告警次数"),
            "运行状态": row.get("运行状态"),
            "评分": score.get("评分"),
            "评分备注": score.get("评分备注"),
            "评分人": score.get("评分人"),
            "评分时间": score.get("评分时间"),
        }

    @staticmethod
    def _rank_key(item: dict[str, Any]) -> tuple[int, float, int, str]:
        """已评分的按评分从高到低排，未评分沉底；同分看告警次数，再看编号保证稳定。"""
        score = item.get("评分")
        try:
            alarms = int(item.get("告警次数") or 0)
        except (TypeError, ValueError):
            alarms = 0
        if score is None:
            return (1, 0.0, alarms, str(item.get("逆变器编号") or ""))
        return (0, -float(score), alarms, str(item.get("逆变器编号") or ""))
