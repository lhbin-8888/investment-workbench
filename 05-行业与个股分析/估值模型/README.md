---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 859136b2f1c50f0401ffc0779368de66_1a9ddd9c8cef11f1b82d525400287e28
    ReservedCode1: 0Voo7h3TI+oB9OiHVmuEDOMNvAlfXz8tfkgbfyGPt213pnoIq2k7tsOb1aoFbGYT1z01X1VNBufDjkRFNLTJnThdJxnAYX8G0zgz4x7gfVHF04yVIfbDdrDUA5ye9plDgiUjpTPiiMlRGdo/eNiY7aoi7/duUOiNT+N4HF9g55VExkFhQIm0HKTLUQs=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 859136b2f1c50f0401ffc0779368de66_1a9ddd9c8cef11f1b82d525400287e28
    ReservedCode2: 0Voo7h3TI+oB9OiHVmuEDOMNvAlfXz8tfkgbfyGPt213pnoIq2k7tsOb1aoFbGYT1z01X1VNBufDjkRFNLTJnThdJxnAYX8G0zgz4x7gfVHF04yVIfbDdrDUA5ye9plDgiUjpTPiiMlRGdo/eNiY7aoi7/duUOiNT+N4HF9g55VExkFhQIm0HKTLUQs=
---

# 估值模型

## 用途
存放公司估值模型文件，包括 DCF、PE/PB 相对估值、DDM 等各类估值方法。

## 推荐文件命名规范
```
股票代码_股票简称_估值模型_YYYYMMDD.xlsx
```
- 示例：`600519_贵州茅台_估值模型_20260731.xlsx`

## 建议内容要素
- DCF 模型（自由现金流预测、WACC、终值）
- 相对估值（PE/PB/PS/EV/EBITDA 与可比公司对比）
- 敏感性分析
- 情景分析（乐观/中性/悲观）
- 安全边际评估
*（内容由AI生成，仅供参考）*

---

## 内嵌工具：个股估值模型

本板块除存放估值文档外，还内嵌「个股估值模型」自动工具：

- **入口**：工作台左侧「投研研究 → 估值模型」，以 iframe 嵌入
- **页面位置**：`05-行业与个股分析/估值模型/工具/vm.html`（纯前端单文件，零后端依赖）
- **技术说明**：见 `工具/README.md`
- **估值框架**：判类型（6 类）→ 选主尺（DCF/PE/PEG/PS/PB）→ 两把尺子交叉验证 → 内在价值区间与安全边际
- **命令行备用**：`工具/valuation_engine.py`（与前端算法一致的 Python 参考实现）
