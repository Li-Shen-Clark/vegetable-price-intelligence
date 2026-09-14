# P4 采购情景引擎运行手册

## 1. 目标与固定边界

本手册从 P0–P3 已冻结产物重建 P4 v0.1。P4 是历史参数化采购情景，不抓取实时价格、不调用地图路线、不连接供应商、不执行采购或自动调价。

固定口径：

- 情景起点：2022-05-01；
- 产品：P2 的 10 种核心蔬菜；
- 跨度：7/14/28 日，默认 28 日；
- 来源：Tier A 产品—城市；目标城市可为全部 117 城；
- 点价格：逐组继承 P2 `release_matrix.json`；
- 风险：P2 已发布区间优先，否则使用起点以前历史发布路线误差 Q80；
- 单位：元/公斤、公斤、公里、元/(公斤·公里)。

所有机器口径以 `config/p4_procurement.yaml` 为准。

## 2. 前置文件

运行前确认下列文件存在：

```text
reference/dim_city.csv
reference/market_mapping.csv
reference/source_city_coordinates.csv
data/gold/fact_city_price.parquet
data/gold/coverage_tiers.parquet
data/modeling/p2_forecast_mart/final_test.parquet
artifacts/p2/final/final_test_predictions.parquet
artifacts/p2/final/release_matrix.json
config/p4_procurement.yaml
```

Python 依赖由项目根目录 `requirements.txt` 管理；前端要求 Node.js ≥22.13。

## 3. 冻结重建顺序

在项目根目录依次运行：

```bash
python3 -m src.procurement.build_city_geo
python3 -m src.procurement.audit_p4_feasibility
python3 -m src.procurement.build_procurement_mart
python3 -m src.procurement.build_default_scenarios
python3 -m src.procurement.run_sensitivity
python3 -m src.procurement.build_procurement_web_data
```

顺序不能交换：可行性审计依赖城市坐标；采购 mart 依赖坐标与 P2 产物；默认场景和敏感性依赖 mart；浏览器数据最后从正式 mart 生成。

## 4. 分步验收

### 4.1 城市坐标与实验契约

```bash
python3 -m unittest tests.test_p4_experiment_contract -v
```

期望：5 项通过；`reference/dim_city_geo.csv` 恰好 117 行，城市 ID 唯一；P2 30 组发布矩阵计数为 1/3/16/10。

### 4.2 采购快照与风险校准

```bash
python3 -m unittest tests.test_p4_procurement_mart -v
```

期望：6 项通过；快照 843 行；残差 30 组；残差最大目标日早于 2022-05-01；未发布区间保持空值。

### 4.3 成本引擎

```bash
python3 -m unittest tests.test_p4_procurement_engine -v
```

期望：7 项通过；包括手算成本、已知距离、数量不改变单位排名、无候选、非法参数和基线披露。

### 4.4 敏感性与浏览器数据

```bash
python3 -m unittest tests.test_p4_sensitivity -v
python3 -m unittest tests.test_p4_procurement_web_data -v
```

期望：5+6 项通过；敏感性 1,080 行；浏览器数据覆盖全部 843 行且哈希匹配。

### 4.5 全项目回归与前端

```bash
python3 -m unittest discover -s tests -v
cd web
npm exec -- oxlint app/procurement/page.tsx
npm run build
npm run dev
```

生产构建应识别 `/`、`/forecast`、`/alerts` 和 `/procurement`。另开终端检查：

```bash
curl -I http://localhost:3000/
curl -I http://localhost:3000/forecast
curl -I http://localhost:3000/alerts
curl -I http://localhost:3000/procurement
curl -I http://localhost:3000/data/procurement/metadata.json
curl -I http://localhost:3000/data/procurement/products/170010.json
```

全部应返回 HTTP 200。全项目 lint 含 P4 之前页面和通用组件的存量问题；P4 验收以采购页定向 lint 和生产构建为准，存量问题不得误记为 P4 新回归。

## 5. 核心结果核对

- `reference/dim_city_geo.csv`：117 行；
- `scenario_snapshot.parquet`：843 行、10 产品、41 唯一来源城市、3 跨度；
- 风险来源：99 行 `released_p90_minus_point`，744 行 `historical_released_route_q80_log_error`；
- 数据可靠性：843 行均为 `origin_price_date_exact`，范围 0.675–1.0；
- `residual_calibration.parquet`：30 行，单组至少 333 条；
- `default_scenarios.json`：10 个北京 28 日情景，每个 1 个本地基准和 3 个外地候选；
- `sensitivity_rows.parquet`：1,080 行；
- `web/public/data/procurement`：1 个 metadata、10 个产品 JSON 和 1 个 manifest。

正式哈希与行数由 `data/modeling/p4_procurement_mart/manifest.json`、`web/public/data/procurement/manifest.json` 和 `artifacts/p4/sensitivity_summary.json` 提供。

## 6. 常见失败与处理

| 症状 | 优先检查 | 处理 |
|---|---|---|
| 城市坐标不是117行 | `dim_city.csv`、源坐标快照、大理特殊规则 | 不做模糊补齐；修正规则后从第一步重建 |
| 发布状态计数改变 | P2 `release_matrix.json` 和预测文件版本 | 停止发布；P4 不允许自行改路线 |
| 残差最大目标日不早于起点 | 残差筛选条件 | 视为前视泄漏，修复后重建全部下游 |
| 未发布区间出现 P10/P90 | mart 发布字段逻辑 | 视为证据越界，禁止页面发布 |
| 页面无产品数据 | `web/public/data/procurement/manifest.json` 与产品 JSON | 重新执行 Web 数据构建，不手改 JSON |
| 当前参数无候选 | 最大距离、最低可靠性与产品覆盖 | 页面显示空状态；不以零成本或低质量来源补齐 |
| 端口无法启动 | 3000/9229 占用或系统权限 | 关闭占用进程或使用允许监听本地端口的终端 |

## 7. 回滚

P4 不覆盖 P0–P3 事实或模型产物。需要回退时，移除 P4 独立配置、`src/procurement`、P4 mart/artifact/docs、`web/public/data/procurement`、`web/app/procurement` 及四页导航中的采购入口即可恢复到 P3 状态。不要删除或改写 `artifacts/p2/final`。
