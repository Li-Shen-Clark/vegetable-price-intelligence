# Vegetable Price Intelligence

该项目把 2014–2022 年、117 个城市、30 种蔬菜的批发市场日度报价整理为可追溯的市场事实、城市日价格和覆盖 Tier，并在此基础上规划 Price Monitor、概率预测、风险预警、采购情景和价格冲击传播分析。

它与现有 pricing engine 互补。pricing engine 面向当下的报价执行、规则和交易流程；本项目提供历史市场情报、数据质量、预测与风险证据。未来可以把这些输出作为 engine 的决策输入，但它本身不是实时定价执行系统。

从 P5 开始，所有阶段必须先通过统一的 Economics & Pricing Stage Gate：明确决策用户、经济机制、单位与约束、比较基准或识别、不确定性、Pricing 工作流接口和不可声称内容。Gate 见 `docs/economics_pricing_stage_gate.md`，避免只增加模型而丢失经济问题。

当前状态：**P0 数据层、P1 Historical Price Monitor、P2 概率预测、P3 价格风险预警与 P4 采购情景 v0.1 已完成本地验收**。P2 的正式结论是 `partial_release`；P3 为 `alert_release`；P4 为只支持历史参数化演示的 `scenario_release`。四个产品页面均未公开部署；P5–P6 尚未完成。

## 已完成的数据资产

```text
dataSource/rawData/*.csv
        ↓
data/bronze/fact_market_price_raw.parquet
        ↓ 市场映射
data/silver/fact_market_price_mapped.parquet
        ↓ 行级质量
data/silver/fact_market_price_quality.parquet
        ↓ 发布与两级聚合
data/gold/fact_market_price.parquet
data/gold/fact_city_price.parquet
        ↓ 覆盖和质量门槛
data/gold/coverage_tiers.parquet
```

- 市场事实：8,682,381 行，完整保留无效价、范围外城市和质量候选风险。
- 城市日事实：7,358,606 行，以市场日中位数再取城市中位数。
- 覆盖 Tier：3,510 个蔬菜×城市组合，A/B/C 为 919 / 1,814 / 777。
- 正式参考表：30 种蔬菜、117 个城市、269 个原始市场名称。

## P1 Historical Price Monitor

P1 是面向 pricing、采购和商业分析场景的历史情报工作台。它不是实时定价执行系统，提供：

- 30 种蔬菜与 Tier A/B 城市的历史月度价格趋势；
- 所选历史月份的价格、月环比、同期城市排名和来源可靠性 KPI；
- 跨城市中位数、四分位价格带、最高/最低价与省份摘要；
- 1–12 月的跨年历史季节区间；
- good/caution/poor 日数、报告市场数、全期覆盖和 Tier 原因；
- 加载、无数据和数据错误状态，以及常驻的历史截止日说明。

浏览器不会直接加载 7,358,606 行城市日事实。`src/monitor/build_monitor_data.py` 将 Gold 聚合为 285,723 条城市×月份记录，拆成 30 个按需加载的产品文件；完整 Web mart 约 24 MiB，单产品约 0.7–0.9 MiB。

## P2 Probabilistic Price Forecasting

P2 对冻结的 10 种核心蔬菜和 366 条 Tier A 产品—城市序列进行 7/14/28 日历史回测：

- 训练 / validation / final-test 任务分别为 43,533 / 11,882 / 16,217 行；
- 三种基线是最近价格、周度模式和历史季节中位数；最近价格在 validation 的 30 个产品×跨度中赢得 28 个；
- 从 28 个候选中冻结 `hurdle_a10_s0p75`，validation WAPE 相对最佳分组基线改善 6.81%；
- 一次性 final test 的模型 WAPE 为 17.54%，最佳基线为 18.72%，相对改善 6.30%；
- 7 日只有 2/10 个产品通过点预测门槛，14 日为 9/10；总体 80% 区间覆盖率为 70.91%；
- 最终发布矩阵为 1 个 `model_target`、3 个 `model_minimum`、16 个 `point_only_model`、10 个 `baseline_fallback`。

`/forecast` 只展示 T5 发布矩阵允许的能力。区间欠校准的切片只展示 P50，失败切片显示冻结最佳基线；页面固定标注 Historical backtest、数据截止日和“不是当前报价”。

## P3 Price Risk Alert

P3 没有把 P2 点预测直接改名为预警，而是独立定义并评估“未来 14 天显著涨价事件”：

- 10 种核心蔬菜、366 条 Tier A 产品—城市序列，每周一生成历史模拟预警；
- 主事件要求未来 14 日峰值涨幅至少 20%，且不低于起点前历史季节峰值涨幅的 90 分位；同序列 21 天内去重；
- train / validation / final-test 分别为 70,589 / 16,388 / 23,530 行，validation 事件率 5.91%；
- validation 从 6 个逻辑回归候选中冻结 `logistic_r0.0001_pw1` 和行动阈值 0.0966；
- 一次性 final test 有 1,576 个事件，PR-AUC 0.2204，最佳简单基线 0.0775，相对提升 184.29%；
- 冻结阈值下 precision 21.31%、recall 37.69%、FPR 9.99%，平均提前 7.18 天，最强 10% 事件召回 63.19%。

P3 全局状态为 `alert_release`，表示离线排序和固定阈值通过预先门槛，不表示可以自动执行。发出提醒中仍有 78.69% 是误报；`/alerts` 因此只把风险信号作为人工复核触发器，明确展示命中、误报、漏报、局部/区域范围和事后实际结果，不自动报价或调价。

## P4 Procurement Scenario Engine

P4 把 P2 已发布的模型或基线点价格转换为可解释的采购候选比较，而不是重新训练或掩盖 P2 的失败切片：

- 固定 2022-05-01 历史情景，覆盖 10 种核心蔬菜、41 个 Tier A 来源城市和 7/14/28 日，页面默认 28 日；
- 843 行采购快照逐组保持 P2 的 1/3/16/10 发布矩阵；`baseline_fallback` 明确显示“不是模型预测”；
- 只有 P2 已发布区间的 99 行使用 `P90−点价格`，其余 744 行使用情景起点以前的历史发布路线残差 Q80，且不伪装成预测区间；
- 117 个目标城市使用独立、可追溯的城市锚点；距离是 Haversine 直线距离乘 1.25 情景系数，不是公路里程；
- 到岸成本统一为 `(发布点价格 + 运输 + 风险)/(1−损耗率)`，本地基准和外地候选使用同一公式；
- 36 组运输费率、损耗率和风险偏好组合量化 Top 3 与第一名稳定性，共形成 1,080 行明细。

`/procurement` 支持目标城市、产品、跨度、采购量、运费、损耗、最大距离、风险偏好和最低可靠性的即时情景重算。输出是“值得询价的候选来源”，没有供应能力、库存、真实运费或成交承诺，不是采购订单或已实现节省。

## 快速开始

### 代码作品集模式（GitHub 不含数据）

GitHub 基线只保留代码、配置、测试和 Markdown 文档，不上传原始数据、CSV/Parquet、参考映射、模型输出或浏览器 JSON：

```bash
python3 scripts/verify_portfolio_bundle.py
cd web
npm ci
npm run build
```

代码作品集模式用于查看实现、方法、测试与产品设计，并验证网站可以完成生产构建；全新 clone 不包含填充页面所需的数据。要运行有内容的四页本地演示，必须在获授权的本地工作区恢复或重建 `web/public/data`，再执行 `npm run dev`。数据边界与恢复方式见 `docs/data_access_and_reproducibility.md`。

### 完整数据模式

环境依赖见 `requirements.txt`。在项目根目录运行一条命令，从现有原始 CSV 重建 P0 全部 Parquet 并执行数据契约测试：

```bash
python3 src/pipeline/build_p0.py
```

恢复完整授权数据后运行全量只读测试：

```bash
python3 -m unittest discover -s tests -v
```

重建 P1 Web mart 和 3 个可复现数据故事：

```bash
python3 src/monitor/build_monitor_data.py
python3 src/monitor/build_p1_stories.py
```

按冻结顺序重建 P2（完整说明见 `docs/p2_runbook.md`）：

```bash
python3 -m src.forecast.audit_p2_feasibility
python3 -m src.forecast.build_forecast_mart
python3 -m src.forecast.build_baseline_scorecard
python3 -m src.forecast.train_point_models
python3 -m src.forecast.calibrate_intervals
python3 -m src.forecast.evaluate_final_test
python3 -m src.forecast.build_forecast_web_data
```

按冻结顺序重建 P3（完整说明见 `docs/p3_runbook.md`）：

```bash
python3 src/alerts/audit_p3_feasibility.py
python3 src/alerts/build_alert_mart.py
python3 src/alerts/build_alert_baselines.py
python3 src/alerts/train_alert_models.py
python3 src/alerts/evaluate_alert_final_test.py
python3 src/alerts/build_alert_web_data.py
```

按冻结顺序重建 P4（完整说明见 `docs/p4_runbook.md`）：

```bash
python3 -m src.procurement.build_city_geo
python3 -m src.procurement.audit_p4_feasibility
python3 -m src.procurement.build_procurement_mart
python3 -m src.procurement.build_default_scenarios
python3 -m src.procurement.run_sensitivity
python3 -m src.procurement.build_procurement_web_data
```

本地运行 P1/P2/P3/P4 网站（Node.js ≥22.13）：

```bash
cd web
npm install
npm run dev
```

- `http://localhost:3000/`：Historical Price Monitor
- `http://localhost:3000/forecast`：Forecast Decision Lab
- `http://localhost:3000/alerts`：Price Risk Alert Replay
- `http://localhost:3000/procurement`：Procurement Scenario Engine

生产构建检查：

```bash
cd web
npm run build
```

当前完整本地数据工作区共 111 项测试：P4 完成时的 101 项 P0–P4 契约，加上 4 项严格无数据作品集契约和 6 项 Economics/Pricing 网站叙事契约。完整数据测试检查本地 Parquet/JSON 的哈希、行数、主键、时间切分、泄漏边界、事件去重、PR 指标、固定 FPR 阈值、冻结模型复算、发布路线、城市坐标、无前视风险、成本手算、参数敏感性和历史边界；全新 clone 在恢复历史数据前只运行作品集验证、叙事契约和网站构建。

## 关键文档

- `GUIDEBOOK.md`：产品定位、模块规格、评估方法和路线图。
- `P0_执行计划.md`：每一步执行前锁定的范围、口径和验收标准。
- `P1_执行计划.md`：Historical Price Monitor 的范围、页面、数据服务和逐步验收计划。
- `P2_执行计划.md`：概率预测从实验契约到本地产品的任务卡和门槛。
- `docs/p2_final_model_card.md`：一次性最终测试与产品×跨度发布矩阵。
- `docs/p2_runbook.md`：P2 本地重建和验收顺序。
- `docs/p2_interview_guide.md`：面向 pricing / data science 求职的项目讲解与演示路径。
- `P3_执行计划.md`：价格风险预警从事件契约到本地页面的任务卡和门槛。
- `docs/p3_final_model_card.md`：独立事件分类的最终测试、产品切片和发布门槛。
- `docs/p3_runbook.md`：P3 从 Gold 到预警页面的冻结重建顺序。
- `P4_执行计划.md`：采购情景从坐标、发布路线到本地交付的冻结任务卡。
- `docs/p4_runbook.md`：P4 从坐标维度到采购页面的顺序化重建与排错说明。
- `docs/p4_interview_guide.md`：P4 的求职讲解、演示路径和常见追问。
- `docs/p4_delivery_checklist.md`：P4 最终测试、构建、HTTP 响应和证据清单。
- `docs/economics_pricing_stage_gate.md`：P0–P4 回顾及 P5 以后每阶段必过的经济学/Pricing 七问门槛。
- `docs/p5_readiness_checklist.md`：P5 开工结论、传播分析契约、经济学门槛和 GitHub/本地边界。
- `docs/data_access_and_reproducibility.md`：作品集模式、完整数据恢复、Git 排除范围和公开许可门槛。
- `docs/data_dictionary.md`：来源单位、所有核心表字段和业务含义。
- `docs/data_quality_report.md`：七项平台指标、主要风险和下游使用边界。
- `docs/coverage_tier_summary.md`：30 种蔬菜的 Tier A/B/C 城市计数。
- `docs/p1_data_stories.md`：由正式 mart 自动生成的 3 个面试演示故事。

各阶段执行日志包含本地操作记录与证据路径，仅保留在本机，不进入 GitHub；公开仓库中的阶段计划和方法文档足以说明设计、验收与边界。

## 使用边界

最新数据为 2022-06-22，不能用于 2026 年当前报价或采购执行。原始数据没有成交量、规格、包装、道路距离、运费和供应能力；采购模块只能先做明确标注假设的情景分析。Tier A 也只表示适合在本历史窗口内做正式回测，不表示实时可用。

P1–P4 当前均为**本地完成、未公开部署**。P2 已证明 14/28 日部分切片具有样本外改善，但没有通过 8% 总体目标、7 日产品覆盖门槛和总体区间覆盖门槛。P3 独立通过全局离线门槛，但召回仍为 37.69%，且提醒中 78.69% 是误报。P4 对弱预测组保留基线，并用参数化运输、损耗与风险缓冲形成询价候选；它不能声称实时采购建议、真实节省或自动调价。下一阶段按 GUIDEBOOK 进入 P5 价格冲击传播分析。
