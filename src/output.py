"""
SQL / JSON 输出模块
生成 INSERT SQL 文件、JSON 配置文件，以及控制台摘要表格
"""

import json
import os
from typing import List


# SQL 字段顺序
_SQL_FIELDS = [
    "box_id", "pid", "direction", "dom", "trust_num",
    "price_float", "number_float", "change_trust_num",
    "change_number_float", "change_survival_time", "status",
]

# 字符串类型字段（需要加引号）
_STR_FIELDS = {"price_float", "number_float", "change_number_float", "change_survival_time"}


def _escape_str(value: str) -> str:
    """对字符串值做基本转义，防止 SQL 注入（仅允许数字、小数点、连字符）"""
    if not isinstance(value, str):
        return str(value)
    # 白名单：只允许数字、小数点、连字符（price_float / number_float 格式）
    allowed = set("0123456789.-")
    sanitized = "".join(c for c in value if c in allowed)
    return sanitized


def _value_to_sql(field: str, value) -> str:
    """将字段值转换为 SQL 字面量"""
    if value is None:
        return "null"
    if field in _STR_FIELDS:
        return f"'{_escape_str(value)}'"
    # 整数 / 方向 / 状态等数值类型
    return str(int(value))


def _config_to_sql_row(config: dict) -> str:
    """将一条配置字典转为 SQL VALUES 行"""
    parts = [_value_to_sql(f, config[f]) for f in _SQL_FIELDS]
    return f"  ({', '.join(parts)})"


def generate_sql(configs: List[dict], output_path: str) -> None:
    """
    生成 INSERT INTO spot_market_making_box SQL 文件
    :param configs: generate_configs 返回的配置列表
    :param output_path: 输出文件路径
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    rows = [_config_to_sql_row(c) for c in configs]
    fields_str = ", ".join(_SQL_FIELDS)

    sql = (
        f"INSERT INTO spot_market_making_box ({fields_str})\n"
        f"VALUES\n"
        + ",\n".join(rows)
        + ";\n"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(sql)

    print(f"[输出] SQL 文件已生成: {output_path}")


def generate_json(configs: List[dict], output_path: str) -> None:
    """
    生成结构化 JSON 配置文件
    :param configs: generate_configs 返回的配置列表
    :param output_path: 输出文件路径
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 过滤掉以 _ 开头的内部字段
    clean = [{k: v for k, v in c.items() if not k.startswith("_")} for c in configs]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)

    print(f"[输出] JSON 文件已生成: {output_path}")


def _pct_to_actual(price_float_pct: str, reference_price: float) -> str:
    """
    将 price_float 百分比区间字符串转换为实际价格区间字符串
    例如：'99.964-100.000' + reference_price=2500 → '2499.10-2500.00'
    """
    low_s, high_s = price_float_pct.split("-")
    from decimal import Decimal as _D
    ref = _D(str(reference_price))
    low_price = ref * _D(low_s) / _D("100")
    high_price = ref * _D(high_s) / _D("100")
    # 保留 2 位小数展示（可读性优先）
    return f"{float(low_price):.4g}-{float(high_price):.4g}"


def print_summary(configs: List[dict], reference_price: float = None) -> None:
    """
    控制台打印配置摘要表格
    price_float 单位为百分比（%），表示相对于参考价的比例区间：
      买盘：50%-100%（价格 = 参考价 × 50%~100%）
      卖盘：100%-150%（价格 = 参考价 × 100%~150%）

    :param configs:         generate_configs 返回的配置列表
    :param reference_price: 参考价格（当前市场价），传入后附加"实际价格区间"列
    """
    show_actual = reference_price is not None

    if show_actual:
        header = (
            f"{'方向':^4} {'档位':^4} {'区间':^6} {'笔数':>6} "
            f"{'价格区间(%)':^26} {'实际价格区间':^22} "
            f"{'数量区间':<18} {'变幻委托':>8} {'存活时间':<10}"
        )
    else:
        header = (
            f"{'方向':^4} {'档位':^4} {'区间':^6} {'笔数':>6} "
            f"{'价格区间(%)':^28} "
            f"{'数量区间':<20} {'变幻委托':>8} {'存活时间':<10}"
        )
    sep = "-" * len(header)

    print("\n" + "=" * len(header))
    print(" 铺单配置摘要")
    print("=" * len(header))
    print(header)
    print(sep)

    for c in configs:
        direction_label = c.get("_direction_label", str(c["direction"]))
        zone_label = {"near": "近盘", "mid": "中盘", "far": "远盘"}.get(c.get("_zone", ""), "")
        if show_actual:
            actual_range = _pct_to_actual(c["price_float"], reference_price)
            print(
                f"{direction_label:^4} "
                f"{c['dom']:^4} "
                f"{zone_label:^6} "
                f"{c['trust_num']:>6} "
                f"{c['price_float']:<26} "
                f"{actual_range:<22} "
                f"{c['number_float']:<18} "
                f"{c['change_trust_num']:>8} "
                f"{c['change_survival_time']:<10}"
            )
        else:
            print(
                f"{direction_label:^4} "
                f"{c['dom']:^4} "
                f"{zone_label:^6} "
                f"{c['trust_num']:>6} "
                f"{c['price_float']:<28} "
                f"{c['number_float']:<20} "
                f"{c['change_trust_num']:>8} "
                f"{c['change_survival_time']:<10}"
            )

    print(sep)
    print(f"共 {len(configs)} 条配置\n")
