# P5 共同冲击与价格传播实验交付清单

> P5 v0.1 已完成。完成实验不等于发布方向网络；正式产品状态是 `common_shock_only`。

## A. 数据与实验治理

- [x] 10 种核心蔬菜、Tier A 城市、3 日/周频和三段连续时间切分已冻结。
- [x] 342 条产品—城市序列通过覆盖门槛。
- [x] 2,736 条候选边由地理规则事前生成，未按价格关系或 final 表现挑选。
- [x] 季节项、P95 冲击阈值和 leave-one-out 共同因子只用允许时期估计。
- [x] exact lag 不跨缺失时间箱。
- [x] final test 在候选、模型、FDR、增益与稳定性门槛冻结后只使用一次。
- [x] `final_test_consumed: true`，正式命令拒绝覆盖或重跑原版本。

## B. 统计证据与发布决定

- [x] 991 条完整样本候选完成 nested distributed-lag OLS。
- [x] 产品内 BH-FDR 将 174 条原始显著关系缩减为 51 条。
- [x] 15 条边同时通过 FDR、正方向与 validation 样本外增益门槛。
- [x] 15 条完成训练分窗与 250 次 moving-block bootstrap，全部通过 60% 稳定率硬门槛。
- [x] 周频敏感性完整披露：14 条可估计，12 条同向，1 条样本不足。
- [x] Final 仅 4/15 RMSE 改善为正、2/15 达 1% 强边；中位改善 -1.39%。
- [x] 网络发布的产品覆盖、70% 正增益和 1% 中位增益门槛均未通过。
- [x] 发布决策由 scorecard 机械复算为 `common_shock_only`，未降低门槛。
- [x] 原始同时相关边经公共因子调整减少 47.60%，支持共同冲击作为必要竞争解释。

## C. Economics & Pricing Gate

| Gate | 结论 | 交付证据 |
|---|---|---|
| G1 决策 | `pass` | 共同压力或高暴露只触发成本、供应和报价人工复核 |
| G2 机制 | `conditional_pass` | 空间套利/信息扩散是候选机制；共同冲击被量化，但无因果识别 |
| G3 单位与约束 | `pass` | CNY/kg、3 日/周频、Tier A、地理候选与有限滞后均版本化 |
| G4 基准/识别 | `pass` | 来源滞后只与目标自身+共同因子基线比较；明确预测非因果 |
| G5 不确定性 | `pass` | FDR、分窗、bootstrap、周频与一次性 final test 完整 |
| G6 Pricing 接口 | `conditional_pass` | 输出只扩大人工复核范围，不生成可执行价格 |
| G7 页面边界 | `pass` | 首屏显示降级状态、历史截止和不可声称内容 |

总 Gate：**`conditional_pass`**。允许发布共同冲击与城市暴露，不允许发布方向传播网络。

## D. 本地产品

- [x] 本地浏览器数据覆盖 10 个产品和 4 个历史窗口。
- [x] 产品 payload 明确 `directional_edges_included: false`，没有来源—目标字段。
- [x] `/propagation` 首屏显示 `common_shock_only` 的中文产品语义。
- [x] 页面提供共同冲击时间线、城市暴露排名、共同因子校正与方向发布门槛双证据链、经济机制、Pricing 接口和识别边界。
- [x] 暴露分数公式透明，并声明不是事件概率。
- [x] 首页、预测、预警和采购页均加入 P5 导航；首页决策链加入冲击暴露。
- [x] 加载、空和错误状态已实现并测试。
- [x] 本地 route HTTP 200，未公开部署。

## E. GitHub 与隐私

- [x] 原始/派生数据、CSV/Parquet、artifacts、浏览器 JSON 和执行日志均由 ignore 规则排除。
- [x] GitHub 只准备代码、非数据配置、测试与方法文档。
- [x] 严格 verifier 检查候选文件与全部 HEAD 历史。
- [x] 本阶段不 push；由用户检查后自行同步。

最终交付状态：**P5 完成；方向网络 `no-go`，共同冲击与城市暴露 `conditional release`。**
