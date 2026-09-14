# P2 本地重建与验收手册

## 1. 环境与边界

在项目根目录运行 Python 步骤。依赖由 `requirements.txt` 固定；P2 点模型只使用 NumPy、Pandas 和 PyArrow，没有运行时依赖 LightGBM、CatBoost 或 scikit-learn。

数据截至 2022-06-22。所有预测页面和报告都是历史回测，不是当前行情、实时报价或自动定价建议。

## 2. 重建顺序

### T0：可行性审计

```bash
python3 -m src.forecast.audit_p2_feasibility
```

输出：

- `docs/p2_feasibility_audit.json`
- `docs/p2_feasibility_audit.md`

预期：10 种蔬菜、366 条 Tier A 序列、60/60 可评估性检查通过。

### T1：防泄漏建模 mart

```bash
python3 -m src.forecast.build_forecast_mart
```

输出：

- `data/modeling/p2_forecast_mart/train.parquet`：43,533 行
- `data/modeling/p2_forecast_mart/validation.parquet`：11,882 行
- `data/modeling/p2_forecast_mart/final_test.parquet`：16,217 行
- `data/modeling/p2_forecast_mart/manifest.json`

每行是一个产品—城市—预测起点—跨度任务。目标日必须真实观测，起点最多使用前 1 日价格。

### T2：Validation 基线

```bash
python3 -m src.forecast.build_baseline_scorecard
```

输出：

- `artifacts/p2/baselines/validation_predictions.parquet`
- `artifacts/p2/baselines/validation_scorecard.json`
- `docs/p2_baseline_report.md`

该步骤只读取 validation，不打开 final test。

### T3：点模型选择与冻结

```bash
python3 -m src.forecast.train_point_models
```

输出：

- `artifacts/p2/models/validation_candidate_predictions.parquet`
- `artifacts/p2/models/candidate_scorecard.json`
- `artifacts/p2/models/frozen_point_model.json`
- `docs/p2_point_model_report.md`

预期冻结模型为 `hurdle_a10_s0p75`。如果输入或配置版本变化导致选择不同模型，必须作为新实验审阅，不能静默覆盖作品集结论。

### T4：区间校准

```bash
python3 -m src.forecast.calibrate_intervals
```

输出：

- `artifacts/p2/probability/validation_probability_predictions.parquet`
- `artifacts/p2/probability/calibration_scorecard.json`
- `artifacts/p2/probability/frozen_interval_calibrator.json`
- `docs/p2_probability_report.md`

预期宽度系数为 0.8，2020 后四个月覆盖率约 82.25%。

### T5：一次性最终测试

```bash
python3 -m src.forecast.evaluate_final_test
```

输出：

- `artifacts/p2/final/final_test_predictions.parquet`
- `artifacts/p2/final/final_scorecard.json`
- `artifacts/p2/final/release_matrix.json`
- `docs/p2_final_model_card.md`

这一阶段已经完成并打开了 2021–2022 final test。不得根据其结果修改当前 v0.1 模型或区间后再次把同一数据称为“最终测试”。若开发 v0.2，应预先定义新验证方案，例如 nested rolling validation、缩短开发窗口并保留新 holdout，或获得更新数据。

### T6：浏览器数据

```bash
python3 -m src.forecast.build_forecast_web_data
```

输出：

- `web/public/data/forecast/metadata.json`
- `web/public/data/forecast/manifest.json`
- `web/public/data/forecast/products/*.json`

预期最后回测起点为 2022-05-01，10 个产品文件，共 315 条当时可评分序列和 843 个任务。

## 3. 自动验收

运行全部 P0、P1、P2 测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

前端检查：

```bash
cd web
npm exec oxlint -- app/forecast/page.tsx
npm exec tsc -- --noEmit
npm run build
```

本地预览：

```bash
cd web
npm run dev
```

访问：

- `http://localhost:3000/`：Historical Price Monitor
- `http://localhost:3000/forecast`：Forecast Decision Lab

## 4. 关键配置与产物关系

```text
config/p2_experiment.yaml
        ↓
config/p2_features.yaml → forecast mart
        ↓
validation baselines
        ↓
config/p2_models.yaml → frozen point model
        ↓
config/p2_probability.yaml → frozen interval calibrator
        ↓
one-time final test → release matrix
        ↓
forecast Web JSON → /forecast
```

正式数字的优先级：

1. `artifacts/p2/final/final_scorecard.json`
2. `artifacts/p2/final/release_matrix.json`
3. `docs/p2_final_model_card.md`

`baselines/v0_diagnostic.json` 是旧映射和全历史诊断，不能用于替代正式结果。

## 5. 常见问题

### PyArrow 输出 CPU cache 警告

受限 macOS 环境可能无法读取 CPU cache 信息。只要程序退出码为 0、manifest 哈希和自动测试通过，该警告不影响数据断言。

### 全站 lint 报脚手架错误

`components/ui/*` 和既有 P1 页面存在脚手架规则告警。P2 forecast 页面可以单独 lint；TypeScript 与生产构建是当前完整站点的阻断检查。不要为清理 P2 以外的生成组件而扩大改动范围。

### 为什么没有给所有预测显示区间

最终测试总体覆盖率只有 70.91%。发布矩阵只允许 4 个产品×跨度展示区间；16 个只展示点预测，10 个回退基线。前端隐藏失败区间是模型治理行为，不是数据缺失。

### 为什么不能重新调宽区间

因为 final test 已经打开。根据测试结果调整再对同一测试集报告，会把测试集变成验证集并夸大可信度。

