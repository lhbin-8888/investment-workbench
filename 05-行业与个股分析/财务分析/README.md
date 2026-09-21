---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 859136b2f1c50f0401ffc0779368de66_196fe1d08cef11f1b82d525400287e28
    ReservedCode1: xFzeMqxPx6KdTO58Ioqedw7igZjU6MRZV8YIhSFsloZJpdOn6WxXczmu7C/QuEXHNpkilKZ6ZcszSYtktWf8TWPburEcX9pOCzWe1y9RAnLAGp7/3EyeEp7wDOP+H48vd1phFqf/9rbOupPENqYwWc7ENZLBUctTCjt68GAW/S7alEtrWqc3dYViChM=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 859136b2f1c50f0401ffc0779368de66_196fe1d08cef11f1b82d525400287e28
    ReservedCode2: xFzeMqxPx6KdTO58Ioqedw7igZjU6MRZV8YIhSFsloZJpdOn6WxXczmu7C/QuEXHNpkilKZ6ZcszSYtktWf8TWPburEcX9pOCzWe1y9RAnLAGp7/3EyeEp7wDOP+H48vd1phFqf/9rbOupPENqYwWc7ENZLBUctTCjt68GAW/S7alEtrWqc3dYViChM=
---

# 财务分析

## 用途
存放上市公司财务报表分析、财务指标拆解、杜邦分析及同行业对比。

## 推荐文件命名规范
```
股票代码_股票简称_YYYYMMDD_财务分析.xlsx / .md
```
- 示例：`600519_贵州茅台_20260731_财务分析.xlsx`

## 建议内容要素
- 三大报表关键数据（利润表/资产负债表/现金流量表）
- 盈利能力指标（ROE/ROA/毛利率/净利率）
- 成长性指标（营收增速/利润增速）
- 偿债能力（资产负债率/流动比率）
- 杜邦分析拆解
- 同行业横向对比
*（内容由AI生成，仅供参考）*

---

## 内嵌工具：个股财务分析

本板块除存放财务分析文档外，还内嵌「个股财务分析」自动工具：

- **入口**：工作台左侧「投研研究 → 财务分析」，以 iframe 嵌入
- **页面位置**：`05-行业与个股分析/财务分析/工具/fa.html`（纯前端单文件，零后端依赖）
- **技术说明**：见 `工具/README.md`
- **命令行备用**：`工具/stock_analyzer.py`（纯 Python 标准库实现，可批量/离线出报告）

## 报告归档

工具页生成报告后，点「导出 PDF」或「上传到文档列表」会把报告登记进本板块下方的文档列表；
另可另存一份自包含 HTML 放入本目录，随同步任务上线实现多设备可见。
