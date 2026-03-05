"""
币安公共 REST API 封装
提供价格查询、tickSize 精度获取、盘口深度查询功能
"""

from __future__ import annotations

import requests

BASE_URL = "https://api.binance.com"
_TIMEOUT = 10  # 请求超时时间（秒）


def _get(path: str, params: dict | None = None) -> dict:
    """发送 GET 请求，统一处理超时与 HTTP 错误"""
    url = BASE_URL + path
    response = requests.get(url, params=params, timeout=_TIMEOUT)
    if not response.ok:
        raise RuntimeError(
            f"币安 API 请求失败: HTTP {response.status_code} - {response.text}"
        )
    return response.json()


def get_price(symbol: str) -> float:
    """获取指定交易对的最新价格

    Args:
        symbol: 交易对，如 "BTCUSDT"

    Returns:
        最新价格浮点数
    """
    data = _get("/api/v3/ticker/price", params={"symbol": symbol})
    return float(data["price"])


def get_tick_size(symbol: str) -> str:
    """获取指定交易对的 tickSize 精度字符串

    优先从 PRICE_FILTER 中读取 tickSize，若不存在则从 LOT_SIZE 中读取。

    Args:
        symbol: 交易对，如 "BTCUSDT"

    Returns:
        tickSize 字符串，如 "0.01000000"
    """
    data = _get("/api/v3/exchangeInfo", params={"symbol": symbol})
    symbols = data.get("symbols", [])
    if not symbols:
        raise ValueError(f"未找到交易对信息: {symbol}")

    filters = {f["filterType"]: f for f in symbols[0].get("filters", [])}

    if "PRICE_FILTER" in filters:
        return filters["PRICE_FILTER"]["tickSize"]
    if "LOT_SIZE" in filters:
        return filters["LOT_SIZE"]["tickSize"]

    raise ValueError(f"未找到 tickSize 信息: {symbol}")


def get_order_book(symbol: str, limit: int = 20) -> dict:
    """获取指定交易对的盘口深度

    Args:
        symbol: 交易对，如 "BTCUSDT"
        limit:  返回档位数量，默认 20，可选 5/10/20/50/100/500/1000/5000

    Returns:
        包含 bids（买盘）和 asks（卖盘）的字典，格式：
        {"bids": [["price", "qty"], ...], "asks": [["price", "qty"], ...]}
    """
    data = _get("/api/v3/depth", params={"symbol": symbol, "limit": limit})
    return {"bids": data["bids"], "asks": data["asks"]}
