---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 859136b2f1c50f0401ffc0779368de66_1bf3f4188cef11f1b82d525400287e28
    ReservedCode1: lGLojbwpoosxUJZcrWgeVrJ+hIjGljmr8HmQfhoRGyqkqfVJ//TK+6hhiAFa8KasVdNZSScqSniNKaloL//MM9UmaZ/Q3C47ffi12FExlLAylzUGAC13aGteG95Rdt2LIVc8SR0W2262bA5tBFDqtpRBgYMl7MwWHZOXjZqzV+ZM3DYj4vB6LYajFPM=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 859136b2f1c50f0401ffc0779368de66_1bf3f4188cef11f1b82d525400287e28
    ReservedCode2: lGLojbwpoosxUJZcrWgeVrJ+hIjGljmr8HmQfhoRGyqkqfVJ//TK+6hhiAFa8KasVdNZSScqSniNKaloL//MM9UmaZ/Q3C47ffi12FExlLAylzUGAC13aGteG95Rdt2LIVc8SR0W2262bA5tBFDqtpRBgYMl7MwWHZOXjZqzV+ZM3DYj4vB6LYajFPM=
---

# 策略回测

## 用途
存放量化策略/交易策略的回测代码、回测结果、参数优化记录。

## 推荐文件命名规范
```
策略名称_YYYYMMDD_回测报告.md / .py
```
- 示例：`双均线策略_20260731_回测报告.md`

## 建议内容要素
- 策略逻辑说明
- 回测参数（时间区间、初始资金、手续费率）
- 回测结果（累计收益、年化收益、最大回撤、夏普比率、胜率）
- 参数优化过程
- 实盘可行性评估
## 在线页面（投研工作台 · 策略回测）
工作台左侧「投研研究 → 策略回测」已嵌入分区式管理页（`10-策略回测/bt.html`）：
- 默认 **9 个分区以「九宫格」（3 列）排布**，每个分区展示一种策略；点宫格即可展开编辑（展开态横跨整行），收起后回到九宫格；点「＋ 增加分区」可手动增加，支持上移 / 下移 / 删除 / 折叠；窄屏自动降为 2 列 / 1 列；
- 每个分区的字段：**策略名称**（手动填写）、**策略程序文件**（本机选择文件或按路径 / 链接载入）、**策略说明与使用文档**、**策略回测情况**（回测区间 / 累计与年化收益 / 基准与超额 / 最大回撤 / 夏普 / 卡玛 / 胜率 / 盈亏比 / 换手率 / 交易次数 + 备注）、**策略风险与注意事项**；
- 内容保存在**本机浏览器**（localStorage），支持「导出全部 JSON / 导入 JSON」备份与迁移；
- 单个分区可「导出本策略报告」，或「导出并归档到文档列表」——报告为自包含 HTML，可再打印为 PDF。

*（内容由AI生成，仅供参考）*
