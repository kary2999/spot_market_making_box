"""
认证路由蓝图
  POST /api/auth/login    — 登录，返回 access + refresh token
  POST /api/auth/refresh  — 用 refresh token 换新 access token
  GET  /api/auth/me       — 获取当前用户信息（需 access token）
"""

import time

import bcrypt
import jwt
from flask import Blueprint, g, jsonify, request

from .jwt_utils import (
    ACCESS_TTL,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from .middleware import jwt_required
from .models import (
    get_user,
    record_login_failure,
    reset_login_state,
)

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _extract_bearer() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    # 1. 基础校验
    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    # 2. 查询用户
    user = get_user(username)
    if user is None:
        # 不泄露用户是否存在
        return jsonify({"error": "用户名或密码错误"}), 401

    # 3. 账户锁定检查
    now = time.time()
    if user["lock_until"] > now:
        remaining = int(user["lock_until"] - now)
        minutes, seconds = divmod(remaining, 60)
        return jsonify({
            "error": f"账户已锁定，请 {minutes} 分 {seconds} 秒后重试",
            "locked": True,
            "retry_after": remaining,
        }), 423

    # 4. 密码验证
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        updated = record_login_failure(username)
        remaining_attempts = max(0, 5 - updated["fail_count"])
        if remaining_attempts > 0:
            msg = f"用户名或密码错误，还可尝试 {remaining_attempts} 次"
        else:
            msg = "密码错误次数过多，账户已锁定 15 分钟"
        return jsonify({
            "error": msg,
            "remaining_attempts": remaining_attempts,
        }), 401

    # 5. 登录成功，重置失败计数
    reset_login_state(username)

    access_token = create_access_token(user["id"], user["username"])
    refresh_token = create_refresh_token(user["id"], user["username"])

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
        "username": user["username"],
    })


@bp.route("/refresh", methods=["POST"])
def refresh():
    data = request.get_json(silent=True) or {}
    token = data.get("refresh_token") or _extract_bearer()

    if not token:
        return jsonify({"error": "缺少 refresh_token"}), 401

    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "refresh_token 已过期，请重新登录"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "refresh_token 无效"}), 401

    if payload.get("type") != "refresh":
        return jsonify({"error": "token 类型错误"}), 401

    access_token = create_access_token(payload["sub"], payload["username"])
    return jsonify({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
    })


@bp.route("/me", methods=["GET"])
@jwt_required
def me():
    return jsonify({
        "user_id": g.current_user["sub"],
        "username": g.current_user["username"],
    })
