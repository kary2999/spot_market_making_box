"""
Portal API 蓝图

用户端:
  POST /portal/api/auth/login           — 邮箱 + 邀请码登录，返回 access + refresh token
  POST /portal/api/auth/refresh         — 用 refresh token 换新 access token
  GET  /portal/api/auth/me              — 当前用户信息（需 access token）
  GET  /portal/api/instances            — 当前用户的实例列表
  GET  /portal/api/usage                — 当前用户的用量记录

管理员端 (role=admin):
  GET    /portal/api/admin/users                          — 所有用户列表
  POST   /portal/api/admin/users                          — 创建用户
  PATCH  /portal/api/admin/users/<uid>                    — 修改用户名/语言
  POST   /portal/api/admin/users/<uid>/suspend            — 停用用户
  POST   /portal/api/admin/users/<uid>/activate           — 启用用户
  GET    /portal/api/admin/instances                      — 所有实例列表
  POST   /portal/api/admin/instances                      — 创建实例
  POST   /portal/api/admin/users/<uid>/instances/<iid>    — 分配实例
  DELETE /portal/api/admin/users/<uid>/instances/<iid>    — 取消分配
"""

from __future__ import annotations

import secrets

import jwt
from flask import Blueprint, g, jsonify, request

from .auth import (
    PORTAL_ACCESS_TTL,
    create_portal_access_token,
    create_portal_refresh_token,
    decode_portal_token,
    portal_admin_required,
    portal_jwt_required,
)
from .models import (
    assign_instance,
    create_instance,
    create_portal_user,
    get_portal_user_by_email,
    get_portal_user_by_id,
    get_usage,
    list_instances,
    list_portal_users,
    list_user_instances,
    set_portal_user_status,
    unassign_instance,
    update_portal_user,
)

bp = Blueprint("portal", __name__, url_prefix="/portal/api")


# ---------------------------------------------------------------------------
# 用户认证
# ---------------------------------------------------------------------------

@bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    invite_token = (data.get("invite_token") or "").strip()

    if not email or not invite_token:
        return jsonify({"error": "email 和 invite_token 不能为空"}), 400

    user = get_portal_user_by_email(email)
    if user is None or user.get("invite_token") != invite_token:
        return jsonify({"error": "邮箱或邀请码无效"}), 401

    if user["status"] == "suspended":
        return jsonify({"error": "账户已停用，请联系管理员"}), 403

    access_token = create_portal_access_token(user["id"], user["email"])
    refresh_token = create_portal_refresh_token(user["id"], user["email"])

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": PORTAL_ACCESS_TTL,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "language": user["language"],
        },
    })


@bp.route("/auth/refresh", methods=["POST"])
def refresh():
    data = request.get_json(silent=True) or {}
    token = data.get("refresh_token") or ""
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]

    if not token:
        return jsonify({"error": "缺少 refresh_token"}), 401

    try:
        payload = decode_portal_token(token)
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "refresh_token 已过期，请重新登录"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "refresh_token 无效"}), 401

    if payload.get("type") != "refresh" or payload.get("iss") != "portal":
        return jsonify({"error": "token 类型错误"}), 401

    access_token = create_portal_access_token(payload["sub"], payload["email"])
    return jsonify({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": PORTAL_ACCESS_TTL,
    })


@bp.route("/auth/me", methods=["GET"])
@portal_jwt_required
def me():
    user = get_portal_user_by_id(g.portal_user["sub"])
    if user is None:
        return jsonify({"error": "用户不存在"}), 404
    return jsonify({
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "language": user["language"],
        "status": user["status"],
    })


# ---------------------------------------------------------------------------
# 用户端：实例 & 用量
# ---------------------------------------------------------------------------

@bp.route("/instances", methods=["GET"])
@portal_jwt_required
def user_instances():
    user_id = g.portal_user["sub"]
    instances = list_user_instances(user_id)
    return jsonify({"instances": instances})


@bp.route("/usage", methods=["GET"])
@portal_jwt_required
def user_usage():
    user_id = g.portal_user["sub"]
    year_month = request.args.get("month")  # 可选，格式 YYYY-MM
    records = get_usage(user_id, year_month)
    return jsonify({"usage": records})


# ---------------------------------------------------------------------------
# 管理员端：用户管理
# ---------------------------------------------------------------------------

@bp.route("/admin/users", methods=["GET"])
@portal_admin_required
def admin_list_users():
    users = list_portal_users()
    return jsonify({"users": users})


@bp.route("/admin/users", methods=["POST"])
@portal_admin_required
def admin_create_user():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()

    if not email:
        return jsonify({"error": "email 不能为空"}), 400

    if get_portal_user_by_email(email):
        return jsonify({"error": "该邮箱已存在"}), 409

    token = secrets.token_urlsafe(32)
    user = create_portal_user(email=email, name=name, invite_token=token)
    return jsonify({"user": user, "invite_token": token}), 201


@bp.route("/admin/users/<int:uid>", methods=["PATCH"])
@portal_admin_required
def admin_update_user(uid: int):
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    language = data.get("language")

    user = update_portal_user(uid, name=name, language=language)
    if user is None:
        return jsonify({"error": "用户不存在"}), 404
    return jsonify({"user": user})


@bp.route("/admin/users/<int:uid>/suspend", methods=["POST"])
@portal_admin_required
def admin_suspend_user(uid: int):
    user = set_portal_user_status(uid, "suspended")
    if user is None:
        return jsonify({"error": "用户不存在"}), 404
    return jsonify({"user": user})


@bp.route("/admin/users/<int:uid>/activate", methods=["POST"])
@portal_admin_required
def admin_activate_user(uid: int):
    user = set_portal_user_status(uid, "active")
    if user is None:
        return jsonify({"error": "用户不存在"}), 404
    return jsonify({"user": user})


# ---------------------------------------------------------------------------
# 管理员端：实例管理
# ---------------------------------------------------------------------------

@bp.route("/admin/instances", methods=["GET"])
@portal_admin_required
def admin_list_instances():
    return jsonify({"instances": list_instances()})


@bp.route("/admin/instances", methods=["POST"])
@portal_admin_required
def admin_create_instance():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    endpoint_url = (data.get("endpoint_url") or "").strip()
    description = (data.get("description") or "").strip()

    if not name or not endpoint_url:
        return jsonify({"error": "name 和 endpoint_url 不能为空"}), 400

    instance = create_instance(name=name, endpoint_url=endpoint_url, description=description)
    return jsonify({"instance": instance}), 201


@bp.route("/admin/users/<int:uid>/instances/<int:iid>", methods=["POST"])
@portal_admin_required
def admin_assign_instance(uid: int, iid: int):
    ok = assign_instance(uid, iid)
    if not ok:
        return jsonify({"error": "该用户已分配此实例"}), 409
    return jsonify({"message": "分配成功"}), 201


@bp.route("/admin/users/<int:uid>/instances/<int:iid>", methods=["DELETE"])
@portal_admin_required
def admin_unassign_instance(uid: int, iid: int):
    unassign_instance(uid, iid)
    return jsonify({"message": "取消分配成功"})
