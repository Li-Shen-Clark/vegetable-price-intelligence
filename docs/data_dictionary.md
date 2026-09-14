# 蔬菜批发价格数据字典

状态：P0 数据契约 v0.1  
本次核验：T8 全表字段与质量口径  
核验日期：2026-09-11

## 1. 数据来源与适用范围

本项目的 30 个蔬菜原始 CSV 来自商务部公共商务信息服务“百家日报”农副产品市场监测页面。本地采集说明列出的来源为商务部重点监测的大型农产品批发市场。

官方页面将该指标标为“批发价格行情（单位：元/公斤）”，并列出“地区、市场、当日价格、前一日价格、环比”等字段。因此本项目将价格单位标准化为：

- 展示单位：人民币元/公斤
- 机器可读单位：`CNY/kg`
- 价格类型：批发市场监测报价
- 不应解释为：零售价格、成交量加权均价、固定等级或固定包装规格价格

原始数据没有成交量、等级、规格和包装字段。任何城市聚合或预测都不能声称已经控制这些差异。

## 2. A1 证据链

| 优先级 | 证据 | 核验结果 |
|---:|---|---|
| 1 | [商务部大白菜日度价格页面](https://cif.mofcom.gov.cn/cif/seach.fhtml?commdityid=170060) | 页面标题明确写明“批发价格行情（单位：元/公斤）”，表头包含“当日价格、前一日价格、环比” |
| 1 | [商务部全国农副产品日报页面](https://cif.mofcom.gov.cn/cif/html/screen/bjScreen.html) | 明确写明“全国平均批发价格”“元/公斤”，并说明数据来自约 100 家大型农副产品批发市场的日报监测 |
| 2 | `dataSource/data_scraping/mofcom(final).py` | 采集接口为 `getEnterpriseListForDate.fhtml`；代码将 `PRICE2` 保存为“当日价格”、`PRICE1` 保存为“前一日价格”、`PRICE3` 保存为“环比” |
| 3 | `dataSource/rawData/*.csv` | 30 个文件均使用相同的 7 列表头；8,682,381 行价格与环比字段均可解析为数值 |
| 4 | 全量公式复核 | 8,682,381 / 8,682,381 行的源“环比”均与 `round((当日价格 - 前一日价格) / 前一日价格 × 100, 2)` 在 ±0.011 个百分点容差内一致 |

页面截图存档：[mofcom_price_unit_2026-09-11.png](evidence/mofcom_price_unit_2026-09-11.png)。截图只用于证明核验时页面的单位和字段标签，不替代原始数据文件。

## 3. 原始字段到标准字段

原始 CSV 表头：

```text
日期,idx,地区,时长,当日价格,前一日价格,环比
```

| 原始字段 | 标准字段 | 类型 | 单位 | 含义与处理规则 |
|---|---|---|---|---|
| 日期 | `date` | date | 日 | 报价对应日期；解析为 `YYYY-MM-DD` |
| idx | `source_row_index` | integer | — | 来源页面中的当日行序号；保留用于追溯，不作为跨日稳定标识 |
| 地区 | `raw_province` | string | — | 来源记录的省级地区；原样保留，后续与市场映射省份交叉检查 |
| 时长 | `raw_market_name` | string | — | 表头存在历史命名错误；实际内容是批发市场或运营企业名称 |
| 当日价格 | `observed_price` | decimal | `CNY/kg` | 当日批发市场监测报价；Bronze 原样保留，Silver 再判定有效性 |
| 前一日价格 | `previous_price` | decimal | `CNY/kg` | 来源系统随记录提供的对比价格；不是本项目通过时间序列移位生成的值 |
| 环比 | `reported_change_pct` | decimal | % | 来源系统提供的有符号变化率；去除 `%` 后保存数值，同时保留原始字符串用于追溯 |

## 4. 环比计算与一致性检查

对本地 2014–2022 历史数据，源字段满足：

```text
calculated_change_pct =
    round((observed_price - previous_price) / previous_price * 100, 2)
```

Silver 层实际保留 `reported_change_pct` 来源值，并生成 `reported_change_consistent_flag`。复算值只在质量检查过程中使用，不另存一列，避免把可由价格确定的冗余值写入事实表。

不要用 `reported_change_pct` 反推价格，也不要覆盖 `observed_price` 或 `previous_price`。

核验时发现，2026 年官方网页的部分可见行可能采用与历史文件不同的符号或分母口径。该现象不改变 2014–2022 本地数据的全量公式验证结果，但意味着未来若追加新数据，必须按采集批次重新验证环比公式并记录版本，不能默认沿用历史口径。

## 5. 已确认与未确认事项

### 已确认

- 价格是批发市场监测报价。
- 原始页面单位为“元/公斤”，项目标准单位为 `CNY/kg`。
- “当日价格”和“前一日价格”使用相同单位。
- 本地 2014–2022 数据的“环比”按标准日变化率公式计算，并四舍五入到两位小数。

### 尚未由原始数据确认

- 单条报价对应的等级、规格、包装和实际成交量。
- “前一日价格”在市场停报时究竟指前一日历日还是上一有效报价日。
- 市场上报价格是否为市场自行计算的均价，以及各市场内部计算规则是否一致。

这些未确认项必须作为模型与产品解释限制保留，不得在后续文档中补写为已知事实。

## 6. 数据层与表粒度

| 表 | 层 | 粒度 | 行数 | 用途 |
|---|---|---|---:|---|
| `fact_market_price_raw` | Bronze | 来源文件中的一条原始报价记录 | 8,682,381 | 无损追溯与重新处理 |
| `fact_market_price_mapped` | Silver | 原始报价记录 + 市场映射 | 8,682,381 | 市场身份与城市归属 |
| `fact_market_price_quality` | Silver | 原始报价记录 + 映射 + 行级质量标记 | 8,682,381 | 数据质量判断；不删记录 |
| `fact_market_price` | Gold | 发布版市场报价记录 | 8,682,381 | 对外稳定的市场级分析事实；与质量 Silver 字节一致 |
| `fact_city_price` | Gold | 城市×蔬菜×有效观测日 | 7,358,606 | Price Monitor、预测与传播分析的主价格表 |
| `coverage_tiers` | Gold | 蔬菜×正式城市 | 3,510 | 历史覆盖、缺口、质量和 A/B/C 资格 |
| `dim_vegetable` | Reference | 一种蔬菜 | 30 | 商品 ID、名称、品类与历史价格层级 |
| `dim_city` | Reference | 一个正式城市 | 117 | 稳定城市 ID、城市名、省份与纳入市场数 |
| `market_mapping` | Reference | 一个原始市场名称 | 269 | 市场身份、正式城市、证据、状态与版本 |

Gold 市场事实没有执行筛选。城市事实只纳入 `mapped_existing_city` 且 `price_valid_flag = true` 的记录。城市日内先把同一市场的重复来源行取中位数，再让每个市场以相同权重进入城市聚合。

## 7. Bronze 字段：`fact_market_price_raw`

| 字段 | 类型 | 可空 | 单位/含义 |
|---|---|---|---|
| `vegetable_id` | int32 | 否 | 商务部商品 ID |
| `vegetable_code` | string | 否 | 项目英文商品代码 |
| `vegetable_name_zh` | string | 否 | 中文商品名 |
| `source_file` | string | 否 | 来源 CSV 文件名 |
| `source_file_row_number` | int64 | 否 | 含表头文件中的物理行号；与 `source_file` 组成追溯键 |
| `source_row_index` | int32 | 否 | 来源 `idx`；只代表页面内行序 |
| `raw_date` | string | 否 | 未修改的日期文本 |
| `date` | date32 | 否 | 解析后的报价日期 |
| `raw_province` | string | 否 | 来源省级报送口径，永不覆盖 |
| `raw_market_name` | string | 否 | 来源市场名称，永不覆盖 |
| `raw_observed_price` | string | 否 | 未修改的当日价格文本 |
| `observed_price` | float64 | 否 | 当日价格，`CNY/kg`；Bronze 可含非正值 |
| `raw_previous_price` | string | 否 | 未修改的前一日价格文本 |
| `previous_price` | float64 | 否 | 来源提供的前一日价格，`CNY/kg` |
| `raw_reported_change` | string | 否 | 未修改的环比文本 |
| `reported_change_pct` | float64 | 否 | 来源环比，百分点数值，例如 2.5 表示 2.5% |

## 8. 映射新增字段：`fact_market_price_mapped`

| 字段 | 类型 | 可空 | 含义 |
|---|---|---|---|
| `market_id` | string | 否 | 版本化市场 ID |
| `standardized_market_name` | string | 否 | NFKC、括号和空格规范后的名称；不替代原名 |
| `market_city` | string | 是 | 正式 117 城市之一；范围外城市为空 |
| `market_province` | string | 是 | 与正式城市一致的省级归属；范围外城市为空 |
| `identified_city` | string | 否 | 研究确认的实际城市，包括范围外城市 |
| `identified_province` | string | 否 | 研究确认的实际省份 |
| `market_longitude` | float64 | 是 | 市场级经度；没有可靠证据时为空 |
| `market_latitude` | float64 | 是 | 市场级纬度；没有可靠证据时为空 |
| `mapping_status` | string | 否 | `mapped_existing_city`、`unmapped_new_city` 或 `unmapped_unknown` |
| `mapping_confidence` | string | 否 | `high`、`medium`、`low`；描述映射证据强度 |
| `mapping_source` | string | 否 | 映射的来源类型 |
| `mapping_version` | string | 否 | 当前正式版本 `v0.2` |
| `raw_market_name_recovered` | string | 是 | 乱码名称的可读恢复值；连接仍用原名 |

`raw_province` 与 `market_province` 表示不同口径。前者是来源报送标签，后者是标准地理归属；新疆生产建设兵团记录的差异被有意保留。

## 9. 质量新增字段：`fact_market_price_quality`

| 字段 | 类型 | 可空 | 含义 |
|---|---|---|---|
| `price_valid_flag` | boolean | 否 | `observed_price` 有限且大于 0 |
| `invalid_price_reason` | string | 是 | 无效价格原因；有效价格为空 |
| `reported_change_consistent_flag` | boolean | 是 | 可复核行的来源环比是否在 ±0.011 个百分点内一致；分母无效时为空 |
| `duplicate_market_date_flag` | boolean | 否 | 同一市场×蔬菜×日期是否出现多条来源行 |
| `zero_change_flag` | boolean | 否 | 与来源提供的前一日价格相同，且该市场序列上一条记录恰好相隔 1 日 |
| `zero_change_run_length` | int32 | 否 | 连续逐日零变动期长度；非零变动行为 0 |
| `stale_quote_flag` | boolean | 否 | `zero_change_run_length ≥ 7`；只表示疑似结转，不等于错误 |
| `days_since_last_valid_quote` | int32 | 是 | 当前有效行为 0；无效行为距本序列最近历史有效报价的日数；此前无有效价时为空 |
| `outlier_flag` | boolean | 否 | 仅用过去最多 90 条、至少 30 条有效历史在 log 价格上得到的候选异常标记 |
| `quality_rule_version` | string | 否 | 当前 `quality_v0.1` |

Gold `fact_market_price` 具有相同的 39 列、顺序、类型和内容。

## 10. 城市日字段：`fact_city_price`

| 字段 | 类型 | 可空 | 单位/含义 |
|---|---|---|---|
| `date` | date32 | 否 | 有至少一个有效市场报价的日期 |
| `vegetable_id` | int32 | 否 | 商品 ID |
| `vegetable_code` | string | 否 | 英文商品代码 |
| `vegetable_name_zh` | string | 否 | 中文商品名 |
| `city_id` | string | 否 | `dim_city` 稳定 ID |
| `market_city` | string | 否 | 正式城市名 |
| `market_province` | string | 否 | 正式省份 |
| `analysis_price` | float64 | 否 | 主分析价格，等于市场日价格的城市中位数，`CNY/kg` |
| `median_price` | float64 | 否 | 城市中位数，`CNY/kg` |
| `trimmed_mean_price` | float64 | 否 | 10% 对称修剪均值，`CNY/kg`；本数据最多 8 个市场，实际未触发修剪，等于普通均值 |
| `number_of_reporting_markets` | int32 | 否 | 城市日内有效且去重后的市场数 |
| `source_record_count` | int64 | 否 | 进入这些市场日的有效来源行数 |
| `stale_quote_share` | float64 | 否 | 含 stale 候选的市场日占比，0–1 |
| `outlier_share` | float64 | 否 | 含 outlier 候选的市场日占比，0–1 |
| `duplicate_market_share` | float64 | 否 | 含多条有效来源行的市场日占比，0–1 |
| `mean_mapping_confidence_score` | float64 | 否 | 市场日平均映射置信分，0–1 |
| `source_reliability_score` | float64 | 否 | 新鲜度、异常、重复、映射和市场支持的加权数据质量分，0–1 |
| `data_quality_flag` | string | 否 | `good`（≥0.85）、`caution`（≥0.65）或 `poor` |
| `aggregation_version` | string | 否 | 当前 `city_price_v0.1` |

可靠性分数不是预测概率，也不表示报价“为真”的概率。88.30% 的城市日只有一个报告市场，因此市场数只占分数的 15%，单市场不会被统一删除。

## 11. 覆盖与 Tier 字段：`coverage_tiers`

| 字段 | 类型 | 可空 | 含义 |
|---|---|---|---|
| `vegetable_id` / `vegetable_code` / `vegetable_name_zh` | int32 / string / string | 否 | 商品身份 |
| `city_id` / `city_name_zh` / `province_name_zh` | string | 否 | 正式城市身份 |
| `calendar_start_date` / `calendar_end_date` | date32 | 否 | 统一窗口 2014-02-02 / 2022-06-22 |
| `calendar_day_count` | int32 | 否 | 统一窗口自然日数 3,063 |
| `first_valid_date` / `last_valid_date` | date32 | 是 | 首末有效城市日；无数据组合为空 |
| `valid_day_count` | int32 | 否 | 有效城市日数 |
| `coverage_rate` | float64 | 否 | 有效日数÷3,063 |
| `active_span_day_count` | int32 | 否 | 首末有效日之间的自然日数；无数据为 0 |
| `active_span_coverage_rate` | float64 | 否 | 有效日数÷活跃跨度；无数据为 0 |
| `leading_gap_days` | int32 | 否 | 日历起点至首个有效日前的缺口 |
| `trailing_gap_days` | int32 | 否 | 最后有效日后至数据集截止日的缺口 |
| `longest_internal_gap_days` | int32 | 否 | 首末有效日之间最长连续缺报天数 |
| `longest_overall_gap_days` | int32 | 否 | leading、trailing、internal 的最大值 |
| `mean_reporting_markets` | float64 | 是 | 有效城市日的平均报告市场数 |
| `max_reporting_markets` | int32 | 否 | 历史最大报告市场数；无数据为 0 |
| `single_market_day_share` | float64 | 是 | 只有一个报告市场的有效城市日占比 |
| `mean_stale_quote_share` | float64 | 是 | 城市日 stale 市场占比的历史均值 |
| `mean_outlier_share` | float64 | 是 | 城市日 outlier 市场占比的历史均值 |
| `mean_duplicate_market_share` | float64 | 是 | 城市日重复市场占比的历史均值 |
| `mean_source_reliability_score` | float64 | 是 | 城市日来源可靠性分的历史均值 |
| `good_day_share` / `caution_day_share` / `poor_day_share` | float64 | 是 | 三类城市日质量占比；有数据时合计为 1 |
| `coverage_score` | float64 | 否 | 覆盖、活跃跨度、近期性和质量的加权诊断分，0–1 |
| `coverage_tier` | string | 否 | `A`、`B` 或 `C` |
| `forecast_eligible_flag` | boolean | 否 | 仅 Tier A 为真；表示历史回测资格 |
| `monitor_eligible_flag` | boolean | 否 | Tier A/B 为真；表示历史监控资格 |
| `tier_reason` | string | 否 | 达标说明或未通过的绝对门槛代码 |
| `tier_rule_version` | string | 否 | 当前 `coverage_tier_v0.1` |

Tier A 要求有效日期≥2,500、活跃跨度覆盖率≥80%、最长内部缺口≤60 日、尾部缺口≤365 日、平均 stale≤25%、平均 outlier≤10%、poor 日≤20%。Tier B 使用 `config/tiering.yaml` 中较宽的监控门槛。Tier 以 2022-06-22 为数据截止日，不能解释为 2026 年实时资格。

## 12. 核心维表

### `dim_city`

| 字段 | 类型 | 含义 |
|---|---|---|
| `city_id` | string | 按“正式省份＋城市”UTF-8 字节序生成的稳定 ID `city_001`…`city_117` |
| `city_name_zh` | string | 正式城市名 |
| `province_name_zh` | string | 正式省份 |
| `included_market_count` | integer | 当前映射中纳入该城市的市场数 |
| `dimension_version` | string | 当前 `city_dim_v0.1` |

### `dim_vegetable`

| 字段组 | 字段 | 含义 |
|---|---|---|
| 身份 | `vegetable_id`, `vegetable_code`, `vegetable_name_zh`, `source_file` | 商品与来源文件 |
| 类别 | `edible_part_group`, `perishability_group`, `storability_group` | 可食部位、易腐性和储存分组 |
| 分类证据 | `classification_evidence`, `classification_source_ref`, `classification_basis`, `classification_version` | 分类的证据强度、引用、理由和版本 |
| 历史统计 | `observation_count`, `valid_price_count` | 来源行数和正价格数 |
| 价格分布 | `median_price_cny_per_kg`, `p25_price_cny_per_kg`, `p75_price_cny_per_kg` | 全历史价格分布，`CNY/kg` |
| 层级 | `typical_price_level`, `price_level_version` | 由历史三分位得到的低/中/高价格层级及版本 |

## 13. 参考映射表

`market_mapping.csv` 的 19 列分为：原始/规范名称（`raw_market_name`, `standardized_name`, `normalized_match_key`, `raw_market_name_recovered`）、市场和位置身份（`market_id`, `canonical_city`, `canonical_province`, `identified_city`, `identified_province`, `longitude`, `latitude`）、映射判断（`mapping_status`, `mapping_confidence`, `mapping_source`, `mapping_evidence`）以及审核/版本（`review_status`, `reviewed_by`, `reviewed_at`, `mapping_version`）。

正式连接始终使用 `raw_market_name` 精确 many-to-one 连接。`normalized_match_key` 只用于候选研究，不能覆盖原始名称或绕过证据审核。

## 14. P4 城市地理维度：`dim_city_geo`

路径：`reference/dim_city_geo.csv`。117 行，与 `dim_city` 一一对应；P4 正式距离只读取本表，不读取旧市场坐标。

| 字段 | 类型 | 可空 | 含义 |
|---|---|---|---|
| `city_id` | string | 否 | `dim_city` 稳定 ID |
| `city_name_zh` / `province_name_zh` | string | 否 | 正式城市、省份名称 |
| `longitude` / `latitude` | float | 否 | WGS84 风格十进制度城市锚点 |
| `coordinate_method` | string | 否 | `city_center_snapshot` 或 `single_official_market_anchor` |
| `coordinate_source` | string | 否 | 版本化项目内来源路径 |
| `source_city_name` | string | 否 | 源坐标名称 |
| `alias_rule` | string | 是 | 粒度不一致时的显式规则；大理县级特殊项使用此字段 |
| `qa_status` | string | 否 | 坐标用途审核状态 |
| `geo_dimension_version` | string | 否 | 当前 `city_geo_v0.1` |

距离单位为公里，计算为城市锚点 Haversine 直线距离；采购情景再乘可配置道路折算系数。它不代表公路里程、运输时效或路线可达性。

## 15. P4 采购情景快照：`scenario_snapshot`

路径：`data/modeling/p4_procurement_mart/scenario_snapshot.parquet`。843 行，主键为 `vegetable_id + city_id + horizon_days`，历史情景起点固定为 2022-05-01。

| 字段组 | 主要字段 | 含义 |
|---|---|---|
| 身份与时间 | `vegetable_id`, `vegetable_code`, `vegetable_name_zh`, `city_id`, `origin_date`, `horizon_days`, `target_date` | 产品、来源城市和冻结预测任务 |
| P2 原始证据 | `origin_price`, `best_baseline_name`, `best_baseline_prediction`, `model_prediction`, `p10`, `p50`, `p90` | P2 final-test 原始预测与基线字段 |
| 正式发布路线 | `release_status`, `released_point_prediction`, `released_p10`, `released_p90`, `release_point_source`, `price_input_label`, `interval_status` | 逐组继承 P2 发布矩阵；未发布区间保持为空 |
| 后来结果 | `later_actual_price` | 目标日后来观察到的实际价格，只用于历史回放，不进入情景排序 |
| 报价质量 | `origin_price_date`, `origin_source_reliability_score`, `origin_data_quality_flag`, `origin_reporting_markets`, `reliability_source` | P2 起点实际报价日的数据质量证据 |
| 地理 | `city_name_zh`, `province_name_zh`, `longitude`, `latitude`, `coordinate_method`, `geo_dimension_version` | 来源城市锚点 |
| 覆盖资格 | `coverage_tier`, `coverage_rate`, `active_span_coverage_rate`, `mean_source_reliability_score`, `poor_day_share`, `forecast_eligible_flag` | Tier A 候选资格和历史质量摘要 |
| 风险校准 | `calibration_level`, `sample_count`, `q80_absolute_log_error`, `risk_basis`, `base_uncertainty_per_kg` | 已发布区间或历史发布路线残差转换后的单位风险基数 |
| 默认决策字段 | `default_reliability_multiplier`, `default_risk_penalty_per_kg`, `eligible_under_default_reliability` | 冻结默认参数下的风险放大和过滤状态 |
| 版本 | `mart_version` | 当前 `p4_procurement_mart_v0.1` |

`later_actual_price` 是事后评估字段。任何模拟当时决策的代码都不得使用它计算候选成本、过滤或排名。

## 16. P4 残差校准：`residual_calibration`

路径：`data/modeling/p4_procurement_mart/residual_calibration.parquet`。30 行，按产品×跨度×实际发布路线分组。

| 字段 | 类型 | 含义 |
|---|---|---|
| `vegetable_id` / `vegetable_name_zh` | int / string | 产品身份 |
| `horizon_days` | int | 7、14 或 28 日 |
| `release_point_source` | string | 冻结模型、最近价格或历史季节基线 |
| `calibration_level` | string | 实际采用的逐级回退层级 |
| `sample_count` | int | 校准样本数；v0.1 单组 333–608 |
| `residual_quantile` | float | 当前 0.8 |
| `q80_absolute_log_error` / `median_absolute_log_error` | float | 发布点价格绝对对数误差分位数 |
| `calibration_target_start` / `calibration_target_end` | date | 校准目标日期范围 |
| `scenario_origin_date` | date | 当前 2022-05-01 |
| `no_lookahead_pass` | boolean | 最大目标日严格早于情景起点 |

该表提供风险排序缓冲，不是概率区间校准结果。

## 17. P4 敏感性明细：`sensitivity_rows`

路径：`artifacts/p4/sensitivity_rows.parquet`。1,080 行，对应 10 个默认产品情景×36 个参数组合×Top 3。

| 字段组 | 字段 | 含义 |
|---|---|---|
| 组合 | `combination_id`, `transport_cost_per_kg_km`, `loss_rate`, `risk_aversion` | 参数网格和稳定组合 ID |
| 情景 | `target_city_id`, `target_city_name_zh`, `vegetable_id`, `vegetable_name_zh`, `horizon_days` | 默认北京、28 日的产品情景 |
| 候选 | `city_id`, `city_name_zh`, `province_name_zh`, `rank` | 当前参数组合的候选来源与名次 |
| 成本 | `unit_landed_cost`, `total_landed_cost` | 当前组合下单位和总到岸成本 |

敏感性行描述参数假设下的排序行为，不能解释为历史真实采购或实现收益。
