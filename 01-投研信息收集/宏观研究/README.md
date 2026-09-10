---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 859136b2f1c50f0401ffc0779368de66_ebf0b2948cee11f196d8525400f8a581
    ReservedCode1: Hs2HZqBdlZwWG8CAU1Gk1H+0ZXgdO7ESob1bFAeRApvmnJYV5ZyIBwlu/RsnqTvnohI59krsBq8OXhBh6xREeHNxlg02I9DQzuOzMjv05BbWXDTfEQlcUN5qraSnN9cGdf7Ngy5HHQX43wz3AXAC/Zi8u+U/Iyd3kZycrZkT2J56yr040XX/CaxHH0Q=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 859136b2f1c50f0401ffc0779368de66_ebf0b2948cee11f196d8525400f8a581
    ReservedCode2: Hs2HZqBdlZwWG8CAU1Gk1H+0ZXgdO7ESob1bFAeRApvmnJYV5ZyIBwlu/RsnqTvnohI59krsBq8OXhBh6xREeHNxlg02I9DQzuOzMjv05BbWXDTfEQlcUN5qraSnN9cGdf7Ngy5HHQX43wz3AXAC/Zi8u+U/Iyd3kZycrZkT2J56yr040XX/CaxHH0Q=
---

# 宏观研究

## 用途
存放宏观经济数据跟踪、GDP/CPI/PMI 等核心指标分析、货币政策与财政政策研究等内容。

## 工作台页面结构（左侧导航 → 投研研究 → 宏观研究）
- **上半页**：全球资产近一周波动曲线（国际黄金、布伦特原油、美债 10 年期/30 年期收益率、人民币兑美元汇率）
- **下半页**：中国宏观政策信息（货币政策 / 财政政策 / 产业政策 / 内需消费，按时间倒序）

### 数据来源与刷新
| 品种 | 来源 |
|------|------|
| COMEX 黄金 | 新浪财经 · 外盘期货日线 |
| 布伦特原油 | 新浪财经 · 外盘期货日线 |
| 美债 10Y / 30Y | FRED（DGS10 / DGS30，公布较市场滞后 1—2 个交易日） |
| 人民币汇率 USD/CNY | Frankfurter（ECB 参考汇率）；数值上行＝人民币贬值 |

刷新命令（会同时更新 `data/macro-weekly.json` 与 index.html 内的离线快照）：
```
python tools/refresh_macro.py
```
政策条目为人工维护，直接在 `tools/refresh_macro.py` 顶部的 `POLICIES` 列表中增删改后重跑上述命令即可。

## 推荐文件命名规范
```
YYYYMMDD_主题_来源.md
```
- 示例：`20260731_三季度GDP预测_中金.md`

## 建议子分类
- 经济数据（月度/季度主要指标跟踪）
- 货币政策（央行操作、利率、准备金率等）
- 国际经济（海外宏观动态）
*（内容由AI生成，仅供参考）*
