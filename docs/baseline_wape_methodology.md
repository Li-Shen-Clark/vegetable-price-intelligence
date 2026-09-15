# Last-value WAPE 诊断口径

状态：P0 A4 基准登记  
版本：`v0_diagnostic`  
数据截止：2022-06-22

## 1. 定位

这是使用完整历史期的可行性诊断，用于给 P2 提供可复现的简单基准。它不是最终测试集成绩，也不是 rolling-origin backtest。正式 P2 必须按照已冻结的训练、验证、测试切分重新登记基准。

## 2. 固定输入

- P2 范围：`config/p2_scope.yaml` 中的 10 种核心蔬菜；
- 原始价格：`dataSource/rawData/<vegetable_code>.csv`；
- 市场映射：`dataSource/data_scraping/mofcom_data/market_Clean.csv` 中 200 个明确映射；
- 未匹配的 69 个市场名称不进入本诊断；27 个尚未人工批准的 `city_guess` 也不进入。

结果文件保存配置、映射、范围和 10 个原始文件的 SHA-256，并记录脚本自身的 SHA-256，用于判断重跑时数据、参数或实现是否发生变化。

## 3. 处理顺序

1. 将“日期”解析为日历日，将“当日价格”解析为数值；
2. 只保留 `observed_price > 0` 且日期在 2014-02-02 至 2022-06-22 之间的记录；
3. 按原始市场名与 200 行旧映射做精确连接；
4. 按蔬菜×城市×日计算市场报价中位数；
5. 只保留至少 2,000 个有效报价日的蔬菜×城市序列；
6. 对每个城市建立日历日索引；预测原点缺值时只允许前向补 1 天；
7. 目标日必须有真实城市日价格，不用填补值充当实际值；
8. 分别生成 7、14、28 天 last-value 预测。

1 天前向补值只用于避免预测原点恰逢单日缺报。连续缺报超过 1 天时不生成该预测，以免把长期陈旧报价当作当前可见价格。

## 4. 指标

```text
WAPE = 100 × Σ|actual - forecast| / Σ|actual|
```

WAPE 在同一蔬菜、同一预测周期的全部合格城市与目标日上汇总。结果同时保存：

- `eligible_city_count`
- `eligible_city_day_count`
- `prediction_count`
- `absolute_error_sum`
- `absolute_actual_sum`
- `wape_percent`

因此可以复核分子、分母和样本量，不只保留最终百分比。

## 5. 运行方式

在项目目录执行：

```bash
python src/benchmarks/baseline_wape.py \
  --config config/baseline_wape.yaml \
  --output baselines/v0_diagnostic.json
```

运行环境需要 Python 与 Pandas。配置文件保存路径、字段、有效价格门槛、城市日期门槛、补值上限、评估区间和预测周期。

## 6. 与早期诊断数字的关系

番茄、土豆和大白菜的旧表是早期诊断。`v0_diagnostic` 使用明确写入配置的 200 行精确映射与 1 天预测原点补值。两者若存在小于几个基点的差异，应优先检查映射版本、缺失处理和四舍五入，而不是把差异解释为模型变化。

## 7. 限制

- 完整历史期包含疫情前后结构变化，不能代表未来表现；
- 本诊断只衡量点预测误差，不评价概率区间或涨价事件；
- 城市中位数会降低单市场噪声，但不能消除不同等级、规格和成交量差异；
- 正式映射完成后必须升级基准版本，不能悄悄覆盖 `v0_diagnostic`。
