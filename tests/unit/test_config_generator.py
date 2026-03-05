"""
单元测试 — ConfigGenerator 类及 _floor_to_precision (src/config_generator.py)
覆盖：等差/等比网格价格生成、下单数量计算、完整配置生成、JSON 导出、边界/异常情况
"""

import json
import os
import tempfile
from decimal import Decimal

import pytest

from src.config_generator import (
    ConfigGenerator,
    _build_price_ranges,
    _calc_number_float,
    _cumulative_qty,
    _decimal_places,
    _floor_to_precision,
    _format_price,
    _format_qty,
    _get_zone,
    generate_configs,
)


# ---------------------------------------------------------------------------
# _floor_to_precision
# ---------------------------------------------------------------------------


class TestFloorToPrecision:
    def test_basic_truncation(self):
        assert _floor_to_precision(Decimal("1.2345"), "0.01") == Decimal("1.23")

    def test_exact_multiple_unchanged(self):
        assert _floor_to_precision(Decimal("1.50"), "0.01") == Decimal("1.50")

    def test_integer_precision(self):
        assert _floor_to_precision(Decimal("1234.9"), "1") == Decimal("1234")

    def test_eight_decimal_places(self):
        result = _floor_to_precision(Decimal("0.000123456789"), "0.00000001")
        assert result == Decimal("0.00012345")

    def test_zero_value(self):
        assert _floor_to_precision(Decimal("0"), "0.01") == Decimal("0")


# ---------------------------------------------------------------------------
# ConfigGenerator.__init__ — 参数验证
# ---------------------------------------------------------------------------


class TestConfigGeneratorInit:
    def test_valid_arithmetic(self):
        gen = ConfigGenerator("BTCUSDT", 90000, 100000, 5, 10000, "0.01", "0.00001")
        assert gen.symbol == "BTCUSDT"
        assert gen.grid_mode == "arithmetic"

    def test_valid_geometric(self):
        gen = ConfigGenerator("ETHUSDT", 2000, 3000, 10, 5000, "0.01", "0.001",
                              grid_mode="geometric")
        assert gen.grid_mode == "geometric"

    def test_grid_count_minimum_is_two(self):
        with pytest.raises(ValueError, match="grid_count"):
            ConfigGenerator("BTCUSDT", 90000, 100000, 1, 10000, "0.01", "0.00001")

    def test_price_low_equal_price_high_raises(self):
        with pytest.raises(ValueError, match="price_low"):
            ConfigGenerator("BTCUSDT", 100000, 100000, 5, 10000, "0.01", "0.00001")

    def test_price_low_greater_than_price_high_raises(self):
        with pytest.raises(ValueError, match="price_low"):
            ConfigGenerator("BTCUSDT", 110000, 100000, 5, 10000, "0.01", "0.00001")

    def test_invalid_grid_mode_raises(self):
        with pytest.raises(ValueError, match="grid_mode"):
            ConfigGenerator("BTCUSDT", 90000, 100000, 5, 10000, "0.01", "0.00001",
                            grid_mode="random")

    def test_string_prices_accepted(self):
        gen = ConfigGenerator("BTCUSDT", "90000", "100000", 5, "10000", "0.01", "0.00001")
        assert gen.price_low == Decimal("90000")
        assert gen.price_high == Decimal("100000")


# ---------------------------------------------------------------------------
# generate_grid_prices — 等差模式
# ---------------------------------------------------------------------------


class TestGenerateGridPricesArithmetic:
    def _gen(self, low, high, count, tick="0.01"):
        return ConfigGenerator("BTCUSDT", low, high, count, 10000, tick, "0.00001")

    def test_returns_correct_count(self):
        prices = self._gen(100, 200, 5).generate_grid_prices()
        assert len(prices) == 5

    def test_first_price_equals_price_low(self):
        gen = self._gen(100, 200, 5)
        prices = gen.generate_grid_prices()
        assert prices[0] == _floor_to_precision(gen.price_low, gen.tick_size)

    def test_last_price_equals_price_high(self):
        gen = self._gen(100, 200, 5)
        prices = gen.generate_grid_prices()
        assert prices[-1] == _floor_to_precision(gen.price_high, gen.tick_size)

    def test_prices_strictly_ascending(self):
        prices = self._gen(100, 200, 10).generate_grid_prices()
        for i in range(len(prices) - 1):
            assert prices[i] < prices[i + 1], f"prices[{i}]={prices[i]} >= prices[{i+1}]={prices[i+1]}"

    def test_equal_spacing(self):
        """等差模式间距应相等（精度截断后可有1个最小单位误差）"""
        prices = self._gen(0, 100, 5, tick="1").generate_grid_prices()
        # expected: 0, 25, 50, 75, 100
        assert prices == [Decimal("0"), Decimal("25"), Decimal("50"),
                          Decimal("75"), Decimal("100")]

    def test_all_prices_aligned_to_tick(self):
        tick = Decimal("0.01")
        prices = self._gen(95000, 96000, 8).generate_grid_prices()
        for p in prices:
            remainder = (p / tick) % 1
            assert remainder == 0, f"price {p} not aligned to tick 0.01"

    def test_two_grid_prices(self):
        prices = self._gen(100, 200, 2).generate_grid_prices()
        assert len(prices) == 2
        assert prices[0] == Decimal("100")
        assert prices[1] == Decimal("200")


# ---------------------------------------------------------------------------
# generate_grid_prices — 等比模式
# ---------------------------------------------------------------------------


class TestGenerateGridPricesGeometric:
    def _gen(self, low, high, count, tick="0.01"):
        return ConfigGenerator("BTCUSDT", low, high, count, 10000, tick, "0.00001",
                               grid_mode="geometric")

    def test_returns_correct_count(self):
        assert len(self._gen(100, 200, 5).generate_grid_prices()) == 5

    def test_first_price_equals_price_low(self):
        gen = self._gen(100, 200, 5)
        prices = gen.generate_grid_prices()
        assert prices[0] == _floor_to_precision(gen.price_low, gen.tick_size)

    def test_prices_strictly_ascending(self):
        prices = self._gen(1000, 2000, 10).generate_grid_prices()
        for i in range(len(prices) - 1):
            assert prices[i] < prices[i + 1]

    def test_all_prices_aligned_to_tick(self):
        tick = Decimal("0.01")
        prices = self._gen(1000, 2000, 6).generate_grid_prices()
        for p in prices:
            remainder = (p / tick) % 1
            assert remainder == 0, f"price {p} not aligned to tick"

    def test_geometric_growth(self):
        """相邻价格的比值近似恒定：(high/low)^(1/(n-1))"""
        gen = self._gen(100, 10000, 5, tick="1")
        prices = gen.generate_grid_prices()
        # 理论比值 = (10000/100)^(1/4) = 100^0.25 ≈ 3.162
        expected_ratio = Decimal("3.16")
        for i in range(len(prices) - 1):
            ratio = prices[i + 1] / prices[i]
            assert abs(ratio - expected_ratio) < Decimal("0.5"), \
                f"ratio at {i}: {ratio} deviates too far from {expected_ratio}"


# ---------------------------------------------------------------------------
# calc_order_qty
# ---------------------------------------------------------------------------


class TestCalcOrderQty:
    def _gen(self):
        return ConfigGenerator("BTCUSDT", 90000, 100000, 5, 50000, "0.01", "0.00001")

    def test_basic_calculation(self):
        gen = self._gen()
        qty = gen.calc_order_qty(Decimal("100"), Decimal("1000"))
        assert qty == Decimal("10.00000")

    def test_rounds_down_not_up(self):
        gen = self._gen()
        # 1000 / 3 = 333.333... → floor to 0.00001 → 333.33333
        qty = gen.calc_order_qty(Decimal("3"), Decimal("1000"))
        assert qty == Decimal("333.33333")

    def test_aligned_to_step_size(self):
        gen = self._gen()
        step = Decimal("0.00001")
        qty = gen.calc_order_qty(Decimal("95000"), Decimal("50000"))
        remainder = (qty / step) % 1
        assert remainder == 0

    def test_zero_price_raises(self):
        gen = self._gen()
        with pytest.raises(ValueError, match="价格必须大于 0"):
            gen.calc_order_qty(Decimal("0"), Decimal("1000"))

    def test_negative_price_raises(self):
        gen = self._gen()
        with pytest.raises(ValueError, match="价格必须大于 0"):
            gen.calc_order_qty(Decimal("-1"), Decimal("1000"))

    def test_tiny_budget_returns_zero_qty(self):
        """预算极小，结果向下截断为 0"""
        gen = self._gen()
        qty = gen.calc_order_qty(Decimal("100000"), Decimal("0.000001"))
        assert qty == Decimal("0.00000")


# ---------------------------------------------------------------------------
# generate_config
# ---------------------------------------------------------------------------


class TestGenerateConfig:
    def _gen(self, low=90000, high=100000, count=6, budget=60000,
             tick="0.01", step="0.00001", mode="arithmetic"):
        return ConfigGenerator("BTCUSDT", low, high, count, budget, tick, step,
                               grid_mode=mode)

    def test_returns_list_of_dicts(self):
        result = self._gen().generate_config()
        assert isinstance(result, list)
        assert all(isinstance(r, dict) for r in result)

    def test_output_length_equals_grid_count(self):
        for n in [2, 5, 10]:
            gen = self._gen(count=n)
            assert len(gen.generate_config()) == n

    def test_required_keys_present(self):
        result = self._gen().generate_config()
        for item in result:
            assert "price" in item
            assert "qty" in item
            assert "side" in item
            assert "order_type" in item

    def test_side_always_buy(self):
        result = self._gen().generate_config()
        for item in result:
            assert item["side"] == "BUY"

    def test_order_type_always_limit(self):
        result = self._gen().generate_config()
        for item in result:
            assert item["order_type"] == "LIMIT"

    def test_price_and_qty_are_strings(self):
        result = self._gen().generate_config()
        for item in result:
            assert isinstance(item["price"], str)
            assert isinstance(item["qty"], str)

    def test_prices_parseable_as_decimal(self):
        result = self._gen().generate_config()
        for item in result:
            Decimal(item["price"])  # should not raise

    def test_qty_non_negative(self):
        result = self._gen().generate_config()
        for item in result:
            assert Decimal(item["qty"]) >= 0

    def test_geometric_mode_output(self):
        result = self._gen(mode="geometric").generate_config()
        assert len(result) == 6

    def test_budget_split_evenly(self):
        """每格预算 = total_budget / grid_count，qty = floor(budget_per_grid / price)"""
        gen = self._gen(low=100, high=200, count=4, budget=400, tick="1", step="1")
        result = gen.generate_config()
        budget_per_grid = Decimal("400") / 4  # = 100
        for item in result:
            price = Decimal(item["price"])
            expected_qty = _floor_to_precision(budget_per_grid / price, "1")
            assert Decimal(item["qty"]) == expected_qty


# ---------------------------------------------------------------------------
# export_json
# ---------------------------------------------------------------------------


class TestExportJson:
    def _gen(self):
        return ConfigGenerator("BTCUSDT", 90000, 100000, 4, 40000, "0.01", "0.00001")

    def test_creates_file(self):
        gen = self._gen()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            gen.export_json(path)
            assert os.path.exists(path)
        finally:
            os.unlink(path)

    def test_valid_json_content(self):
        gen = self._gen()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            gen.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert "symbol" in data
            assert "grid_mode" in data
            assert "orders" in data
        finally:
            os.unlink(path)

    def test_symbol_in_json(self):
        gen = self._gen()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            gen.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["symbol"] == "BTCUSDT"
        finally:
            os.unlink(path)

    def test_orders_count_matches_grid_count(self):
        gen = self._gen()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            gen.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data["orders"]) == gen.grid_count
        finally:
            os.unlink(path)

    def test_grid_mode_in_json(self):
        gen = ConfigGenerator("ETHUSDT", 2000, 3000, 5, 5000, "0.01", "0.001",
                              grid_mode="geometric")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            gen.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["grid_mode"] == "geometric"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# _get_zone
# ---------------------------------------------------------------------------


class TestGetZone:
    def test_dom1_near(self):
        assert _get_zone(1) == "near"

    def test_dom2_mid(self):
        assert _get_zone(2) == "mid"

    def test_dom3_mid(self):
        assert _get_zone(3) == "mid"

    def test_dom4_far(self):
        assert _get_zone(4) == "far"

    def test_dom5_far(self):
        assert _get_zone(5) == "far"

    def test_dom6_far(self):
        assert _get_zone(6) == "far"


# ---------------------------------------------------------------------------
# _decimal_places
# ---------------------------------------------------------------------------


class TestDecimalPlaces:
    def test_two_decimal_places(self):
        assert _decimal_places("0.01") == 2

    def test_eight_decimal_places_normalized(self):
        # "0.00100000" normalizes to "0.001" → 3 places
        assert _decimal_places("0.00100000") == 3

    def test_integer_tick_zero_places(self):
        assert _decimal_places("1") == 0

    def test_five_zeros_tick(self):
        assert _decimal_places("0.00001") == 5


# ---------------------------------------------------------------------------
# _format_price / _format_qty
# ---------------------------------------------------------------------------


class TestFormatPrice:
    def test_rounds_down_to_tick(self):
        result = _format_price(Decimal("95000.999"), Decimal("0.01"))
        assert result == "95000.99"

    def test_exact_multiple_unchanged(self):
        assert _format_price(Decimal("100.00"), Decimal("0.01")) == "100.00"

    def test_integer_tick(self):
        assert _format_price(Decimal("99.9"), Decimal("1")) == "99"


class TestFormatQty:
    def test_rounds_down(self):
        result = _format_qty(Decimal("1.0059"), Decimal("0.001"))
        assert result == "1.005"

    def test_exact_qty(self):
        assert _format_qty(Decimal("2.500"), Decimal("0.001")) == "2.500"


# ---------------------------------------------------------------------------
# _cumulative_qty
# ---------------------------------------------------------------------------


class TestCumulativeQty:
    def test_sums_first_n(self):
        side = [["100", "2.0"], ["99", "3.0"], ["98", "5.0"]]
        assert _cumulative_qty(side, 2) == Decimal("5.0")

    def test_depth_exceeds_length(self):
        side = [["100", "1.0"], ["99", "1.0"]]
        assert _cumulative_qty(side, 10) == Decimal("2.0")

    def test_zero_depth_returns_zero(self):
        side = [["100", "1.0"]]
        assert _cumulative_qty(side, 0) == Decimal("0")

    def test_string_qty_parsed(self):
        side = [["100.5", "0.500"]]
        assert _cumulative_qty(side, 1) == Decimal("0.5")


# ---------------------------------------------------------------------------
# _calc_number_float
# ---------------------------------------------------------------------------

# 简单盘口：买卖各 20 档，每档 qty=1
_SIDE_20 = [[str(i), "1.0"] for i in range(1, 21)]
_ORDER_BOOK = {"bids": _SIDE_20, "asks": _SIDE_20}
_STEP = Decimal("0.001")


class TestCalcNumberFloat:
    def test_near_returns_range_string(self):
        result = _calc_number_float(_ORDER_BOOK, "near", _STEP)
        assert "-" in result

    def test_min_less_than_max(self):
        result = _calc_number_float(_ORDER_BOOK, "mid", _STEP)
        lo, hi = result.split("-")
        assert Decimal(lo) < Decimal(hi)

    def test_far_zone_no_crash(self):
        result = _calc_number_float(_ORDER_BOOK, "far", _STEP)
        assert "-" in result

    def test_small_order_book_no_crash(self):
        small = {"bids": [["100", "0.001"]], "asks": [["101", "0.001"]]}
        result = _calc_number_float(small, "near", Decimal("0.001"))
        assert "-" in result


# ---------------------------------------------------------------------------
# _build_price_ranges
# ---------------------------------------------------------------------------


class TestBuildPriceRanges:
    def test_count_matches_levels(self):
        ranges = _build_price_ranges(100.0, Decimal("0.01"), 6, -1)
        assert len(ranges) == 6

    def test_sell_each_range_low_lt_high(self):
        for lo, hi in _build_price_ranges(100.0, Decimal("0.01"), 6, -1):
            assert hi > lo

    def test_buy_price_not_negative(self):
        for lo, _ in _build_price_ranges(0.01, Decimal("0.01"), 6, 1):
            assert lo >= Decimal("0")

    def test_sell_ranges_contiguous(self):
        ranges = _build_price_ranges(100.0, Decimal("0.01"), 6, -1)
        for i in range(1, len(ranges)):
            assert ranges[i][0] == ranges[i - 1][1]

    def test_buy_ranges_contiguous(self):
        ranges = _build_price_ranges(100.0, Decimal("0.01"), 6, 1)
        for i in range(1, len(ranges)):
            assert ranges[i][1] == ranges[i - 1][0]


# ---------------------------------------------------------------------------
# generate_configs
# ---------------------------------------------------------------------------

_EXCHANGE_INFO = {"tickSize": "0.01", "stepSize": "0.001"}


class TestGenerateConfigs:
    def _call(self, **kwargs):
        defaults = dict(
            symbol="BTCUSDT",
            levels=6,
            total_usdt=1000.0,
            pid=42,
            current_price=95000.0,
            exchange_info=_EXCHANGE_INFO,
            order_book=_ORDER_BOOK,
        )
        defaults.update(kwargs)
        return generate_configs(**defaults)

    def test_total_count_is_levels_times_two(self):
        assert len(self._call()) == 12  # 6 levels × 2 directions

    def test_required_keys_present(self):
        required = {
            "box_id", "pid", "direction", "dom", "trust_num",
            "price_float", "number_float", "change_trust_num",
            "change_number_float", "change_survival_time", "status",
        }
        for c in self._call():
            assert required.issubset(c.keys())

    def test_pid_matches_input(self):
        for c in self._call(pid=99):
            assert c["pid"] == 99

    def test_both_directions_present(self):
        directions = {c["direction"] for c in self._call()}
        assert directions == {-1, 1}

    def test_dom_range_1_to_levels(self):
        doms = {c["dom"] for c in self._call()}
        assert doms == set(range(1, 7))

    def test_status_always_one(self):
        for c in self._call():
            assert c["status"] == 1

    def test_box_id_is_none(self):
        for c in self._call():
            assert c["box_id"] is None

    def test_dom1_change_trust_num_zero(self):
        for c in self._call():
            if c["dom"] == 1:
                assert c["change_trust_num"] == 0

    def test_dom_gt_1_change_trust_num_one(self):
        for c in self._call():
            if c["dom"] > 1:
                assert c["change_trust_num"] == 1

    def test_price_float_contains_dash(self):
        for c in self._call():
            assert "-" in c["price_float"]

    def test_direction_labels_in_internal_field(self):
        labels = {c["_direction_label"] for c in self._call()}
        assert labels == {"买", "卖"}

    def test_zone_field_present(self):
        for c in self._call():
            assert c.get("_zone") in ("near", "mid", "far")
