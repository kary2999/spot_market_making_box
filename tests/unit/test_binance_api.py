"""Unit tests for src/binance_api.py.

All HTTP calls are mocked — no real network access required.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.binance_api as binance_api
from src.binance_api import get_order_book, get_price, get_tick_size

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_response(data: dict, ok: bool = True, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.text = str(data)
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# _get (internal helper)
# ---------------------------------------------------------------------------


class TestInternalGet:
    @patch("src.binance_api.requests.get")
    def test_raises_runtime_error_on_http_failure(self, mock_get):
        mock_get.return_value = _mock_response({}, ok=False, status_code=400)
        with pytest.raises(RuntimeError, match="HTTP 400"):
            binance_api._get("/api/v3/ticker/price")

    @patch("src.binance_api.requests.get")
    def test_returns_json_on_success(self, mock_get):
        mock_get.return_value = _mock_response({"price": "100.0"})
        result = binance_api._get("/api/v3/ticker/price")
        assert result == {"price": "100.0"}

    @patch("src.binance_api.requests.get")
    def test_builds_url_from_base_url(self, mock_get):
        mock_get.return_value = _mock_response({"price": "100.0"})
        binance_api._get("/api/v3/ticker/price", params={"symbol": "BTCUSDT"})
        args, kwargs = mock_get.call_args
        assert args[0] == binance_api.BASE_URL + "/api/v3/ticker/price"
        assert kwargs["params"] == {"symbol": "BTCUSDT"}

    @patch("src.binance_api.requests.get")
    def test_timeout_applied(self, mock_get):
        mock_get.return_value = _mock_response({"price": "1.0"})
        binance_api._get("/api/v3/ticker/price")
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == binance_api._TIMEOUT


# ---------------------------------------------------------------------------
# get_price
# ---------------------------------------------------------------------------


class TestGetPrice:
    @patch("src.binance_api.requests.get")
    def test_returns_float_btc(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_ticker.json"))
        price = get_price("BTCUSDT")
        assert price == 95000.00
        assert isinstance(price, float)

    @patch("src.binance_api.requests.get")
    def test_returns_float_eth(self, mock_get):
        mock_get.return_value = _mock_response(_load("eth_ticker.json"))
        price = get_price("ETHUSDT")
        assert isinstance(price, float)
        assert price > 0

    @patch("src.binance_api.requests.get")
    def test_symbol_passed_as_param(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_ticker.json"))
        get_price("BTCUSDT")
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"symbol": "BTCUSDT"}

    @patch("src.binance_api.requests.get")
    def test_raises_on_http_error(self, mock_get):
        mock_get.return_value = _mock_response({}, ok=False, status_code=404)
        with pytest.raises(RuntimeError, match="HTTP 404"):
            get_price("BTCUSDT")

    @patch("src.binance_api.requests.get")
    def test_raises_key_error_when_price_missing(self, mock_get):
        mock_get.return_value = _mock_response({"symbol": "BTCUSDT"})
        with pytest.raises(KeyError):
            get_price("BTCUSDT")


# ---------------------------------------------------------------------------
# get_tick_size
# ---------------------------------------------------------------------------


class TestGetTickSize:
    @patch("src.binance_api.requests.get")
    def test_returns_tick_size_from_price_filter(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_exchange_info.json"))
        tick = get_tick_size("BTCUSDT")
        assert tick == "0.01"
        assert isinstance(tick, str)

    @patch("src.binance_api.requests.get")
    def test_returns_tick_size_eth(self, mock_get):
        mock_get.return_value = _mock_response(_load("eth_exchange_info.json"))
        tick = get_tick_size("ETHUSDT")
        assert isinstance(tick, str)
        assert len(tick) > 0

    @patch("src.binance_api.requests.get")
    def test_falls_back_to_lot_size_when_no_price_filter(self, mock_get):
        data = {
            "symbols": [
                {
                    "symbol": "TESTUSDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "tickSize": "0.001", "stepSize": "0.001"},
                    ],
                }
            ]
        }
        mock_get.return_value = _mock_response(data)
        tick = get_tick_size("TESTUSDT")
        assert tick == "0.001"

    @patch("src.binance_api.requests.get")
    def test_raises_value_error_when_symbols_empty(self, mock_get):
        mock_get.return_value = _mock_response({"symbols": []})
        with pytest.raises(ValueError, match="未找到交易对信息"):
            get_tick_size("BTCUSDT")

    @patch("src.binance_api.requests.get")
    def test_raises_value_error_when_no_relevant_filter(self, mock_get):
        data = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "MIN_NOTIONAL", "minNotional": "5.00"},
                    ],
                }
            ]
        }
        mock_get.return_value = _mock_response(data)
        with pytest.raises(ValueError, match="未找到 tickSize 信息"):
            get_tick_size("BTCUSDT")

    @patch("src.binance_api.requests.get")
    def test_raises_on_http_error(self, mock_get):
        mock_get.return_value = _mock_response({}, ok=False, status_code=500)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            get_tick_size("BTCUSDT")

    @patch("src.binance_api.requests.get")
    def test_symbol_passed_as_param(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_exchange_info.json"))
        get_tick_size("BTCUSDT")
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"symbol": "BTCUSDT"}


# ---------------------------------------------------------------------------
# get_order_book
# ---------------------------------------------------------------------------


class TestGetOrderBook:
    @patch("src.binance_api.requests.get")
    def test_returns_bids_and_asks(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_depth.json"))
        book = get_order_book("BTCUSDT")
        assert "bids" in book
        assert "asks" in book

    @patch("src.binance_api.requests.get")
    def test_btc_bids_asks_count(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_depth.json"))
        book = get_order_book("BTCUSDT")
        assert len(book["bids"]) == 20
        assert len(book["asks"]) == 20

    @patch("src.binance_api.requests.get")
    def test_eth_depth(self, mock_get):
        mock_get.return_value = _mock_response(_load("eth_depth.json"))
        book = get_order_book("ETHUSDT")
        assert "bids" in book
        assert "asks" in book

    @patch("src.binance_api.requests.get")
    def test_default_limit_is_20(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_depth.json"))
        get_order_book("BTCUSDT")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["limit"] == 20

    @patch("src.binance_api.requests.get")
    def test_custom_limit_forwarded(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_depth.json"))
        get_order_book("BTCUSDT", limit=5)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["limit"] == 5

    @patch("src.binance_api.requests.get")
    def test_symbol_passed_as_param(self, mock_get):
        mock_get.return_value = _mock_response(_load("btc_depth.json"))
        get_order_book("SHIBUSDT")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["symbol"] == "SHIBUSDT"

    @patch("src.binance_api.requests.get")
    def test_raises_on_http_error(self, mock_get):
        mock_get.return_value = _mock_response({}, ok=False, status_code=400)
        with pytest.raises(RuntimeError, match="HTTP 400"):
            get_order_book("BTCUSDT")

    @patch("src.binance_api.requests.get")
    def test_only_bids_asks_in_return_value(self, mock_get):
        """Verify lastUpdateId and other fields are stripped from result."""
        mock_get.return_value = _mock_response(_load("btc_depth.json"))
        book = get_order_book("BTCUSDT")
        assert set(book.keys()) == {"bids", "asks"}

    @patch("src.binance_api.requests.get")
    def test_raises_key_error_when_bids_missing(self, mock_get):
        mock_get.return_value = _mock_response({"asks": [["100.0", "1.0"]]})
        with pytest.raises(KeyError):
            get_order_book("BTCUSDT")
