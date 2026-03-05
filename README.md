# AiAgentManage

币安现货网格铺单配置管理工具，自动从币安 API 获取行情数据，计算并生成网格做市策略的铺单参数配置。

## 功能特性

- 从币安公共 API 实时获取价格、精度信息（tickSize/stepSize）和盘口深度
- 支持等差（arithmetic）和等比（geometric）两种网格模式
- 按盘口区间（近盘 / 中盘 / 远盘）自动计算挂单数量浮动范围
- 生成多档位（1~6 档）买卖双向铺单配置
- 支持将配置导出为 JSON 文件

## 项目结构

```
AiAgentManage/
├── src/
│   ├── binance_api.py      # 币安公共 REST API 封装
│   └── config_generator.py # 铺单配置计算引擎
├── tests/
│   ├── unit/               # 单元测试
│   ├── integration/        # 集成测试
│   └── e2e/                # 端到端测试
└── README.md
```

## 安装

**环境要求：** Python 3.10+

```bash
# 克隆仓库
git clone <repository-url>
cd AiAgentManage

# 安装依赖
pip install requests
```

## 使用说明

### 获取行情数据

```python
from src.binance_api import get_price, get_exchange_info, get_order_book

symbol = "BTCUSDT"

# 获取当前价格
price = get_price(symbol)

# 获取精度信息
exchange_info = get_exchange_info(symbol)  # {"tickSize": "0.01", "stepSize": "0.00001"}

# 获取盘口深度（前 20 档）
order_book = get_order_book(symbol, limit=20)
```

### 生成多档位铺单配置

```python
from src.config_generator import generate_configs

configs = generate_configs(
    symbol="BTCUSDT",
    levels=6,
    total_usdt=10000,
    pid=1,
    current_price=price,
    exchange_info=exchange_info,
    order_book=order_book,
)

for cfg in configs:
    print(cfg["_direction_label"], cfg["dom"], cfg["price_float"], cfg["number_float"])
```

### 使用网格配置生成器

```python
from src.config_generator import ConfigGenerator

gen = ConfigGenerator(
    symbol="BTCUSDT",
    price_low=90000,
    price_high=100000,
    grid_count=10,
    total_budget=5000,
    tick_size="0.01",
    step_size="0.00001",
    grid_mode="arithmetic",  # 或 "geometric"
)

# 生成配置列表
orders = gen.generate_config()

# 导出为 JSON
gen.export_json("btcusdt_grid.json")
```

## 运行测试

```bash
pytest tests/
```

## 贡献指南

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交改动：`git commit -m "feat: 描述你的改动"`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request，描述改动内容和测试情况

**代码规范：**
- 遵循 PEP 8 风格
- 新功能须附带对应单元测试
- 提交信息使用约定式提交格式（`feat:` / `fix:` / `docs:` 等前缀）

## 许可证

MIT License
