"""绿植更换记录校验规则。"""

from ..constants import MEASURE_UNIT, OLD_PLANT_STATUS, PLANT_CATEGORY, REPLACEMENT_REASON
from ..errors import ValidationError
from .common import PayloadValidator

IMPORT_MAX_ITEMS = 500


def validate_plant_replacement(payload):
    return (
        PayloadValidator(payload)
        .integer("green_space_id", "所属绿地", required=True, min_value=1)
        .integer("maintenance_record_id", "关联养护记录", min_value=1)
        .string("plant_name", "植株名称", required=True, max_length=96)
        .enum("plant_category", "植物类别", group=PLANT_CATEGORY, required=True)
        .string("spec", "规格", max_length=64)
        .number("quantity", "更换数量", required=True, min_value=0.01, max_value=999999)
        .enum("unit", "计量单位", group=MEASURE_UNIT, default="plant")
        .enum("reason", "更换原因", group=REPLACEMENT_REASON, required=True)
        .enum("old_plant_status", "原植株状况", group=OLD_PLANT_STATUS)
        .date("replace_date", "更换日期", required=True)
        .string("supplier", "供苗单位", max_length=96)
        .number("unit_price", "单价", min_value=0, max_value=99999999)
        .string("operator", "登记人", max_length=64)
        .text("remark", "备注", max_length=2000)
        .done()
    )


def validate_replacement_import(payload):
    """批量导入校验：批次号 + 逐行字段校验。

    行级错误按行号汇总后一次抛出（422），整批不写入；
    全部通过才返回 {"batch_no", "items"} 交给 service 幂等入账。
    """

    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    batch_no = str(payload.get("batch_no") or "").strip()
    if not batch_no:
        raise ValidationError("提交的数据未通过校验", details={"batch_no": "导入批次号不能为空"})
    if len(batch_no) > 64:
        raise ValidationError(
            "提交的数据未通过校验", details={"batch_no": "导入批次号长度不能超过 64 个字符"}
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationError("提交的数据未通过校验", details={"items": "导入明细不能为空"})
    if len(raw_items) > IMPORT_MAX_ITEMS:
        raise ValidationError(
            "提交的数据未通过校验",
            details={"items": f"单批导入不能超过 {IMPORT_MAX_ITEMS} 行"},
        )

    items = []
    line_errors = []
    seen_lines = set()
    for index, raw in enumerate(raw_items, start=1):
        raw = raw if isinstance(raw, dict) else {}
        line_no = str(raw.get("line_no") or "").strip()
        errors = {}
        if not line_no:
            errors["line_no"] = "行号不能为空"
        elif len(line_no) > 64:
            errors["line_no"] = "行号长度不能超过 64 个字符"
        elif line_no in seen_lines:
            errors["line_no"] = "行号在同一批次内重复"
        try:
            clean = validate_plant_replacement(raw)
        except ValidationError as exc:
            errors.update(exc.details or {})
            clean = None
        if errors:
            line_errors.append({"line_no": line_no or f"#{index}", "errors": errors})
        else:
            seen_lines.add(line_no)
            items.append({"line_no": line_no, **clean})
    if line_errors:
        raise ValidationError("导入数据未通过校验，整批未写入", details={"items": line_errors})
    return {"batch_no": batch_no, "items": items}
