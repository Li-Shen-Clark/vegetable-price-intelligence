# P7 GitHub Pages Delivery Checklist

> 验收日期：2026-09-14  
> 正式地址：<https://li-shen-clark.github.io/vegetable-price-intelligence/>  
> 发布提交：`8bafe96`（首个线上版本）

## 1. 招聘内容

- [x] 英文首屏说明核心问题：把批发市场信号转化为受治理的 Pricing 决策支持。
- [x] 首屏说明个人贡献：经济学问题设计、数据工程、模型评估、发布治理、Pricing handoff 与产品交付。
- [x] 展示 8.68M 市场记录、117 城、30 种蔬菜和 177 项测试。
- [x] P0–P5 形成连续决策链，而不是模型功能列表。
- [x] P2 `partial_release`、P3 `alert_release`、P4 `scenario_release` 与 P5 network `no-go` 均被显式保留。
- [x] 明确本项目是 Pricing Engine 的上游 intelligence layer，不是自动定价引擎。
- [x] 公开页提供 GitHub、Case Study、evidence matrix、integration contract 与本清单入口。

## 2. Economics & Pricing Gate

- [x] G1：招聘方可快速识别项目支持成本、风险、询价和报价复核的决策用途。
- [x] G2：价格离散、预期、不确定性、交易成本、共同冲击和识别进入产品逻辑。
- [x] G3：保留 CNY/kg、7/14/28 日、历史截止和选择集约束。
- [x] G4：公开页保留强基线、固定误报预算、参数化反事实和非因果边界。
- [x] G5：失败切片、误报、敏感性和 no-go 是主要结果，而非隐藏限制。
- [x] G6：只向 Pricing 工作流提供 evidence/review inputs，不批准价格、订单或供应商。
- [x] G7：明确 2022-06-22 截止、无实时系统、无商业收益、无最优零售价与无因果传播结论。

## 3. 发布安全

- [x] GitHub 仓库不跟踪原始数据、CSV/Parquet、浏览器 mart、artifacts、模型产物或执行日志。
- [x] Pages workflow 只上传 `portfolio-site/`，不上传仓库整体。
- [x] 静态包仅含 HTML、CSS、PNG、robots、sitemap 与 `.nojekyll`。
- [x] 静态包 verifier 检查扩展名、符号链接、文件大小、本机绝对路径、数据引用和活动运行时。
- [x] 页面不含 JavaScript、fetch、表单、iframe、localhost 或数据文件请求。
- [x] workflow 使用最小权限：默认 `contents: read`，仅 deploy job 使用 `pages: write` 与 `id-token: write`。

## 4. 自动与本地验收

- [x] 完整本地测试：177/177。
- [x] Code-only 测试：39/39。
- [x] Web lint：0 error。
- [x] Web production build：6 个路由构建成功。
- [x] Pages bundle verifier：6 个文件、1,969,044 bytes，通过。
- [x] Portfolio bundle verifier：无数据和执行日志，必需文件齐全。
- [x] 本地静态预览：首页、CSS、OG 与 sitemap 均返回 HTTP 200。

## 5. GitHub 与线上验收

- [x] 仓库按用户明确授权从 Private 改为 Public。
- [x] Pages source 配置为 GitHub Actions，默认域名强制 HTTPS。
- [x] Actions run `34894187554` 重跑后状态为 Success：verify 8 秒、deploy 11 秒。
- [x] 正式首页返回 HTTP 200，`content-type: text/html; charset=utf-8`。
- [x] `styles.css`、`og.png`、`sitemap.xml` 和 `robots.txt` 均返回 HTTP 200。
- [x] 正式 HTML 的 title、description、viewport、canonical、Open Graph 与 Twitter metadata 指向最终 github.io 地址。
- [x] 线上页面仍显示历史截止、无自动定价和无数据公开边界。

## 6. 最终结论

P7 Gate：`pass`。

这个 `pass` 只表示公开招聘页面、发布安全与线上可访问性达到门槛。它不把 P2 的部分发布、P3 的误报负担、P4 的参数化情景或 P5 的网络 no-go 提升成更强的模型与商业结论。

仍可选择增强但不阻塞 P7 的内容：60–90 秒演示视频、个人简历/LinkedIn/联系入口、自定义域名，以及完全脱敏的交互 walkthrough。添加任何个人信息或新公开数据前需重新执行发布边界审查。
