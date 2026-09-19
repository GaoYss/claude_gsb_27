"""绿植更换记录接口测试。"""

from datetime import date


def replacement_payload(space_id, **overrides):
    payload = {
        "green_space_id": space_id,
        "plant_name": "红叶石楠",
        "plant_category": "shrub",
        "spec": "冠幅 80-100cm",
        "quantity": 24,
        "unit": "plant",
        "reason": "dead",
        "old_plant_status": "dead",
        "replace_date": "2026-03-16",
        "supplier": "萧山苗木合作社",
        "unit_price": 88.5,
        "operator": "王海涛",
    }
    payload.update(overrides)
    return payload


def test_create_replacement_computes_amount(api, make_space):
    space = make_space()
    data = api.data(api.post("/api/v1/plant-replacements", replacement_payload(space.id)), 201)
    assert data["replacement_no"].startswith("PR-")
    assert data["quantity"] == 24.0
    assert data["amount"] == 2124.0
    assert data["plant_category_label"] == "灌木"
    assert data["reason_label"] == "枯死更换"
    assert data["unit_label"] == "株"


def test_amount_is_empty_without_unit_price(api, make_space):
    space = make_space()
    data = api.data(api.post("/api/v1/plant-replacements",
                             replacement_payload(space.id, unit_price=None)), 201)
    assert data["unit_price"] is None
    assert data["amount"] is None


def test_quantity_and_category_are_validated(api, make_space):
    space = make_space()
    response = api.post("/api/v1/plant-replacements",
                        replacement_payload(space.id, quantity=0, plant_category="bonsai"))
    assert response.status_code == 422
    details = response.get_json()["data"]
    assert "quantity" in details and "plant_category" in details


def test_record_must_belong_to_same_green_space(api, make_record, make_space):
    record = make_record()
    other_space = make_space(name="无关绿地")
    response = api.post("/api/v1/plant-replacements",
                        replacement_payload(other_space.id, maintenance_record_id=record.id))
    assert response.status_code == 422
    assert "不属于所选绿地" in response.get_json()["data"]["maintenance_record_id"]


def test_update_recomputes_amount(api, make_replacement):
    replacement = make_replacement()
    data = api.data(api.put(f"/api/v1/plant-replacements/{replacement.id}", {
        "green_space_id": replacement.green_space_id,
        "plant_name": replacement.plant_name,
        "plant_category": replacement.plant_category,
        "quantity": 50,
        "unit": "plant",
        "reason": replacement.reason,
        "replace_date": "2026-03-20",
        "unit_price": 10,
    }))
    assert data["quantity"] == 50.0
    assert data["amount"] == 500.0
    assert data["replace_date"] == "2026-03-20"


def test_summary_groups_by_category_and_reason(api, make_replacement):
    make_replacement(quantity=10, unit_price=100, plant_category="tree", reason="dead")
    make_replacement(quantity=20, unit_price=50, plant_category="tree", reason="aging")
    make_replacement(quantity=5, unit_price=20, plant_category="shrub", reason="dead")

    data = api.data(api.get("/api/v1/plant-replacements/summary"))
    assert data["total_count"] == 3
    assert data["total_quantity"] == 35.0
    assert data["total_amount"] == 2100.0

    by_category = {item["value"]: item for item in data["by_category"]}
    assert by_category["tree"]["count"] == 2
    assert by_category["tree"]["quantity"] == 30.0
    assert by_category["shrub"]["amount"] == 100.0

    by_reason = {item["value"]: item for item in data["by_reason"]}
    assert by_reason["dead"]["count"] == 2
    assert by_reason["aging"]["quantity"] == 20.0


def test_list_filters_by_green_space_and_reason(api, make_replacement, make_space):
    space = make_space(name="目标绿地")
    make_replacement(space=space, reason="dead")
    make_replacement(space=space, reason="upgrade")
    make_replacement()

    data = api.data(api.get("/api/v1/plant-replacements", green_space_id=space.id,
                            reason="upgrade"))
    assert data["meta"]["total"] == 1
    assert data["items"][0]["reason"] == "upgrade"


def test_delete_replacement(api, make_replacement):
    replacement = make_replacement()
    api.delete(f"/api/v1/plant-replacements/{replacement.id}")
    assert api.get(f"/api/v1/plant-replacements/{replacement.id}").status_code == 404


def test_detail_traces_record_and_task(api, make_task, make_record, make_replacement):
    """顺查链路：更换记录 → 养护记录 → 任务，一跳都不能断。"""

    task = make_task()
    record = make_record(task=task)
    replacement = make_replacement(record=record, supplier="萧山苗木合作社", operator="王海涛")

    data = api.data(api.get(f"/api/v1/plant-replacements/{replacement.id}"))
    assert data["green_space"]["id"] == task.green_space_id
    assert data["record"]["record_no"] == record.record_no
    assert data["record"]["task"]["task_no"] == task.task_no
    assert data["supplier"] == "萧山苗木合作社"
    assert data["operator"] == "王海涛"


def test_list_filters_by_task(api, make_task, make_record, make_replacement):
    task = make_task()
    record = make_record(task=task)
    linked = make_replacement(record=record)
    make_replacement(space=task.green_space)  # 同绿地但未关联任务
    make_replacement()  # 其他绿地

    data = api.data(api.get("/api/v1/plant-replacements", task_id=task.id))
    assert data["meta"]["total"] == 1
    assert data["items"][0]["id"] == linked.id


def test_cost_summary_groups_by_space_and_month(api, make_space, make_replacement):
    space_a = make_space(name="滨河公园")
    space_b = make_space(name="文体中心绿地")
    make_replacement(space=space_a, quantity=10, unit_price=100, replace_date=date(2026, 3, 5))
    make_replacement(space=space_a, quantity=4, unit_price=50, replace_date=date(2026, 4, 11))
    make_replacement(space=space_b, quantity=6, unit_price=80, replace_date=date(2026, 3, 20))

    data = api.data(api.get("/api/v1/plant-replacements/cost-summary"))

    by_space = {item["name"]: item for item in data["by_green_space"]}
    assert by_space["滨河公园"]["count"] == 2
    assert by_space["滨河公园"]["amount"] == 1200.0
    assert by_space["文体中心绿地"]["amount"] == 480.0

    by_month = {item["month"]: item for item in data["by_month"]}
    assert by_month["2026-03"]["count"] == 2
    assert by_month["2026-03"]["amount"] == 1480.0
    assert by_month["2026-04"]["amount"] == 200.0


def test_cost_summary_respects_date_and_space_filters(api, make_space, make_replacement):
    space_a = make_space(name="滨河公园")
    make_replacement(space=space_a, quantity=10, unit_price=100, replace_date=date(2026, 3, 5))
    make_replacement(space=space_a, quantity=4, unit_price=50, replace_date=date(2026, 5, 11))
    make_replacement(quantity=6, unit_price=80, replace_date=date(2026, 3, 20))

    data = api.data(api.get(
        "/api/v1/plant-replacements/cost-summary",
        green_space_id=space_a.id,
        date_from="2026-03-01",
        date_to="2026-03-31",
    ))
    assert len(data["by_green_space"]) == 1
    assert data["by_green_space"][0]["amount"] == 1000.0
    assert [item["month"] for item in data["by_month"]] == ["2026-03"]
