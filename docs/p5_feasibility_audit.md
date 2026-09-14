# P5-T0 可行性审计

## 结论

状态：`pass`。本审计只放行传播 mart、公共因子和基线开发；尚未估计、选择或展示任何方向边。

## 产品级支持

| 产品 | Tier A | P5 可用城市 | 候选边 | 完整对占比 | Train/Validation/Final 正向冲击 |
|---|---:|---:|---:|---:|---:|
| 大白菜 | 40 | 37 | 296 | 22.2% | 1084/204/302 |
| 圆白菜 | 36 | 32 | 256 | 25.8% | 963/171/283 |
| 黄瓜 | 41 | 39 | 312 | 21.1% | 1158/229/300 |
| 西红柿 | 44 | 41 | 328 | 20.0% | 1218/274/345 |
| 土豆 | 30 | 29 | 232 | 28.6% | 844/171/276 |
| 青椒 | 38 | 33 | 264 | 25.0% | 997/224/340 |
| 白萝卜 | 33 | 32 | 256 | 25.8% | 922/178/236 |
| 芹菜 | 40 | 38 | 304 | 21.6% | 1137/226/311 |
| 茄子 | 40 | 37 | 296 | 22.2% | 1092/228/296 |
| 洋葱 | 24 | 24 | 192 | 34.8% | 709/143/185 |

## 硬检查

- `ten_core_products_present`：pass
- `minimum_eligible_cities`：pass
- `candidate_density_capped`：pass
- `candidate_sources_bounded`：pass
- `train_shock_support`：pass
- `validation_shock_support`：pass
- `final_test_support_only`：pass
- `no_directional_models_fitted`：pass
- `final_test_not_used_for_selection`：pass

## Economics & Pricing Gate

- G1：输出只触发成本、供应和报价人工复核。
- G2：共同冲击是空间套利/信息扩散的竞争解释，必须先剔除。
- G3：产品、城市、频率、候选边和滞后均已事前限制。
- G4：自身滞后是最低基线；当前没有因果识别。
- G5：FDR、重采样、窗口稳定性与样本外增益仍是后续硬门槛。
- G6：只作为 Pricing Engine 的上游风险范围输入。
- G7：数据截止 2022-06-22；无流量、天气、产量、库存和真实运输网络。

Gate：`conditional_pass_to_mart`。若后续没有稳定样本外边，必须降级为 `common_shock_only`。
