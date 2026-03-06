"""
现货铺单配置生成器 CLI 入口

用法示例：
  python generate_box_config.py --symbol eth_usdt --pid 3 --levels 9 \
      --total_usdt 2000000 --depth_ratio 0.3

参数说明：
  --symbol      交易对，支持 btc_usdt / eth_usdt 等格式
  --pid         项目 ID（写入 spot_market_making_box.pid）
  --levels      每侧档位数，默认 6
  --total_usdt  总量（USDT），用于展示，默认 1000000
  --depth_ratio 深度比，单边有效量 = total_usdt × depth_ratio / 2，默认 0.2
  --output_dir  SQL/JSON 输出目录，默认 ./output
"""

from __future__ import annotations

import argparse
import os
import sys

# 将项目根目录加入 Python 路径，确保本地 src 包可正常导入
sys.path.insert(0, os.path.dirname(__file__))

from src.binance_api import get_exchange_info, get_order_book, get_price
from src.config_generator import generate_configs
from src.output import generate_sql, print_summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="现货铺单配置生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--symbol", required=True, help="交易对，如 eth_usdt")
    parser.add_argument("--pid", type=int, required=True, help="项目 ID")
    parser.add_argument("--levels", type=int, default=6, help="每侧档位数（默认 6）")
    parser.add_argument(
        "--total_usdt", type=float, default=1_000_000.0, help="总量 USDT（默认 1000000）"
    )
    parser.add_argument(
        "--depth_ratio", type=float, default=0.2, help="深度比，用于计算单边有效量（默认 0.2）"
    )
    parser.add_argument("--output_dir", default="output", help="SQL/JSON 输出目录（默认 ./output）")
    return parser.parse_args()


def _print_header(
    symbol: str,
    current_price: float,
    pid: int,
    levels: int,
    total_usdt: float,
    depth_ratio: float,
    record_count: int,
) -> None:
    """打印摘要标题栏"""
    single_side = total_usdt * depth_ratio / 2
    far_cover_pct = depth_ratio * 100 * 10  # 远盘覆盖比例（示意值）
    symbol_display = symbol.upper().replace("_", "/")
    sell_count = record_count // 2
    buy_count = record_count - sell_count

    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  交易对   : {symbol_display}  (参考价格: {current_price})")
    print(
        f"  pid      : {pid}   档位数: {levels}   "
        f"总量: {total_usdt:,.0f} USDT"
    )
    print(
        f"  深度比   : {depth_ratio}   "
        f"远盘覆盖: {far_cover_pct:.1f}%"
    )
    print(f"  单边有效量: {single_side:,.0f} USDT")
    print(f"  生成记录 : {record_count} 条 ({sell_count} 卖单 + {buy_count} 买单)")
    print(f"{sep}\n")


def _print_table(configs: list, levels: int) -> None:
    """打印买卖价格区间对照表（按档位分组）"""
    # 按 dom 聚合买卖方
    sell_map = {c["dom"]: c for c in configs if c["direction"] == -1}
    buy_map = {c["dom"]: c for c in configs if c["direction"] == 1}

    header = (
        f"{'档位':^6} {'区域':^6} {'委托数':>6}"
        f"  {'卖 price_float(%)':<26}  {'买 price_float(%)':<26}"
    )
    print(header)
    print("-" * len(header))

    zone_cn = {"near": "近盘", "mid": "中盘", "far": "远盘"}
    for dom in range(1, levels + 1):
        sc = sell_map.get(dom, {})
        bc = buy_map.get(dom, {})
        zone_label = zone_cn.get(sc.get("_zone", ""), "")
        trust_num = sc.get("trust_num", "-")
        sell_pf = sc.get("price_float", "-")
        buy_pf = bc.get("price_float", "-")
        print(
            f"{dom:^6} {zone_label:^6} {trust_num:>6}"
            f"  {sell_pf:<26}  {buy_pf:<26}"
        )
    print()


def main() -> None:
    args = _parse_args()

    symbol = args.symbol.lower()
    pid = args.pid
    levels = args.levels
    total_usdt = args.total_usdt
    depth_ratio = args.depth_ratio
    output_dir = args.output_dir

    # ── 1. 拉取币安数据 ──────────────────────────────────────────────────────
    print(f"[API] 正在获取 {symbol.upper()} 行情数据...")
    try:
        current_price = get_price(symbol)
        exchange_info = get_exchange_info(symbol)
        order_book = get_order_book(symbol, limit=20)
    except Exception as exc:
        print(f"[错误] 币安 API 请求失败: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[API] 参考价格: {current_price}  tickSize: {exchange_info['tickSize']}")

    # ── 2. 生成配置 ──────────────────────────────────────────────────────────
    configs = generate_configs(
        symbol=symbol,
        levels=levels,
        total_usdt=total_usdt,
        pid=pid,
        current_price=current_price,
        exchange_info=exchange_info,
        order_book=order_book,
    )

    # ── 3. 输出摘要 ──────────────────────────────────────────────────────────
    _print_header(
        symbol=symbol,
        current_price=current_price,
        pid=pid,
        levels=levels,
        total_usdt=total_usdt,
        depth_ratio=depth_ratio,
        record_count=len(configs),
    )
    _print_table(configs, levels)
    print_summary(configs, reference_price=current_price)

    # ── 4. 生成 SQL 文件 ─────────────────────────────────────────────────────
    safe_symbol = symbol.replace("/", "_")
    sql_path = os.path.join(output_dir, f"{safe_symbol}_pid{pid}.sql")
    generate_sql(configs, sql_path)


if __name__ == "__main__":
    main()
