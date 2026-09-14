# 省份冲突审计方法

版本：`province_conflicts_v0.2`  
审计日期：2026-09-11  
输入：`data/silver/fact_market_price_mapped.parquet`

## 1. 目的

本审计用于区分两个不同概念：原始来源如何报送省份，以及市场在正式地理映射中属于哪个省份。冲突本身不等于数据错误，也不能成为覆盖原始字段的理由。

## 2. 冲突定义

只对 `mapping_status = mapped_existing_city` 的记录检查：

```text
raw_province != market_province
```

`unmapped_new_city` 没有正式省份，不纳入本审计。汇总粒度为 `raw_market_name × raw_province × market_province`。

## 3. 输出字段

`docs/province_conflicts.csv` 每行保存市场 ID、原始市场名、原始省份、正式城市和省份、冲突记录数、市场总记录数、两个占比、商品数、日期范围、裁决、理由、证据和审核元数据。

裁决枚举：

- `reporting_scope_difference`：报送单位与地理省份描述的是不同维度，二者均保留。
- `source_province_error`：有证据证明来源省份标签错误；本版没有此类结论。
- `mapping_review_required`：正式映射自身存在明显矛盾，需要在下一版本修订。
- `unresolved`：证据不足；本版没有此类项目。

## 4. v0.2 当前结果

Silver 共 8,682,381 条记录，冲突 107,948 条，占 1.2433%，涉及 6 个市场组合：

- 107,948 条、6 个组合：原始标签为“新疆生产建设兵团”，正式地理省份为“新疆维吾尔自治区”。商务部页面会把兵团作为独立报送口径，故裁决为 `reporting_scope_difference`。
- `mapping_review_required = 0`，`source_province_error = 0`，`unresolved = 0`。

v0.1 审计曾包含 193,023 条冲突。其中特有的 85,075 条来自 `mk54` 和 `mk173` 的旧映射省份错误，已在 `market_mapping v0.2` 更正；旧清单保存在 `docs/province_conflicts_v0.1.csv`。

## 5. 使用规则

1. 不覆盖 `raw_province`，不删除冲突记录。
2. 分析地理归属时使用正式城市/省份；分析报送体系时使用原始省份。
3. `reporting_scope_difference` 可继续进入城市级分析，但报告中要说明兵团口径。
4. v0.2 当前没有 `mapping_review_required`；若未来出现，相关记录在更正前不得用于依赖正式省份的分组。
5. 映射修订必须升级版本、记录差异并重建 Silver，不能在下游临时替换。

## 6. 复现

```bash
python3 src/quality/audit_province_conflicts.py \
  --silver data/silver/fact_market_price_mapped.parquet \
  --output-json /tmp/province_conflicts.json
```

脚本输出可由表格构建流程生成 `docs/province_conflicts.csv`。审计时间作为版本元数据固定，因此相同输入和代码会生成相同内容。
