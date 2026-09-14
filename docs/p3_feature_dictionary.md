# P3 预警 mart 字段字典

## 粒度与切分

每行是一个 `vegetable_id + city_id + origin_date` 周度预警任务。`split` 固定为 train、validation 或 final_test；三者目标窗口不交叉。final_test 标签已经独立物化，但在 P3-T4 前不得用于模型、特征或阈值选择。

## 身份与起点

- `vegetable_*`、`city_id`、`market_city`、`market_province`：产品和城市身份。
- `origin_date`、`origin_price_date`、`origin_fill_days`：计划预警日、实际起点价格日和最多 1 天的填充标记。
- `origin_price`、`log_origin_price`：起点价格及对数。
- `origin_*quality*`、`origin_stale_quote_share`、`origin_outlier_share`、`origin_source_reliability_score`：起点时可见的数据质量。

## 历史特征

- `lag_price_*`、`lag_gap_*`、`lag_missing_*`、`return_*`：1/7/14/28/56 日 as-of 价格、间隔、缺失和对数变化。
- `rolling_*`：7/14/28/56/90 日价格均值、中位数、标准差、变异系数、有效天数和质量均值。
- `recent_up_day_share_14d`、`recent_down_day_share_14d`：最近 14 日有效价格变动方向。
- `historical_same_month_*`、`origin_vs_seasonal_log_ratio`：只使用起点以前同月价格的季节参照。
- `historical_event_rate_*`：只使用目标窗口已在当前起点前结束的历史事件；52 周率和全历史率分别保留。

## 目标与事件标签

- `future_peak_*`：未来 14 日真实有效观测的峰值、日期和相对涨幅；只用于训练/评估。
- `seasonal_threshold_q90/q95`：由当前起点以前已经完成的历史 14 日窗口计算的分位阈值。
- `seasonal_threshold_level/count`：阈值回退层级与历史样本数。
- `raw_event_abs*_q*`：绝对涨幅与历史季节阈值同时满足的重叠窗口。
- `event_label_abs*_q*`：在 raw event 上再做同序列 21 天去重后的事件起点。
- `event_label`：正式 `abs20_q90` 标签；`primary_raw_event` 是其去重前窗口。
- `event_effective_return_threshold`、`event_crossing_date`、`event_lead_days`：正式事件的实际门槛、首次跨越日和 1–14 日提前量。

## 泄漏边界

模型输入不得包含任何 `future_*`、`target_*`、`seasonal_threshold_*`、`raw_event_*`、`event_label*`、`event_crossing_date`、`event_lead_days` 字段。所有模型特征列表必须在 `config/p3_models.yaml` 中显式白名单冻结。
