import pytest

from conftest import make_order


def payload(**kwargs):
    base = {"title": "取快递", "pickup": "菜鸟驿站", "dropoff": "3栋201", "fee": "8.50", "timeout_minutes": 30}
    base.update(kwargs)
    return base


def test_create_order(api, student):
    r = api.post("/api/orders", token=student["token"], json=payload())
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "pending"
    assert data["fee"] == "8.50"
    assert data["requester_id"] == student["id"]
    assert data["courier_id"] is None


def test_order_no_format(api, student):
    r = api.post("/api/orders", token=student["token"], json=payload())
    no = r.json()["data"]["order_no"]
    assert no.startswith("CX")
    assert len(no) == 16
    assert no[2:10].isdigit()


def test_fee_boundary_min(api, student):
    r = api.post("/api/orders", token=student["token"], json=payload(fee="1.00"))
    assert r.status_code == 200
    assert r.json()["data"]["fee"] == "1.00"


def test_fee_boundary_max(api, student):
    api.post("/api/wallet/recharge", token=student["token"], json={"amount": "300.00"})
    r = api.post("/api/orders", token=student["token"], json=payload(fee="500.00"))
    assert r.status_code == 200


@pytest.mark.parametrize("fee", ["0.99", "500.01", "-1.00"])
def test_fee_out_of_range(api, student, fee):
    r = api.post("/api/orders", token=student["token"], json=payload(fee=fee))
    assert r.status_code == 400
    assert r.json()["code"] == 40004


@pytest.mark.parametrize("fee", ["8.505", "abc", None])
def test_fee_bad_format(api, student, fee):
    r = api.post("/api/orders", token=student["token"], json=payload(fee=fee))
    assert r.status_code == 400
    assert r.json()["code"] == 40002


def test_timeout_boundary_min(api, student):
    r = api.post("/api/orders", token=student["token"], json=payload(timeout_minutes=10))
    assert r.status_code == 200


@pytest.mark.parametrize("minutes", [9, 181, 0])
def test_timeout_out_of_range(api, student, minutes):
    r = api.post("/api/orders", token=student["token"], json=payload(timeout_minutes=minutes))
    assert r.status_code == 400
    assert r.json()["code"] == 40004


@pytest.mark.parametrize(
    "field,value",
    [("title", "取"), ("title", "取" * 31), ("pickup", ""), ("dropoff", "x" * 51)],
)
def test_text_field_length(api, student, field, value):
    r = api.post("/api/orders", token=student["token"], json=payload(**{field: value}))
    assert r.status_code == 400
    assert r.json()["code"] == 40002


def test_create_without_token(api):
    r = api.post("/api/orders", json=payload())
    assert r.status_code == 401
    assert r.json()["code"] == 40101


def test_create_insufficient_wallet(api, student):
    r = api.post("/api/orders", token=student["token"], json=payload(fee="301.00"))
    assert r.status_code == 409
    assert r.json()["code"] == 40903


def test_list_mine(api, student, courier):
    o1 = make_order(api, student)
    make_order(api, student, title="第二单")
    r = api.get("/api/orders", token=student["token"])
    ids = [x["id"] for x in r.json()["data"]["items"]]
    assert o1["id"] in ids
    assert len(ids) == 2


def test_list_available_for_courier(api, student, courier):
    make_order(api, student)
    r = api.get("/api/orders?scope=available", token=courier["token"])
    assert r.status_code == 200
    assert len(r.json()["data"]["items"]) >= 1
    assert all(x["status"] == "pending" for x in r.json()["data"]["items"])


def test_list_filter_status(api, student, courier):
    o = make_order(api, student)
    api.post(f"/api/orders/{o['id']}/take", token=courier["token"])
    r = api.get("/api/orders?status=taken", token=student["token"])
    assert [x["id"] for x in r.json()["data"]["items"]] == [o["id"]]


def test_list_pagination(api, student):
    for i in range(3):
        make_order(api, student, title=f"第{i}单")
    r = api.get("/api/orders?page=1&size=2", token=student["token"])
    assert len(r.json()["data"]["items"]) == 2


def test_detail(api, student, order):
    r = api.get(f"/api/orders/{order['id']}", token=student["token"])
    assert r.status_code == 200
    assert r.json()["data"]["order_no"] == order["order_no"]


def test_detail_not_found(api, student):
    r = api.get("/api/orders/999999", token=student["token"])
    assert r.status_code == 404
    assert r.json()["code"] == 40401


def test_cancel_pending(api, student, order):
    r = api.post(f"/api/orders/{order['id']}/cancel", token=student["token"])
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "cancelled"


def test_cancel_by_other(api, student, courier, order):
    r = api.post(f"/api/orders/{order['id']}/cancel", token=courier["token"])
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_cancel_taken(api, student, taken_order):
    r = api.post(f"/api/orders/{taken_order['id']}/cancel", token=student["token"])
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_create_extra_fields_ignored(api, student):
    body = payload(note="请放门口", phone="13800000001")
    r = api.post("/api/orders", token=student["token"], json=body)
    assert r.status_code == 200
    assert "note" not in r.json()["data"]


def test_order_visible_to_courier(api, student, courier, order):
    r = api.get(f"/api/orders/{order['id']}", token=courier["token"])
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "pending"
