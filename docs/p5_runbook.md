# P5 共同冲击与价格传播实验运行手册

## 1. 目标与固定边界

P5 检验：在先剔除季节性与全国共同价格变化后，某来源城市的历史残差是否能稳定提高目标城市未来残差的预测。正式结果为 `common_shock_only`，因此产品只发布共同冲击与城市暴露，不发布方向网络。

固定口径：

- 产品：P2 冻结的 10 种核心蔬菜；
- 城市：每产品 Tier A，最终 342 条合格产品—城市序列；
- 主频率：连续 3 日箱，滞后 1–4 箱；稳健性为周频 1–2 周；
- 时间：2014-02-02–2019-12-31 train、2020 validation、2021-01-01–2022-06-22 final test；
- 候选：地理规则事前限制，每个目标最多 8 个来源；
- 基线：目标残差和 leave-one-out 共同因子各 1–4 阶滞后；
- 完整模型：基线加来源残差 1–4 阶滞后；
- 统计：产品内 BH-FDR `q=0.05`、训练分窗、250 次 8 箱 moving-block bootstrap；
- 解释：只称预测性 lead-lag，不称因果贸易流、实时信号或自动调价。

全部机器口径以 `config/p5_propagation_experiment.yaml` 为准。

## 2. 前置文件

```text
config/p2_scope.yaml
config/p5_propagation_experiment.yaml
reference/dim_city_geo.csv
data/gold/fact_city_price.parquet
data/gold/coverage_tiers.parquet
```

P0–P4 事实与模型只读。P5 数据、artifacts 与浏览器 JSON 都由 Git 忽略并保留本机。

## 3. 冻结执行顺序

当前 `p5_propagation_v0.1` 的 final test 已消费，不能再次运行。以下顺序用于解释或在一个新的、版本号不同且重新审查的实验中复现；不得删除正式 final artifact 后原版本重跑。

```bash
python3 -m src.propagation.audit_p5_feasibility
python3 -m src.propagation.build_propagation_mart
python3 -m src.propagation.build_propagation_baselines
python3 -m src.propagation.train_directional_models
python3 -m src.propagation.validate_edge_stability
python3 -m src.propagation.evaluate_final_test
python3 -m src.propagation.build_propagation_web_data
```

顺序不可交换：候选先于方向模型冻结，validation 先于稳定性冻结，稳定性边集合先于 final test 冻结。`evaluate_final_test` 检测到已消费配置或既有 release artifact 时会拒绝运行。

## 4. 正式结果核对

- 合格系列：342；事前地理候选边：2,736；
- 可建模候选：991；训练期原始显著：174；FDR 后：51；
- Validation 冻结：15；稳定性通过：15；
- 周频：14 条样本充分，12 条同向；
- Final RMSE 改善为正：4/15；强边：2/15；
- Final 正增益占比：26.67%；中位 RMSE 改善：-1.39%；
- 满足每产品至少 3 条确认边的产品：0；
- 原始同时相关 FDR 边 1,481，公共因子调整后 776，减少 47.60%；
- 发布状态：`common_shock_only`。

详细本地证据位于 `artifacts/p5/`；可提交的方法摘要见 `docs/p5_directional_model_report.md`、`docs/p5_stability_report.md` 和 `docs/p5_model_card.md`。

## 5. 分步测试

```bash
python3 -m unittest tests.test_p5_experiment_contract -v
python3 -m unittest tests.test_p5_propagation_mart -v
python3 -m unittest tests.test_p5_propagation_baselines -v
python3 -m unittest tests.test_p5_directional_models -v
python3 -m unittest tests.test_p5_edge_stability -v
python3 -m unittest tests.test_p5_final_release -v
python3 -m unittest tests.test_p5_propagation_web_data -v
python3 -m unittest tests.test_p5_propagation_page -v
```

全量回归与前端：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/verify_portfolio_bundle.py
cd web
npm exec -- oxlint app/propagation/page.tsx
npm run build
npm run dev
```

本地检查 `/propagation`、`/data/propagation/metadata.json` 与一个产品 JSON 都应返回 HTTP 200。全站 lint 仍含共享 UI 和旧页面的存量规则问题；P5 以新增页面定向 lint、全站生产构建和全量 Python 契约为验收证据。

## 6. 常见失败

| 症状 | 含义 | 处理 |
|---|---|---|
| 候选边超过 35% | 地理事前筛选失效 | 停止，不执行方向模型；修正候选规则并升实验版本 |
| common factor 包含当前城市 | leave-one-out 泄漏 | 重建全部 P5 mart 与下游，不保留旧结果 |
| exact lag 跨越缺失箱 | 时间关系伪造 | 修复 lag join 后升版本重建 |
| final 命令拒绝运行 | 原版本已消费或 artifact 已存在 | 不覆盖；新问题必须建立新实验版本 |
| 页面出现方向边 | 与 `common_shock_only` 决策冲突 | 阻止发布，重建浏览器数据并检查页面 |
| 周频样本不足 | 频率敏感性证据不完整 | 保留缺失标记，不降低预设样本门槛 |

## 7. 回滚

P5 不覆盖 P0–P4。产品需要回退时，移除 `/propagation` 路由和导航入口，并停用本地 `web/public/data/propagation`；不要删除正式 `artifacts/p5/final/release_decision.json`，它是 final test 已消费和降级决策的审计证据。
