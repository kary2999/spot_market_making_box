"""
配置计算引擎
根据币安 API 数据生成所有档位的铺单参数
"""

import math
from decimal import Decimal, ROUND_DOWN


# 各档位 trust_num 分配比例（共 6 档）
TRUST_NUM_RATIOS = {1: 0.05, 2: 0.10, 3: 0.20, 4: 0.25, 5: 0.25, 6: 0.15}

# 各档位对应价格区间宽度（单位：tickSize 倍数）
TICK_WIDTHS = {1: 2, 2: 10, 3: 20, 4: 80, 5: 150, 6: 200}

# change_survival_time 配置
SURVIVAL_TIME = {1: "3-10", 2: "10-30", 3: "10-30", 4: "10-30", 5: "10-30", 6: "10-30"}

# 区间分类：近盘 / 中盘 / 远盘
ZONE_NEAR = {1}
ZONE_MID = {2, 3}
ZONE_FAR = {4, 5, 6}

# 盘口深度累计档位对应关系（用于取 number_float）
# 近盘取前 2 档累计，中盘取前 8 档，远盘取前 20 档
DEPTH_LEVELS = {
    "near": 2,
    "mid": 8,
    "far": 20,
}


def _get_zone(dom: int) -> str:
    if dom in ZONE_NEAR:
        return "near"
    if dom in ZONE_MID:
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
    生成各档位价格区间列表
    :param direction: 1=买（向下延伸），-1=卖（向上延伸）
    :return: [(price_low, price_high), ...] 按 dom 1..levels 顺序
    """
    price = Decimal(str(current_price))
    ranges = []
    cursor = price  # 当前起始边界

    for dom in range(1, levels + 1):
        width_ticks = TICK_WIDTHS.get(dom, 200)
        width = tick_size * width_ticks

        if direction == -1:
            # 卖方：价格从当前价向上延伸
            low = cursor
            high = cursor + width
            ranges.append((low, high))
            cursor = high
        else:
            # 买方：价格从当前价向下延伸
            high = cursor
            low = cursor - width
            low = low.max(Decimal("0"))  # 价格不能为负
            ranges.append((low, high))
            cursor = low

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

    configs = []

    for direction in [-1, 1]:  # -1=卖, 1=买
        price_ranges = _build_price_ranges(current_price, tick_size, levels, direction)

        # 预计算各区间 number_float（同区间内档位保持一致）
        zone_number_float = {}
        for zone in ("near", "mid", "far"):
            zone_number_float[zone] = _calc_number_float(order_book, zone, step_size)

        for dom in range(1, levels + 1):
            zone = _get_zone(dom)
            ratio = TRUST_NUM_RATIOS.get(dom, 0.10)
            trust_num = max(1, math.floor(total_trust * ratio))

            low, high = price_ranges[dom - 1]
            price_float = f"{_format_price(low, tick_size)}-{_format_price(high, tick_size)}"

            number_float = zone_number_float[zone]
            change_number_float = number_float

            change_trust_num = 0 if dom in ZONE_NEAR else 1
            change_survival_time = SURVIVAL_TIME[dom]

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
