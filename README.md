# 现货铺单配置生成器

## 项目简介

自动根据交易所精度 + 币安/Gate/KuCoin/Bitget 盘口深度，生成符合市场真实分布的铺单配置（INSERT + UPDATE SQL）。

---

## 文件结构

```
spot_market_making_box/
├── generate_box_config.php   # 单个交易对生成
├── batch_generate.php        # 批量生成（读 symbol.ini）
├── symbol.ini                # 批量配置文件（pid => symbol）
├── control_panel.php         # 控制面板（查看运行日志）
├── output/                   # 生成的 SQL 文件目录
│   ├── batch_all.sql         # 所有交易对汇总 SQL
│   └── <symbol>_pid<pid>.sql # 单个交易对 SQL
└── logs/
    └── operations.log        # 操作日志（control_panel 读取）
```

---

## 数据来源

| 数据 | 来源 |
|------|------|
| 价格精度 (price_precision) | 本所 exchangeInfo API |
| 数量精度 (number_precision) | 本所 exchangeInfo API |
| 最小挂单量 (min_trade) | 本所 exchangeInfo API |
| 参考价格 | 币安（回退：Gate → KuCoin → Bitget） |
| 盘口深度 | 币安（回退：Gate → KuCoin → Bitget） |

本所 API：
```
https://app.nn88zl.com/spot/read/pub/exchangeInfo?app_id=AwyOTFRlsfQ5mRkqwCNaEd5T
```

---

## 铺单核心规则

### 档位分布

| 区域 | dom | 说明 |
|------|-----|------|
| 近盘 | 1-2 | 紧贴当前价，给用户看的盘口深度 |
| 均分 | 3-9 | 承接大单，提供滑点保护 |

### 价格区间

- **总覆盖范围**：当前价 ±50%（卖方 100%~150%，买方 50%~100%）
- **近盘宽度**：每档 = `当前价 × 2% ÷ tickSize` 个价格位（自动适配精度，上限100，下限5）
- **均分区间**：`(50% - 近盘总宽度) ÷ 7` 均分到 dom3-9

### 挂单量（number_float）

**近盘（dom1-2）**：
- 基于币安前5档深度统计
- `min = 盘口最小档量 × 0.2`
- `max = 盘口中位数（去最大值） × 0.2`
- 近盘 max ≤ 均分 max（保证近盘不压过中远盘）

**均分（dom3-9）**：
- 基于币安前20档深度统计
- `固定单 number_float = max×50% - max`
- `变动单 change_number_float = max - max`（固定最大值）

### 委托笔数（trust_num）

- 总量：`--total_trust`（默认800，买卖各400）
- 近盘：`nearTicks × 0.85`（填充率 ≥ 0.8）
- 均分：`(单侧总量 - 近盘总量) ÷ 7`

### 变动单配置

| 字段 | 近盘 | 均分 |
|------|------|------|
| change_trust_num | 0（不变动） | 1（允许变动） |
| change_survival_time | 3-10 秒 | 10-30 秒 |

---

## 使用方法

### 单个生成

```bash
php generate_box_config.php \
  --symbol trx_usdt \
  --pid 3 \
  --levels 9 \
  --total_usdt 2000000 \
  --depth_ratio 0.3 \
  --total_trust 800
```

**参数说明：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --symbol | 交易对（必填） | - |
| --pid | 项目 ID（必填） | - |
| --levels | 每侧档位数 | 9 |
| --total_usdt | 总资金量 USDT | 1000000 |
| --depth_ratio | 深度比例 | 0.2 |
| --total_trust | 买卖合计委托上限 | 800 |
| --output_dir | SQL 输出目录 | ./output |

### 批量生成

```bash
php batch_generate.php
# 或指定配置文件
php batch_generate.php --ini symbol.ini
```

### symbol.ini 格式

```ini
[config]
levels = 9
total_usdt = 2000000
depth_ratio = 0.3
total_trust = 800
output_dir = output

[symbols]
; pid = symbol
3 = trx_usdt
8 = sol_usdt
14 = xrp_usdt
```

---

## SQL 输出格式

每个交易对生成两类 SQL：

**INSERT**（首次入库）：
```sql
INSERT INTO spot_market_making_box (box_id, pid, direction, dom, trust_num, ...)
VALUES
  (null, 3, -1, 1, 85, '100.000-100.348', ...),
  ...;
```

**UPDATE**（更新参数）：
```sql
UPDATE spot_market_making_box
SET trust_num = 85, price_float = '100.000-100.348', ...
WHERE pid = 3 AND direction = -1 AND dom = 1;
```

- `direction = -1`：卖单
- `direction = 1`：买单
- `dom`：档位编号（1=最近盘）

---

## 多交易所回退逻辑

```
币安 → Gate.io → KuCoin → Bitget
```

若某交易所无此交易对（HTTP 400）自动跳转下一个，全部失败则该交易对标记为失败并跳过，不中断批量流程。

---

## 常见问题

**Q: 为什么某些交易对生成失败？**
- 本所有此交易对但所有行情交易所均无 → 需手动添加数据源

**Q: 近盘价格位数怎么确定？**
- 自动计算：`round(当前价 × 2% ÷ tickSize)`，范围 5-100
- TRX（5位精度）≈ 100 ticks；SUSHI（3位精度）≈ 5 ticks

**Q: 如何只更新部分参数？**
- 直接执行生成的 UPDATE SQL 即可，按 pid+direction+dom 精准更新

---

## 依赖

- PHP 7.3+
- 扩展：`bcmath`、`curl`
- 无需数据库，所有数据实时从 API 获取
