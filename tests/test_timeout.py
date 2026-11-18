from datetime import datetime, timedelta

import pytest

from conftest import make_order


def age_order(db, order_id, minutes=20):
    old = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with db.cursor() as cur:
        cur.execute("UPDATE orders SET created_at=%s WHERE id=%s", (old, order_id))
    db.commit()


def test_detail_marks_expired(api, student, db):
    o = make_order(api, student, timeout=10)
    age_order(db, o["id"])
    r = api.get(f"/api/orders/{o['id']}", token=student["token"])
    assert r.json()["data"]["expired"] is True


def test_fresh_order_not_expired(api, student, order):
    r = api.get(f"/api/orders/{order['id']}", token=student["token"])
    assert r.json()["data"]["expired"] is False


@pytest.mark.xfail(reason="BUG-CX-03：超过接单时限的订单仍然能被接单")
def test_take_expired_should_reject(api, student, courier, db):
    o = make_order(api, student, timeout=10)
    age_order(db, o["id"])
    r = api.post(f"/api/orders/{o['id']}/take", token=courier["token"])
    assert r.status_code == 409
    assert r.json()["code"] == 40904


def test_expired_can_still_be_cancelled(api, student, db):
    o = make_order(api, student, timeout=10)
    age_order(db, o["id"])
    r = api.post(f"/api/orders/{o['id']}/cancel", token=student["token"])
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "cancelled"


def test_admin_sees_expired_order(api, student, admin, db):
    o = make_order(api, student, timeout=10)
    age_order(db, o["id"])
    r = api.get("/api/admin/orders", token=admin["token"])
    row = [x for x in r.json()["data"]["items"] if x["id"] == o["id"]][0]
    assert row["expired"] is True


def test_admin_stats_shape(api, student, admin):
    make_order(api, student)
    r = api.get("/api/admin/stats", token=admin["token"])
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["users"] >= 4
    assert "pending" in data["orders_by_status"]
