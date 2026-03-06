"""
配置计算引擎
根据币安 API 数据生成所有档位的铺单参数
"""

from __future__ import annotations

import json
import math
from decimal import Decimal, ROUND_DOWN
from typing import List


# 各区间 tick 数边界（按距当前价的最小变动单位数量划分）
# 近盘：0 到 NEAR_TICK_BOUNDARY tick 内（紧靠当前价）
# 中盘：NEAR_TICK_BOUNDARY 到 MID_TICK_BOUNDARY tick 内
# 远盘：MID_TICK_BOUNDARY tick 到 50% 价格总范围
NEAR_TICK_BOUNDARY = 150
MID_TICK_BOUNDARY = 100_000

# 盘口深度累计档位对应关系（用于取 number_float）
# 近盘取前 2 档累计，中盘取前 8 档，远盘取前 20 档
DEPTH_LEVELS = {
    "near": 2,
    "mid": 8,
    "far": 20,
}

# 各区间 trust_num 相对平均值的倍率
# trust_num_per_level = round(total_trust / levels × multiplier)
_ZONE_TRUST_MULTIPLIERS = {
    "near": Decimal("0.4"),
    "mid":  Decimal("0.8"),
    "far":  Decimal("1.2"),
}


def _compute_zones(levels: int) -> tuple:
    """
    根据档位总数动态划分近/中/远盘集合

    规则（与单元测试兼容）：
      levels ≤ 6：近盘 {1}，远盘从第 4 档开始，中盘居中
      levels > 6：近盘 {1, 2}，远盘为最后 2 档，中盘居中

    :return: (near_set, mid_set, far_set)
    """
    if levels <= 3:
        near = frozenset({1})
        far = frozenset({levels})
        mid = frozenset(range(2, levels))
    elif levels <= 6:
        # 保持与原 6 档行为一致：dom 1 = 近盘，dom 2-3 = 中盘，dom 4+ = 远盘
        near = frozenset({1})
        mid = frozenset(range(2, 4))
        far = frozenset(range(4, levels + 1))
    else:
        # 档位数较多：前 2 档近盘，后 2 档远盘，其余中盘
        near = frozenset({1, 2})
        far = frozenset({levels - 1, levels})
        mid = frozenset(range(3, levels - 1))
    return near, mid, far


def _get_zone(dom: int) -> str:
    """仅用于 6 档默认行为（单元测试向后兼容）"""
    if dom == 1:
        return "near"
    if dom in (2, 3):
        return "mid"
    return "far"


def _decimal_places(tick_str: str) -> int:
    """从 tickSize 字符串计算小数位数，如 '0.01' → 2"""
    d = Decimal(tick_str).normalize()
    sign, digits, exponent = d.as_tuple()
    return max(0, -exponent)


def _format_price(value: Decimal, tick_size: Decimal) -> str:
    """按 tickSize 精度格式化价格"""
    places = _decimal_places(str(tick_size))
    quantize_str = Decimal(10) ** -places
    return str(value.quantize(quantize_str, rounding=ROUND_DOWN))


def _format_qty(value: Decimal, step_size: Decimal) -> str:
    """按 stepSize 精度格式化数量"""
    places = _decimal_places(str(step_size))
    quantize_str = Decimal(10) ** -places
    return str(value.quantize(quantize_str, rounding=ROUND_DOWN))


def _cumulative_qty(order_book_side: list, depth: int) -> Decimal:
    """取盘口某侧前 depth 档的累计数量（支持字符串或数值格式）"""
    total = Decimal("0")
    for i, entry in enumerate(order_book_side):
        if i >= depth:
            break
        # Binance 原始格式为 ["price_str", "qty_str"]
        qty = entry[1] if isinstance(entry, (list, tuple)) else entry
        total += Decimal(str(qty))
    return total


def _calc_number_float(order_book: dict, zone: str, step_size: Decimal) -> str:
    """
    根据盘口深度计算 number_float
    取买卖双侧对应深度累计量的均值 × 0.2，返回 'min-max' 格式
    """
    depth = DEPTH_LEVELS[zone]
    bid_qty = _cumulative_qty(order_book["bids"], depth)
    ask_qty = _cumulative_qty(order_book["asks"], depth)
    avg_qty = (bid_qty + ask_qty) / 2

    base = (avg_qty * Decimal("0.2")).max(step_size)
    qty_min = _format_qty(base * Decimal("0.5"), step_size)
    qty_max = _format_qty(base, step_size)

    # 防止 min == max（极端行情）
    if qty_min == qty_max:
        qty_min = _format_qty(step_size, step_size)

    return f"{qty_min}-{qty_max}"


def _build_price_ranges(
    current_price: float,
    tick_size: Decimal,
    levels: int,
    direction: int,
) -> list:
    """
    根据 tick 数边界动态计算各档位价格百分比区间

    区间划分（按距当前价的 tick 数量）：
      近盘：0 到 NEAR_TICK_BOUNDARY（150）tick
      中盘：150 到 MID_TICK_BOUNDARY（100,000）tick
      远盘：100,000 tick 到 50% 价格范围边界

    买方：从 100% 向下延伸到 50%，price_float 如 '99.928-100.000'
    卖方：从 100% 向上延伸到 150%，price_float 如 '100.000-100.072'

    :param current_price: 当前市场价格
    :param tick_size:     价格最小变动单位
    :param levels:        总档位数
    :param direction:     1=买（向下），-1=卖（向上）
    :return: [(low_pct, high_pct), ...] 按 dom 1..levels 顺序，Decimal 百分比值
    """
    price = Decimal(str(current_price))
    # 50% 价格范围对应的总 tick 数（至少为 1）
    total_ticks = max(1, int(price * Decimal("0.5") / tick_size))

    # 各区间 tick 边界（不超过总 tick 数）
    near_end = min(NEAR_TICK_BOUNDARY, total_ticks)
    mid_end = min(MID_TICK_BOUNDARY, total_ticks)

    near_ticks_raw = near_end
    mid_ticks_raw = mid_end - near_end
    far_ticks_raw = total_ticks - mid_end

    # 获取各区间的档位集合
    near_zone, mid_zone, far_zone = _compute_zones(levels)
    near_count = len(near_zone)
    mid_count = len(mid_zone)
    far_count = len(far_zone)

    # 有效 tick 数：每档至少 1 tick，防止零宽度区间
    effective_near = max(near_count, near_ticks_raw)
    effective_mid = max(mid_count, mid_ticks_raw)
    effective_far = max(far_count, far_ticks_raw)
    total_effective = Decimal(effective_near + effective_mid + effective_far)

    # 各区间百分比宽度（归一化到总 50% 范围）
    near_pct_total = Decimal(effective_near) / total_effective * Decimal("50")
    mid_pct_total = Decimal(effective_mid) / total_effective * Decimal("50")
    far_pct_total = Decimal(effective_far) / total_effective * Decimal("50")

    # 各档位百分比宽度（区间总宽度平均分配给该区间的档位数）
    near_per_dom = near_pct_total / Decimal(near_count) if near_count > 0 else Decimal(0)
    mid_per_dom = mid_pct_total / Decimal(mid_count) if mid_count > 0 else Decimal(0)
    far_per_dom = far_pct_total / Decimal(far_count) if far_count > 0 else Decimal(0)

    ranges = []
    cursor_pct = Decimal("100")

    for dom in range(1, levels + 1):
        if dom in near_zone:
            width_pct = near_per_dom
        elif dom in mid_zone:
            width_pct = mid_per_dom
        else:
            width_pct = far_per_dom

        if direction == -1:
            # 卖方：从 100% 向上延伸
            low_pct = cursor_pct
            high_pct = cursor_pct + width_pct
            ranges.append((low_pct, high_pct))
            cursor_pct = high_pct
        else:
            # 买方：从 100% 向下延伸
            high_pct = cursor_pct
            low_pct = cursor_pct - width_pct
            ranges.append((low_pct, high_pct))
            cursor_pct = low_pct

    return ranges


def generate_configs(
    symbol: str,
    levels: int,
    total_usdt: float,
    pid: int,
    current_price: float,
    exchange_info: dict,
    order_book: dict,
) -> list:
    """
    生成所有档位配置（买卖双向）
    :return: 字典列表，每个元素对应一行 INSERT 记录
    """
    tick_size = Decimal(exchange_info["tickSize"])
    step_size = Decimal(exchange_info["stepSize"])

    total_trust = 1000  # 总笔数上限

    # 动态计算各档所属区间（near/mid/far）
    near_zone, mid_zone, far_zone = _compute_zones(levels)

    def _zone_of(dom: int) -> str:
        if dom in near_zone:
            return "near"
        if dom in mid_zone:
            return "mid"
        return "far"

    # 每档 trust_num = round(total_trust / levels × 区间倍率)
    base_trust = Decimal(total_trust) / Decimal(levels)

    configs = []

    for direction in [-1, 1]:  # -1=卖, 1=买
        price_ranges = _build_price_ranges(current_price, tick_size, levels, direction)

        # 预计算各区间 number_float（同区间内档位保持一致）
        zone_number_float = {}
        for zone in ("near", "mid", "far"):
            zone_number_float[zone] = _calc_number_float(order_book, zone, step_size)

        for dom in range(1, levels + 1):
            zone = _zone_of(dom)
            # trust_num 按区间倍率分配，四舍五入
            trust_num = max(1, int(base_trust * _ZONE_TRUST_MULTIPLIERS[zone] + Decimal("0.5")))

            low_pct, high_pct = price_ranges[dom - 1]
            # price_float 存储百分比字符串，最多 3 位小数，如 '99.928-100.000'
            pct_fmt = Decimal("0.001")
            price_float = (
                f"{low_pct.quantize(pct_fmt, rounding=ROUND_DOWN)}"
                f"-{high_pct.quantize(pct_fmt, rounding=ROUND_DOWN)}"
            )

            number_float = zone_number_float[zone]
            change_number_float = number_float

            # 近盘不变幻委托，中远盘开启
            change_trust_num = 0 if dom in near_zone else 1
            # 近盘存活时间短，中远盘长
            change_survival_time = "3-10" if dom in near_zone else "10-30"

            configs.append({
                "box_id": None,
                "pid": pid,
                "direction": direction,
                "dom": dom,
                "trust_num": trust_num,
                "price_float": price_float,
                "number_float": number_float,
                "change_trust_num": change_trust_num,
                "change_number_float": change_number_float,
                "change_survival_time": change_survival_time,
                "status": 1,
                # 附加信息，方便打印摘要
                "_symbol": symbol,
                "_zone": zone,
                "_direction_label": "卖" if direction == -1 else "买",
            })

    return configs


# ---------------------------------------------------------------------------
# 网格铺单配置生成器
# ---------------------------------------------------------------------------


def _floor_to_precision(value: Decimal, precision: str) -> Decimal:
    """将 value 按 precision 字符串向下取整（复用 tick_size/step_size 精度逻辑）"""
    tick = Decimal(precision).normalize()
    return (value // tick) * tick


class ConfigGenerator:
    """网格铺单配置生成器

    Args:
        symbol:       交易对，如 "BTCUSDT"
        price_low:    网格价格区间下限
        price_high:   网格价格区间上限
        grid_count:   网格档位数量（至少 2）
        total_budget: 总预算（计价货币，如 USDT）
        tick_size:    价格精度字符串，如 "0.01000000"
        step_size:    数量精度字符串，如 "0.00001000"
        grid_mode:    网格模式，'arithmetic'（等差）或 'geometric'（等比），默认等差
    """

    def __init__(
        self,
        symbol: str,
        price_low: float | str,
        price_high: float | str,
        grid_count: int,
        total_budget: float | str,
        tick_size: str,
        step_size: str,
        grid_mode: str = "arithmetic",
    ) -> None:
        if grid_count < 2:
            raise ValueError("grid_count 至少为 2")
        if grid_mode not in ("arithmetic", "geometric"):
            raise ValueError("grid_mode 必须为 'arithmetic' 或 'geometric'")

        self.symbol = symbol
        self.price_low = Decimal(str(price_low))
        self.price_high = Decimal(str(price_high))
        self.grid_count = grid_count
        self.total_budget = Decimal(str(total_budget))
        self.tick_size = tick_size
        self.step_size = step_size
        self.grid_mode = grid_mode

        if self.price_low >= self.price_high:
            raise ValueError("price_low 必须小于 price_high")

    def generate_grid_prices(self) -> List[Decimal]:
        """在 [price_low, price_high] 区间生成 grid_count 个价格档位

        等差模式：价格均匀分布；等比模式：价格按等比数列分布。
        结果按 tick_size 精度截断（向下取整）。

        Returns:
            长度为 grid_count 的 Decimal 价格列表，从低到高排列
        """
        n = self.grid_count
        low, high = self.price_low, self.price_high
        prices: List[Decimal] = []

        if self.grid_mode == "arithmetic":
            step = (high - low) / (n - 1)
            for i in range(n):
                prices.append(_floor_to_precision(low + step * i, self.tick_size))
        else:
            # 等比：ratio = (high/low) ^ (1/(n-1))
            ratio = (high / low) ** (Decimal(1) / Decimal(n - 1))
            for i in range(n):
                prices.append(_floor_to_precision(low * (ratio ** i), self.tick_size))

        return prices

    def calc_order_qty(self, price: Decimal, budget_per_grid: Decimal) -> Decimal:
        """根据每格预算和价格计算下单数量，按 step_size 精度向下取整

        Args:
            price:           该档位价格
            budget_per_grid: 每格分配预算

        Returns:
            按 step_size 精度向下取整的下单数量
        """
        if price <= Decimal(0):
            raise ValueError("价格必须大于 0")
        return _floor_to_precision(budget_per_grid / price, self.step_size)

    def generate_config(self) -> List[dict]:
        """生成完整铺单配置，预算平均分配到每个网格档位

        Returns:
            List[dict]，每个元素包含 price、qty、side、order_type
        """
        prices = self.generate_grid_prices()
        budget_per_grid = self.total_budget / self.grid_count
        return [
            {
                "price": str(price),
                "qty": str(self.calc_order_qty(price, budget_per_grid)),
                "side": "BUY",
                "order_type": "LIMIT",
            }
            for price in prices
        ]

    def export_json(self, filepath: str) -> None:
        """将配置序列化写入 JSON 文件

        Args:
            filepath: 目标文件路径
        """
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "symbol": self.symbol,
                    "grid_mode": self.grid_mode,
                    "orders": self.generate_config(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
