"""
JWT 验证中间件 — 装饰器 jwt_required
"""

from functools import wraps

import jwt
from flask import g, jsonify, request

from .jwt_utils import decode_token


def jwt_required(f):
    """保护路由，要求请求头携带有效的 Bearer access token。"""

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "缺少认证 token"}), 401

        token = auth_header[7:]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "token 已过期，请重新登录或刷新 token"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "token 无效"}), 401

        if payload.get("type") != "access":
            return jsonify({"error": "token 类型错误，请使用 access token"}), 401

        g.current_user = payload
        return f(*args, **kwargs)

    return decorated
