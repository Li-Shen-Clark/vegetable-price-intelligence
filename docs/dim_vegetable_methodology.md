# `dim_vegetable` 分类与价格档位方法

状态：A2 初版  
版本：`v0.1`  
编制日期：2026-09-11

## 1. 用途

`reference/dim_vegetable.csv` 为 30 种蔬菜提供稳定 ID、中英文名称、粗粒度采后属性和历史价格档位。它用于后续分组分析和结果解释，不是保质期承诺，也不代替具体品种、成熟度、包装和冷链条件。

## 2. 名称与 ID

`vegetable_id`、`vegetable_code` 和 `vegetable_name_zh` 取自 `dataSource/data_scraping/README.md`。英文代码必须与 `dataSource/rawData/<vegetable_code>.csv` 一一对应。

## 3. 易腐性与耐储性

### 3.1 主要依据

1. [FAO：园艺作物相对易腐性与潜在储藏期](https://www.fao.org/4/x5403e/x5403e09.htm)：按接近最优温湿度条件，将商品分为 very high、high、moderate、low、very low，并给出潜在储藏期区间。
2. [FAO：鲜活农产品类型与可食部](https://www.fao.org/4/T0073E/T0073E01.htm)：区分叶、茎、根、块茎、鳞茎、果实和未成熟豆荚等可食部类型。
3. [FAO：蔬菜最佳储藏条件示例](https://www.fao.org/4/y4358e/y4358e08.htm)：提供洋葱、蒜、胡萝卜、甘蓝、莴苣、西兰花、菜花、番茄、椒类、茄子和黄瓜等商品的储藏条件与期限示例。
4. [FAO：根、块茎和鳞茎的愈伤与储藏](https://www.fao.org/4/y4358e/y4358e05.htm)：说明马铃薯、薯蓣、洋葱和蒜等储藏器官可通过愈伤或干燥延长储藏期。

所有储藏期都依赖品种、成熟度、损伤、温度、湿度和包装。本表记录的是用于产品分组的相对等级，不是对单批货物的天数预测。

### 3.2 枚举与边界

`perishability_group`：

- `high`：FAO very high 或 high，通常潜在储藏期少于 4 周；
- `medium`：FAO moderate，通常为 4–8 周；
- `low`：FAO low 或 very low，通常超过 8 周。

`storability_group`：

- `short`：参考储藏期少于 2 周；
- `medium`：参考储藏期为 2–8 周；
- `long`：参考储藏期超过 8 周。

`classification_evidence`：

- `direct`：FAO 表格直接列出该商品或明确同名商品；
- `close_proxy`：按同一可食部、商品形态和采后行为使用近似商品类别；
- `expert_rule`：资料不足时的人工规则。本版不允许没有一句依据的 `expert_rule`。

`classification_basis` 用一句中文说明每个产品为何落入该组。使用近似项时必须明确写出代理对象，避免把代理分类表述为精确事实。

## 4. 历史价格统计

每个产品从对应原始 CSV 的 `当日价格` 计算：

- `observation_count`：全部记录数；
- `valid_price_count`：`observed_price > 0` 的记录数；
- `median_price_cny_per_kg`：有效价格中位数；
- `p25_price_cny_per_kg`：有效价格第 25 百分位；
- `p75_price_cny_per_kg`：有效价格第 75 百分位。

30 个文件共有 8,682,381 行。其中 8,651,109 行当日价格大于 0，31,272 行等于 0，没有负数或不可解析值。零值不参与价格分位数，但仍计入 `observation_count`。

## 5. 数据驱动价格档位

先计算 30 个产品各自的历史有效价格中位数，再对这 30 个中位数计算三分位点：

- 第 33.33 百分位：`2.933333 CNY/kg`；
- 第 66.67 百分位：`3.933333 CNY/kg`。

`typical_price_level` 的边界为：

```text
low:    median <= 2.933333
medium: 2.933333 < median <= 3.933333
high:   median > 3.933333
```

结果恰好分为 10 个 `low`、10 个 `medium` 和 10 个 `high`。这是 2014–2022 样本内部的相对档位，不代表固定或跨时期不变的绝对价格等级。

## 6. 版本与复核规则

- 分类版本写入 `classification_version`；本版为 `fao_v0.1`。
- 价格档位方法版本写入 `price_level_version`；本版为 `historical_tertiles_v0.1`。
- 新增年份或改变有效价格规则后，必须重新计算价格档位并记录版本。
- 发现更准确的商品级储藏资料时，可以替换 `close_proxy`，但必须先写修订计划，再追加执行日志。
- `perishability_group` 与 `storability_group` 都以潜在储藏行为为依据，相关性较强。建模时不能把二者当作相互独立的因果变量；是否同时使用应由回测或消融实验决定。
