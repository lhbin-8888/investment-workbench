# -*- coding: utf-8 -*-
"""生成「板块筛选逻辑与标准说明书」Word 版（含 2 张示意图）"""
import datetime
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

CN_FONT = '微软雅黑'
CODE_FONT = 'Consolas'
FIG1 = r'D:\投研工作台\quant\figures\diagram_longtou.png'
FIG2 = r'D:\投研工作台\quant\figures\flow_dingpan.png'
OUT = r'D:\投研工作台\quant\板块筛选逻辑与标准说明书.docx'

doc = Document()

# ---- 页面与基础样式 ----
for sec in doc.sections:
    sec.left_margin = Cm(2.2); sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.0); sec.bottom_margin = Cm(2.0)

style = doc.styles['Normal']
style.font.name = 'Calibri'
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn('w:eastAsia'), CN_FONT)

def set_cn(run, size=10.5, bold=False, color=None, font=CN_FONT):
    run.font.name = 'Calibri'
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn('w:eastAsia'), font)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run

def shade_para(p, color='F2F2F2'):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:fill'), color)
    pPr.append(shd)

def shade_cell(cell, color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:fill'), color)
    tcPr.append(shd)

def h1(text):
    p = doc.add_paragraph()
    set_cn(p.add_run(text), size=16, bold=True, color='1F3864')
    p.space_after = Pt(4)

def h2(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    set_cn(p.add_run(text), size=13, bold=True, color='C55A11')
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr'); btm = OxmlElement('w:bottom')
    btm.set(qn('w:val'), 'single'); btm.set(qn('w:sz'), '6')
    btm.set(qn('w:color'), 'C55A11'); pBdr.append(btm); pPr.append(pBdr)

def body(text, bold=False, color=None, size=10.5):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    set_cn(p.add_run(text), size=size, bold=bold, color=color)
    return p

def note(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    set_cn(p.add_run(text), size=9, color='7F6000')
    shade_para(p, 'FFF2CC')

def code(text):
    for ln in text.split('\n'):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        r = p.add_run(ln)
        r.font.name = CODE_FONT
        r.font.size = Pt(9)
        r._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        shade_para(p, 'F2F2F2')
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def kv_table(rows):
    t = doc.add_table(rows=0, cols=2)
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for label, val in rows:
        rc = t.add_row().cells
        rc[0].width = Cm(3.4); rc[1].width = Cm(13.0)
        p0 = rc[0].paragraphs[0]
        set_cn(p0.add_run(label), size=10, bold=True, color='1F3864')
        shade_cell(rc[0], 'F7F9FC')
        p1 = rc[1].paragraphs[0]
        set_cn(p1.add_run(val), size=10)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def bullets(items):
    for it in items:
        p = doc.add_paragraph(style='List Bullet')
        set_cn(p.add_run(it), size=10)

def pic(path, width_in=6.2, caption=None):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(path, width=Inches(width_in))
    if caption:
        c = doc.add_paragraph(); c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_cn(c.add_run(caption), size=9, color='555555')

# ===================== 封面 =====================
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(24)
set_cn(p.add_run('板块筛选逻辑与标准说明书'), size=22, bold=True, color='1F3864')
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
set_cn(p.add_run('通达信纯本地方案 · 6 大智能板块选股体系'), size=11, color='555555')
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
set_cn(p.add_run('生成日期：%s ｜ 适用系统：D:\\投研工作台\\quant\\ ｜ 通达信目录：D:\\TDX'
                 % datetime.date.today().strftime('%Y-%m-%d')), size=9, color='888888')

# ---- 总览 ----
h2('一、六板块总览')
overview = [
    ['板块', '通达信文件', '周期/视角', '定位', '刷新方式'],
    ['AI自选', 'AIZX.blk', '日线·盘中', '当日/短波段强势主池', '盘中守护每5分钟'],
    ['AI周线', 'AIWEEK.blk', '周线·中线', '中线趋势龙主升浪', '每周五收盘后'],
    ['热点板块池', 'RDKB.blk', '板块指数', '当天最强板块（选股上游）', '每日16:30｜盘中守护'],
    ['热点股池', 'RDGP.blk', '日线·盘中', '热点板块内前3强势股', '每日16:30｜盘中守护'],
    ['龙头启动', 'LTQD.blk', '日线·盘中', '回踩20日线后放量突破前高', '条件选股/Ctrl+T'],
    ['盯盘信号', 'DPXH.blk', '1分钟·盘中', '实时量价异动预警落盘', '条件预警盘中触发'],
]
t = doc.add_table(rows=len(overview), cols=5)
t.style = 'Table Grid'
for j, v in enumerate(overview[0]):
    c = t.rows[0].cells[j]
    set_cn(c.paragraphs[0].add_run(v), size=9, bold=True, color='FFFFFF')
    shade_cell(c, '1F3864')
for i, row in enumerate(overview[1:], 1):
    for j, v in enumerate(row):
        set_cn(t.rows[i].cells[j].paragraphs[0].add_run(v), size=9)
body('')
body('六个板块构成一条完整链路：热点板块池(RDKB) 与 AI自选(AIZX) 是两条独立选股主线，'
     '热点股池(RDGP) 由 RDKB 派生，盯盘信号(DPXH) 是盘中实时预警落盘，'
     '龙头启动(LTQD) 是回踩20日线后放量突破前高的启动信号，'
     'AI周线(AIWEEK) 提供中线视角。所有阈值均取自本机已落地脚本，改脚本即改标准。')

doc.add_page_break()

# ===================== 1. AI自选 =====================
h2('二、AI自选（日线 · AIZX）')
kv_table([
    ('定位', '日线视角下的强势股筛选，盘中盯盘主池。核心方法论「AI自选标准」：均线多头 + 涨幅区间 + 量比区间 + 排除项。'),
    ('数据来源', '本地日线 D:\\TDX\\vipdoc\\{sh,sz}\\lday 算均线/涨幅/量比；广义AI自选主系统另接东财实时含换手率。'),
    ('筛选逻辑', '四路独立选股合并去重：①技术突破 ②主线龙头 ③基本面 ④打板情绪；加 --split 生成4个分路明细板块。'),
    ('入选标准·阈值',
     '均线多头：收盘价 > MA5 > MA10 > MA20 且 MA5 向上。｜涨幅：0.5%~9.5%（下限过滤没动的票，上限避开近涨停）。'
     '｜量比：1.2~3.0（放量但不失控）。｜换手率（放宽项）：3%~25%（仅AIZX技术/打板路用，本地RDGP未实现）。'
     '四路关键阈值：技术突破 涨幅2~9.5%、量比≥1.5、换手3~25%、主力净流入≥5000万；主线龙头 流通市值≥50亿、'
     '主力净流入>0；基本面 PE≤60、净流入≥3000万、涨幅-1~7%；打板情绪 涨幅≥4%、量比≥2、换手≥5%。'),
    ('排除项', 'ST/*ST；停牌（末笔量=0）；本地日线根数<60；下跌/平盘（涨幅≤0.1%）；涨幅>9.5%；北交所43x/83x/87x/92x。'),
    ('输出板块', 'AI自选 AIZX.blk（四路合并，≤30只）；明细 AITECH/AIZXL/AIZXFB/AIZXDB（--split）。'),
    ('刷新方式', '盘中守护 run_picker.py --loop 交易日9:30-15:00每5分钟一轮；计划任务 TDX_AutoPick 每交易日08:55拉起。前提：通达信完成盘后数据下载。'),
])

# ===================== 2. AI周线 =====================
h2('三、AI周线（周线 · AIWEEK）')
kv_table([
    ('定位', '周线视角中线波段选股，依据「MA3/MA5/MA10 多头 + 3周刚上穿5周 + 3周已上穿20周 + 一阳穿三线」早期突破信号，抓刚启动的趋势票。与日线体系独立。'),
    ('数据来源', '纯本地、零网络：本地日线按"周五"聚合为周线（周线日期取当周周五，与通达信口径一致），再算周线均线。'),
    ('筛选逻辑', '周线均线：3周=极短趋势、5周=短趋势、10周=波段、20周=中期趋势。'),
    ('入选标准·阈值',
     '以下全部满足才入选：① 多头排列：MA3 > MA5 > MA10。'
     '② 3周均线刚上穿5周均线（本周金叉）。③ 3周均线已上穿20周均线（中期趋势转多）。'
     '④ 最近一根周K线一阳穿三线：当周收阳、收盘站上MA3/MA5/MA10、当周最低价低于三线最低者(MA10)（容差1%）。'
     '⑤ 剔除最近3日连续下跌；⑥ 剔除最近10日日线连跌累计>8% 或 较近期高点回撤>12%；'
     '⑦ 剔除近13周累计涨幅>50%（高位过度拉升）；⑧ 剔除ST/*ST、北交所、亏损股（净利润<0，无数据保守保留）。'),
    ('量能（加分非门槛）',
     '当周量≥前10周均量×1.5 打"放量"标签并加分；score=100+周涨幅×100+(量比−1)×20+站上3周线幅度×50+站上20周线幅度×30。'),
    ('排除项', '最近3日连跌、最近10日日线连跌>8%或回撤>12%、近13周涨幅>50%、ST/*ST、北交所、亏损股；数据不足60周剔除。'),
    ('输出板块', 'AI周线 AIWEEK.blk（全市场扫描，默认≤80只）。'),
    ('刷新方式', '默认每日盘后15:00后触发（脚本内置校验）；计划任务"通达信周线选股"每天15:30运行（需本机双击 setup_weekly_task.bat 注册一次）。手动：weekly_picker.py --force。'),
])

# ===================== 3. 热点板块池 =====================
h2('四、热点板块池（板块指数 · RDKB）')
kv_table([
    ('定位', '当天/近期最强板块集合，是热点股池(RDGP)的上游输入。与 .402 板块指数页口径对齐。'),
    ('数据来源', '本地板块指数日线 D:\\TDX\\vipdoc\\sh\\lday（881/880板块指数代码）；配置 tdxzs.cfg / tdxzs3.cfg。'),
    ('筛选逻辑', '扫描 429 个板块（881一二级行业128 + 880概念/地区301；排除三级子行业、880老行业、风格合成）。'),
    ('入选标准·阈值',
     '取两者并集：A. 当日前十强：当日涨幅降序前10名（当日涨幅>0）。'
     'B. 三日内也强：近3日累计涨幅 ≥ 3% 且 MA5 ≥ MA20（中期趋势向上）。'),
    ('排除项', '板块指数当日无成交（末笔量≤0）；不在 .402 显示范围的板块（三级子行业/880老行业/风格合成）。'),
    ('输出板块', '热点板块 RDKB.blk（当日前十 ∪ 三日强势，约10~30个）。'),
    ('刷新方式', '每日 16:30 自动化（d7962c75）串跑：先刷新 RDKB，再驱动 RDGP。脚本 analyze_sector_strength_v3.py。前提：日线已盘后下载。交易时段另可由「东财实时守护」(realtime_sector_daemon.py)盘中每5分钟滚动刷新，详见第九节。'),
])

# ===================== 4. 热点股池 =====================
h2('五、热点股池（日线 · RDGP）')
kv_table([
    ('定位', '对热点板块池(RDKB)每个强势板块，按"AI自选标准"各取前3只个股，绑定通达信自定义版面中上部框。'),
    ('数据来源', 'RDKB.blk（10个强势板块）→ 881用 tdxzs3.cfg/tdxhy.cfg 反查成分，880用 infoharbor_block.dat 反查；个股日线算指标；tnf 解析名称排雷ST。全部本地。'),
    ('筛选逻辑',
     '三档选股（每板块保证出3只，按优先级补齐）：第1档 达标：涨幅0.5~9.5% 且 均线多头(C>MA5>MA10>MA20) 且 量比1.2~3.0。'
     '第2档 补位：涨幅0.5~9.5% 且（均线多头 或 量比1.2~3.0 任一）。'
     '第3档 领涨：当日上涨(>0.1%) 且 非停牌/退市（仅前两档不足3只时兜底）。'
     '排序：先按档位升序(1最优)，同档按 score 降序。'),
    ('入选标准·阈值',
     'MIN_PCT=0.5 / MAX_PCT=9.5（涨幅）；MIN_VR=1.2 / MAX_VR=3.0（量比）；MIN_BARS=25；LEAD_PCT=0.1（领涨下限）。'
     'score = 涨幅% + 2.0×min(量比,3.0) + 0.5×(收盘价/MA20−1)×100×(均线多头?1:0)。'),
    ('排除项', 'ST/*ST（tnf名称本地识别剔除并顺延）；停牌(末笔量0)；本地日线根数<25；下跌/平盘(涨幅≤0.1%)；涨幅>9.5%（近涨停）；北交所。'),
    ('输出板块', '热点股池 RDGP.blk（每板块前3，跨板块去重）。'),
    ('刷新方式', '每日 16:30 自动化（d7962c75）全链路：RDKB→RDGP。脚本 pick_top3_per_sector.py --apply；预演 pick_top3_per_sector.py。交易时段「东财实时守护」亦会盘中刷新 RDGP（详见第九节）。'),
])

doc.add_page_break()

# ===================== 5. 龙头启动 =====================
h2('六、龙头启动（日线 · LTQD）')
kv_table([
    ('定位', '捕捉"上升趋势 → 近期回踩20日线 → 重新站上 → 放量突破前高"的启动信号，是回踩确认后当天开始突破的票。纯通达信原生条件选股公式实现（不依赖投研工作台脚本）。'),
    ('数据来源', '通达信实时/日线行情；公式单只股票维度计算，板块验证用 HYBLOCK + INSUM 统计所属板块涨停占比/站上MA20占比（需先建底层指标：涨停判断、站上MA20判断、均线多头判断）。'),
    ('筛选逻辑', '分三阶段叠加判定：阶段一铺垫（趋势垫+前期涨幅确认上升）→ 阶段二启动（突破前高+突破放量拉起那一刻）→ 全程叠加企稳/收盘守住/近期回踩/守住/轻量板块验证/排雷。'),
    ('入选标准·阈值',
     '趋势垫：MA60 ≥ REF(MA60,1)（60日线走平或向上，排除下跌途中小反弹）。｜前期涨幅：C > MA20×1.05（确有过上涨，否则不叫回踩）。'
     '｜近期回踩：近5日最低价曾落在 MA20×0.97 ~ MA20×1.03（贴20日线±3%，隐含缩量背景）。'
     '｜收盘守住：C > MA20 且 C ≥ O；守住：近3日收盘均在MA20上方（确认非假突破）。'
     '｜企稳：C > MA5 且 C > O。｜突破：C > REF(HHV(H,20),1)（过前20日高，不含今日，避免自我循环）。'
     '｜突破放量：V > MA(V,20)×1.3。｜板块验证(轻量)：所属板块站上MA20占比 HYSG > 20。'),
    ('排除项（排雷）', 'ST/*ST/退；停牌(量=0)；未涨停(ZL:=DYNAINFO(14)<9.8)；数据不足(COUNT(C>0,60)=60 不满足)；短期暴涨剔除：20日内曾摸过+30%（HHV(H,20)/REF(C,20)-1 > 0.3 已过热，排除）；板块不热(HY_OK不达标)。'),
    ('输出板块', '龙头启动 LTQD.blk（条件选股结果经 Ctrl+T 选股后"加入板块"落盘；已用本地日线回填，通达信内可见）。'),
    ('刷新方式',
     '手动：Ctrl+T 条件选股 → 选「龙头启动」→ 开始选股 → 结果 Ctrl+A 全选 → 右键「加入板块」选「龙头启动」。'
     '盘中自动：也可挂条件预警（监控品种选盯盘池，K线周期切日线，公式挂「龙头启动」，结果输出到板块选「龙头启动」）。'
     '⚠ 通达信公式不能直接写 .blk，需手动加板块或用条件预警落盘（与盯盘信号同理）。'),
])
pic(FIG1, width_in=6.3, caption='图1  龙头启动「回踩→突破」示意：上升趋势→回踩20日线±3%→收盘守住→放量突破前高')
body('龙头启动 完整公式（D:\\投研工作台\\quant\\tdx_intraday_watch\\龙头启动_修正版.txt，输出行须写成完整一行）', size=9, color='555555')
code('''MA60:=MA(C,60);
趋势垫:=MA60>=REF(MA60,1);
MA20:=MA(C,20);
前期涨幅:=C>MA20*1.05;
近期回踩:=LLV(L,5)<=MA20*1.03 AND LLV(L,5)>=MA20*0.97;
收盘守住:=C>MA20 AND C>=O;
守住:=EVERY(C>MA20,3);
MA5:=MA(C,5);
企稳:=C>MA5 AND C>O;
前高:=REF(HHV(H,20),1);
突破:=C>前高;
VMA20:=MA(V,20);
突破放量:=V>VMA20*1.3;
HY:=HYBLOCK;
HYZS:=BLOCKSETNUM(HY);
HYZT:=IF(HYZS>0,INSUM(HY,'涨停判断',1,0)/HYZS*100,0);
HYSG:=IF(HYZS>0,INSUM(HY,'站上MA20判断',1,0)/HYZS*100,0);
HY_OK:=HYSG>20;
VOK:=VOL>0;
EXCL:=NOT(NAMELIKE('ST')) AND NOT(NAMELIKE('退'));
ZL:=DYNAINFO(14)<9.8;
足量:=COUNT(C>0,60)=60;
ZF20MAX:=HHV(H,20)/REF(C,20)-1;
不暴涨:=ZF20MAX<=0.3;
VOK AND EXCL AND ZL AND 足量 AND 趋势垫 AND 前期涨幅 AND 突破 AND 突破放量 AND 企稳 AND 收盘守住 AND 近期回踩 AND 守住 AND HY_OK AND 不暴涨;''')
note('⚠ 输出行必须写成完整一行（多行用 AND 开头续写会报"最少应有1个输出"）。'
     '旧版 bug 已修正：原版把"回踩区(当日贴MA20±3%)"与"突破"同日硬AND，数学互斥→全市场0只；'
     '本版让回踩成为近期历史确认、突破为当日主信号，二者不再打架（已实测可选出，回填约10只）。')
note('★ 最重要的止损纪律：信号出现后，若收盘连续2天在20日线下方，或单日收盘跌破20日线3%，'
     '说明支撑失效，立即离场——不要因"已经亏了"而死扛。')

# ===================== 6. 盯盘信号 =====================
h2('七、盯盘信号（1分钟 · DPXH）')
kv_table([
    ('定位', '盘中实时量价异动预警，触发后自动写入「盯盘信号」板块，作为当日异动观察池与次日观察候选。'),
    ('数据来源', '实时盘中行情（通达信条件预警引擎驱动），公式只用收盘价C与成交量V，无任何 Level-2 依赖。'),
    ('筛选逻辑', '条件预警引擎盘中扫描"盯盘池"全部品种，对每只在1分钟周期上判定量价异动。'),
    ('入选标准·阈值',
     '【稳健版·量价异动】满足全部条件即触发：① 可交易：成交量>0 且 非ST/退 且 涨幅<9.8%（排除涨停买不到）。'
     '② 分钟涨幅 > 0.6%（(C−REF(C,1))/REF(C,1)×100）。③ 放量：成交量 > 5日均量（V>MA(V,5)）。'),
    ('排除项', 'ST/*ST/退；停牌(量=0)；已涨停(涨幅≥9.8%)；缩量(量≤5日均量)；涨幅未达0.6%。'),
    ('输出板块', '盯盘信号 DPXH.blk（条件预警"预警结果输出到自定义板块"指向它）。'),
    ('刷新方式', '条件预警盘中实时触发（9:30-15:00），非脚本落盘。七步配置见下。'),
])
body('稳健版完整公式（D:\\投研工作台\\quant\\tdx_intraday_watch\\预警-量价异动_稳健版.txt）', size=9, color='555555')
code('''VOK:=VOL>0;
EXCL:=NOT(NAMELIKE('ST')) AND NOT(NAMELIKE('退'));
PRE:=REF(C,1);
ZF:=IF(PRE>0,(C-PRE)/PRE*100,0);
USABLE:=VOK AND EXCL AND ZF<9.8;
VMA:=MA(V,5);
VOL_OK:=VMA>0 AND V>VMA;
USABLE AND ZF>0.6 AND VOL_OK;''')
note('注：稳健版已删除原 A1 的换手率条件(TO_OK:=DYNAINFO(37)>1)。'
     '原因：部分券商行情源不向条件预警喂换手率值，返回0导致整链归零、永不触发。'
     '删掉后仅用"涨幅+放量"判定，盘中最稳。')
body('条件预警七步配置（一步不能漏）：', bold=True)
bullets([
    'Ctrl+F → 条件选股 → 新建「预警-量价异动」→ 粘贴上方稳健版公式 → 确定。',
    'Ctrl+Y（或 .918）打开条件预警设置。',
    '「预警品种设置」→ 添加品种 → 选「盯盘池」（最易漏，是"设了没反应"头号原因）。',
    '「预警公式设置」→ 添加公式 → 选「预警-量价异动」。',
    '「其他设置」→ 勾选：系统扬声器声音 / 弹出列表对话框 / 预警结果输出到自定义板块（选「盯盘信号」）。',
    '「功能 → 预警系统 → 条件预警开关」点一下开启（通达信不记忆，每次需确认）。',
    '「功能 → 预警系统 → 条件预警列表」随时回看触发记录。',
])
pic(FIG2, width_in=5.6, caption='图2  盯盘信号 判读铁律流程图（放量+价不涨=出货；放量+价上行=真流入；缩量+走平=退潮）')
note('核心判读铁律：放量(柱长)+价格不涨 → 出货别跟；放量+价格上行+涨速上翘 → 真流入可跟；'
     '缩量+涨速走平 → 退潮撤。公式使用前须把分析图周期切到「1分钟」(按F5)，否则 REF(C,1) 取值错误。')

doc.add_page_break()

# ===================== 7. 共同前提 =====================
h2('八、共同前提与已知限制')
bullets([
    '本地日线需更新：依赖本地 .day，须收盘且完成"盘后数据下载"后运行，否则结果是旧数据。',
    '北交所不收录：43x/83x/87x/92x 代码自动拒收（主板行情不收录）。',
    '打分是规则分不是 AI 分：规则透明可控，深度研判需另接模型。',
    '日线 MA 反映截至昨日：盘中跑时 .day 末根通常是昨日收盘，MA 反映截至昨日的趋势结构。',
    '不处理法定节假日：交易时段只按时间判断，节假日会空跑（不写脏数据）。',
    '板块需刷新：新建/更新板块后，通达信对「自选股」右键 → 刷新（或重启）才能看到。',
])

# ===================== 盘中实时（新增） =====================
h2('九、盘中实时热点刷新机制（RDKB/RDGP 盘中守护）')
kv_table([
    ('定位', '把原盘后(16:30)才刷新的「热点板块 RDKB」「热点股池 RDGP」升级为盘中实时刷新，交易时段每5分钟滚动更新，与盘后批处理互补（盘中看当下、盘后定全量）。'),
    ('为什么必须外部程序', '通达信公式不能遍历板块（HYBLOCK 只返当前票），且本地 .day 盘中末根=昨日收盘、拿不到当日实时行情。故用东财 push2 实时接口在外部算，再写回板块。'),
    ('数据来源', '东财 push2（全市场个股实时涨跌幅/量比/行业 f100）+ 本地板块指数日线 .day（三日强与均线多头）。复用 datasource.py / tdx_writer.py / pick_top3_per_sector.py。'),
    ('算法口径（RDKB）', '当日强 ∪ 三日强 去重：A. 当日强=东财全市场个股按涨跌幅降序前 N 页 → 按行业 f100 分组 → 行业平均涨幅降序前10（avg>0 且映射到 881/880）。B. 三日强=本地 .day 近3日涨幅 ≥ 3% 且 MA5 ≥ MA20 的前15个板块。'),
    ('算法口径（RDGP）', '对 RDKB 每个板块成员，取东财实时涨幅/量比 + 本地 MA 多头，按 AI 自选标准三档（达标/补位/领涨）各取前3，跨板块去重落盘。'),
    ('口径说明', '当日强=真盘中（东财实时）；三日强与均线多头=本地 .day（截至昨日结构）。刻意设计：盘中 .day 无当日 bar，趋势用昨日收盘代表反而更稳，与"今日启动"叠加成组合信号。'),
    ('输出板块', '热点板块 RDKB.blk / 热点股池 RDGP.blk（自动登记，通达信可见）。'),
    ('启动方式', '双击 start_realtime_daemon.bat 新窗口常驻（已配交易时段自动拉起）；或命令行 python realtime_sector_daemon.py --loop。'),
    ('刷新方式', '守护仅在交易时段（9:30-11:30 / 13:00-15:00）取数写盘，其余时段休眠；单实例锁防重复；每轮生成报告 实时热点_*.md，日志在 logs/。'),
])
note('⚠ 旧版曾用东财板块列表接口(fs=b:BK0430/...)，本机实测返回的是个股名而非板块名，导致行业映射崩塌(RDKB仅2个)。现版已改用"个股池按行业分组"方案，覆盖率~90%。')
code('''# 盘中实时守护 启停
python realtime_sector_daemon.py --loop            # 常驻循环（每300秒一轮）
python realtime_sector_daemon.py --once --apply    # 单轮并写盘
python realtime_sector_daemon.py --once            # 单轮预演（不写盘）
# 交易时段自动拉起：WorkBuddy 定时任务（周一至周五 09:25 / 12:55）''')

# ===================== 8. 核心命令 =====================
h2('十、核心命令索引')
code('''# 日线 AI自选（AIZX）盘中守护 / 单轮
python run_picker.py --loop
python run_picker.py --split    # 额外生成4个分路明细板块

# 热点股池（RDGP）预演 / 落盘
python pick_top3_per_sector.py         # 预演
python pick_top3_per_sector.py --apply # 落盘到 RDGP

# 周线 AI周线（AIWEEK）
python weekly_picker.py --force              # 手动跑并写入
python weekly_picker.py --force --dry-run    # 只看结果''')

doc.save(OUT)
print('Word 生成成功：', OUT)
