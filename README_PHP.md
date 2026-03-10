# 📊 现货铺单配置生成器 (PHP 版)

根据币安实时行情数据，自动生成现货做市铺单配置（买卖双向多档位），输出 SQL 文件。

## 🛠️ 环境要求

- PHP 8.3+
- 扩展：`curl`、`bcmath`、`mbstring`

## 🚀 使用方法

```bash
php generate_box_config.php \
  --symbol eth_usdt \
  --pid 3 \
  --levels 9 \
  --total_usdt 2000000 \
  --depth_ratio 0.3
```

## 📋 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--symbol` | ✅ | - | 交易对，如 `eth_usdt` / `btc_usdt` |
| `--pid` | ✅ | - | 项目 ID |
| `--levels` | ❌ | 6 | 每侧档位数 |
| `--total_usdt` | ❌ | 1000000 | 总量（USDT） |
| `--depth_ratio` | ❌ | 0.2 | 深度比，单边有效量 = total × ratio / 2 |
| `--output_dir` | ❌ | ./output | SQL 输出目录 |

## 📐 架构说明

**单文件设计** — 所有功能集成在 `generate_box_config.php` 一个文件中：

- 🔗 **币安 API** — 实时获取价格、tickSize/stepSize、盘口深度
- 🧮 **配置引擎** — 动态计算近/中/远盘区间、价格百分比、委托数量
- 📄 **SQL 输出** — 生成 `INSERT INTO spot_market_making_box` 语句

## 📊 区间划分规则

| 区间 | tick 范围 | 特点 |
|------|-----------|------|
| 近盘 | 0 ~ 150 tick | 紧靠当前价，不变幻委托，存活时间短 |
| 中盘 | 150 ~ 100,000 tick | 中间区域，开启变幻委托 |
| 远盘 | 100,000 tick ~ 50% | 远离当前价，委托数最多 |

## 📁 输出示例

执行后会在 `output/` 目录生成 SQL 文件：

```
output/eth_usdt_pid3.sql
```

SQL 格式：
```sql
INSERT INTO spot_market_making_box (box_id, pid, direction, dom, trust_num, ...)
VALUES
  (null, 3, -1, 1, 44, '100.000-100.036', ...),
  ...
```

## 📝 License

MIT
