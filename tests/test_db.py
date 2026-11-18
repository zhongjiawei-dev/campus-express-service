from conftest import make_order


def test_order_row_matches_api(api, student, order, db):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM orders WHERE id=%s", (order["id"],))
        row = cur.fetchone()
    assert row["title"] == order["title"]
    assert row["fee_cents"] == 850
    assert row["status"] == "pending"
    assert row["requester_id"] == student["id"]


def test_wallet_and_flow_consistent(api, signed_order, student, courier, db):
    with db.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (student["id"],))
        assert cur.fetchone()["wallet_cents"] == 29150
        cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (courier["id"],))
        assert cur.fetchone()["wallet_cents"] == 5850
        cur.execute("SELECT SUM(amount_cents) AS s FROM flows WHERE user_id=%s", (student["id"],))
        assert cur.fetchone()["s"] == -850
        cur.execute("SELECT COUNT(*) AS c FROM flows WHERE ref=%s", (signed_order["order_no"],))
        assert cur.fetchone()["c"] == 2


def test_credit_log_after_review(api, signed_order, student, db):
    api.post(f"/api/orders/{signed_order['id']}/review", token=student["token"], json={"rating": 5})
    with db.cursor() as cur:
        cur.execute("SELECT change_value FROM credit_logs WHERE user_id=%s", (student["id"],))
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["change_value"] == 1


def test_no_orphan_flows(api, signed_order, db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM flows f LEFT JOIN orders o ON o.order_no=f.ref "
            "WHERE f.type IN ('order_pay','order_income') AND o.id IS NULL"
        )
        assert cur.fetchone()["c"] == 0


def test_order_no_unique(api, student, db):
    make_order(api, student, title="单A")
    make_order(api, student, title="单B")
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total, COUNT(DISTINCT order_no) AS uniq FROM orders")
        row = cur.fetchone()
    assert row["total"] == row["uniq"]


def test_chain_payload_fee(api, order, student, db):
    with db.cursor() as cur:
        cur.execute("SELECT payload FROM chain_records WHERE order_id=%s", (order["id"],))
        payload = cur.fetchone()["payload"]
    assert '"fee": "8.50"' in payload


def test_user_credit_default(api, db):
    with db.cursor() as cur:
        cur.execute("SELECT credit_score FROM users WHERE phone='13800000001'")
        assert cur.fetchone()["credit_score"] == 100


def test_seed_wallets(api, db):
    with db.cursor() as cur:
        cur.execute("SELECT phone, wallet_cents FROM users ORDER BY id")
        rows = {r["phone"]: r["wallet_cents"] for r in cur.fetchall()}
    assert rows["13800000001"] == 30000
    assert rows["13800000002"] == 5000
    assert rows["13800000003"] == 5000
