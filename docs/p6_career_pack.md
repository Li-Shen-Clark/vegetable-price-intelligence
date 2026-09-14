# P6 Career Pack：Pricing / Economics 求职材料

## 使用原则

- 一份简历只选 3–4 条，不要把以下所有 bullet 同时放入。
- 指标必须与 `docs/p6_evidence_matrix.md` 一致；不写 revenue uplift、profit impact、production deployment 或 causal propagation。
- “Built”用于已完成的本地系统；“designed”用于尚未上线的 Pricing Engine 集成契约。
- 面向美国岗位时优先使用英文 bullet；中文版本用于准备口述逻辑，不建议逐字翻译到英文简历。

## Pricing Analyst 版本

### 推荐英文 bullets

- Built an economics-informed pricing intelligence workflow from 8.68M wholesale market records across 117 cities and 30 vegetables, converting noisy quotes into auditable market benchmarks, risk signals, and cost-review inputs.
- Translated partially released 7/14/28-day forecasts into a risk-adjusted landed-cost scenario engine, preserving model-versus-baseline labels and testing sourcing rankings across 36 transport, loss, and risk assumptions.
- Designed a price-spike review policy that achieved 37.69% recall at a validation-frozen 9.99% false-positive rate with 7.18 days of average historical lead time, explicitly routing alerts to human review rather than automatic repricing.
- Defined a governed interface between market intelligence and a pricing engine, separating evidence, fallback status, and margin-review triggers from customer, inventory, contract, and approval rules.

### 中文口述重点

- 强调你不是只做预测，而是把价格信号转成成本基准、毛利复核和候选询价。
- 解释为什么 persistence baseline、风险偏好和运输损耗都是 pricing decision 的组成部分。
- 主动说明数据没有销量和客户维度，所以不估计需求弹性或最优零售价。

## Pricing Data Scientist 版本

### 推荐英文 bullets

- Developed rolling-origin 7/14/28-day price forecasts with strong persistence and seasonal baselines, one-time final evaluation, and slice-level release governance; delivered 6.30% lower WAPE overall while falling back on 10 weak product-horizon groups.
- Built an independent price-spike classifier with validation-only threshold selection, reaching PR-AUC 0.2204 versus 0.0775 for the best simple baseline and enforcing a 10% false-positive-rate action budget.
- Evaluated 2,736 predeclared geographic lead-lag candidates using leave-one-out common factors, product-level BH-FDR, split stability, 250-block bootstrap, and sealed final testing; rejected network release when only 4/15 frozen edges improved out of sample.
- Implemented 152 automated data, leakage, metric, release, scenario, and product-boundary tests across a local Python/Parquet and React analytics system.

### 中文口述重点

- 强调 validation 冻结、final 只使用一次、模型不合格就回退，而不是只讲模型名称。
- P5 的价值在于正确拒绝网络发布，体现 experiment design 和 model risk governance。
- P2 的 6.30% 是相对最佳分组基线的总体改善，不是所有城市和跨度都改善。

## Economics / Data Scientist 版本

### 推荐英文 bullets

- Operationalized economic concepts—spatial price dispersion, expectations, transaction costs, uncertainty, and common shocks—into testable pricing and procurement decision rules using a nine-year non-balanced city panel.
- Separated common market movement from city-specific residuals with a leave-one-out factor; contemporaneous FDR relationships fell 47.60%, demonstrating how omitted common shocks can overstate apparent spatial transmission.
- Framed city lead-lag as incremental predictive information beyond target and common-factor history, applying predeclared geographic choice sets and out-of-sample no-go criteria rather than causal trade-flow claims.
- Built a data-quality and coverage-tier system that retained unmatched and low-quality observations for audit while restricting formal modeling to eligible product-city series.

### 中文口述重点

- 价格离散不自动等于套利机会；还要考虑市场构成、交易成本和供货约束。
- 共同冲击是传播模型的核心竞争解释，而不是模型里的一个普通特征。
- 因果语言需要识别策略；当前项目只支持描述性或预测性证据。

## 30 秒自我介绍

### 中文

我用 117 个城市、30 种蔬菜的九年批发价格搭建了一套 Pricing Intelligence 系统。项目从市场映射和数据质量开始，依次建立历史基准、多周期预测、涨价风险预警、风险调整采购情景和共同冲击分析。最重要的是每层都有强基线和发布门槛：不合格的模型会回退，方向网络在 final test 失败后没有发布。这体现了我如何把经济学问题、数据科学和 Pricing 决策治理连接起来。

### English

I built an economics-informed pricing intelligence system using nine years of wholesale vegetable prices across 117 cities. It connects auditable market measurement, multi-horizon forecasts, spike-risk review, landed-cost scenarios, and common-shock analysis. Each layer has a strong baseline and release gate: weak forecasts fall back, and a city lead-lag network was withheld after failing sealed final testing. The project shows how I connect economic reasoning and data science to governed pricing decisions rather than producing an unqualified model score.

## 2 分钟项目回答

1. **Business problem:** Pricing teams need cost expectations and risk evidence before deciding a customer price, but the source dataset only contains historical wholesale quotes.
2. **Data foundation:** I converted 8.68M raw market records into auditable market and city-day facts, with explicit mapping, quality and coverage tiers.
3. **Modeling:** I evaluated 7/14/28-day forecasts against strong persistence/seasonal baselines and built a separate 14-day spike-risk classifier under a fixed false-alert budget.
4. **Decision layer:** I converted released model or baseline prices into transport-, loss-, reliability- and uncertainty-adjusted landed-cost scenarios.
5. **Economics test:** I examined spatial lead-lag only after removing leave-one-out common movement and controlling multiple testing. The network failed the sealed final release gate, so the product shows common shocks and exposure instead.
6. **Pricing boundary:** These outputs can trigger cost, margin, supply and quote review. A real pricing engine would still need current costs, inventory, customers, contracts, elasticity and approval rules.

## STAR 故事

### Story A：模型没有达到目标，如何处理？

- **Situation:** P2 的总体预测改善只有 6.30%，且区间覆盖和 7 日产品表现不一致。
- **Task:** 在不隐藏失败切片的前提下形成可用产品。
- **Action:** 冻结产品×跨度 release matrix；点预测、区间、point-only 和 baseline fallback 分开发布；P4 原样继承状态。
- **Result:** 形成 1/3/16/10 的透明发布矩阵，下游没有把基线重新命名为模型预测。

### Story B：如何平衡误报与漏报？

- **Situation:** 涨价事件稀少，单看 accuracy 没有意义。
- **Task:** 在可接受的人工复核负担下提高事件发现能力。
- **Action:** 用 PR-AUC 比较模型，并只在 validation 的 FPR≤10% 约束下冻结阈值。
- **Result:** Final recall 37.69%、FPR 9.99%、平均提前 7.18 天；同时披露 precision 21.31%，明确只能人工复核。

### Story C：发现统计显著但不稳定的高级结论怎么办？

- **Situation:** P5 在训练和 validation 得到 15 条显著、稳定且有增益的城市 lead-lag。
- **Task:** 判断是否足以进入产品。
- **Action:** 保持 final test 封存到候选、FDR、增益和 bootstrap 门槛全部冻结，再只评分一次。
- **Result:** Final 只有 4/15 改善为正且中位改善为负，因此网络 no-go，产品降级为共同冲击与城市暴露。

## 常见追问的短答案

### 这是 pricing project，还是 forecasting project？

Forecasting 是其中一层。项目的核心是如何把市场测量、预期、不确定性和成本约束转成可治理的 Pricing 输入，同时保留业务审批和回退。

### 为什么没有做 price elasticity？

数据没有销量、客户、促销或价格实验。没有数量反应就无法识别需求曲线；硬做 elasticity 会制造因果和商业价值幻觉。

### 你如何证明没有过拟合？

使用时间顺序 train/validation/final、强简单基线、validation-only 选择、一次性 final test、切片发布门槛和稳定性检查。结果不通过时不调整门槛。

### 项目与现有 pricing engine 是否重复？

不重复。本项目输出成本和风险证据；pricing engine 再加入库存、客户、合同、margin floor 和审批规则形成可执行报价。

### 如果拿到生产数据，下一步是什么？

先接入新鲜度监控、真实采购/物流/库存和客户合同，再定义可量化的 pricing outcome 与审批实验；不会先增加更复杂的模型。

## 禁止使用的简历措辞

- “optimized retail prices”
- “increased revenue/profit”
- “deployed a real-time pricing engine”
- “identified causal price transmission”
- “recommended optimal suppliers”
- “all forecasts outperformed baseline”
