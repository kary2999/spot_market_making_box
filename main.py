"""
现货铺单配置生成器 — 主入口
用法:
  python main.py --symbol btc_usdt --total_usdt 5000000 --pid 2
  python main.py --symbol btc_usdt --levels 6 --total_usdt 5000000 --pid 2 --exchange binance
"""

import argparse
import os
import sys

from src import binance_api, config_generator, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="现货铺单配置生成器 — 自动查询币安行情并生成 SQL/JSON 配置"
    )
    parser.add_argument("--symbol", required=True, help="交易对，如 btc_usdt")
    parser.add_argument("--exchange", default="binance", help="参考交易所（默认 binance）")
    parser.add_argument("--levels", type=int, default=6, help="档位数量（默认 6）")
    parser.add_argument("--total_usdt", type=float, required=True, help="计划铺单总量（USDT）")
    parser.add_argument("--pid", type=int, required=True, help="对应铺单表的 pid")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    symbol = args.symbol.lower()
    levels = args.levels
    total_usdt = args.total_usdt
    pid = args.pid

    print(f"[信息] 开始生成配置: symbol={symbol}, levels={levels}, total_usdt={total_usdt}, pid={pid}")

    try:
        # 1. 查询币安行情
        print("[信息] 正在查询币安当前价格...")
        current_price = binance_api.get_price(symbol)
        print(f"[信息] 当前价格: {current_price}")

        print("[信息] 正在查询交易规则（tickSize/stepSize）...")
        exchange_info = binance_api.get_exchange_info(symbol)
        print(f"[信息] tickSize={exchange_info['tickSize']}, stepSize={exchange_info['stepSize']}")

        print("[信息] 正在查询盘口深度...")
        order_book = binance_api.get_order_book(symbol, limit=20)
        print(f"[信息] 获取到 {len(order_book['bids'])} 档买盘 / {len(order_book['asks'])} 档卖盘")

        # 2. 生成配置
        print("[信息] 正在计算档位配置...")
        configs = config_generator.generate_configs(
            symbol=symbol,
            levels=levels,
            total_usdt=total_usdt,
            pid=pid,
            current_price=current_price,
            exchange_info=exchange_info,
            order_book=order_book,
        )

        # 3. 打印摘要
        output.print_summary(configs)

        # 4. 输出文件
        output_dir = "output"
        sql_path = os.path.join(output_dir, f"{symbol}_config.sql")
        json_path = os.path.join(output_dir, f"{symbol}_config.json")

        output.generate_sql(configs, sql_path)
        output.generate_json(configs, json_path)

        print("[完成] 配置生成成功。")

    except RuntimeError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[中断] 用户取消操作。", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
