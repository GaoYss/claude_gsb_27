"""绿植更换批量导入测试：幂等、行级校验与费用归集口径。"""


def import_payload(space_id, batch_no="IMP-20260918-001", lines=2, **overrides):
    items = []
    for n in range(1, lines + 1):
        items.append({
            "line_no": str(n),
            "green_space_id": space_id,
            "plant_name": f"香樟-{n}",
            "plant_category": "tree",
            "quantity": 10,
            "unit": "plant",
            "reason": "dead",
            "replace_date": "2026-03-15",
            "supplier": "萧山苗木合作社",
            "unit_price": 100,
            "operator": "王海涛",
        })
    payload = {"batch_no": batch_no, "items": items}
    payload.update(overrides)
    return payload


def test_import_creates_rows_with_batch_marks(api, make_space):
    space = make_space()
    data = api.data(api.post("/api/v1/plant-replacements/imports",
                             import_payload(space.id)), 200)
    assert data["batch_no"] == "IMP-20260918-001"
    assert data["total"] == 2
    assert data["created_count"] == 2
    assert data["skipped_count"] == 0
    assert [item["status"] for item in data["items"]] == ["created", "created"]
    assert all(item["replacement_no"].startswith("PR-") for item in data["items"])

    # 批次信息随记录落库，可顺查来源
    first = api.data(api.get(f"/api/v1/plant-replacements/{data['items'][0]['id']}"))
    assert first["import_batch"] == "IMP-20260918-001"
    assert first["import_line"] == "1"
    assert first["amount"] == 1000.0


def test_reimport_same_batch_is_not_counted_twice(api, make_space):
    space = make_space()
    body = import_payload(space.id)
    first = api.data(api.post("/api/v1/plant-replacements/imports", body), 200)
    assert first["created_count"] == 2

    # 同一批重复导入：全部跳过，费用归集不翻倍
    second = api.data(api.post("/api/v1/plant-replacements/imports", body), 200)
    assert second["created_count"] == 0
    assert second["skipped_count"] == 2
    assert [item["replacement_no"] for item in second["items"]] == [
        item["replacement_no"] for item in first["items"]
    ]

    summary = api.data(api.get("/api/v1/plant-replacements/summary"))
    assert summary["total_count"] == 2
    assert summary["total_amount"] == 2000.0
    cost = api.data(api.get("/api/v1/plant-replacements/cost-summary"))
    assert cost["by_green_space"][0]["amount"] == 2000.0


def test_reimport_with_extra_lines_only_creates_new_ones(api, make_space):
    space = make_space()
    api.data(api.post("/api/v1/plant-replacements/imports",
                      import_payload(space.id, lines=2)), 200)

    replay = import_payload(space.id, lines=2)
    replay["items"].append({
        "line_no": "3",
        "green_space_id": space.id,
        "plant_name": "红叶石楠",
        "plant_category": "shrub",
        "quantity": 5,
        "reason": "supplement",
        "replace_date": "2026-03-16",
        "unit_price": 40,
    })
    data = api.data(api.post("/api/v1/plant-replacements/imports", replay), 200)
    assert [item["status"] for item in data["items"]] == ["skipped", "skipped", "created"]

    summary = api.data(api.get("/api/v1/plant-replacements/summary"))
    assert summary["total_count"] == 3
    assert summary["total_amount"] == 2200.0


def test_import_with_invalid_line_rolls_back_whole_batch(api, make_space):
    space = make_space()
    body = import_payload(space.id)
    body["items"][1]["quantity"] = 0  # 第二行数量非法
    response = api.post("/api/v1/plant-replacements/imports", body)
    assert response.status_code == 422
    items = response.get_json()["data"]["items"]
    assert items[0]["line_no"] == "2"
    assert "quantity" in items[0]["errors"]

    # 整批未写入，包括合法的第一行
    listing = api.data(api.get("/api/v1/plant-replacements"))
    assert listing["meta"]["total"] == 0


def test_import_validates_business_rules_per_line(api, make_space, make_record):
    space = make_space()
    record = make_record()  # 属于另一块绿地
    body = import_payload(space.id, lines=1)
    body["items"][0]["maintenance_record_id"] = record.id
    response = api.post("/api/v1/plant-replacements/imports", body)
    assert response.status_code == 422
    assert "不属于所选绿地" in response.get_json()["data"]["items"][0]["errors"][
        "maintenance_record_id"
    ]
    assert api.data(api.get("/api/v1/plant-replacements"))["meta"]["total"] == 0


def test_import_rejects_duplicate_line_no_in_same_batch(api, make_space):
    space = make_space()
    body = import_payload(space.id)
    body["items"][1]["line_no"] = body["items"][0]["line_no"]
    response = api.post("/api/v1/plant-replacements/imports", body)
    assert response.status_code == 422
    assert "重复" in response.get_json()["data"]["items"][0]["errors"]["line_no"]


def test_import_requires_batch_no_and_items(api, make_space):
    space = make_space()
    response = api.post("/api/v1/plant-replacements/imports",
                        {"batch_no": "", "items": []})
    assert response.status_code == 422
    assert "batch_no" in response.get_json()["data"]

    response = api.post("/api/v1/plant-replacements/imports",
                        {"batch_no": "IMP-X", "items": []})
    assert response.status_code == 422
    assert "items" in response.get_json()["data"]


def test_list_filters_by_import_batch(api, make_space, make_replacement):
    space = make_space()
    api.data(api.post("/api/v1/plant-replacements/imports",
                      import_payload(space.id, batch_no="IMP-A")), 200)
    api.data(api.post("/api/v1/plant-replacements/imports",
                      import_payload(space.id, batch_no="IMP-B", lines=1)), 200)
    make_replacement(space=space)  # 手动登记，无批次

    data = api.data(api.get("/api/v1/plant-replacements", import_batch="IMP-A"))
    assert data["meta"]["total"] == 2
    assert {item["import_batch"] for item in data["items"]} == {"IMP-A"}

    # 不同批次互不影响；手动登记记录不带批次
    assert api.data(api.get("/api/v1/plant-replacements", import_batch="IMP-B"))[
        "meta"
    ]["total"] == 1
    manual = api.data(api.get("/api/v1/plant-replacements"))
    assert manual["meta"]["total"] == 4
