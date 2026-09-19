"""绿植更换记录业务逻辑。"""

from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from ..constants import ENUM_GROUPS
from ..errors import ConflictError, ValidationError
from ..extensions import db
from ..models import GreenSpace, MaintenanceRecord, PlantReplacement
from ..utils.numbers import to_float
from ..utils.sorting import parse_sort
from .base_service import BaseService
from .code_generator import daily_prefix


class PlantReplacementService(BaseService):
    """绿植更换记录：登记更换明细并自动核算金额。"""

    model = PlantReplacement
    label = "绿植更换记录"
    code_field = "replacement_no"
    code_width = 3

    SORTABLE = {
        "replace_date": PlantReplacement.replace_date,
        "quantity": PlantReplacement.quantity,
        "amount": PlantReplacement.amount,
        "created_at": PlantReplacement.created_at,
    }

    @classmethod
    def code_prefix(cls):
        return daily_prefix("PR")

    # ------------------------------------------------------------ 校验与派生
    @classmethod
    def prepare_instance(cls, instance, payload):
        green_space_id = payload.get("green_space_id", instance.green_space_id)
        space = db.session.get(GreenSpace, green_space_id) if green_space_id else None
        if space is None:
            raise ValidationError("登记失败", details={"green_space_id": "所选绿地不存在"})

        record_id = payload.get("maintenance_record_id", instance.maintenance_record_id)
        if record_id:
            record = db.session.get(MaintenanceRecord, record_id)
            if record is None:
                raise ValidationError(
                    "登记失败", details={"maintenance_record_id": "关联的养护记录不存在"}
                )
            if record.green_space_id != space.id:
                raise ValidationError(
                    "登记失败",
                    details={"maintenance_record_id": "关联的养护记录不属于所选绿地"},
                )

        replace_date = payload.get("replace_date", instance.replace_date)
        if replace_date and space.established_date and replace_date < space.established_date:
            raise ValidationError(
                "登记失败",
                details={"replace_date": f"更换日期不能早于该绿地建成日期 {space.established_date}"},
            )

    @classmethod
    def apply_derived(cls, instance):
        """金额 = 数量 × 单价；未填单价时留空，由前端提示补录。"""

        if instance.unit_price is None:
            instance.amount = None
        else:
            instance.amount = (
                Decimal(str(instance.quantity or 0)) * Decimal(str(instance.unit_price))
            ).quantize(Decimal("0.01"))

    # ------------------------------------------------------------ 查询
    @classmethod
    def _apply_filters(cls, query, filters):
        if filters.get("green_space_id"):
            query = query.filter(PlantReplacement.green_space_id == filters["green_space_id"])
        if filters.get("maintenance_record_id"):
            query = query.filter(
                PlantReplacement.maintenance_record_id == filters["maintenance_record_id"]
            )
        if filters.get("task_id"):
            # 按任务反查：更换记录通过养护记录挂到任务上
            query = query.join(
                MaintenanceRecord,
                PlantReplacement.maintenance_record_id == MaintenanceRecord.id,
            ).filter(MaintenanceRecord.task_id == filters["task_id"])
        if filters.get("import_batch"):
            query = query.filter(PlantReplacement.import_batch == filters["import_batch"])
        if filters.get("plant_category"):
            query = query.filter(PlantReplacement.plant_category == filters["plant_category"])
        if filters.get("reason"):
            query = query.filter(PlantReplacement.reason == filters["reason"])
        if filters.get("date_from"):
            query = query.filter(PlantReplacement.replace_date >= filters["date_from"])
        if filters.get("date_to"):
            query = query.filter(PlantReplacement.replace_date <= filters["date_to"])
        keyword = filters.get("keyword")
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(
                or_(
                    PlantReplacement.replacement_no.like(like),
                    PlantReplacement.plant_name.like(like),
                    PlantReplacement.spec.like(like),
                    PlantReplacement.supplier.like(like),
                    PlantReplacement.operator.like(like),
                )
            )
        return query

    @classmethod
    def list_replacements(cls, filters, args):
        query = cls._apply_filters(db.session.query(PlantReplacement), filters)
        return query.order_by(
            parse_sort(args, cls.SORTABLE, PlantReplacement.replace_date.desc())
        )

    @classmethod
    def detail(cls, obj_id):
        return cls.get(obj_id).to_dict(detail=True)

    @classmethod
    def summary(cls, filters):
        """更换汇总：按植物类别与更换原因统计数量、金额。"""

        def _group(column, group_key):
            rows = (
                cls._apply_filters(
                    db.session.query(
                        column,
                        func.count(PlantReplacement.id),
                        func.coalesce(func.sum(PlantReplacement.quantity), 0),
                        func.coalesce(func.sum(PlantReplacement.amount), 0),
                    ),
                    filters,
                )
                .group_by(column)
                .all()
            )
            return [
                {
                    "value": value,
                    "label": ENUM_GROUPS[group_key].label(value),
                    "count": count,
                    "quantity": to_float(quantity) or 0,
                    "amount": to_float(amount) or 0,
                }
                for value, count, quantity, amount in rows
            ]

        totals = cls._apply_filters(
            db.session.query(
                func.count(PlantReplacement.id),
                func.coalesce(func.sum(PlantReplacement.quantity), 0),
                func.coalesce(func.sum(PlantReplacement.amount), 0),
            ),
            filters,
        ).one()

        return {
            "total_count": totals[0] or 0,
            "total_quantity": to_float(totals[1]) or 0,
            "total_amount": to_float(totals[2]) or 0,
            "by_category": _group(PlantReplacement.plant_category, "plant_category"),
            "by_reason": _group(PlantReplacement.reason, "replacement_reason"),
        }

    @classmethod
    def cost_summary(cls, filters):
        """费用归集：按绿地与按月汇总更换费用，把每笔支出落到绿地与时间段上。"""

        space_rows = (
            cls._apply_filters(
                db.session.query(
                    GreenSpace.id,
                    GreenSpace.code,
                    GreenSpace.name,
                    func.count(PlantReplacement.id),
                    func.coalesce(func.sum(PlantReplacement.quantity), 0),
                    func.coalesce(func.sum(PlantReplacement.amount), 0),
                ).join(PlantReplacement, PlantReplacement.green_space_id == GreenSpace.id),
                filters,
            )
            .group_by(GreenSpace.id, GreenSpace.code, GreenSpace.name)
            .order_by(func.coalesce(func.sum(PlantReplacement.amount), 0).desc())
            .all()
        )

        year_col = db.extract("year", PlantReplacement.replace_date)
        month_col = db.extract("month", PlantReplacement.replace_date)
        month_rows = (
            cls._apply_filters(
                db.session.query(
                    year_col,
                    month_col,
                    func.count(PlantReplacement.id),
                    func.coalesce(func.sum(PlantReplacement.quantity), 0),
                    func.coalesce(func.sum(PlantReplacement.amount), 0),
                ),
                filters,
            )
            .group_by(year_col, month_col)
            .order_by(year_col, month_col)
            .all()
        )

        return {
            "by_green_space": [
                {
                    "green_space_id": space_id,
                    "code": code,
                    "name": name,
                    "count": count,
                    "quantity": to_float(quantity) or 0,
                    "amount": to_float(amount) or 0,
                }
                for space_id, code, name, count, quantity, amount in space_rows
            ],
            "by_month": [
                {
                    "month": f"{int(year):04d}-{int(month):02d}",
                    "count": count,
                    "quantity": to_float(quantity) or 0,
                    "amount": to_float(amount) or 0,
                }
                for year, month, count, quantity, amount in month_rows
            ],
        }

    # ------------------------------------------------------------ 批量导入
    @classmethod
    def import_batch(cls, batch_no, items):
        """批量导入更换记录（幂等）。

        同一 (batch_no, line_no) 只入账一次：重复导入同一批数据时，
        已存在的行按 skipped 返回原记录，不会重复创建，费用也不会重复归集。
        任一行校验失败则整批回滚，不产生部分写入。
        """

        for _ in range(cls.MAX_CODE_RETRY):
            try:
                return cls._import_once(batch_no, items)
            except IntegrityError:
                # 并发导入同批数据或编号冲突：回滚后重试，
                # 已被其他请求写入的行会在下一轮按 skipped 处理
                db.session.rollback()
        raise ConflictError("导入批次与已有数据冲突，请稍后重试")

    @classmethod
    def _import_once(cls, batch_no, items):
        existing = {
            row.import_line: row
            for row in db.session.query(PlantReplacement)
            .filter(PlantReplacement.import_batch == batch_no)
            .all()
        }

        results = {}
        pending = []
        for item in items:
            hit = existing.get(item["line_no"])
            if hit is None:
                pending.append(item)
            else:
                results[item["line_no"]] = cls._import_result(item["line_no"], "skipped", hit)

        # 业务规则（绿地存在、关联记录同绿地、日期不早于建成日期）逐行预检，有错整批拒绝
        line_errors = []
        for item in pending:
            payload = cls._import_payload(batch_no, item)
            try:
                cls.prepare_instance(PlantReplacement(**payload), payload)
            except ValidationError as exc:
                line_errors.append({"line_no": item["line_no"], "errors": exc.details or {}})
        if line_errors:
            raise ValidationError("导入数据未通过校验，整批未写入", details={"items": line_errors})

        for item in pending:
            payload = cls._import_payload(batch_no, item)
            payload[cls.code_field] = cls.generate_code()
            instance = PlantReplacement(**payload)
            cls.apply_derived(instance)
            db.session.add(instance)
            db.session.flush()
            results[item["line_no"]] = cls._import_result(item["line_no"], "created", instance)

        db.session.commit()
        ordered = [results[item["line_no"]] for item in items]
        return {
            "batch_no": batch_no,
            "total": len(ordered),
            "created_count": sum(1 for row in ordered if row["status"] == "created"),
            "skipped_count": sum(1 for row in ordered if row["status"] == "skipped"),
            "items": ordered,
        }

    @staticmethod
    def _import_payload(batch_no, item):
        payload = {key: value for key, value in item.items() if key != "line_no"}
        payload["import_batch"] = batch_no
        payload["import_line"] = item["line_no"]
        return payload

    @staticmethod
    def _import_result(line_no, status, instance):
        return {
            "line_no": line_no,
            "status": status,
            "id": instance.id,
            "replacement_no": instance.replacement_no,
        }
