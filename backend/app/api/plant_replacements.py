"""绿植更换记录接口。"""

from flask import Blueprint, request

from ..schemas import validate_plant_replacement
from ..schemas.filters import replacement_filters
from ..services import PlantReplacementService
from ..utils.pagination import paginate, parse_page_args
from ..utils.requests import json_body
from ..utils.responses import created, ok

bp = Blueprint("plant_replacements", __name__)


@bp.get("/plant-replacements")
def list_replacements():
    filters = replacement_filters(request.args)
    page, page_size = parse_page_args()
    query = PlantReplacementService.list_replacements(filters, request.args)
    data = paginate(query, page, page_size)
    data["summary"] = PlantReplacementService.summary(filters)
    return ok(data)


@bp.get("/plant-replacements/summary")
def replacement_summary():
    return ok(PlantReplacementService.summary(replacement_filters(request.args)))


@bp.get("/plant-replacements/cost-report")
def replacement_cost_report():
    """更换费用按绿地 × 时间段（月/季/年）归属，筛选条件与列表一致。"""

    group_by = (request.args.get("group_by") or "month").strip()
    return ok(PlantReplacementService.cost_report(replacement_filters(request.args), group_by))


@bp.post("/plant-replacements/import")
def import_replacements():
    """批量导入更换明细：batch_no 为幂等键，同批次重复提交不重复入账。"""

    result, replayed = PlantReplacementService.import_batch(json_body())
    if replayed:
        return ok(result, message="该批次已导入过，返回首次结果，未重复入账")
    return created(result, message="批量导入完成")


@bp.post("/plant-replacements")
def create_replacement():
    payload = validate_plant_replacement(json_body())
    replacement = PlantReplacementService.create(payload)
    return created(replacement.to_dict(detail=True), message="绿植更换记录登记成功")


@bp.get("/plant-replacements/<int:replacement_id>")
def get_replacement(replacement_id):
    return ok(PlantReplacementService.detail(replacement_id))


@bp.put("/plant-replacements/<int:replacement_id>")
def update_replacement(replacement_id):
    payload = validate_plant_replacement(json_body())
    replacement = PlantReplacementService.update(replacement_id, payload)
    return ok(replacement.to_dict(detail=True), message="绿植更换记录已更新")


@bp.delete("/plant-replacements/<int:replacement_id>")
def delete_replacement(replacement_id):
    PlantReplacementService.delete(replacement_id)
    return ok(None, message="绿植更换记录已删除")
