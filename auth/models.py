"""
用户数据模型 — SQLite 存储，bcrypt 密码哈希
"""

import os
import sqlite3
import time

import bcrypt

DB_PATH = os.environ.get("AUTH_DB_PATH", "auth.db")

MAX_FAIL = 5
LOCK_SECONDS = 15 * 60  # 15 分钟


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            fail_count    INTEGER NOT NULL DEFAULT 0,
            lock_until    REAL    NOT NULL DEFAULT 0,
            created_at    REAL    NOT NULL DEFAULT (strftime('%s','now'))
        )
        """
    )
    conn.commit()
    conn.close()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_user(username: str, password: str) -> None:
    """创建用户，密码使用 bcrypt 哈希存储。"""
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hashed),
        )


def get_user(username: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def record_login_failure(username: str) -> dict:
    """递增失败计数，达到上限时锁定账户，返回更新后的用户记录。"""
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET fail_count = fail_count + 1 WHERE username = ?",
            (username,),
        )
        row = conn.execute(
            "SELECT fail_count FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row and row["fail_count"] >= MAX_FAIL:
            conn.execute(
                "UPDATE users SET lock_until = ? WHERE username = ?",
                (now + LOCK_SECONDS, username),
            )
    return get_user(username)


def reset_login_state(username: str) -> None:
    """登录成功后重置失败计数与锁定状态。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET fail_count = 0, lock_until = 0 WHERE username = ?",
            (username,),
        )


def seed_demo_user() -> None:
    """初始化演示账户 admin/Admin@1234（仅首次运行时创建）。"""
    if get_user("admin") is None:
        create_user("admin", "Admin@1234")
        print("[auth] 演示账户已创建: admin / Admin@1234")
