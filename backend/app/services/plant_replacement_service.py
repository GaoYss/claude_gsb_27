"""绿植更换记录业务逻辑。"""

import hashlib
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..constants import ENUM_GROUPS
from ..errors import ConflictError, ValidationError
from ..extensions import db
from ..models import (
    GreenSpace,
    MaintenanceRecord,
    PlantReplacement,
    PlantReplacementImportBatch,
)
from ..utils.numbers import to_float
from ..utils.sorting import parse_sort
from .base_service import BaseService
from .code_generator import daily_prefix

# 参与明细内容指纹的字段（顺序固定），用于跨批次去重
FINGERPRINT_FIELDS = (
    "green_space_id",
    "replace_date",
    "plant_name",
    "plant_category",
    "spec",
    "quantity",
    "unit",
    "reason",
    "supplier",
    "unit_price",
)


def content_fingerprint(data):
    """按业务内容生成稳定指纹：字段规范化后 sha256，内容相同则指纹相同。"""

    parts = []
    for field in FINGERPRINT_FIELDS:
        value = data.get(field)
        if field in {"quantity", "unit_price"} and value is not None:
            value = str(Decimal(str(value)).quantize(Decimal("0.01")))
        elif isinstance(value, str):
            value = value.strip()
        parts.append("" if value is None else str(value))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PlantReplacementService(BaseService):
    """绿植更换记录：登记更换明细、自动核算金额并维护来源关联。"""

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
        cls.apply_source(instance, record_id=record_id, expected_space=space)

        replace_date = payload.get("replace_date", instance.replace_date)
        if replace_date and space.established_date and replace_date < space.established_date:
            raise ValidationError(
                "登记失败",
                details={"replace_date": f"更换日期不能早于该绿地建成日期 {space.established_date}"},
            )

    @staticmethod
    def apply_source(instance, *, record_id, expected_space=None):
        """按关联养护记录同步任务外键与来源快照。

        - 关联到养护记录时：任务跟随记录，记录编号与任务编号/名称一并冻结为快照；
        - 取消关联时：清空实时外键与快照（仅用于表单创建/更新场景）。
        删任务、删记录的保留快照逻辑走 detach_* 方法，不经过这里。
        """

        record = None
        if record_id:
            record = db.session.get(MaintenanceRecord, record_id)
            if record is None:
                raise ValidationError(
                    "登记失败", details={"maintenance_record_id": "关联的养护记录不存在"}
                )
            if expected_space is not None and record.green_space_id != expected_space.id:
                raise ValidationError(
                    "登记失败",
                    details={"maintenance_record_id": "关联的养护记录不属于所选绿地"},
                )

        if record is None:
            instance.maintenance_record_id = None
            instance.task_id = None
            instance.record_snapshot_no = None
            instance.task_snapshot_no = None
            instance.task_snapshot_title = None
            return

        instance.maintenance_record_id = record.id
        instance.record_snapshot_no = record.record_no
        instance.task_id = record.task_id
        instance.task_snapshot_no = record.task.task_no if record.task else None
        instance.task_snapshot_title = record.task.title if record.task else None

    @classmethod
    def refresh_record_links(cls, record):
        """养护记录改挂任务后，重算其名下更换记录的任务关联与快照。"""

        items = (
            db.session.query(PlantReplacement)
            .filter(PlantReplacement.maintenance_record_id == record.id)
            .all()
        )
        for item in items:
            item.task_id = record.task_id
            item.task_snapshot_no = record.task.task_no if record.task else None
            item.task_snapshot_title = record.task.title if record.task else None
        return len(items)

    @classmethod
    def _linked_to_task_query(cls, task):
        """与某任务关联的更换记录：自身 task_id 直连，或经名下养护记录间接关联。"""

        linked_record_ids = db.select(MaintenanceRecord.id).where(
            MaintenanceRecord.task_id == task.id
        )
        return db.session.query(PlantReplacement).outerjoin(
            MaintenanceRecord,
            PlantReplacement.maintenance_record_id == MaintenanceRecord.id,
        ).filter(
            or_(
                PlantReplacement.task_id == task.id,
                PlantReplacement.maintenance_record_id.in_(linked_record_ids),
            )
        )

    @classmethod
    def count_by_task(cls, task):
        return cls._linked_to_task_query(task).count()

    @classmethod
    def detach_task_links(cls, task):
        """任务被删除：更换记录全部保留，仅断开实时外键并冻结任务快照。

        - task_id 置空（任务已不存在，不能留悬空引用）；
        - 任务编号/名称快照缺失时补盖，保证事后仍能说明更换出自哪个任务。
        """

        items = cls._linked_to_task_query(task).all()
        count = 0
        for item in items:
            item.task_id = None
            if not item.task_snapshot_no:
                item.task_snapshot_no = task.task_no
                item.task_snapshot_title = task.title
            count += 1
        return count

    @classmethod
    def detach_record_links(cls, record_id):
        """养护记录被删除：置空记录外键但保留记录编号快照，任务关联不动。"""

        return (
            db.session.query(PlantReplacement)
            .filter(PlantReplacement.maintenance_record_id == record_id)
            .update({PlantReplacement.maintenance_record_id: None}, synchronize_session=False)
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
            task_id = filters["task_id"]
            linked_record_ids = db.select(MaintenanceRecord.id).where(
                MaintenanceRecord.task_id == task_id
            )
            query = query.filter(
                or_(
                    PlantReplacement.task_id == task_id,
                    PlantReplacement.maintenance_record_id.in_(linked_record_ids),
                )
            )
        if filters.get("plant_category"):
            query = query.filter(PlantReplacement.plant_category == filters["plant_category"])
        if filters.get("reason"):
            query = query.filter(PlantReplacement.reason == filters["reason"])
        if filters.get("supplier"):
            query = query.filter(PlantReplacement.supplier == filters["supplier"])
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
                    PlantReplacement.task_snapshot_no.like(like),
                )
            )
        return query

    @classmethod
    def list_replacements(cls, filters, args):
        query = cls._apply_filters(db.session.query(PlantReplacement), filters)
        # 预加载 to_dict 用到的关联，避免列表 N+1（green_space/import_batch 已 joined）
        query = query.options(
            selectinload(PlantReplacement.record).selectinload(MaintenanceRecord.task),
            selectinload(PlantReplacement.task),
        )
        return query.order_by(
            parse_sort(args, cls.SORTABLE, PlantReplacement.replace_date.desc())
        )

    @classmethod
    def detail(cls, obj_id):
        return cls.get(obj_id).to_dict(detail=True)

    @classmethod
    def list_by_task(cls, task):
        """任务反查：该任务关联的全部更换明细。

        优先走更换记录自身的 task_id（含来源快照）；同时兼容历史数据——
        旧记录经养护记录的 task_id 间接关联，用 outerjoin 一并查出，OR 条件不会重复。
        """

        return (
            db.session.query(PlantReplacement)
            .outerjoin(MaintenanceRecord, PlantReplacement.maintenance_record_id == MaintenanceRecord.id)
            .options(
                selectinload(PlantReplacement.record).selectinload(MaintenanceRecord.task),
                selectinload(PlantReplacement.task),
            )
            .filter(
                or_(
                    PlantReplacement.task_id == task.id,
                    MaintenanceRecord.task_id == task.id,
                )
            )
            .order_by(PlantReplacement.replace_date.desc(), PlantReplacement.id.desc())
            .all()
        )

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

    # ------------------------------------------------------------ 费用归属
    @staticmethod
    def _period_key(day, group_by):
        if group_by == "year":
            return f"{day:%Y}", f"{day:%Y}年"
        if group_by == "quarter":
            quarter = (day.month - 1) // 3 + 1
            return f"{day:%Y}-Q{quarter}", f"{day:%Y}年第{quarter}季度"
        return f"{day:%Y-%m}", f"{day:%Y}年{day.month}月"

    @classmethod
    def cost_report(cls, filters, group_by="month"):
        """更换费用按「绿地 × 时间段」归属。

        明细在 Python 侧聚合（与看板趋势口径一致），SQLite / PostgreSQL 行为相同；
        筛选条件与更换列表完全一致，保证报表金额可下钻到同一批明细。
        """

        group_by = group_by if group_by in {"month", "quarter", "year"} else "month"
        rows = (
            cls._apply_filters(
                db.session.query(
                    PlantReplacement.green_space_id,
                    PlantReplacement.replace_date,
                    PlantReplacement.quantity,
                    PlantReplacement.amount,
                ),
                filters,
            )
            .order_by(PlantReplacement.replace_date.asc())
            .all()
        )
        if not rows:
            return {
                "group_by": group_by,
                "green_space_count": 0,
                "total_count": 0,
                "total_quantity": 0.0,
                "total_amount": 0.0,
                "items": [],
            }

        spaces = {
            item.id: item
            for item in db.session.query(GreenSpace)
            .filter(GreenSpace.id.in_({row[0] for row in rows}))
            .all()
        }

        buckets = {}
        for space_id, day, quantity, amount in rows:
            period, period_label = cls._period_key(day, group_by)
            key = (space_id, period)
            bucket = buckets.setdefault(
                key,
                {
                    "green_space_id": space_id,
                    "code": None,
                    "name": None,
                    "district": None,
                    "period": period,
                    "period_label": period_label,
                    "count": 0,
                    "quantity": 0.0,
                    "amount": 0.0,
                },
            )
            space = spaces.get(space_id)
            if space is not None:
                bucket["code"] = space.code
                bucket["name"] = space.name
                bucket["district"] = space.district
            bucket["count"] += 1
            bucket["quantity"] = round(bucket["quantity"] + float(quantity or 0), 2)
            bucket["amount"] = round(bucket["amount"] + float(amount or 0), 2)

        # 先按时间段正序，同一时间段内金额高的绿地在前
        items = sorted(buckets.values(), key=lambda item: (item["period"], -item["amount"]))

        return {
            "group_by": group_by,
            "green_space_count": len({item["green_space_id"] for item in items}),
            "total_count": sum(item["count"] for item in items),
            "total_quantity": round(sum(item["quantity"] for item in items), 2),
            "total_amount": round(sum(item["amount"] for item in items), 2),
            "items": items,
        }

    # ------------------------------------------------------------ 批量导入
    @classmethod
    def import_batch(cls, payload):
        """以 batch_no 为幂等键批量导入更换明细。

        - 同一 batch_no 重复提交：直接重放首次结果，不二次入账；
        - 批次内 / 跨批次内容重复：按内容指纹跳过，只入账一次；
        - 任一行校验失败不影响其它行，错误按行号返回。
        """

        batch_no = (payload.get("batch_no") or "").strip()
        if not batch_no:
            raise ValidationError("导入失败", details={"batch_no": "请提供批次号作为幂等键"})
        if len(batch_no) > 64:
            raise ValidationError("导入失败", details={"batch_no": "批次号长度不能超过 64 个字符"})

        existing = (
            db.session.query(PlantReplacementImportBatch)
            .filter(PlantReplacementImportBatch.batch_no == batch_no)
            .one_or_none()
        )
        if existing is not None:
            # 幂等重放：整批已处理过，原样返回首次结果
            return existing.to_dict(), True

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ValidationError("导入失败", details={"items": "请提供至少一条更换明细"})
        if len(raw_items) > 1000:
            raise ValidationError("导入失败", details={"items": "单次导入不能超过 1000 条"})

        source = str(payload.get("source") or "manual").strip()[:32] or "manual"

        batch = PlantReplacementImportBatch(batch_no=batch_no, source=source, total_rows=len(raw_items))
        db.session.add(batch)
        try:
            db.session.flush()
        except IntegrityError as exc:
            # 并发提交相同批次号：后到者按幂等重放处理
            db.session.rollback()
            if "batch_no" not in str(getattr(exc, "orig", exc)):
                raise
            existing = (
                db.session.query(PlantReplacementImportBatch)
                .filter(PlantReplacementImportBatch.batch_no == batch_no)
                .one_or_none()
            )
            if existing is not None:
                return existing.to_dict(), True
            raise ConflictError("批次号与已有记录冲突，请更换后重试") from exc

        imported, duplicates, failures = [], [], []
        seen_fingerprints = set()

        for index, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, dict):
                failures.append({"row": index, "errors": {"_": "该行必须是 JSON 对象"}})
                continue
            try:
                data = cls._validate_import_row(raw)
            except ValidationError as exc:
                failures.append({"row": index, "errors": exc.details})
                continue

            fingerprint = content_fingerprint(data)
            if fingerprint in seen_fingerprints:
                duplicates.append({"row": index, "reason": "同一批次内重复"})
                continue
            if (
                db.session.query(PlantReplacement.id)
                .filter(PlantReplacement.content_fingerprint == fingerprint)
                .first()
                is not None
            ):
                duplicates.append({"row": index, "reason": "与已入账记录内容重复"})
                seen_fingerprints.add(fingerprint)
                continue

            replacement, error = cls._insert_import_row(batch.id, data, fingerprint)
            if error is not None:
                if error == "duplicate":
                    duplicates.append({"row": index, "reason": "与已入账记录内容重复"})
                    seen_fingerprints.add(fingerprint)
                else:
                    failures.append({"row": index, "errors": error})
                continue

            seen_fingerprints.add(fingerprint)
            imported.append({"row": index, "replacement_no": replacement.replacement_no})

        batch.imported_count = len(imported)
        batch.duplicate_count = len(duplicates)
        batch.failed_count = len(failures)
        batch.result_detail = {"imported": imported, "duplicates": duplicates, "failures": failures}
        db.session.commit()
        return batch.to_dict(), False

    @staticmethod
    def _validate_import_row(raw):
        from ..schemas.plant_replacement import validate_plant_replacement

        return validate_plant_replacement(raw)

    @classmethod
    def _insert_import_row(cls, batch_id, data, fingerprint):
        """单行写入独立 savepoint，行级唯一冲突不拖垮整批。"""

        data = dict(data)
        for _ in range(cls.MAX_CODE_RETRY):
            data["replacement_no"] = cls.generate_code()
            instance = cls.model(**data)
            cls.prepare_instance(instance, data)
            cls.apply_derived(instance)
            instance.import_batch_id = batch_id
            instance.content_fingerprint = fingerprint
            savepoint = db.session.begin_nested()
            try:
                db.session.add(instance)
                db.session.flush()
                return instance, None
            except IntegrityError as exc:
                savepoint.rollback()
                # SQLite/PostgreSQL 的唯一冲突信息里都带列名或约束名
                message = str(getattr(exc, "orig", exc))
                if "content_fingerprint" in message:
                    return None, "duplicate"
                if "replacement_no" in message:
                    continue  # 编号冲突，换号重试
                return None, {"_": "该行写入失败，请检查数据是否与已有记录冲突"}
        return None, {"_": "编号生成冲突，请稍后重试"}
