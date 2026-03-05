"""
币安公共 REST API 封装
提供价格查询、tickSize/stepSize/minQty 精度获取、盘口深度查询功能
"""

from __future__ import annotations

import requests

BASE_URL = "https://api.binance.com"
_TIMEOUT = 10  # 请求超时时间（秒）


def normalize_symbol(symbol: str) -> str:
    """将内部交易对格式转为币安格式，如 'btc_usdt' -> 'BTCUSDT'"""
    return symbol.replace("_", "").upper()


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
        symbol: 交易对，支持 'btc_usdt' 或 'BTCUSDT' 格式

    Returns:
        最新价格浮点数
    """
    data = _get("/api/v3/ticker/price", params={"symbol": normalize_symbol(symbol)})
    return float(data["price"])


def get_exchange_info(symbol: str) -> dict:
    """获取指定交易对的 tickSize、stepSize、minQty 精度信息

    Args:
        symbol: 交易对，支持 'btc_usdt' 或 'BTCUSDT' 格式

    Returns:
        dict，包含：
            - tickSize (str): 最小价格变动单位，如 '0.01000000'
            - stepSize (str): 最小数量变动单位，如 '0.00001000'
            - minQty (str): 最小下单数量，如 '0.00001000'
            - price_precision (int): 价格小数位数
            - qty_precision (int): 数量小数位数
    """
    data = _get("/api/v3/exchangeInfo", params={"symbol": normalize_symbol(symbol)})
    symbols = data.get("symbols", [])
    if not symbols:
        raise ValueError(f"未找到交易对信息: {symbol}")

    filters = {f["filterType"]: f for f in symbols[0].get("filters", [])}

    if "PRICE_FILTER" not in filters:
        raise ValueError(f"未找到 PRICE_FILTER 信息: {symbol}")
    if "LOT_SIZE" not in filters:
        raise ValueError(f"未找到 LOT_SIZE 信息: {symbol}")

    tick_size = filters["PRICE_FILTER"]["tickSize"]
    step_size = filters["LOT_SIZE"]["stepSize"]
    min_qty = filters["LOT_SIZE"]["minQty"]

    def _decimal_places(value: str) -> int:
        """计算有效小数位数，例如 '0.01000000' -> 2"""
        value = value.rstrip("0")
        if "." in value:
            return len(value.split(".")[1])
        return 0

    return {
        "tickSize": tick_size,
        "stepSize": step_size,
        "minQty": min_qty,
        "price_precision": _decimal_places(tick_size),
        "qty_precision": _decimal_places(step_size),
    }


def get_order_book(symbol: str, limit: int = 20) -> dict:
    """获取指定交易对的盘口深度

    Args:
        symbol: 交易对，支持 'btc_usdt' 或 'BTCUSDT' 格式
        limit:  返回档位数量，默认 20，可选 5/10/20/50/100/500/1000/5000

    Returns:
        dict，包含：
            - bids (list): 买盘 [[price(float), qty(float)], ...]，从高到低排列
            - asks (list): 卖盘 [[price(float), qty(float)], ...]，从低到高排列
            - best_bid (float): 最优买价
            - best_ask (float): 最优卖价
            - bid_total_qty (float): 买盘总数量
            - ask_total_qty (float): 卖盘总数量
    """
    data = _get("/api/v3/depth", params={"symbol": normalize_symbol(symbol), "limit": limit})

    bids = [[float(p), float(q)] for p, q in data["bids"]]
    asks = [[float(p), float(q)] for p, q in data["asks"]]

    if not bids or not asks:
        raise RuntimeError(f"盘口数据为空: {symbol}")

    return {
        "bids": bids,
        "asks": asks,
        "best_bid": bids[0][0],
        "best_ask": asks[0][0],
        "bid_total_qty": sum(q for _, q in bids),
        "ask_total_qty": sum(q for _, q in asks),
    }


if __name__ == "__main__":
    import json

    symbol = "btc_usdt"
    print(f"=== 币安 API 测试: {symbol} ===\n")

    price = get_price(symbol)
    print(f"当前价格: {price}\n")

    info = get_exchange_info(symbol)
    print(f"精度信息:\n{json.dumps(info, indent=2, ensure_ascii=False)}\n")

    book = get_order_book(symbol, limit=20)
    print(f"最优买价: {book['best_bid']}, 最优卖价: {book['best_ask']}")
    print(f"买盘总量: {book['bid_total_qty']:.6f}, 卖盘总量: {book['ask_total_qty']:.6f}")
    print(f"Top 3 买盘: {book['bids'][:3]}")
    print(f"Top 3 卖盘: {book['asks'][:3]}")
