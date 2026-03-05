"""
JWT 签发与解码工具
"""

import os
import time

import jwt

SECRET_KEY: str = os.environ.get("JWT_SECRET", "change-me-before-production")
ACCESS_TTL: int = int(os.environ.get("JWT_ACCESS_TTL", 3600))       # 1 小时
REFRESH_TTL: int = int(os.environ.get("JWT_REFRESH_TTL", 604800))   # 7 天
ALGORITHM = "HS256"


def _make_token(user_id: int, username: str, token_type: str, ttl: int) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, username: str) -> str:
    return _make_token(user_id, username, "access", ACCESS_TTL)


def create_refresh_token(user_id: int, username: str) -> str:
    return _make_token(user_id, username, "refresh", REFRESH_TTL)


def decode_token(token: str) -> dict:
    """解码并验证 token，过期或无效时抛出 jwt 异常。"""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
