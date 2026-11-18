import pytest


def test_timeline_has_created(api, student, order):
    r = api.get(f"/api/orders/{order['id']}/timeline", token=student["token"])
    assert r.status_code == 200
    records = r.json()["data"]
    assert len(records) == 1
    assert records[0]["event"] == "created"
    assert records[0]["payload"]["status"] == "pending"


def test_timeline_after_take(api, taken_order, student):
    r = api.get(f"/api/orders/{taken_order['id']}/timeline", token=student["token"])
    assert [x["event"] for x in r.json()["data"]] == ["created", "taken"]


def test_record_hash_is_sha256(api, order, student):
    r = api.get(f"/api/orders/{order['id']}/timeline", token=student["token"])
    for rec in r.json()["data"]:
        assert len(rec["record_hash"]) == 64
        int(rec["record_hash"], 16)


def test_prev_hash_links(api, delivered_order, student):
    r = api.get(f"/api/orders/{delivered_order['id']}/timeline", token=student["token"])
    records = r.json()["data"]
    for prev, cur in zip(records, records[1:]):
        assert cur["prev_hash"] == prev["record_hash"]
    assert records[0]["prev_hash"] == "0" * 64


def test_verify_valid(api, signed_order, student):
    r = api.get(f"/api/orders/{signed_order['id']}/verify", token=student["token"])
    assert r.status_code == 200
    assert r.json()["data"]["valid"] is True
    assert r.json()["data"]["checked"] == 5


def test_verify_after_status_tamper(api, signed_order, student, db):
    with db.cursor() as cur:
        cur.execute("UPDATE orders SET status='cancelled' WHERE id=%s", (signed_order["id"],))
    db.commit()
    r = api.get(f"/api/orders/{signed_order['id']}/verify", token=student["token"])
    assert r.json()["data"]["valid"] is False


def test_verify_after_title_tamper(api, signed_order, student, db):
    with db.cursor() as cur:
        cur.execute("UPDATE orders SET title='改过的标题' WHERE id=%s", (signed_order["id"],))
    db.commit()
    r = api.get(f"/api/orders/{signed_order['id']}/verify", token=student["token"])
    assert r.json()["data"]["valid"] is False


@pytest.mark.xfail(reason="BUG-CX-04：哈希没覆盖金额，改完跑腿费仍然显示存证有效")
def test_verify_after_fee_tamper(api, signed_order, student, db):
    with db.cursor() as cur:
        cur.execute("UPDATE orders SET fee_cents=1 WHERE id=%s", (signed_order["id"],))
    db.commit()
    r = api.get(f"/api/orders/{signed_order['id']}/verify", token=student["token"])
    assert r.json()["data"]["valid"] is False


def test_timeline_not_found(api, student):
    r = api.get("/api/orders/999999/timeline", token=student["token"])
    assert r.status_code == 404


def test_chain_rows_in_db(api, signed_order, db):
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM chain_records WHERE order_id=%s", (signed_order["id"],))
        assert cur.fetchone()["c"] == 5
