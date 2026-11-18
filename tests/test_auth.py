import time
import uuid

import pytest


def new_phone():
    return "138" + str(uuid.uuid4().int)[:8]


def test_health(api):
    r = api.get("/api/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "up"


def test_register_success(api):
    phone = new_phone()
    r = api.post("/api/register", json={"phone": phone, "password": "Abc12345"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["phone"] == phone
    assert len(body["data"]["token"]) == 32
    assert body["data"]["role"] == "student"


def test_register_duplicate_phone(api):
    r = api.post("/api/register", json={"phone": "13800000001", "password": "Abc12345"})
    assert r.status_code == 409
    assert r.json()["code"] == 40901


@pytest.mark.parametrize("phone", ["20000000001", "1380000000", "138000000011", "1380000000a", ""])
def test_register_bad_phone(api, phone):
    r = api.post("/api/register", json={"phone": phone, "password": "Abc12345"})
    assert r.status_code == 400
    assert r.json()["code"] == 40002


def test_register_short_password(api):
    r = api.post("/api/register", json={"phone": new_phone(), "password": "12345"})
    assert r.status_code == 400
    assert r.json()["code"] == 40002


def test_register_json_array(api):
    r = api.post("/api/register", json=["13800000009", "Abc12345"])
    assert r.status_code == 400
    assert r.json()["code"] == 40001


def test_login_success(api):
    r = api.post("/api/login", json={"phone": "13800000002", "password": "Run@123"})
    assert r.status_code == 200
    assert r.json()["data"]["role"] == "courier"


def test_login_admin(api):
    r = api.post("/api/login", json={"phone": "13800000000", "password": "Admin@123"})
    assert r.status_code == 200
    assert r.json()["data"]["role"] == "admin"


def test_login_wrong_password(api):
    r = api.post("/api/login", json={"phone": "13800000001", "password": "Wrong123"})
    assert r.status_code == 401
    assert r.json()["code"] == 40103


def test_login_unknown_phone(api):
    r = api.post("/api/login", json={"phone": "13999999999", "password": "Abc12345"})
    assert r.status_code == 401
    assert r.json()["code"] == 40103


def test_login_empty_phone(api):
    r = api.post("/api/login", json={"phone": "", "password": "Abc12345"})
    assert r.status_code == 400
    assert r.json()["code"] == 40002


def test_login_empty_password(api):
    r = api.post("/api/login", json={"phone": "13800000001", "password": ""})
    assert r.status_code == 400
    assert r.json()["code"] == 40002


def test_me_without_token(api):
    r = api.get("/api/me")
    assert r.status_code == 401
    assert r.json()["code"] == 40101


def test_me_with_bad_token(api):
    r = api.get("/api/me", token="f" * 32)
    assert r.status_code == 401
    assert r.json()["code"] == 40102


def test_me_with_expired_token(api, db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO tokens (token, user_id, expires_at) VALUES (%s,2,%s)",
            ("e" * 32, int(time.time()) - 60),
        )
    db.commit()
    r = api.get("/api/me", token="e" * 32)
    assert r.status_code == 401
    assert r.json()["code"] == 40102
    assert "过期" in r.json()["message"]


def test_me_with_malformed_header(api, student):
    r = api.get("/api/me", token=student["token"])
    assert r.status_code == 200
    import requests
    resp = requests.get(api.base + "/api/me", headers={"Authorization": "Basic abc"}, timeout=10)
    assert resp.status_code == 401
    assert resp.json()["code"] == 40102


def test_profile_masks_phone(api, student):
    r = api.get("/api/users/2", token=student["token"])
    assert r.status_code == 200
    assert r.json()["data"]["phone"] == "138****0001"


def test_register_empty_body(api):
    r = api.post("/api/register", json={})
    assert r.status_code == 400
    assert r.json()["code"] == 40002
