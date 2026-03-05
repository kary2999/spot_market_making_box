"""
Portal JWT 工具 — 与管理员 auth 使用独立的密钥和 token 前缀
"""

from __future__ import annotations

import os
import time
from functools import wraps

import jwt
from flask import g, jsonify, request

PORTAL_SECRET: str = os.environ.get("PORTAL_JWT_SECRET", "portal-change-me-before-production")
PORTAL_ACCESS_TTL: int = int(os.environ.get("PORTAL_ACCESS_TTL", 3600))     # 1 小时
PORTAL_REFRESH_TTL: int = int(os.environ.get("PORTAL_REFRESH_TTL", 604800)) # 7 天
ALGORITHM = "HS256"


def _make_token(user_id: int, email: str, token_type: str, ttl: int) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "type": token_type,
        "iss": "portal",
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, PORTAL_SECRET, algorithm=ALGORITHM)


def create_portal_access_token(user_id: int, email: str) -> str:
    return _make_token(user_id, email, "access", PORTAL_ACCESS_TTL)


def create_portal_refresh_token(user_id: int, email: str) -> str:
    return _make_token(user_id, email, "refresh", PORTAL_REFRESH_TTL)


def decode_portal_token(token: str) -> dict:
    return jwt.decode(token, PORTAL_SECRET, algorithms=[ALGORITHM])


def _extract_bearer() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def portal_jwt_required(f):
    """装饰器：验证 portal access token，通过后将 payload 写入 g.portal_user。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_bearer()
        if not token:
            return jsonify({"error": "缺少认证令牌"}), 401
        try:
            payload = decode_portal_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "令牌已过期，请重新登录"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "令牌无效"}), 401

        if payload.get("type") != "access" or payload.get("iss") != "portal":
            return jsonify({"error": "令牌类型错误"}), 401

        g.portal_user = payload
        return f(*args, **kwargs)
    return decorated


def portal_admin_required(f):
    """装饰器：验证管理员身份（基于同一 portal JWT，role 字段）。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_bearer()
        if not token:
            return jsonify({"error": "缺少认证令牌"}), 401
        try:
            payload = decode_portal_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "令牌已过期"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "令牌无效"}), 401

        if payload.get("type") != "access" or payload.get("iss") != "portal":
            return jsonify({"error": "令牌类型错误"}), 401
        if payload.get("role") != "admin":
            return jsonify({"error": "权限不足"}), 403

        g.portal_user = payload
        return f(*args, **kwargs)
    return decorated


def make_admin_token(user_id: int, email: str) -> str:
    """为管理员签发含 role=admin 的 access token。"""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "role": "admin",
        "iss": "portal",
        "iat": now,
        "exp": now + PORTAL_ACCESS_TTL,
    }
    return jwt.encode(payload, PORTAL_SECRET, algorithm=ALGORITHM)
