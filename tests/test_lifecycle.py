import pytest


def take(api, courier, order):
    return api.post(f"/api/orders/{order['id']}/take", token=courier["token"])


def test_take_success(api, student, courier, order):
    r = take(api, courier, order)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "taken"
    assert data["courier_id"] == courier["id"]
    assert data["taken_at"]


def test_take_own_order(api, student, order):
    r = api.post(f"/api/orders/{order['id']}/take", token=student["token"])
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_take_twice(api, student, courier, courier2, order):
    assert take(api, courier, order).status_code == 200
    r = take(api, courier2, order)
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_take_by_student(api, student):
    from conftest import make_order
    o = make_order(api, student)
    r = api.post(f"/api/orders/{o['id']}/take", token=student["token"])
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_take_cancelled(api, student, courier, order):
    api.post(f"/api/orders/{order['id']}/cancel", token=student["token"])
    r = take(api, courier, order)
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_pickup_success(api, taken_order, courier):
    r = api.post(f"/api/orders/{taken_order['id']}/pickup", token=courier["token"])
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "delivering"
    assert r.json()["data"]["picked_at"]


def test_pickup_by_other_courier(api, taken_order, courier2):
    r = api.post(f"/api/orders/{taken_order['id']}/pickup", token=courier2["token"])
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_pickup_wrong_status(api, delivering_order, courier):
    r = api.post(f"/api/orders/{delivering_order['id']}/pickup", token=courier["token"])
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_deliver_success(api, delivering_order, courier):
    r = api.post(f"/api/orders/{delivering_order['id']}/deliver", token=courier["token"])
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "delivered"


def test_deliver_by_requester(api, delivering_order, student):
    r = api.post(f"/api/orders/{delivering_order['id']}/deliver", token=student["token"])
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_deliver_twice(api, delivered_order, courier):
    r = api.post(f"/api/orders/{delivered_order['id']}/deliver", token=courier["token"])
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_sign_success(api, delivered_order, student):
    r = api.post(f"/api/orders/{delivered_order['id']}/sign", token=student["token"])
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "signed"


def test_sign_by_courier(api, delivered_order, courier):
    r = api.post(f"/api/orders/{delivered_order['id']}/sign", token=courier["token"])
    assert r.status_code == 403
    assert r.json()["code"] == 40301


def test_sign_before_deliver(api, delivering_order, student):
    r = api.post(f"/api/orders/{delivering_order['id']}/sign", token=student["token"])
    assert r.status_code == 409
    assert r.json()["code"] == 40902


@pytest.mark.xfail(reason="BUG-CX-02：已签收还能再签一次，导致重复扣款")
def test_sign_twice_should_reject(api, signed_order, student):
    r = api.post(f"/api/orders/{signed_order['id']}/sign", token=student["token"])
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_wallet_after_sign(api, signed_order, student, courier):
    assert api.get("/api/wallet", token=student["token"]).json()["data"]["wallet"] == "291.50"
    assert api.get("/api/wallet", token=courier["token"]).json()["data"]["wallet"] == "58.50"


def test_flows_after_sign(api, signed_order, student):
    r = api.get("/api/flows", token=student["token"])
    types = [x["type"] for x in r.json()["data"]]
    assert "order_pay" in types
    pay = [x for x in r.json()["data"] if x["type"] == "order_pay"][0]
    assert pay["amount"] == "-8.50"
    assert pay["ref"] == signed_order["order_no"]


def test_courier_income_flow(api, signed_order, courier):
    r = api.get("/api/flows?type=order_income", token=courier["token"])
    assert r.status_code == 200
    assert r.json()["data"][0]["amount"] == "8.50"


@pytest.mark.xfail(reason="BUG-CX-01：签收后双方信用分都没有增加")
def test_credit_after_sign(api, signed_order, student, courier):
    assert api.get("/api/credit", token=student["token"]).json()["data"]["credit_score"] == 102
    assert api.get("/api/credit", token=courier["token"]).json()["data"]["credit_score"] == 102


def test_review_success(api, signed_order, student):
    r = api.post(
        f"/api/orders/{signed_order['id']}/review",
        token=student["token"],
        json={"rating": 5, "comment": "送得很快"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["review_rating"] == 5
    credit = api.get("/api/credit", token=student["token"]).json()["data"]
    assert credit["credit_score"] == 101
    assert credit["logs"][0]["change_value"] == 1


def test_review_bad_rating(api, signed_order, student):
    r = api.post(f"/api/orders/{signed_order['id']}/review", token=student["token"], json={"rating": 6})
    assert r.status_code == 400
    assert r.json()["code"] == 40004


def test_review_before_sign(api, delivered_order, student):
    r = api.post(f"/api/orders/{delivered_order['id']}/review", token=student["token"], json={"rating": 5})
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_review_by_other(api, signed_order, courier):
    r = api.post(f"/api/orders/{signed_order['id']}/review", token=courier["token"], json={"rating": 1})
    assert r.status_code == 403
    assert r.json()["code"] == 40301


@pytest.mark.xfail(reason="BUG-CX-05：同一单可以重复评价，信用分重复加减")
def test_review_twice_should_reject(api, signed_order, student):
    api.post(f"/api/orders/{signed_order['id']}/review", token=student["token"], json={"rating": 5})
    r = api.post(f"/api/orders/{signed_order['id']}/review", token=student["token"], json={"rating": 1})
    assert r.status_code == 409
    assert r.json()["code"] == 40902


def test_review_low_rating_deducts(api, signed_order, student):
    r = api.post(f"/api/orders/{signed_order['id']}/review", token=student["token"], json={"rating": 2})
    assert r.status_code == 200
    assert api.get("/api/credit", token=student["token"]).json()["data"]["credit_score"] == 99
