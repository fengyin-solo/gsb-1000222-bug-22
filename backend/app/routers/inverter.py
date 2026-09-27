"""逆变器管理接口：维护逆变器，覆盖停机检查、复位告警、恢复运行等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.inverter import InverterService

router = APIRouter(prefix="/api/inverter", tags=["逆变器管理"])

service = InverterService()

LIST_FIELDS = ["逆变器编号", "逆变器型号", "额定功率", "所属电站", "投产日期", "运行时长", "告警次数", "运行状态"]
STATUSES = ["运行", "待机", "告警", "停机", "维修中"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按逆变器编号检索"),
    status: str | None = Query(default=None, description="运行、待机、告警、停机、维修中"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按逆变器编号与状态过滤逆变器管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/plants", response_model=dict)
def list_plants() -> dict:
    """电站切换下拉选项：与排行同源，直接取自逆变器行的所属电站。"""
    return {"items": service.list_plants()}


@router.get("/ranking", response_model=dict)
def ranking(plant: str | None = Query(default=None, description="按所属电站过滤，缺省为全部电站")) -> dict:
    """逆变器排行榜：按设备编号关联评分，切换电站时不会带出上一电站的残留评分。"""
    items = service.ranking(plant)
    return {"items": items, "total": len(items)}


@router.get("/ranking/{device_no}", response_model=dict)
def ranking_detail(device_no: str) -> dict:
    """单台逆变器详情：按逆变器编号读取，与排行榜、评分读回看到的是同一份数据。"""
    entry = service.device_detail(device_no)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"逆变器 {device_no} 不存在或已归档")
    return entry


@router.post("/ranking/{device_no}/score", response_model=ActionResult)
def save_score(device_no: str, payload: EntryPayload) -> ActionResult:
    """保存评分：同一设备只保留一份最新评分，返回的读回结果与排行、详情同源。"""
    raw_score = payload.values.get("score")
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="评分需为 0-100 的数字")
    entry, message = service.save_score(
        device_no,
        score,
        remark=str(payload.values.get("remark") or ""),
        operator=str(payload.values.get("operator") or ""),
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条逆变器明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"逆变器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条逆变器，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="逆变器已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条逆变器执行停机检查、复位告警、恢复运行；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出逆变器管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "inverter", "total": total, "items": items}
