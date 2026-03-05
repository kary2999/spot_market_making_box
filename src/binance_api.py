"""Binance REST API client.

Provides helpers for the three endpoints needed by the spot market-making
configuration generator:
  - ticker/price      -> current market price
  - exchangeInfo      -> tick/step size, minQty
  - depth             -> top-N order book levels
"""
from __future__ import annotations

from typing import Any

import requests

BINANCE_BASE_URL = "https://api.binance.com/api/v3"
DEFAULT_TIMEOUT = 10  # seconds


def _format_symbol(symbol: str) -> str:
    """Convert 'btc_usdt' -> 'BTCUSDT'."""
    return symbol.replace("_", "").upper()


def get_ticker_price(symbol: str, timeout: int = DEFAULT_TIMEOUT) -> float:
    """Return the latest trade price for *symbol* as a float."""
    binance_symbol = _format_symbol(symbol)
    url = f"{BINANCE_BASE_URL}/ticker/price"
    response = requests.get(url, params={"symbol": binance_symbol}, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if "price" not in data:
        raise ValueError(f"Unexpected response format - 'price' key missing: {data}")
    return float(data["price"])


def get_exchange_info(symbol: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return tick/step size and minQty for *symbol*.

    Returns dict with keys: tickSize (str), stepSize (str), minQty (str).
    """
    binance_symbol = _format_symbol(symbol)
    url = f"{BINANCE_BASE_URL}/exchangeInfo"
    response = requests.get(url, params={"symbol": binance_symbol}, timeout=timeout)
    response.raise_for_status()
    data = response.json()

    result: dict[str, Any] = {}
    for symbol_info in data.get("symbols", []):
        if symbol_info.get("symbol") == binance_symbol:
            for f in symbol_info.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    result["tickSize"] = f["tickSize"]
                elif f.get("filterType") == "LOT_SIZE":
                    result["stepSize"] = f["stepSize"]
                    result["minQty"] = f["minQty"]
            break

    if not result:
        raise ValueError(f"Symbol '{binance_symbol}' not found in exchangeInfo response")
    if "tickSize" not in result:
        raise ValueError(f"PRICE_FILTER missing for '{binance_symbol}'")
    if "stepSize" not in result:
        raise ValueError(f"LOT_SIZE filter missing for '{binance_symbol}'")
    return result


def get_order_book_depth(
    symbol: str, limit: int = 20, timeout: int = DEFAULT_TIMEOUT
) -> dict[str, Any]:
    """Return order book depth with *limit* levels for *symbol*."""
    binance_symbol = _format_symbol(symbol)
    url = f"{BINANCE_BASE_URL}/depth"
    response = requests.get(
        url, params={"symbol": binance_symbol, "limit": limit}, timeout=timeout
    )
    response.raise_for_status()
    data = response.json()
    if "bids" not in data or "asks" not in data:
        raise ValueError(f"Unexpected depth response format - missing bids/asks: {data}")
    return data
