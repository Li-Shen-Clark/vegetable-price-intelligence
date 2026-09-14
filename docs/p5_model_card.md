# P5 模型卡：价格冲击传播

## 发布结论

正式状态：`common_shock_only`。15 条冻结边只在预设 final test 上评估一次；发布状态由冻结门槛机械生成。

| 发布门槛 | 实际 | 要求 | 结果 |
|---|---:|---:|---|
| `minimum_products_with_required_edges` | 0 | 5 | 未通过 |
| `positive_final_edge_share` | 0.26666666666666666 | 0.7 | 未通过 |
| `median_final_rmse_improvement` | -0.013867528760551053 | 0.01 | 未通过 |
| `fdr_and_stability_complete` | True | True | 通过 |
| `common_factor_network_reduction` | True | True | 通过 |
| `noncausal_language_contract` | True | True | 通过 |

## Final-test 证据

冻结边 15 条，final RMSE 改善为正 4 条，强边（至少 1%）2 条；正增益占比 26.7%，中位 RMSE 改善 -1.39%。

## 共同冲击诊断

在训练期同一地理候选集合上，原始变化的同时相关 FDR 边为 1481 条；剔除季节与 leave-one-out 共同因子后为 776 条，减少 47.6%。这是同步性诊断，不是方向或因果检验。

## 可用与不可用

本模型可用于历史成本风险的人工复核：识别共同价格冲击、比较城市暴露，并说明为何某些 lead-lag 候选没有获得足够发布证据。它不能证明城市间贸易流，不能作为实时预警，不能自动调价，也不能声称利润改善。

所有价格数据、scorecard、JSON/Parquet artifacts 和浏览器数据只保留本机，不进入 GitHub。
