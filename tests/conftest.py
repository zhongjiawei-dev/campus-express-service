import os
import socket
import subprocess
import sys
import time
import urllib.request

import pymysql
import pytest
import requests
from pymysql.cursors import DictCursor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = dict(
    host=os.environ.get("DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("DB_PORT", "3306")),
    user=os.environ.get("DB_USER", "campus"),
    password=os.environ.get("DB_PASSWORD", "Campus@123"),
    database=os.environ.get("DB_NAME", "campus_test"),
    charset="utf8mb4",
    cursorclass=DictCursor,
    autocommit=False,
)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("服务没起来")


@pytest.fixture(scope="session")
def base_url():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "app/server.py", "--port", str(port), "--reset"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "QUIET": "1"},
    )
    base = f"http://127.0.0.1:{port}"
    try:
        wait_up(base + "/api/health")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def db():
    conn = pymysql.connect(**DB)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_db(db):
    with db.cursor() as cur:
        for table in ("credit_logs", "flows", "chain_records", "orders"):
            cur.execute(f"DELETE FROM {table}")
        cur.execute("UPDATE users SET wallet_cents=30000, credit_score=100 WHERE phone='13800000001'")
        cur.execute("UPDATE users SET wallet_cents=5000, credit_score=100 WHERE phone IN ('13800000002','13800000003')")
        cur.execute("UPDATE users SET wallet_cents=0, credit_score=100 WHERE phone='13800000000'")
    db.commit()
    yield


class Client:
    def __init__(self, base):
        self.base = base
        self.session = requests.Session()

    def get(self, path, token=None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.session.get(self.base + path, headers=headers, timeout=10, **kwargs)

    def post(self, path, token=None, json=None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.session.post(self.base + path, headers=headers, json=json, timeout=10, **kwargs)

    def login(self, phone, password):
        r = self.post("/api/login", json={"phone": phone, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["data"]["token"]


@pytest.fixture
def api(base_url):
    return Client(base_url)


@pytest.fixture
def student(api):
    return {"token": api.login("13800000001", "Stu@123"), "id": 2}


@pytest.fixture
def courier(api):
    return {"token": api.login("13800000002", "Run@123"), "id": 3}


@pytest.fixture
def courier2(api):
    return {"token": api.login("13800000003", "Run@456"), "id": 4}


@pytest.fixture
def admin(api):
    return {"token": api.login("13800000000", "Admin@123"), "id": 1}


def make_order(api, owner, title="取快递", pickup="菜鸟驿站", dropoff="3栋201", fee="8.50", timeout=30):
    r = api.post(
        "/api/orders",
        token=owner["token"],
        json={"title": title, "pickup": pickup, "dropoff": dropoff, "fee": fee, "timeout_minutes": timeout},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.fixture
def order(api, student):
    return make_order(api, student)


@pytest.fixture
def taken_order(api, student, courier):
    o = make_order(api, student)
    r = api.post(f"/api/orders/{o['id']}/take", token=courier["token"])
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.fixture
def delivering_order(api, taken_order, courier):
    r = api.post(f"/api/orders/{taken_order['id']}/pickup", token=courier["token"])
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.fixture
def delivered_order(api, delivering_order, courier):
    r = api.post(f"/api/orders/{delivering_order['id']}/deliver", token=courier["token"])
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.fixture
def signed_order(api, delivered_order, student):
    r = api.post(f"/api/orders/{delivered_order['id']}/sign", token=student["token"])
    assert r.status_code == 200, r.text
    return r.json()["data"]
