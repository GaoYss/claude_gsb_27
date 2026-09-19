"""绿植更换关联与溯源测试：绿地 / 养护记录 / 任务 / 登记人 / 供苗单位双向可查。"""

from datetime import date


def base_row(space_id, **overrides):
    row = {
        "green_space_id": space_id,
        "plant_name": "香樟",
        "plant_category": "tree",
        "quantity": 10,
        "unit": "plant",
        "reason": "dead",
        "replace_date": "2026-03-15",
        "supplier": "萧山苗木合作社",
        "unit_price": 128.5,
        "operator": "王海涛",
    }
    row.update(overrides)
    return row


# ------------------------------------------------------------ 顺向关联
def test_replacement_detail_links_space_record_task(api, make_space, make_task, make_record):
    space = make_space()
    task = make_task(space=space)
    record = make_record(task=task)
    data = api.data(api.post("/api/v1/plant-replacements",
                             base_row(space.id, maintenance_record_id=record.id)), 201)

    # 绿地
    assert data["green_space"] == {"id": space.id, "code": space.code,
                                   "name": space.name, "district": space.district}
    # 养护记录
    assert data["record"]["id"] == record.id
    assert data["record"]["record_no"] == record.record_no
    assert data["record"]["task_id"] == task.id
    # 任务（经养护记录自动带出）
    assert data["task_id"] == task.id
    assert data["task"]["task_no"] == task.task_no
    assert data["task"]["title"] == task.title
    # 登记人与供苗单位
    assert data["operator"] == "王海涛"
    assert data["supplier"] == "萧山苗木合作社"


def test_replacement_without_record_has_no_task(api, make_space):
    space = make_space()
    data = api.data(api.post("/api/v1/plant-replacements", base_row(space.id)), 201)
    assert data["record"] is None
    assert data["task"] is None
    assert data["task_snapshot"] is None


# ------------------------------------------------------------ 反向查询
def test_task_detail_returns_replacement_items(api, make_task, make_record, make_replacement):
    task = make_task()
    record = make_record(task=task)
    make_replacement(record=record, quantity=10, unit_price=100, plant_name="香樟",
                     supplier="临安绿源苗圃")
    make_replacement(record=record, quantity=5, unit_price=200, plant_name="桂花",
                     supplier="临安绿源苗圃")

    data = api.data(api.get(f"/api/v1/maintenance-tasks/{task.id}"))
    assert data["progress"]["replacement_count"] == 2
    assert data["progress"]["replacement_quantity"] == 15.0
    assert data["progress"]["replacement_amount"] == 2000.0
    assert {item["plant_name"] for item in data["replacements"]} == {"香樟", "桂花"}
    # 明细里能拿到绿地与供苗单位
    first = data["replacements"][0]
    assert first["green_space_id"] == task.green_space_id
    assert first["supplier"]


def test_replacement_list_filters_by_task(api, make_task, make_record, make_replacement):
    task = make_task()
    record = make_record(task=task)
    make_replacement(record=record)
    make_replacement()  # 无关更换

    data = api.data(api.get("/api/v1/plant-replacements", task_id=task.id))
    assert data["meta"]["total"] == 1
    assert data["items"][0]["task_id"] == task.id


def test_task_list_progress_counts_replacements(api, make_task, make_record, make_replacement):
    task = make_task()
    record = make_record(task=task)
    make_replacement(record=record)

    data = api.data(api.get("/api/v1/maintenance-tasks", green_space_id=task.green_space_id))
    progress = data["items"][0]["progress"]
    assert progress["record_count"] == 1
    assert progress["replacement_count"] == 1


# ------------------------------------------------------------ 删除后的溯源
def test_delete_record_keeps_record_snapshot(api, make_record, make_replacement):
    record = make_record()
    replacement = make_replacement(record=record)

    api.delete(f"/api/v1/maintenance-records/{record.id}")

    data = api.data(api.get(f"/api/v1/plant-replacements/{replacement.id}"))
    assert data["maintenance_record_id"] is None
    assert data["record"] is None
    # 记录编号快照保留，出处不含糊
    assert data["record_snapshot"] == {"record_no": record.record_no, "deleted": True}
    # 更换记录本身仍在、仍归属绿地
    assert data["green_space_id"] == replacement.green_space_id


def test_reassign_record_task_updates_replacement_task(api, make_space, make_task, make_record, make_replacement):
    space = make_space()
    first_task = make_task(space=space, title="第一个任务")
    second_task = make_task(space=space, title="第二个任务")
    record = make_record(task=first_task)
    replacement = make_replacement(record=record)
    assert replacement.task_id == first_task.id

    # 把养护记录改挂到另一个任务
    api.put(f"/api/v1/maintenance-records/{record.id}", {
        "task_id": second_task.id,
        "record_date": "2026-03-12",
        "work_content": "改挂任务的养护记录",
        "quality_result": "qualified",
    })

    data = api.data(api.get(f"/api/v1/plant-replacements/{replacement.id}"))
    assert data["task_id"] == second_task.id
    assert data["task"]["task_no"] == second_task.task_no


# ------------------------------------------------------------ 费用归属
def test_cost_report_attributes_amount_to_green_space_and_period(api, make_space, make_replacement):
    first = make_space(name="甲绿地")
    second = make_space(name="乙绿地")
    make_replacement(space=first, replace_date=date(2026, 1, 10), quantity=10, unit_price=100)
    make_replacement(space=first, replace_date=date(2026, 1, 20), quantity=5, unit_price=200)
    make_replacement(space=second, replace_date=date(2026, 2, 5), quantity=2, unit_price=500)

    report = api.data(api.get("/api/v1/plant-replacements/cost-report", group_by="month"))
    assert report["total_amount"] == 3000.0
    assert report["green_space_count"] == 2

    by_key = {(item["name"], item["period"]): item for item in report["items"]}
    assert by_key[("甲绿地", "2026-01")]["amount"] == 2000.0
    assert by_key[("甲绿地", "2026-01")]["count"] == 2
    assert by_key[("乙绿地", "2026-02")]["amount"] == 1000.0

    # 按季聚合：1、2 月同在第一季度，但仍按绿地分开
    quarterly = api.data(api.get("/api/v1/plant-replacements/cost-report", group_by="quarter"))
    keys = {(item["name"], item["period"]) for item in quarterly["items"]}
    assert ("甲绿地", "2026-Q1") in keys
    assert ("乙绿地", "2026-Q1") in keys

    # 筛选单处绿地后只归属该绿地
    scoped = api.data(api.get("/api/v1/plant-replacements/cost-report",
                              green_space_id=first.id, group_by="month"))
    assert scoped["total_amount"] == 2000.0
    assert {item["green_space_id"] for item in scoped["items"]} == {first.id}


def test_cost_report_empty_result(api):
    report = api.data(api.get("/api/v1/plant-replacements/cost-report"))
    assert report["items"] == []
    assert report["total_amount"] == 0.0


# ------------------------------------------------------------ 幂等导入
def test_import_batch_is_idempotent_and_dedups(api, make_space):
    space = make_space()
    payload = {
        "batch_no": "IMP-20260410-01",
        "source": "excel",
        "items": [
            base_row(space.id, quantity=10),
            base_row(space.id, quantity=10),                 # 同批重复
            base_row(space.id, quantity=20, plant_name="桂花"),
            {"plant_name": "缺少必填字段的坏行"},
        ],
    }
    first = api.data(api.post("/api/v1/plant-replacements/import", payload), 201)
    assert first["imported_count"] == 2
    assert first["duplicate_count"] == 1
    assert first["failed_count"] == 1
    assert first["result_detail"]["failures"][0]["row"] == 4

    # 同批次号整批重放，不二次入账（幂等重放走 200）
    replay = api.data(api.post("/api/v1/plant-replacements/import", payload))
    assert replay["id"] == first["id"]
    assert replay["imported_count"] == 2

    listing = api.data(api.get("/api/v1/plant-replacements", green_space_id=space.id))
    assert listing["meta"]["total"] == 2


def test_import_cross_batch_content_dedup(api, make_space):
    space = make_space()
    batch_one = {"batch_no": "B1", "items": [base_row(space.id, quantity=10)]}
    api.data(api.post("/api/v1/plant-replacements/import", batch_one), 201)

    # 不同批次号，但内容与已入账记录完全相同 → 判重；另一条新内容入账
    batch_two = {
        "batch_no": "B2",
        "items": [
            base_row(space.id, quantity=10),
            base_row(space.id, quantity=30, plant_name="玉兰"),
        ],
    }
    result = api.data(api.post("/api/v1/plant-replacements/import", batch_two), 201)
    assert result["imported_count"] == 1
    assert result["duplicate_count"] == 1

    listing = api.data(api.get("/api/v1/plant-replacements", green_space_id=space.id))
    assert listing["meta"]["total"] == 2


def test_import_requires_batch_no(api, make_space):
    space = make_space()
    response = api.post("/api/v1/plant-replacements/import",
                        {"items": [base_row(space.id)]})
    assert response.status_code == 422
    assert "batch_no" in response.get_json()["data"]


def test_imported_replacement_is_tagged_with_batch(api, make_space):
    space = make_space()
    result = api.data(api.post("/api/v1/plant-replacements/import", {
        "batch_no": "BATCH-TAG-1",
        "items": [base_row(space.id)],
    }), 201)
    replacement_no = result["result_detail"]["imported"][0]["replacement_no"]

    listing = api.data(api.get("/api/v1/plant-replacements", green_space_id=space.id))
    row = listing["items"][0]
    assert row["replacement_no"] == replacement_no
    assert row["import_batch_no"] == "BATCH-TAG-1"
