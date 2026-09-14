# P4 采购快照数据字典

## `scenario_snapshot.parquet`

粒度为产品×来源城市×历史情景起点×预测跨度。点价格逐组沿用 P2 发布路线；城市坐标来自 `dim_city_geo.csv`；可靠性来自预测起点实际报价日期的 Gold 城市日事实。

| 字段 | 含义 |
|---|---|
| `released_point_prediction` | P2 正式发布点价格，可能是模型或冻结基线，元/公斤 |
| `release_status` / `release_point_source` | P2 发布状态与实际点价格来源 |
| `released_p10` / `released_p90` | 仅 P2 允许发布的区间；其他组为空 |
| `price_input_label` | 面向用户的模型或基线说明 |
| `origin_source_reliability_score` | 起点实际使用报价日的数据可靠性分数 |
| `reliability_source` | 精确起点报价日或过去28日中位数回退 |
| `base_uncertainty_per_kg` | 合格区间上沿缓冲或无前视历史残差缓冲，元/公斤 |
| `risk_basis` | 风险缓冲来源；经验残差不是校准区间 |
| `eligible_under_default_reliability` | 是否通过默认 0.65 可靠性阈值 |
| `later_actual_price` | 历史目标日真实价，只用于事后核对，不参与排名或风险校准 |

## `residual_calibration.parquet`

每个产品×跨度×实际发布路线一行。`q80_absolute_log_error` 只使用 `target_date < 2022-05-01` 的已完成 P2 final-test 历史预测；所有组至少 30 行。该表提供未发布区间切片的经验风险缓冲，不生成 P10/P90。
