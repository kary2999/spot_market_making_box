# 现货铺单配置生成器 - 业务需求文档

## 概述

本模块用于生成 `spot_market_making_box` 表的铺单配置，支持买卖双向、多档位、近/中/远盘区域划分。

---

## 核心概念

### price_float 字段

**存储格式：百分比区间字符串**，如 `'99.964-100.000'`，表示相对于参考价的价格范围。

- 精度：最多 3 位小数（如 `99.999`），至少 1 位（如 `99.9`）
- **买盘（direction=1）**：价格区间在参考价以下，范围 50%~100%
  - 示例：参考价 10000 USDT，铺单价格在 5000~10000 USDT
  - price_float 示例：`'50.000-100.000'`（多档会细分）
- **卖盘（direction=-1）**：价格区间在参考价以上，范围 100%~150%
  - 示例：参考价 10000 USDT，铺单价格在 10000~15000 USDT
  - price_float 示例：`'100.000-150.000'`（多档会细分）

**约束**：
- 买方所有档位的 high ≤ 100
- 卖方所有档位的 low ≥ 100

---

## 近/中/远盘区域划分

基于距当前价的 **tick 数量**来划分区域，不是固定百分比：

| 区域 | tick 数范围 | 说明 |
|------|------------|------|
| 近盘 | 0 ~ 150 tick | 紧靠当前价，最多铺到前 150 个价格档 |
| 中盘 | 150 ~ 100,000 tick | 中间区域 |
| 远盘 | 100,000 tick ~ 总 tick 数 | 总 tick 数 = 价格 × 50% ÷ tickSize |

**示例（BTC，价格 10000 USDT，tickSize 0.01）**：
- 总 tick 数 = 10000 × 0.5 / 0.01 = 500,000
- 近盘：0~150 tick = 1.50 USDT 价格范围
- 中盘：150~100,000 tick = 998.50 USDT 价格范围
- 远盘：100,000~500,000 tick = 4,000 USDT 价格范围

---

## 档位（dom）区域分配规则

| 总档位数 | 近盘 | 中盘 | 远盘 |
|---------|------|------|------|
| ≤ 3    | dom1 | dom2..n-1 | dom_n |
| 4~6    | dom1 | dom2-3 | dom4+ |
| > 6    | dom1,dom2 | dom3..n-2 | dom_n-1, dom_n |

---

## trust_num（委托笔数）分配

- 总上限：1000 笔
- 基准 = 1000 / 档位数
- 各区域按倍率分配：
  - 近盘：基准 × 0.4
  - 中盘：基准 × 0.8
  - 远盘：基准 × 1.2

---

## number_float（数量浮动区间）

基于币安盘口深度累计量计算，单位为基础货币数量：

| 区域 | 取深度档数 |
|------|----------|
| 近盘 | 前 2 档 |
| 中盘 | 前 8 档 |
| 远盘 | 前 20 档 |

计算：`avg_qty = (buy_depth + sell_depth) / 2`，`base = avg_qty × 0.2`，区间为 `[base × 0.5, base]`

---

## change_trust_num（变幻委托）

- 近盘（dom1 或 dom1,dom2）：`change_trust_num = 0`（不启用）
- 中盘 / 远盘：`change_trust_num = 1`（启用）

---

## change_survival_time（存活时间）

- 近盘：`'3-10'`（秒）
- 中盘 / 远盘：`'10-30'`（秒）

---

## CLI 入口

```bash
python generate_box_config.py \
  --symbol eth_usdt \
  --pid 3 \
  --levels 9 \
  --total_usdt 2000000 \
  --depth_ratio 0.3
```

参数说明：
- `--symbol`：交易对（小写，下划线分隔）
- `--pid`：策略 ID
- `--levels`：档位数（买卖各 n 档，共 2n 条记录）
- `--total_usdt`：总铺单量（USDT）
- `--depth_ratio`：盘口深度使用比例（默认 0.3）

输出：`output/{symbol}_pid{pid}.sql` 和 `output/{symbol}_pid{pid}.json`

---

## 核心表结构

```sql
spot_market_making_box (
  pid INT,
  direction TINYINT,        -- -1=卖, 1=买
  dom TINYINT,              -- 档位编号（1 开始）
  trust_num INT,            -- 委托笔数
  price_float VARCHAR(32),  -- 价格百分比区间，如 '99.964-100.000'
  number_float VARCHAR(32), -- 数量区间，如 '0.128-0.256'
  change_trust_num TINYINT, -- 0=不变幻, 1=变幻
  change_number_float VARCHAR(32),
  change_survival_time VARCHAR(16), -- 存活时间，如 '3-10'
  status TINYINT            -- 1=启用
)
```
