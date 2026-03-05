"""
Portal 数据模型 — SQLite
表结构：
  portal_users      — 员工账户
  instances         — OpenClaw 实例
  user_instances    — 实例分配关系
  usage_records     — 月度 token 用量
"""

from __future__ import annotations

import os
import sqlite3
import time

PORTAL_DB_PATH = os.environ.get("PORTAL_DB_PATH", "portal.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    UNIQUE NOT NULL,
    name          TEXT    NOT NULL DEFAULT '',
    language      TEXT    NOT NULL DEFAULT 'zh',
    status        TEXT    NOT NULL DEFAULT 'active',   -- active | suspended
    invite_token  TEXT,
    created_at    REAL    NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS instances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    endpoint_url  TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL DEFAULT 'active',   -- active | inactive
    created_at    REAL    NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS user_instances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES portal_users(id),
    instance_id   INTEGER NOT NULL REFERENCES instances(id),
    assigned_at   REAL    NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE(user_id, instance_id)
);

CREATE TABLE IF NOT EXISTS usage_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES portal_users(id),
    instance_id   INTEGER NOT NULL REFERENCES instances(id),
    year_month    TEXT    NOT NULL,   -- 'YYYY-MM'
    tokens        INTEGER NOT NULL DEFAULT 0,
    conversations INTEGER NOT NULL DEFAULT 0,
    updated_at    REAL    NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE(user_id, instance_id, year_month)
);
"""


def init_portal_db() -> None:
    conn = sqlite3.connect(PORTAL_DB_PATH)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(PORTAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# portal_users
# ---------------------------------------------------------------------------

def get_portal_user_by_email(email: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM portal_users WHERE email = ?", (email,)
        ).fetchone()
    return dict(row) if row else None


def get_portal_user_by_id(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM portal_users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def create_portal_user(email: str, name: str = "", invite_token: str | None = None) -> dict:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO portal_users (email, name, invite_token) VALUES (?, ?, ?)",
            (email, name, invite_token),
        )
    return get_portal_user_by_email(email)


def update_portal_user(user_id: int, name: str | None = None, language: str | None = None) -> dict:
    fields, values = [], []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if language is not None:
        fields.append("language = ?")
        values.append(language)
    if fields:
        values.append(user_id)
        with _connect() as conn:
            conn.execute(
                f"UPDATE portal_users SET {', '.join(fields)} WHERE id = ?",
                values,
            )
    return get_portal_user_by_id(user_id)


def set_portal_user_status(user_id: int, status: str) -> dict:
    with _connect() as conn:
        conn.execute(
            "UPDATE portal_users SET status = ? WHERE id = ?",
            (status, user_id),
        )
    return get_portal_user_by_id(user_id)


def list_portal_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM portal_users ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# instances
# ---------------------------------------------------------------------------

def create_instance(name: str, endpoint_url: str, description: str = "") -> dict:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO instances (name, endpoint_url, description) VALUES (?, ?, ?)",
            (name, endpoint_url, description),
        )
        instance_id = cur.lastrowid
    return get_instance_by_id(instance_id)


def get_instance_by_id(instance_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM instances WHERE id = ?", (instance_id,)
        ).fetchone()
    return dict(row) if row else None


def list_instances() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM instances ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_user_instances(user_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.* FROM instances i
            JOIN user_instances ui ON ui.instance_id = i.id
            WHERE ui.user_id = ? AND i.status = 'active'
            ORDER BY ui.assigned_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# user_instances (assignment)
# ---------------------------------------------------------------------------

def assign_instance(user_id: int, instance_id: int) -> bool:
    """分配实例给用户。已分配时返回 False，否则返回 True。"""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO user_instances (user_id, instance_id) VALUES (?, ?)",
                (user_id, instance_id),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def unassign_instance(user_id: int, instance_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM user_instances WHERE user_id = ? AND instance_id = ?",
            (user_id, instance_id),
        )


# ---------------------------------------------------------------------------
# usage_records
# ---------------------------------------------------------------------------

def get_usage(user_id: int, year_month: str | None = None) -> list[dict]:
    """获取用量记录。year_month 为 None 时返回全部月份。"""
    with _connect() as conn:
        if year_month:
            rows = conn.execute(
                "SELECT * FROM usage_records WHERE user_id = ? AND year_month = ?",
                (user_id, year_month),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM usage_records WHERE user_id = ? ORDER BY year_month DESC",
                (user_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def upsert_usage(user_id: int, instance_id: int, year_month: str, tokens: int, conversations: int = 1) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO usage_records (user_id, instance_id, year_month, tokens, conversations, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, instance_id, year_month)
            DO UPDATE SET tokens = tokens + excluded.tokens,
                          conversations = conversations + excluded.conversations,
                          updated_at = excluded.updated_at
            """,
            (user_id, instance_id, year_month, tokens, conversations, now),
        )
