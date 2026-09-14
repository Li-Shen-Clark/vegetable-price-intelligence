# P4 城市与市场坐标审计

本审计只用于决定 P4 的城市距离锚点。旧市场坐标保留在 P0 映射中，但不进入 P4 正式距离计算。

## 汇总

- 正式映射市场：246 个。
- 有市场坐标：200 个；缺失：46 个。
- 距城市锚点超过 50 公里：100 个。
- 距城市锚点超过 100 公里：87 个。
- 中位偏差：49.80 公里；最大偏差：1600.00 公里。
- 结论：legacy 市场坐标不足以支持自动质心或主市场聚合。P4 使用独立城市锚点维度。

状态计数：

- `manual_review`：13
- `missing_market_coordinate`：46
- `severe_city_mismatch`：87
- `wide_city_or_county_market`：22
- `within_25km`：78

## 偏差最大的市场坐标

| 市场 | 正式城市 | 偏差（公里） | 状态 |
|---|---|---:|---|
| 遵义黔北果蔬投资经营有限责任公司 | 遵义市 | 1600.00 | `severe_city_mismatch` |
| 五龙蔬菜批发市场 | 赣州市 | 1571.07 | `severe_city_mismatch` |
| 两湖绿谷农产品交易物流有限公司 | 荆州市 | 1163.76 | `severe_city_mismatch` |
| 海南凤翔蔬菜批发市场 | 海口市 | 1149.75 | `severe_city_mismatch` |
| 两湖绿谷物流股份有限公司 | 荆州市 | 1117.92 | `severe_city_mismatch` |
| 北海宏腾农贸市场经营管理有限公司 | 北海市 | 1088.14 | `severe_city_mismatch` |
| 南宁农产品交易中心有限责任公司 | 南宁市 | 1036.15 | `severe_city_mismatch` |
| 广西新柳邕农产品批发市场有限公司 | 柳州市 | 932.54 | `severe_city_mismatch` |
| 重庆双福 | 重庆市 | 892.91 | `severe_city_mismatch` |
| 桂林万禾市场管理有限责任公司 | 桂林市 | 890.32 | `severe_city_mismatch` |
| 贵阳地利农产品物流园有限公司 | 贵阳市 | 888.12 | `severe_city_mismatch` |
| 兴化市桃源果蔬综合批发市场有限公司 | 泰州市 | 880.24 | `severe_city_mismatch` |
| 桂林五里店果蔬批发市场有限责任公司 | 桂林市 | 868.47 | `severe_city_mismatch` |
| 厦门闽夏农副产品批发市场有限公司 | 厦门市 | 859.22 | `severe_city_mismatch` |
| 厦门夏商农产品集团有限公司中埔蔬菜农副产品批发市场 | 厦门市 | 854.46 | `severe_city_mismatch` |

详细逐市场结果见 `docs/p4_coordinate_audit.csv`。距离为 Haversine 直线距离，不是道路里程。
