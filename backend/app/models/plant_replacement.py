"""绿植更换记录模型。"""

from ..constants import MEASURE_UNIT, OLD_PLANT_STATUS, PLANT_CATEGORY, REPLACEMENT_REASON
from ..extensions import db
from ..utils.dates import format_date, format_datetime
from ..utils.numbers import to_float
from .mixins import TimestampMixin, amount_column, quantity_column


class PlantReplacement(TimestampMixin, db.Model):
    """绿植更换记录：绿地内植株的更换、补植与品种改造。

    关联与溯源策略：

    - ``green_space_id``：必填，费用与统计一律归属到具体绿地；
    - ``maintenance_record_id`` / ``task_id``：可空外键，养护记录或任务被删除时
      由 service 层显式置空（跨 SQLite/PostgreSQL 行为一致），更换记录本身保留；
    - ``record_snapshot_no`` / ``task_snapshot_*``：登记时冻结的来源编号与名称快照。
      外键仍在时快照随关联一起更新；来源被删除后外键置空、快照保留，
      因此「这条更换来自哪次作业」始终可查，不会因删任务而变得含糊。
    """

    __tablename__ = "plant_replacement"

    id = db.Column(db.Integer, primary_key=True)
    replacement_no = db.Column(db.String(32), nullable=False, unique=True, index=True)
    green_space_id = db.Column(
        db.Integer, db.ForeignKey("green_space.id", ondelete="CASCADE"), nullable=False, index=True
    )
    maintenance_record_id = db.Column(
        db.Integer,
        db.ForeignKey("maintenance_record.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("maintenance_task.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 来源快照：外键置空后仍能说明更换明细的出处
    record_snapshot_no = db.Column(db.String(32))
    task_snapshot_no = db.Column(db.String(32))
    task_snapshot_title = db.Column(db.String(128))
    # 幂等批量导入归属（见 PlantReplacementImportBatch），手工登记时为空
    import_batch_id = db.Column(
        db.Integer,
        db.ForeignKey("plant_replacement_import_batch.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 明细内容指纹：同内容的更换明细（含绿地、植株、规格、数量、日期、供苗单位等）
    # 全局只入账一次，作为批次号幂等之外的第二道去重保险
    content_fingerprint = db.Column(db.String(64), nullable=True, unique=True, index=True)

    plant_name = db.Column(db.String(96), nullable=False, index=True)
    plant_category = db.Column(db.String(32), nullable=False, index=True)
    spec = db.Column(db.String(64))
    quantity = db.Column(quantity_column(), nullable=False, default=0)
    unit = db.Column(db.String(16), nullable=False, default="plant")
    reason = db.Column(db.String(32), nullable=False, index=True)
    old_plant_status = db.Column(db.String(16))
    replace_date = db.Column(db.Date, nullable=False, index=True)
    supplier = db.Column(db.String(96))
    unit_price = db.Column(amount_column())
    amount = db.Column(amount_column())
    operator = db.Column(db.String(64))
    remark = db.Column(db.Text)

    green_space = db.relationship("GreenSpace", back_populates="replacements", lazy="joined")
    record = db.relationship(
        "MaintenanceRecord", back_populates="replacements", foreign_keys=[maintenance_record_id]
    )
    task = db.relationship("MaintenanceTask", back_populates="replacements", foreign_keys=[task_id])
    # joined：列表/详情每行都要带出批次号，避免 N+1；裸列聚合查询不受影响
    import_batch = db.relationship("PlantReplacementImportBatch", back_populates="replacements", lazy="joined")

    def _record_brief(self):
        if self.record is None:
            return None
        return {
            "id": self.record.id,
            "record_no": self.record.record_no,
            "record_date": format_date(self.record.record_date),
            "task_id": self.record.task_id,
            "task_no": self.record.task.task_no if self.record.task else None,
        }

    def _task_brief(self):
        if self.task is None:
            return None
        return {
            "id": self.task.id,
            "task_no": self.task.task_no,
            "title": self.task.title,
            "status": self.task.status,
        }

    def to_dict(self, detail=False):
        data = {
            "id": self.id,
            "replacement_no": self.replacement_no,
            "green_space_id": self.green_space_id,
            "green_space": self.green_space.to_brief() if self.green_space else None,
            "maintenance_record_id": self.maintenance_record_id,
            "record": self._record_brief(),
            # 养护记录已删除但更换记录保留时，用快照说明出处
            "record_snapshot": (
                {"record_no": self.record_snapshot_no, "deleted": True}
                if self.record is None and self.record_snapshot_no
                else None
            ),
            "task_id": self.task_id,
            "task": self._task_brief(),
            # 任务已删除时 task_id 置空、快照保留，明确「原属哪个任务」
            "task_snapshot": (
                {
                    "task_no": self.task_snapshot_no,
                    "title": self.task_snapshot_title,
                    "deleted": True,
                }
                if self.task is None and self.task_snapshot_no
                else None
            ),
            "plant_name": self.plant_name,
            "plant_category": self.plant_category,
            "plant_category_label": PLANT_CATEGORY.label(self.plant_category),
            "spec": self.spec,
            "quantity": to_float(self.quantity),
            "unit": self.unit,
            "unit_label": MEASURE_UNIT.label(self.unit),
            "reason": self.reason,
            "reason_label": REPLACEMENT_REASON.label(self.reason),
            "old_plant_status": self.old_plant_status,
            "old_plant_status_label": (
                OLD_PLANT_STATUS.label(self.old_plant_status) if self.old_plant_status else None
            ),
            "replace_date": format_date(self.replace_date),
            "supplier": self.supplier,
            "unit_price": to_float(self.unit_price),
            "amount": to_float(self.amount),
            "operator": self.operator,
            "import_batch_id": self.import_batch_id,
            "import_batch_no": self.import_batch.batch_no if self.import_batch else None,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
        if detail:
            data["remark"] = self.remark
        return data


class PlantReplacementImportBatch(TimestampMixin, db.Model):
    """绿植更换批量导入批次：以 batch_no 作为幂等键。

    同一批次号重复提交时整批重放，直接返回首次结果，不会二次入账；
    批次内再按明细指纹去重，跨批次的重复内容也只入账一次。
    """

    __tablename__ = "plant_replacement_import_batch"

    id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(64), nullable=False, unique=True, index=True)
    source = db.Column(db.String(32), nullable=False, default="manual")
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    imported_count = db.Column(db.Integer, nullable=False, default=0)
    duplicate_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    result_detail = db.Column(db.JSON)
    remark = db.Column(db.String(255))

    replacements = db.relationship("PlantReplacement", back_populates="import_batch")

    def to_dict(self):
        return {
            "id": self.id,
            "batch_no": self.batch_no,
            "source": self.source,
            "total_rows": self.total_rows,
            "imported_count": self.imported_count,
            "duplicate_count": self.duplicate_count,
            "failed_count": self.failed_count,
            "result_detail": self.result_detail,
            "remark": self.remark,
            "created_at": format_datetime(self.created_at),
        }
