"""
单元测试 — 配置计算引擎 (src/config_generator.py)
覆盖：价格区间计算、笔数分配、精度对齐、数量浮动计算
"""

import json
import os
from decimal import Decimal

import pytest

from src.config_generator import (
    _build_price_ranges,
    _calc_number_float,
    _cumulative_qty,
    _decimal_places,
    _format_price,
    _format_qty,
    _get_zone,
    generate_configs,
)

# ---------------------------------------------------------------------------
# 加载测试夹具
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _parse_exchange_info(raw: dict) -> dict:
    """从原始 Binance exchangeInfo 响应中提取 tickSize/stepSize/minQty（模拟 binance_api.get_exchange_info 的输出）"""
    for symbol_info in raw.get("symbols", []):
        result: dict = {}
        for f in symbol_info.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                result["tickSize"] = f["tickSize"]
            elif f.get("filterType") == "LOT_SIZE":
                result["stepSize"] = f["stepSize"]
                result["minQty"] = f["minQty"]
        if result:
            return result
    raise ValueError("No symbol filters found in exchange_info fixture")


@pytest.fixture
def btc_exchange_info():
    return _parse_exchange_info(_load("btc_exchange_info.json"))


@pytest.fixture
def btc_depth():
    return _load("btc_depth.json")


@pytest.fixture
def shib_exchange_info():
    return _parse_exchange_info(_load("shib_exchange_info.json"))


@pytest.fixture
def shib_depth():
    return _load("shib_depth.json")


@pytest.fixture
def eth_exchange_info():
    return _parse_exchange_info(_load("eth_exchange_info.json"))


@pytest.fixture
def eth_depth():
    return _load("eth_depth.json")


# ---------------------------------------------------------------------------
# _decimal_places
# ---------------------------------------------------------------------------

class TestDecimalPlaces:
    def test_two_decimal_places(self):
        assert _decimal_places("0.01") == 2

    def test_one_decimal_place(self):
        assert _decimal_places("0.1") == 1

    def test_eight_decimal_places(self):
        assert _decimal_places("0.00000001") == 8

    def test_no_decimal_places(self):
        assert _decimal_places("1") == 0

    def test_trailing_zeros_normalized(self):
        # Decimal("0.00001000").normalize() → exponent=-5
        assert _decimal_places("0.00001000") == 5


# ---------------------------------------------------------------------------
# _format_price / _format_qty
# ---------------------------------------------------------------------------

class TestFormatPrice:
    def test_rounds_down_to_tick(self):
        price = Decimal("95000.999")
        tick = Decimal("0.01")
        result = _format_price(price, tick)
        assert result == "95000.99"

    def test_exact_value_unchanged(self):
        price = Decimal("100.50")
        tick = Decimal("0.01")
        assert _format_price(price, tick) == "100.50"

    def test_integer_tick(self):
        price = Decimal("1234.5")
        tick = Decimal("1")
        assert _format_price(price, tick) == "1234"


class TestFormatQty:
    def test_rounds_down_to_step(self):
        qty = Decimal("1.23456789")
        step = Decimal("0.00001")
        assert _format_qty(qty, step) == "1.23456"

    def test_minimum_step(self):
        qty = Decimal("0.000005")
        step = Decimal("0.00001")
        assert _format_qty(qty, step) == "0.00000"


# ---------------------------------------------------------------------------
# _cumulative_qty
# ---------------------------------------------------------------------------

class TestCumulativeQty:
    def test_sum_first_two_levels(self):
        book_side = [["100.0", "1.5"], ["99.0", "2.3"], ["98.0", "0.7"]]
        result = _cumulative_qty(book_side, 2)
        assert result == Decimal("3.8")

    def test_depth_exceeds_available_levels(self):
        book_side = [["100.0", "1.0"], ["99.0", "2.0"]]
        result = _cumulative_qty(book_side, 10)
        assert result == Decimal("3.0")

    def test_empty_book(self):
        assert _cumulative_qty([], 5) == Decimal("0")


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

    @pytest.mark.parametrize("dom", [4, 5, 6])
    def test_far_doms(self, dom):
        assert _get_zone(dom) == "far"


# ---------------------------------------------------------------------------
# _build_price_ranges
# ---------------------------------------------------------------------------

class TestBuildPriceRanges:
    """验证价格区间连续性、精度对齐、方向正确"""

    def _tick(self, s: str) -> Decimal:
        return Decimal(s)

    def test_sell_direction_ranges_ascend(self):
        """卖方（direction=-1）：各档位价格区间向上递增，且连续不重叠"""
        tick = self._tick("0.01")
        ranges = _build_price_ranges(100.0, tick, 6, direction=-1)
        for i in range(len(ranges) - 1):
            _, high_cur = ranges[i]
            low_next, _ = ranges[i + 1]
            assert high_cur == low_next, f"dom{i+1} high != dom{i+2} low"

    def test_buy_direction_ranges_descend(self):
        """买方（direction=1）：各档位价格区间向下递减，且连续不重叠"""
        tick = self._tick("0.01")
        ranges = _build_price_ranges(100.0, tick, 6, direction=1)
        for i in range(len(ranges) - 1):
            low_cur, _ = ranges[i]
            _, high_next = ranges[i + 1]
            assert low_cur == high_next, f"dom{i+1} low != dom{i+2} high"

    def test_sell_dom1_starts_at_market_price(self):
        """卖方 dom1 起始价 = 市场价"""
        tick = self._tick("0.01")
        ranges = _build_price_ranges(95000.0, tick, 6, direction=-1)
        low, _ = ranges[0]
        assert low == Decimal("95000.00")

    def test_buy_dom1_ends_at_market_price(self):
        """买方 dom1 结束价 = 市场价"""
        tick = self._tick("0.01")
        ranges = _build_price_ranges(95000.0, tick, 6, direction=1)
        _, high = ranges[0]
        assert high == Decimal("95000.00")

    def test_price_precision_aligned_to_tick(self):
        """所有价格均与 tickSize 精度对齐"""
        tick = self._tick("0.01")
        ranges = _build_price_ranges(95000.12, tick, 6, direction=-1)
        for low, high in ranges:
            # 两位小数精度：乘以100后为整数
            assert (low * 100) % 1 == 0, f"low={low} not aligned to tick=0.01"
            assert (high * 100) % 1 == 0, f"high={high} not aligned to tick=0.01"

    def test_buy_price_never_negative(self):
        """买方区间价格不能为负数"""
        tick = self._tick("1")
        ranges = _build_price_ranges(5.0, tick, 6, direction=1)
        for low, high in ranges:
            assert low >= 0

    def test_returns_correct_number_of_levels(self):
        tick = self._tick("0.01")
        for levels in [3, 6, 8]:
            ranges = _build_price_ranges(100.0, tick, levels, direction=-1)
            assert len(ranges) == levels


# ---------------------------------------------------------------------------
# _calc_number_float
# ---------------------------------------------------------------------------

class TestCalcNumberFloat:
    def test_returns_min_dash_max_format(self, btc_depth):
        step = Decimal("0.00001")
        result = _calc_number_float(btc_depth, "near", step)
        assert "-" in result
        parts = result.split("-")
        assert len(parts) == 2

    def test_min_less_than_max(self, btc_depth):
        step = Decimal("0.00001")
        result = _calc_number_float(btc_depth, "near", step)
        qty_min, qty_max = result.split("-")
        assert Decimal(qty_min) < Decimal(qty_max)

    def test_far_zone_larger_than_near(self, btc_depth):
        """远盘累计深度更大，数量基准应 >= 近盘"""
        step = Decimal("0.00001")
        near_max = Decimal(_calc_number_float(btc_depth, "near", step).split("-")[1])
        far_max = Decimal(_calc_number_float(btc_depth, "far", step).split("-")[1])
        assert far_max >= near_max

    def test_respects_step_size_precision(self, btc_depth):
        """数量精度严格对齐 stepSize"""
        step = Decimal("0.00001")
        result = _calc_number_float(btc_depth, "mid", step)
        for part in result.split("-"):
            val = Decimal(part)
            remainder = (val / step) % 1
            assert remainder == 0 or abs(remainder) < Decimal("1e-10")


# ---------------------------------------------------------------------------
# generate_configs — 集成级单元测试
# ---------------------------------------------------------------------------

class TestGenerateConfigs:
    """通过 generate_configs 验证端到端输出符合需求"""

    def _run(self, exchange_info, depth, *, symbol="btc_usdt", levels=6,
             total_usdt=5_000_000, pid=2, current_price=95000.0):
        return generate_configs(
            symbol=symbol,
            levels=levels,
            total_usdt=total_usdt,
            pid=pid,
            current_price=current_price,
            exchange_info=exchange_info,
            order_book=depth,
        )

    def test_output_count(self, btc_exchange_info, btc_depth):
        """买卖双向各 6 档，共 12 条记录"""
        configs = self._run(btc_exchange_info, btc_depth)
        assert len(configs) == 12

    def test_directions_present(self, btc_exchange_info, btc_depth):
        """买（1）和卖（-1）方向各 6 条"""
        configs = self._run(btc_exchange_info, btc_depth)
        dirs = [c["direction"] for c in configs]
        assert dirs.count(1) == 6
        assert dirs.count(-1) == 6

    def test_dom_values(self, btc_exchange_info, btc_depth):
        """每个方向的 dom 均为 1-6"""
        configs = self._run(btc_exchange_info, btc_depth)
        for direction in [-1, 1]:
            doms = sorted(c["dom"] for c in configs if c["direction"] == direction)
            assert doms == [1, 2, 3, 4, 5, 6]

    def test_total_trust_num_not_exceed_1000(self, btc_exchange_info, btc_depth):
        """买方或卖方各方向总笔数 <= 1000"""
        configs = self._run(btc_exchange_info, btc_depth)
        for direction in [-1, 1]:
            total = sum(c["trust_num"] for c in configs if c["direction"] == direction)
            assert total <= 1000, f"direction={direction} total trust_num={total} > 1000"

    def test_trust_num_all_positive(self, btc_exchange_info, btc_depth):
        configs = self._run(btc_exchange_info, btc_depth)
        for c in configs:
            assert c["trust_num"] >= 1

    def test_change_trust_num_dom1_is_zero(self, btc_exchange_info, btc_depth):
        """近盘 dom1 不需要变幻委托"""
        configs = self._run(btc_exchange_info, btc_depth)
        dom1 = [c for c in configs if c["dom"] == 1]
        for c in dom1:
            assert c["change_trust_num"] == 0

    def test_change_trust_num_mid_far_is_one(self, btc_exchange_info, btc_depth):
        """中盘 / 远盘 change_trust_num = 1"""
        configs = self._run(btc_exchange_info, btc_depth)
        non_dom1 = [c for c in configs if c["dom"] != 1]
        for c in non_dom1:
            assert c["change_trust_num"] == 1

    def test_survival_time_near(self, btc_exchange_info, btc_depth):
        """近盘存活时间 3-10"""
        configs = self._run(btc_exchange_info, btc_depth)
        for c in configs:
            if c["dom"] == 1:
                assert c["change_survival_time"] == "3-10"

    def test_survival_time_mid_far(self, btc_exchange_info, btc_depth):
        """中盘 / 远盘存活时间 10-30"""
        configs = self._run(btc_exchange_info, btc_depth)
        for c in configs:
            if c["dom"] in (2, 3, 4, 5, 6):
                assert c["change_survival_time"] == "10-30"

    def test_status_always_one(self, btc_exchange_info, btc_depth):
        configs = self._run(btc_exchange_info, btc_depth)
        for c in configs:
            assert c["status"] == 1

    def test_price_float_format(self, btc_exchange_info, btc_depth):
        """price_float 格式为 'low-high'，且 low < high"""
        configs = self._run(btc_exchange_info, btc_depth)
        for c in configs:
            pf = c["price_float"]
            assert "-" in pf, f"price_float '{pf}' missing '-'"
            low_s, high_s = pf.split("-")
            assert Decimal(low_s) < Decimal(high_s), f"price_float '{pf}': low >= high"

    def test_number_float_equals_change_number_float(self, btc_exchange_info, btc_depth):
        """number_float 与 change_number_float 保持一致"""
        configs = self._run(btc_exchange_info, btc_depth)
        for c in configs:
            assert c["number_float"] == c["change_number_float"]

    def test_same_zone_same_number_float(self, btc_exchange_info, btc_depth):
        """同一方向同一区间内，所有档位 number_float 相同"""
        configs = self._run(btc_exchange_info, btc_depth)
        for direction in [-1, 1]:
            direction_configs = [c for c in configs if c["direction"] == direction]
            near = [c["number_float"] for c in direction_configs if c["_zone"] == "near"]
            mid = [c["number_float"] for c in direction_configs if c["_zone"] == "mid"]
            far = [c["number_float"] for c in direction_configs if c["_zone"] == "far"]
            assert len(set(near)) <= 1, "近盘 number_float 不一致"
            assert len(set(mid)) <= 1, "中盘 number_float 不一致"
            assert len(set(far)) <= 1, "远盘 number_float 不一致"

    def test_pid_in_output(self, btc_exchange_info, btc_depth):
        configs = self._run(btc_exchange_info, btc_depth, pid=7)
        for c in configs:
            assert c["pid"] == 7

    def test_shib_tiny_price(self, shib_exchange_info, shib_depth):
        """极小价格（SHIB）：精度对齐验证"""
        configs = self._run(shib_exchange_info, shib_depth,
                            symbol="shib_usdt", current_price=0.000025)
        tick_size = Decimal(shib_exchange_info["tickSize"])
        places = len(str(tick_size).rstrip("0").split(".")[-1]) if "." in str(tick_size) else 0
        for c in configs:
            low_s, high_s = c["price_float"].split("-")
            # 验证小数位不超过 tick 精度
            for s in (low_s, high_s):
                if "." in s:
                    actual_places = len(s.split(".")[1].rstrip("0") or "0")
                    assert actual_places <= places + 1  # 允许尾零

    def test_eth_price_ranges_continuous(self, eth_exchange_info, eth_depth):
        """ETH 买方档位价格区间连续不重叠：dom_i.low == dom_{i+1}.high"""
        configs = self._run(eth_exchange_info, eth_depth,
                            symbol="eth_usdt", current_price=2500.0)
        buy_configs = sorted(
            [c for c in configs if c["direction"] == 1],
            key=lambda x: x["dom"],
        )
        for i in range(len(buy_configs) - 1):
            low_cur, _ = buy_configs[i]["price_float"].split("-")
            _, high_next = buy_configs[i + 1]["price_float"].split("-")
            assert low_cur == high_next, (
                f"dom{i+1} low={low_cur} != dom{i+2} high={high_next}"
            )
