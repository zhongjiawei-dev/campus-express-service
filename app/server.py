#!/usr/bin/env python3
"""校园快递代取平台 · 练习用被测服务。

零框架依赖，HTTP 用标准库，数据落 MariaDB/MySQL。
启动：
    python app/server.py --port 9300 --reset
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import pymysql
from pymysql.cursors import DictCursor

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("DB_PORT", "3306")),
    user=os.environ.get("DB_USER", "campus"),
    password=os.environ.get("DB_PASSWORD", "Campus@123"),
    database=os.environ.get("DB_NAME", "campus_test"),
    charset="utf8mb4",
    cursorclass=DictCursor,
    autocommit=False,
)

TOKEN_TTL = 2 * 3600

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id INT PRIMARY KEY AUTO_INCREMENT,
        phone VARCHAR(11) NOT NULL UNIQUE,
        password VARCHAR(64) NOT NULL,
        role VARCHAR(16) NOT NULL DEFAULT 'student',
        credit_score INT NOT NULL DEFAULT 100,
        wallet_cents INT NOT NULL DEFAULT 0,
        created_at VARCHAR(32) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS tokens (
        token CHAR(32) PRIMARY KEY,
        user_id INT NOT NULL,
        expires_at BIGINT NOT NULL,
        INDEX idx_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS orders (
        id INT PRIMARY KEY AUTO_INCREMENT,
        order_no VARCHAR(24) NOT NULL UNIQUE,
        requester_id INT NOT NULL,
        courier_id INT NULL,
        title VARCHAR(40) NOT NULL,
        pickup VARCHAR(80) NOT NULL,
        dropoff VARCHAR(80) NOT NULL,
        fee_cents INT NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        timeout_minutes INT NOT NULL DEFAULT 60,
        created_at VARCHAR(32) NOT NULL,
        taken_at VARCHAR(32) NULL,
        picked_at VARCHAR(32) NULL,
        delivered_at VARCHAR(32) NULL,
        signed_at VARCHAR(32) NULL,
        cancelled_at VARCHAR(32) NULL,
        review_rating INT NULL,
        review_comment VARCHAR(120) NULL,
        INDEX idx_status (status),
        INDEX idx_requester (requester_id),
        INDEX idx_courier (courier_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS chain_records (
        id INT PRIMARY KEY AUTO_INCREMENT,
        order_id INT NOT NULL,
        event VARCHAR(16) NOT NULL,
        payload TEXT NOT NULL,
        prev_hash CHAR(64) NOT NULL,
        record_hash CHAR(64) NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        INDEX idx_order (order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS flows (
        id INT PRIMARY KEY AUTO_INCREMENT,
        user_id INT NOT NULL,
        type VARCHAR(24) NOT NULL,
        amount_cents INT NOT NULL,
        ref VARCHAR(32) NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        INDEX idx_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS credit_logs (
        id INT PRIMARY KEY AUTO_INCREMENT,
        user_id INT NOT NULL,
        change_value INT NOT NULL,
        reason VARCHAR(40) NOT NULL,
        ref VARCHAR(32) NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        INDEX idx_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        self.code = code
        self.message = message
        self.status = status


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_cents(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("金额格式不对")
    try:
        amount = float(str(value))
    except ValueError:
        raise ValueError("金额格式不对")
    cents = int(round(amount * 100))
    if abs(amount * 100 - cents) > 1e-6:
        raise ValueError("金额最多两位小数")
    return cents


def to_yuan(cents):
    return f"{cents / 100:.2f}"


def order_hash(prev_hash, order_id, event, title, status):
    raw = f"{prev_hash}|{order_id}|{event}|{title}|{status}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def connect():
    return pymysql.connect(**DB_CONFIG)


def init_schema(conn, reset=False):
    with conn.cursor() as cur:
        if reset:
            for table in ("credit_logs", "flows", "chain_records", "orders", "tokens", "users"):
                cur.execute(f"DROP TABLE IF EXISTS {table}")
        for sql in SCHEMA:
            cur.execute(sql)
    conn.commit()


def seed(conn):
    users = [
        ("13800000000", "Admin@123", "admin", 100, 0),
        ("13800000001", "Stu@123", "student", 100, 30000),
        ("13800000002", "Run@123", "courier", 100, 5000),
        ("13800000003", "Run@456", "courier", 100, 5000),
    ]
    with conn.cursor() as cur:
        for phone, password, role, credit, wallet in users:
            cur.execute(
                "INSERT INTO users (phone, password, role, credit_score, wallet_cents, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (phone, password, role, credit, wallet, now_str()),
            )
    conn.commit()


class Api:
    def __init__(self, conn):
        self.conn = conn

    # ---------- 基础 ----------
    def body_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(40001, "请求体不是合法 JSON", 400)
        if not isinstance(data, dict):
            raise ApiError(40001, "请求体必须是 JSON 对象", 400)
        return data

    def ok(self, data=None):
        return 200, {"code": 0, "message": "ok", "data": data}

    def current_user(self):
        header = self.headers.get("Authorization") or ""
        if not header:
            raise ApiError(40101, "未登录", 401)
        if not header.startswith("Bearer "):
            raise ApiError(40102, "token 格式不对", 401)
        token = header[7:].strip()
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT t.token, t.expires_at, u.id, u.phone, u.role, u.credit_score, u.wallet_cents "
                "FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=%s",
                (token,),
            )
            row = cur.fetchone()
        if not row:
            raise ApiError(40102, "token 无效", 401)
        if row["expires_at"] < int(time.time()):
            raise ApiError(40102, "token 已过期", 401)
        return row

    def require_role(self, user, role):
        if user["role"] != role:
            raise ApiError(40301, "没有权限", 403)

    def issue_token(self, user_id):
        token = os.urandom(16).hex()
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tokens (token, user_id, expires_at) VALUES (%s,%s,%s)",
                (token, user_id, int(time.time()) + TOKEN_TTL),
            )
        self.conn.commit()
        return token

    def user_view(self, row):
        return {
            "id": row["id"],
            "phone": row["phone"][:3] + "****" + row["phone"][-4:],
            "role": row["role"],
            "credit_score": row["credit_score"],
            "wallet": to_yuan(row["wallet_cents"]),
        }

    def order_view(self, row):
        expired = row["status"] == "pending" and self.is_expired(row)
        return {
            "id": row["id"],
            "order_no": row["order_no"],
            "requester_id": row["requester_id"],
            "courier_id": row["courier_id"],
            "title": row["title"],
            "pickup": row["pickup"],
            "dropoff": row["dropoff"],
            "fee": to_yuan(row["fee_cents"]),
            "status": row["status"],
            "timeout_minutes": row["timeout_minutes"],
            "expired": expired,
            "created_at": row["created_at"],
            "taken_at": row["taken_at"],
            "picked_at": row["picked_at"],
            "delivered_at": row["delivered_at"],
            "signed_at": row["signed_at"],
            "review_rating": row["review_rating"],
            "review_comment": row["review_comment"],
        }

    def is_expired(self, row):
        try:
            created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            return False
        return time.time() > created + row["timeout_minutes"] * 60

    def append_chain(self, order_id, event, order_row):
        payload = {
            "order_no": order_row["order_no"],
            "title": order_row["title"],
            "status": order_row["status"],
            "fee": to_yuan(order_row["fee_cents"]),
            "pickup": order_row["pickup"],
            "dropoff": order_row["dropoff"],
        }
        with self.conn.cursor() as cur:
            cur.execute("SELECT record_hash FROM chain_records WHERE order_id=%s ORDER BY id DESC LIMIT 1", (order_id,))
            last = cur.fetchone()
            prev = last["record_hash"] if last else "0" * 64
            h = order_hash(prev, order_id, event, payload["title"], payload["status"])
            cur.execute(
                "INSERT INTO chain_records (order_id, event, payload, prev_hash, record_hash, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (order_id, event, json.dumps(payload, ensure_ascii=False), prev, h, now_str()),
            )

    # ---------- 账号 ----------
    def register(self):
        data = self.body_json()
        phone = str(data.get("phone") or "").strip()
        password = str(data.get("password") or "")
        if not re.match(r"^1[3-9]\d{9}$", phone):
            raise ApiError(40002, "手机号格式不对", 400)
        if len(password) < 6:
            raise ApiError(40002, "密码至少 6 位", 400)
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
            if cur.fetchone():
                raise ApiError(40901, "手机号已注册", 409)
            cur.execute(
                "INSERT INTO users (phone, password, role, credit_score, wallet_cents, created_at) VALUES (%s,%s,'student',100,0,%s)",
                (phone, password, now_str()),
            )
            user_id = cur.lastrowid
        self.conn.commit()
        token = self.issue_token(user_id)
        return self.ok({"phone": phone, "token": token, "role": "student"})

    def login(self):
        data = self.body_json()
        phone = str(data.get("phone") or "").strip()
        password = str(data.get("password") or "")
        if not phone or not password:
            raise ApiError(40002, "手机号和密码不能为空", 400)
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, password, role FROM users WHERE phone=%s", (phone,))
            user = cur.fetchone()
        if not user or user["password"] != password:
            raise ApiError(40103, "手机号或密码错", 401)
        token = self.issue_token(user["id"])
        return self.ok({"token": token, "role": user["role"]})

    def me(self):
        user = self.current_user()
        return self.ok(self.user_view(user))

    def profile(self, user_id):
        self.current_user()
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, phone, role, credit_score, wallet_cents FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
        if not row:
            raise ApiError(40401, "用户不存在", 404)
        return self.ok(self.user_view(row))

    # ---------- 订单 ----------
    def create_order(self):
        user = self.current_user()
        data = self.body_json()
        title = str(data.get("title") or "").strip()
        pickup = str(data.get("pickup") or "").strip()
        dropoff = str(data.get("dropoff") or "").strip()
        if not 2 <= len(title) <= 30:
            raise ApiError(40002, "标题长度 2-30", 400)
        if not 2 <= len(pickup) <= 50 or not 2 <= len(dropoff) <= 50:
            raise ApiError(40002, "取件/送达地点长度 2-50", 400)
        try:
            fee = to_cents(data.get("fee"))
        except ValueError as e:
            raise ApiError(40002, str(e), 400)
        if fee < 100 or fee > 50000:
            raise ApiError(40004, "跑腿费 1-500 元", 400)
        raw_timeout = data.get("timeout_minutes")
        if raw_timeout is None:
            raw_timeout = 60
        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError):
            raise ApiError(40002, "timeout_minutes 必须是整数", 400)
        if not 10 <= timeout <= 180:
            raise ApiError(40004, "超时时间 10-180 分钟", 400)
        if user["wallet_cents"] < fee:
            raise ApiError(40903, "钱包余额不足", 409)
        order_no = "CX" + datetime.now().strftime("%Y%m%d") + f"{random.randint(0, 999999):06d}"
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (order_no, requester_id, title, pickup, dropoff, fee_cents, status, timeout_minutes, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                (order_no, user["id"], title, pickup, dropoff, fee, timeout, now_str()),
            )
            order_id = cur.lastrowid
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            row = cur.fetchone()
            self.append_chain(order_id, "created", row)
        self.conn.commit()
        return self.ok(self.order_view(row))

    def list_orders(self):
        user = self.current_user()
        qs = parse_qs(urlparse(self.path).query)
        status = (qs.get("status") or [""])[0]
        scope = (qs.get("scope") or ["mine"])[0]
        page = max(1, int((qs.get("page") or ["1"])[0] or 1))
        size = min(50, max(1, int((qs.get("size") or ["20"])[0] or 20)))
        where = []
        args = []
        if status:
            where.append("status=%s")
            args.append(status)
        if user["role"] != "admin":
            if scope == "courier":
                where.append("courier_id=%s")
                args.append(user["id"])
            elif scope == "available":
                where.append("status='pending'")
            else:
                where.append("requester_id=%s")
                args.append(user["id"])
        sql = "SELECT * FROM orders"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT %s OFFSET %s"
        args.extend([size, (page - 1) * size])
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        return self.ok({"items": [self.order_view(r) for r in rows], "page": page, "size": size})

    def get_order(self, order_id):
        self.current_user()
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            row = cur.fetchone()
        if not row:
            raise ApiError(40401, "订单不存在", 404)
        return self.ok(self.order_view(row))

    def _load_order(self, order_id):
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            row = cur.fetchone()
        if not row:
            raise ApiError(40401, "订单不存在", 404)
        return row

    def take_order(self, order_id):
        user = self.current_user()
        self.require_role(user, "courier")
        row = self._load_order(order_id)
        if row["requester_id"] == user["id"]:
            raise ApiError(40301, "不能接自己的订单", 403)
        if row["status"] != "pending":
            raise ApiError(40902, "当前状态不能接单", 409)
        # 超时判断漏了，BUG-CX-03：过期订单仍然能接
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE orders SET courier_id=%s, status='taken', taken_at=%s WHERE id=%s",
                (user["id"], now_str(), order_id),
            )
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            new_row = cur.fetchone()
            self.append_chain(order_id, "taken", new_row)
        self.conn.commit()
        return self.ok(self.order_view(new_row))

    def pickup_order(self, order_id):
        user = self.current_user()
        row = self._load_order(order_id)
        if row["courier_id"] != user["id"]:
            raise ApiError(40301, "只有接单骑手能操作", 403)
        if row["status"] != "taken":
            raise ApiError(40902, "当前状态不能取件", 409)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE orders SET status='delivering', picked_at=%s WHERE id=%s", (now_str(), order_id))
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            new_row = cur.fetchone()
            self.append_chain(order_id, "picked", new_row)
        self.conn.commit()
        return self.ok(self.order_view(new_row))

    def deliver_order(self, order_id):
        user = self.current_user()
        row = self._load_order(order_id)
        if row["courier_id"] != user["id"]:
            raise ApiError(40301, "只有接单骑手能操作", 403)
        if row["status"] != "delivering":
            raise ApiError(40902, "当前状态不能标记送达", 409)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE orders SET status='delivered', delivered_at=%s WHERE id=%s", (now_str(), order_id))
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            new_row = cur.fetchone()
            self.append_chain(order_id, "delivered", new_row)
        self.conn.commit()
        return self.ok(self.order_view(new_row))

    def sign_order(self, order_id):
        user = self.current_user()
        row = self._load_order(order_id)
        if row["requester_id"] != user["id"]:
            raise ApiError(40301, "只有下单人能签收", 403)
        # 已签收还允许再签一次，BUG-CX-02：重复签收会重复扣款
        if row["status"] not in ("delivered", "signed"):
            raise ApiError(40902, "当前状态不能签收", 409)
        courier_id = row["courier_id"]
        with self.conn.cursor() as cur:
            cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (user["id"],))
            requester_wallet = cur.fetchone()["wallet_cents"]
            if requester_wallet < row["fee_cents"]:
                raise ApiError(40903, "余额不足，无法签收", 409)
            cur.execute("UPDATE users SET wallet_cents=wallet_cents-%s WHERE id=%s", (row["fee_cents"], user["id"]))
            cur.execute("UPDATE users SET wallet_cents=wallet_cents+%s WHERE id=%s", (row["fee_cents"], courier_id))
            cur.execute(
                "INSERT INTO flows (user_id, type, amount_cents, ref, created_at) VALUES (%s,'order_pay',%s,%s,%s)",
                (user["id"], -row["fee_cents"], row["order_no"], now_str()),
            )
            cur.execute(
                "INSERT INTO flows (user_id, type, amount_cents, ref, created_at) VALUES (%s,'order_income',%s,%s,%s)",
                (courier_id, row["fee_cents"], row["order_no"], now_str()),
            )
            # 签收后没有加信用分，BUG-CX-01
            cur.execute("UPDATE orders SET status='signed', signed_at=%s WHERE id=%s", (now_str(), order_id))
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            new_row = cur.fetchone()
            self.append_chain(order_id, "signed", new_row)
        self.conn.commit()
        return self.ok(self.order_view(new_row))

    def cancel_order(self, order_id):
        user = self.current_user()
        row = self._load_order(order_id)
        if row["requester_id"] != user["id"]:
            raise ApiError(40301, "只有下单人能取消", 403)
        if row["status"] != "pending":
            raise ApiError(40902, "当前状态不能取消", 409)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE orders SET status='cancelled', cancelled_at=%s WHERE id=%s", (now_str(), order_id))
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            new_row = cur.fetchone()
            self.append_chain(order_id, "cancelled", new_row)
        self.conn.commit()
        return self.ok(self.order_view(new_row))

    def review_order(self, order_id):
        user = self.current_user()
        row = self._load_order(order_id)
        if row["requester_id"] != user["id"]:
            raise ApiError(40301, "只有下单人能评价", 403)
        if row["status"] != "signed":
            raise ApiError(40902, "签收后才能评价", 409)
        data = self.body_json()
        try:
            rating = int(data.get("rating"))
        except (TypeError, ValueError):
            raise ApiError(40002, "评分必须是整数", 400)
        if not 1 <= rating <= 5:
            raise ApiError(40004, "评分 1-5", 400)
        comment = str(data.get("comment") or "")[:100]
        delta = 1 if rating >= 4 else (-1 if rating <= 2 else 0)
        with self.conn.cursor() as cur:
            # 没有判断是否已评价，BUG-CX-05：重复评价会重复加信用分
            cur.execute(
                "UPDATE orders SET review_rating=%s, review_comment=%s WHERE id=%s",
                (rating, comment, order_id),
            )
            if delta:
                cur.execute("UPDATE users SET credit_score=credit_score+%s WHERE id=%s", (delta, user["id"]))
                cur.execute(
                    "INSERT INTO credit_logs (user_id, change_value, reason, ref, created_at) VALUES (%s,%s,'review',%s,%s)",
                    (user["id"], delta, row["order_no"], now_str()),
                )
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            new_row = cur.fetchone()
            self.append_chain(order_id, "reviewed", new_row)
        self.conn.commit()
        return self.ok(self.order_view(new_row))

    # ---------- 存证 ----------
    def timeline(self, order_id):
        self.current_user()
        self._load_order(order_id)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, event, payload, prev_hash, record_hash, created_at FROM chain_records WHERE order_id=%s ORDER BY id",
                (order_id,),
            )
            rows = cur.fetchall()
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return self.ok(rows)

    def verify_chain(self, order_id):
        self.current_user()
        order = self._load_order(order_id)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, event, payload, prev_hash, record_hash FROM chain_records WHERE order_id=%s ORDER BY id",
                (order_id,),
            )
            rows = cur.fetchall()
        prev = "0" * 64
        broken_at = None
        for r in rows:
            payload = json.loads(r["payload"])
            expected = order_hash(prev, order_id, r["event"], payload.get("title", ""), payload.get("status", ""))
            if r["prev_hash"] != prev or r["record_hash"] != expected:
                broken_at = r["id"]
                break
            prev = r["record_hash"]
        latest_ok = True
        if rows:
            latest = json.loads(rows[-1]["payload"])
            latest_ok = latest.get("status") == order["status"] and latest.get("title") == order["title"]
            # 只比标题和状态，金额没比，BUG-CX-04
        valid = broken_at is None and latest_ok
        return self.ok({"valid": valid, "checked": len(rows), "broken_at": broken_at})

    # ---------- 钱包 / 信用 ----------
    def wallet(self):
        user = self.current_user()
        with self.conn.cursor() as cur:
            cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (user["id"],))
            cents = cur.fetchone()["wallet_cents"]
        return self.ok({"wallet": to_yuan(cents)})

    def recharge(self):
        user = self.current_user()
        data = self.body_json()
        try:
            cents = to_cents(data.get("amount"))
        except ValueError as e:
            raise ApiError(40002, str(e), 400)
        if cents < 100 or cents > 100000:
            raise ApiError(40004, "充值金额 1-1000 元", 400)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE users SET wallet_cents=wallet_cents+%s WHERE id=%s", (cents, user["id"]))
            cur.execute(
                "INSERT INTO flows (user_id, type, amount_cents, ref, created_at) VALUES (%s,'recharge',%s,'-',%s)",
                (user["id"], cents, now_str()),
            )
            cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (user["id"],))
            balance = cur.fetchone()["wallet_cents"]
        self.conn.commit()
        return self.ok({"wallet": to_yuan(balance)})

    def flows(self):
        user = self.current_user()
        qs = parse_qs(urlparse(self.path).query)
        flow_type = (qs.get("type") or [""])[0]
        sql = "SELECT id, type, amount_cents, ref, created_at FROM flows WHERE user_id=%s"
        args = [user["id"]]
        if flow_type:
            sql += " AND type=%s"
            args.append(flow_type)
        sql += " ORDER BY id DESC"
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        for r in rows:
            r["amount"] = to_yuan(r.pop("amount_cents"))
        return self.ok(rows)

    def credit(self):
        user = self.current_user()
        with self.conn.cursor() as cur:
            cur.execute("SELECT credit_score FROM users WHERE id=%s", (user["id"],))
            score = cur.fetchone()["credit_score"]
            cur.execute(
                "SELECT change_value, reason, ref, created_at FROM credit_logs WHERE user_id=%s ORDER BY id DESC",
                (user["id"],),
            )
            logs = cur.fetchall()
        return self.ok({"credit_score": score, "logs": logs})

    # ---------- 管理 ----------
    def admin_orders(self):
        user = self.current_user()
        self.require_role(user, "admin")
        qs = parse_qs(urlparse(self.path).query)
        status = (qs.get("status") or [""])[0]
        with self.conn.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM orders WHERE status=%s ORDER BY id DESC", (status,))
            else:
                cur.execute("SELECT * FROM orders ORDER BY id DESC")
            rows = cur.fetchall()
        return self.ok({"items": [self.order_view(r) for r in rows]})

    def admin_stats(self):
        user = self.current_user()
        self.require_role(user, "admin")
        with self.conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) AS c, COALESCE(SUM(fee_cents),0) AS fee FROM orders GROUP BY status")
            by_status = {r["status"]: {"count": r["c"], "fee": to_yuan(r["fee"])} for r in cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS c FROM users")
            users = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM chain_records")
            records = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM flows WHERE type='order_pay'")
            paid = cur.fetchone()["c"]
        return self.ok({"users": users, "chain_records": records, "paid_orders": paid, "orders_by_status": by_status})

    def health(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM users")
            users = cur.fetchone()["c"]
        return self.ok({"status": "up", "users": users})


class Handler(BaseHTTPRequestHandler):
    server_version = "CampusExpress/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if not os.environ.get("QUIET"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _dispatch(self, method):
        conn = connect()
        api = Api(conn)
        api.headers = self.headers
        api.path = self.path
        api.rfile = self.rfile
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if method == "GET" and path == "/api/health":
                return api.health()
            if method == "POST" and path == "/api/register":
                return api.register()
            if method == "POST" and path == "/api/login":
                return api.login()
            if method == "GET" and path == "/api/me":
                return api.me()
            m = re.match(r"^/api/users/(\d+)$", path)
            if method == "GET" and m:
                return api.profile(int(m.group(1)))
            if method == "GET" and path == "/api/orders":
                return api.list_orders()
            if method == "POST" and path == "/api/orders":
                return api.create_order()
            m = re.match(r"^/api/orders/(\d+)$", path)
            if method == "GET" and m:
                return api.get_order(int(m.group(1)))
            for suffix, fn in (
                ("take", api.take_order),
                ("pickup", api.pickup_order),
                ("deliver", api.deliver_order),
                ("sign", api.sign_order),
                ("cancel", api.cancel_order),
                ("review", api.review_order),
                ("timeline", api.timeline),
                ("verify", api.verify_chain),
            ):
                m = re.match(rf"^/api/orders/(\d+)/{suffix}$", path)
                if method == "GET" and suffix in ("timeline", "verify") and m:
                    return fn(int(m.group(1)))
                if method == "POST" and suffix not in ("timeline", "verify") and m:
                    return fn(int(m.group(1)))
            if method == "GET" and path == "/api/wallet":
                return api.wallet()
            if method == "POST" and path == "/api/wallet/recharge":
                return api.recharge()
            if method == "GET" and path == "/api/flows":
                return api.flows()
            if method == "GET" and path == "/api/credit":
                return api.credit()
            if method == "GET" and path == "/api/admin/orders":
                return api.admin_orders()
            if method == "GET" and path == "/api/admin/stats":
                return api.admin_stats()
            raise ApiError(40401, "接口不存在", 404)
        except ApiError as e:
            return e.status, {"code": e.code, "message": e.message, "data": None}
        except Exception:
            traceback.print_exc()
            return 500, {"code": 50001, "message": "服务端异常", "data": None}
        finally:
            conn.close()

    def do_GET(self):
        try:
            status, payload = self._dispatch("GET")
        except Exception:
            status, payload = 500, {"code": 50001, "message": "服务端异常", "data": None}
        self._send(status, payload)

    def do_POST(self):
        try:
            status, payload = self._dispatch("POST")
        except Exception:
            status, payload = 500, {"code": 50001, "message": "服务端异常", "data": None}
        self._send(status, payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9300)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    conn = connect()
    init_schema(conn, reset=args.reset)
    if args.reset:
        seed(conn)
    conn.close()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"campus express listening on :{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
