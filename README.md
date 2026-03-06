# AiAgentManage — 现货铺单配置生成器

自动从币安公共 API 获取行情数据，按近盘 / 中盘 / 远盘三区域分配策略，生成 `spot_market_making_box` 表的多档位铺单参数，并导出可直接执行的 INSERT SQL 文件。

---

## 功能特性

- 实时拉取币安价格、tickSize/stepSize 精度信息和盘口深度（前 20 档）
- 按 tick 数动态划分近盘（0~150 tick）/ 中盘（150~100000 tick）/ 远盘（>100000 tick）
- 支持 1~N 档位，自动分配各区域 trust_num、change_trust_num、change_survival_time
- `price_float` 以**百分比区间**字符串表示（如 `99.964-100.000`），买盘 50%~100%，卖盘 100%~150%
- 生成 INSERT SQL 文件（写入 `output/` 目录）

---

## 项目结构

```
AiAgentManage/
├── generate_box_config.py      # CLI 入口
├── src/
│   ├── binance_api.py          # 币安公共 REST API 封装
│   ├── config_generator.py     # 铺单配置计算引擎
│   └── output.py               # SQL 输出 & 控制台摘要
├── tests/
│   ├── conftest.py             # pytest fixtures（btc/eth/shib 模拟数据）
│   ├── test_config_generator.py# 集成测试
│   └── unit/
│       └── test_config_generator.py  # 单元测试
├── docs/
│   └── spot_market_making_requirements.md  # 完整业务需求文档
└── output/                     # 生成的 SQL 文件输出目录
```

---

## 安装

**环境要求：** Python 3.10+

```bash
git clone https://github.com/kary2999/spot_market_making_box.git
cd spot_market_making_box
pip install requests
```

---

## 使用说明

### CLI 快速生成

```bash
python generate_box_config.py \
  --symbol eth_usdt \
  --pid 3 \
  --levels 9 \
  --total_usdt 2000000 \
  --depth_ratio 0.3
```

**参数说明：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--symbol` | 交易对，如 `eth_usdt`、`btc_usdt` | 必填 |
| `--pid` | 项目 ID，写入 `spot_market_making_box.pid` | 必填 |
| `--levels` | 每侧档位数 | `6` |
| `--total_usdt` | 总量（USDT） | `1000000` |
| `--depth_ratio` | 深度比，单边有效量 = total_usdt × depth_ratio / 2 | `0.2` |
| `--output_dir` | SQL 输出目录 | `./output` |

**输出示例：**

```
[API] 正在获取 ETH_USDT 行情数据...
[API] 参考价格: 3200.5  tickSize: 0.01
────────────────────────────────────────────────────────────
  交易对   : ETH/USDT  (参考价格: 3200.5)
  pid      : 3   档位数: 9   总量: 2,000,000 USDT
  深度比   : 0.3   远盘覆盖: 300.0%
  单边有效量: 300,000 USDT
  生成记录 : 18 条 (9 卖单 + 9 买单)
────────────────────────────────────────────────────────────

档位  区域  委托数  卖 price_float(%)            买 price_float(%)
...
[SQL] 已写入 output/eth_usdt_pid3.sql（18 条记录）
```

### Python API

```python
from src.binance_api import get_exchange_info, get_order_book, get_price
from src.config_generator import generate_configs

symbol = "eth_usdt"
current_price = get_price(symbol)
exchange_info  = get_exchange_info(symbol)   # {"tickSize": "0.01", "stepSize": "0.0001"}
order_book     = get_order_book(symbol, limit=20)

configs = generate_configs(
    symbol=symbol,
    levels=6,
    total_usdt=1_000_000,
    pid=1,
    current_price=current_price,
    exchange_info=exchange_info,
    order_book=order_book,
)

for cfg in configs:
    print(cfg["dom"], cfg["direction"], cfg["price_float"], cfg["trust_num"])
```

---

## 核心字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `pid` | int | 项目 ID |
| `symbol` | str | 交易对，如 `eth_usdt` |
| `direction` | int | `1` = 买盘，`-1` = 卖盘 |
| `dom` | int | 档位序号，从 1 开始 |
| `price_float` | str | 百分比区间，如 `99.964-100.000` |
| `number_float` | str | 委托量浮动区间，如 `100-500` |
| `trust_num` | int | 该档委托上限 |
| `change_trust_num` | int | 是否允许动态调整（近盘=0，中/远盘=1） |
| `change_survival_time` | str | 委托存活时间区间（近盘 `3-10`，中/远盘 `10-30`） |

---

## 区域划分规则

| 区域 | tick 数范围 | trust_num 倍率 | change_trust_num | change_survival_time |
|------|-------------|---------------|-----------------|---------------------|
| 近盘 | 0 ~ 150 | 0.4× | 0 | `3-10` |
| 中盘 | 150 ~ 100000 | 0.8× | 1 | `10-30` |
| 远盘 | > 100000 | 1.2× | 1 | `10-30` |

- `≤6` 档：近盘 = dom1，远盘从第 4 档起，中盘居中
- `>6` 档：近盘 = dom1-2，远盘 = 最后 2 档，中盘居中

---

## 运行测试

```bash
pytest tests/
```

346 条测试全部通过（含 btc/eth/shib 模拟 fixture）。

---

## 贡献指南

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交改动：`git commit -m "feat: 描述你的改动"`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request

**代码规范：**
- 遵循 PEP 8，注释全部用中文
- 新功能须附带对应单元测试
- commit message 使用约定式提交格式（`feat:` / `fix:` / `docs:` 等）

---

## 许可证

MIT License
