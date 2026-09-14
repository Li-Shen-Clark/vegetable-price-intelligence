# P3 价格风险预警本地重建说明

## 范围与前提

P3 使用 P0 Gold 城市日价格和 Tier A 产品—城市序列，产出 2014–2022 历史事件标签、概率预警离线评估和 `/alerts` 历史回放页。它不抓取实时行情，不自动报价或调价。

在项目根目录、Python 依赖安装完成后，必须按下列顺序运行。顺序不可互换，因为事件、模型和行动阈值逐步冻结。

## 重建顺序

```bash
python3 src/alerts/audit_p3_feasibility.py
python3 src/alerts/build_alert_mart.py
python3 src/alerts/build_alert_baselines.py
python3 src/alerts/train_alert_models.py
python3 src/alerts/evaluate_alert_final_test.py
python3 src/alerts/build_alert_web_data.py
python3 -m unittest discover -s tests -v
```

对应产物：

1. `docs/p3_feasibility_audit.*`：周度起点、未来观测和原始涨价率。
2. `data/modeling/p3_alert_mart/`：train、validation、final_test 标签与特征。
3. `artifacts/p3/baselines/`：三种简单基线、PR 曲线和 validation 记分牌。
4. `artifacts/p3/models/`：6 个候选、冻结逻辑回归、validation 行动阈值。
5. `artifacts/p3/final/`：一次性最终测试、发布门槛、错误案例和模型卡证据。
6. `web/public/data/alerts/`：浏览器 metadata、manifest 和 10 个按产品加载的数据文件。

## 网站

Node.js ≥22.13：

```bash
cd web
npm install
npm run build
npm run dev
```

打开 `http://localhost:3000/alerts`。页面必须同时满足：

- 顶部标记 Historical replay 与数据截止 2022-06-22；
- 默认案例能解析到历史真阳性；
- 产品、城市、预警起点选择可用；
- 风险概率、冻结阈值、实际事件和行动建议不混为一谈；
- “触发复核”文案不声称自动调价。

## 冻结与失败处理

- `config/p3_alert_experiment.yaml` 冻结主事件和发布门槛。
- `artifacts/p3/models/frozen_alert_model.json` 冻结模型、预处理和 validation 阈值。
- `evaluate_alert_final_test.py` 不允许在 final_test 上重新拟合或重新选阈值。
- 若重建后哈希或指标变化，先检查 Gold、配置和依赖版本；不要手工修改 JSON。
- 若最终状态变为 `research_only` 或 `no_signal`，页面必须按 `release_decision.json` 降级，不得保留可执行式提醒。

## 当前冻结结果

- final-test PR-AUC 0.2204；最佳基线 0.0775。
- threshold 0.0966；precision 21.31%、recall 37.69%、FPR 9.99%。
- release status：`alert_release`，仅授权历史回放和人工复核触发设计。
