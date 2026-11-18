import os

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "data", "order_cases.yaml"), encoding="utf-8") as f:
    CASES = yaml.safe_load(f)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_order_validation_cases(api, student, case):
    body = {
        "title": "取快递",
        "pickup": "菜鸟驿站",
        "dropoff": "3栋201",
        "fee": case.get("fee", "5.00"),
        "timeout_minutes": case.get("timeout", 30),
    }
    body.update(case.get("patch", {}))
    r = api.post("/api/orders", token=student["token"], json=body)
    assert r.status_code == case["status"], r.text
    assert r.json()["code"] == case["code"]
