"""逆变器管理接口：维护逆变器，覆盖停机检查、复位告警、恢复运行等动作。

排行榜、设备详情、评分保存三个入口都按逆变器编号关联同一份数据；
/ranking、/device、/score、/export 这类静态路径必须放在 /{entry_id} 之前，
否则会被路径参数抢先匹配。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.inverter import InverterService

router = APIRouter(prefix="/api/inverter", tags=["逆变器管理"])

service = InverterService()

LIST_FIELDS = ["逆变器编号", "逆变器型号", "额定功率", "所属电站", "投产日期", "运行时长", "告警次数", "运行状态"]
STATUSES = ["运行", "待机", "告警", "停机", "维修中"]


@router.get("/ranking")
def get_ranking(
    station: str | None = Query(default=None, description="按所属电站过滤，缺省为全部电站"),
) -> dict[str, Any]:
    """逆变器排行榜：运行时长、告警次数与评分来自同一份按编号关联的数据。"""
    items = service.ranking(station)
    return {
        "station": station or "",
        "stations": service.stations(),
        "items": items,
        "total": len(items),
    }


@router.get("/device/{code}")
def get_device(code: str) -> dict[str, Any]:
    """按逆变器编号读取设备详情；不存在时给出可读的错误说明。"""
    entry = service.device_detail(code)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"逆变器 {code} 不存在或已归档")
    return entry


@router.post("/score", response_model=ActionResult)
def save_score(payload: EntryPayload) -> ActionResult:
    """保存设备评分：按逆变器编号入账，一台设备只留最新一条；返回保存后的读回结果。"""
    code = str(payload.values.get("逆变器编号") or "").strip()
    entry, message = service.save_score(
        code,
        payload.values.get("评分"),
        remark=str(payload.values.get("评语") or "").strip(),
        operator=str(payload.values.get("评分人") or "").strip(),
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出逆变器管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "inverter", "total": total, "items": items}


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
