# P2 建模 Mart 与特征字典

## 粒度与分区

每行唯一代表一个 `vegetable_id × city_id × origin_date × horizon_days` 预测任务。训练、验证、最终测试分别写入独立 Parquet，避免模型选择阶段误读最终测试目标。

训练起点为 2016-01 至 2019-12 的每个月月初；验证和最终测试起点沿用 `config/p2_experiment.yaml`。所有目标必须是目标日真实、正值、非 poor 观测。

## 标识与时间字段

| 字段 | 含义 | 预测时是否可用 |
|---|---|---|
| `split` | train / validation / final_test | 是 |
| `vegetable_id/code/name` | 蔬菜标识 | 是 |
| `city_id` | 城市标识 | 是 |
| `origin_date` | 预测起点 | 是 |
| `horizon_days` | 7 / 14 / 28 日 | 是 |
| `target_date` | 目标日期，由起点和跨度确定 | 是；目标价格未知 |
| `origin_price_date` | 起点价格实际观测日期 | 是 |
| `origin_fill_days` | 起点价格来自当日或前 1 日 | 是 |

## 数值特征

| 特征组 | 字段 | 构造规则 |
|---|---|---|
| 起点 | `origin_price`, `log_origin_price` | 当日或最多前 1 日合格价格 |
| 历史量 | `history_observation_count` | 严格在起点以前的资格检查；特征历史截止起点当日 |
| 日历滞后 | `lag_price_{1,7,14,28,56}d` | 在指定滞后日或其前最多 3 日 as-of 获取 |
| 滞后质量 | `lag_gap_*`, `lag_missing_*` | 实际 gap 和缺失标记 |
| 价格变化 | `return_{1,7,14,28,56}d` | 起点价格相对滞后价格的对数变化 |
| 滚动统计 | `rolling_{count,mean,median,std}_{7,14,28,56,90}d` | 日历窗口内、截止起点的合格价格 |
| 稀疏变价 | `historical_unchanged_share` | 起点以前相邻自然日价格不变的占比 |
| 周期 | `origin/target_day_of_year_{sin,cos}`, `origin/target_month` | 预测时已知的日历信息 |
| 月度季节 | `historical_seasonal_median` | 起点以前、与目标月份相同的历史价格中位数；不足 5 条时回退全历史中位数 |
| 周度模式 | `weekly_pattern_median` | 起点以前、与目标日星期相同的最近 4 条价格中位数 |

## 目标字段

`target_price` 是正式价格水平；`log_target_price` 是模型主目标；`target_price_change`、`target_log_return` 和 `target_direction` 只用于辅助诊断。任何以 `target_` 开头且包含实际价格或变化的字段都不得进入特征矩阵。

## 泄漏边界

1. 特征计算最多使用 `origin_date` 当日信息。
2. 365 条最低历史资格严格只计起点以前的观测。
3. 目标价格必须来自 `target_date` 的真实观测，不允许填充。
4. 最终测试文件可以被构建和封存，但 P2-T3/T4 的选择程序不得读取其中的目标。
5. 缺失填补、缩放和类别编码由后续每个训练窗单独拟合，本 mart 不做跨期拟合。

