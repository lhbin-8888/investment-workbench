# -*- coding: utf-8 -*-
"""
生成「板块筛选逻辑与标准说明书」PDF
覆盖 5 个板块：AI自选 / AI周线 / 热点板块池 / 盯盘信号 / 热点股池
模板：定位 / 数据来源 / 筛选逻辑 / 入选标准·阈值 / 排除项 / 输出板块 / 刷新方式
"""
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, ListFlowable, ListItem,
                                PageBreak, HRFlowable)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# ---- 注册中文（Adobe 内置 CJK，无需字体文件）----
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
CN = 'STSong-Light'

# ---- 样式 ----
styles = getSampleStyleSheet()
H1 = ParagraphStyle('H1', fontName=CN, fontSize=20, leading=26,
                    spaceAfter=4, textColor=colors.HexColor('#1F3864'))
SUB = ParagraphStyle('SUB', fontName=CN, fontSize=10, leading=15,
                     textColor=colors.HexColor('#555555'), spaceAfter=10)
H2 = ParagraphStyle('H2', fontName=CN, fontSize=13.5, leading=18,
                    spaceBefore=10, spaceAfter=6,
                    textColor=colors.HexColor('#C55A11'))
BODY = ParagraphStyle('BODY', fontName=CN, fontSize=10, leading=15,
                      spaceAfter=4, alignment=TA_LEFT)
SMALL = ParagraphStyle('SMALL', fontName=CN, fontSize=8.5, leading=12,
                       textColor=colors.HexColor('#444444'))
CODE = ParagraphStyle('CODE', fontName=CN, fontSize=9, leading=13,
                      textColor=colors.HexColor('#1A1A1A'),
                      backColor=colors.HexColor('#F2F2F2'),
                      borderPadding=6, spaceAfter=6, spaceBefore=2)
LBL = ParagraphStyle('LBL', fontName=CN, fontSize=10, leading=15,
                     textColor=colors.HexColor('#1F3864'))
NOTE = ParagraphStyle('NOTE', fontName=CN, fontSize=9, leading=13,
                      textColor=colors.HexColor('#7F6000'),
                      backColor=colors.HexColor('#FFF2CC'),
                      borderPadding=5, spaceAfter=6, spaceBefore=4)

story = []

def section(title):
    story.append(Paragraph(title, H2))
    story.append(HRFlowable(width='100%', thickness=0.6,
                            color=colors.HexColor('#C55A11'),
                            spaceAfter=4))

def kv_table(rows):
    """rows: list of (label, value)"""
    data = [[Paragraph('<b>%s</b>' % l, LBL), Paragraph(v, BODY)] for l, v in rows]
    t = Table(data, colWidths=[34*mm, 140*mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), CN),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LINEBELOW', (0,0), (-1,-1), 0.3, colors.HexColor('#DDDDDD')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F7F9FC')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 4))

def bullets(items):
    li = [ListItem(Paragraph(x, BODY), leftIndent=6) for x in items]
    story.append(ListFlowable(li, bulletType='bullet', start='•',
                              leftIndent=14, bulletColor=colors.HexColor('#C55A11')))
    story.append(Spacer(1, 2))

# ===================== 封面 =====================
story.append(Spacer(1, 30))
story.append(Paragraph('板块筛选逻辑与标准说明书', H1))
story.append(Paragraph('通达信纯本地方案 · 5 大智能板块选股体系', SUB))
story.append(Paragraph(
    '生成日期：%s &nbsp;|&nbsp; 适用系统：<font face="%s">D:\\投研工作台\\quant\\</font> &nbsp;|&nbsp; 通达信目录：<font face="%s">D:\\TDX</font>'
    % (datetime.date.today().strftime('%Y-%m-%d'), CN, CN), SMALL))
story.append(HRFlowable(width='100%', thickness=1.2,
                        color=colors.HexColor('#1F3864'), spaceBefore=8, spaceAfter=10))

story.append(Paragraph('一、六板块总览', H2))
overview = [
    ['板块', '通达信文件', '周期/视角', '定位', '刷新方式'],
    ['AI自选', 'AIZX.blk', '日线·盘中', '当日/短波段强势主池', '盘中守护每5分钟'],
    ['AI周线', 'AIWEEK.blk', '周线·中线', '中线趋势龙主升浪', '每周五收盘后'],
    ['热点板块池', 'RDKB.blk', '板块指数', '当天最强板块（选股上游）', '每日16:30｜盘中守护'],
    ['热点股池', 'RDGP.blk', '日线·盘中', '热点板块内前3强势股', '每日16:30｜盘中守护'],
    ['龙头启动', 'LTQD.blk', '日线·盘中', '回踩20日线后放量突破前高', '条件选股/Ctrl+T'],
    ['盯盘信号', 'DPXH.blk', '1分钟·盘中', '实时量价异动预警落盘', '条件预警盘中触发'],
]
t = Table(overview, colWidths=[24*mm, 24*mm, 24*mm, 56*mm, 46*mm])
t.setStyle(TableStyle([
    ('FONTNAME', (0,0), (-1,-1), CN),
    ('FONTSIZE', (0,0), (-1,-1), 9),
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1F3864')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#BBBBBB')),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F2F5FA')]),
    ('TOPPADDING', (0,0), (-1,-1), 5),
    ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ('LEFTPADDING', (0,0), (-1,-1), 5),
]))
story.append(t)
story.append(Spacer(1, 6))
story.append(Paragraph(
    '六个板块构成一条完整链路：<b>热点板块池(RDKB)</b> 与 <b>AI自选(AIZX)</b> 是两条独立选股主线，'
    '<b>热点股池(RDGP)</b> 由 RDKB 派生，<b>盯盘信号(DPXH)</b> 是盘中实时预警落盘，'
    '<b>龙头启动(LTQD)</b> 是回踩20日线后放量突破前高的启动信号，'
    '<b>AI周线(AIWEEK)</b> 提供中线视角。所有阈值均取自本机已落地脚本，改脚本即改标准。', BODY))
story.append(PageBreak())

# ===================== 1. AI自选 =====================
section('二、AI自选（日线 · AIZX）')
kv_table([
    ('定位', '日线视角下的强势股筛选，盘中盯盘主池。核心方法论「AI自选标准」：均线多头 + 涨幅区间 + 量比区间 + 排除项。'),
    ('数据来源', '本地日线 <font face="%s">D:\\TDX\\vipdoc\\{sh,sz}\\lday</font> 算均线/涨幅/量比；广义AI自选主系统另接东财实时含换手率。' % CN),
    ('筛选逻辑', '四路独立选股合并去重：①技术突破 ②主线龙头 ③基本面 ④打板情绪；加 --split 生成4个分路明细板块。'),
    ('入选标准·阈值',
     '<b>均线多头</b>：收盘价 &gt; MA5 &gt; MA10 &gt; MA20 且 MA5 向上。<br/>'
     '<b>涨幅</b>：0.5% ~ 9.5%（下限过滤没动的票，上限避开近涨停）。<br/>'
     '<b>量比</b>：1.2 ~ 3.0（放量但不失控）。<br/>'
     '<b>换手率（放宽项）</b>：3%~25%（仅AIZX技术/打板路用，本地RDGP未实现）。<br/>'
     '四路关键阈值：技术突破 涨幅2~9.5%、量比≥1.5、换手3~25%、主力净流入≥5000万；'
     '主线龙头 流通市值≥50亿、主力净流入&gt;0；基本面 PE≤60、净流入≥3000万、涨幅-1~7%；'
     '打板情绪 涨幅≥4%、量比≥2、换手≥5%。'),
    ('排除项', 'ST/*ST；停牌（末笔量=0）；本地日线根数&lt;60；下跌/平盘（涨幅≤0.1%）；涨幅&gt;9.5%；北交所43x/83x/87x/92x。'),
    ('输出板块', 'AI自选 AIZX.blk（四路合并，≤30只）；明细 AITECH/AIZXL/AIZXFB/AIZXDB（--split）。'),
    ('刷新方式',
     '盘中守护 <font face="%s">run_picker.py --loop</font> 交易日9:30-15:00每5分钟一轮；'
     '计划任务 TDX_AutoPick 每交易日08:55拉起。前提：通达信完成盘后数据下载。' % CN),
])

# ===================== 2. AI周线 =====================
section('三、AI周线（周线 · AIWEEK）')
kv_table([
    ('定位', '周线视角中线波段选股，依据「MA3/MA5/MA10 多头 + 3周刚上穿5周 + 3周已上穿20周 + 一阳穿三线」早期突破信号，抓刚启动的趋势票。与日线体系独立。'),
    ('数据来源', '<b>纯本地、零网络</b>：本地日线按"周五"聚合为周线（周线日期取当周周五，与通达信口径一致），再算周线均线。'),
    ('筛选逻辑', '周线均线：3周=极短趋势、5周=短趋势、10周=波段、20周=中期趋势。'),
    ('入选标准·阈值',
     '以下<b>全部满足</b>才入选：<br/>'
     '① <b>多头排列</b>：MA3 &gt; MA5 &gt; MA10。<br/>'
     '② <b>3周刚上穿5周</b>（本周金叉）。③ <b>3周已上穿20周</b>（中期趋势转多）。<br/>'
     '④ <b>一阳穿三线</b>：当周收阳、收盘站上MA3/MA5/MA10、当周最低价低于三线最低者(MA10)（容差1%）。<br/>'
     '⑤ 剔除最近3日连续下跌；⑥ 剔除最近10日日线连跌累计&gt;8% 或 较近期高点回撤&gt;12%；<br/>'
     '⑦ 剔除近13周累计涨幅&gt;50%（高位过度拉升）；⑧ 剔除ST/*ST、北交所、亏损股（净利润&lt;0，无数据保守保留）。'),
    ('量能（加分非门槛）',
     '当周量≥前10周均量×1.5 打"放量"标签并加分；score=100+周涨幅×100+(量比−1)×20+站上3周线幅度×50+站上20周线幅度×30。'),
    ('排除项', '最近3日连跌、最近10日日线连跌&gt;8%或回撤&gt;12%、近13周涨幅&gt;50%、ST/*ST、北交所、亏损股；数据不足60周剔除。'),
    ('输出板块', 'AI周线 AIWEEK.blk（全市场扫描，默认≤80只）。'),
    ('刷新方式',
     '默认每日盘后15:00后触发（脚本内置校验）；计划任务"通达信周线选股"每天15:30运行'
     '（需本机双击 setup_weekly_task.bat 注册一次）。手动：<font face="%s">weekly_picker.py --force</font>。' % CN),
])

# ===================== 3. 热点板块池 =====================
section('四、热点板块池（板块指数 · RDKB）')
kv_table([
    ('定位', '当天/近期最强板块集合，是热点股池(RDGP)的上游输入。与 .402 板块指数页口径对齐。'),
    ('数据来源', '本地板块指数日线 <font face="%s">D:\\TDX\\vipdoc\\sh\\lday</font>（881/880板块指数代码）；配置 tdxzs.cfg / tdxzs3.cfg。' % CN),
    ('筛选逻辑', '扫描 429 个板块（881一二级行业128 + 880概念/地区301；排除三级子行业、880老行业、风格合成）。'),
    ('入选标准·阈值',
     '取两者并集：<br/>'
     'A. <b>当日前十强</b>：当日涨幅降序前10名（当日涨幅&gt;0）。<br/>'
     'B. <b>三日内也强</b>：近3日累计涨幅 ≥ 3% <b>且</b> MA5 ≥ MA20（中期趋势向上）。'),
    ('排除项', '板块指数当日无成交（末笔量≤0）；不在 .402 显示范围的板块（三级子行业/880老行业/风格合成）。'),
    ('输出板块', '热点板块 RDKB.blk（当日前十 ∪ 三日强势，约10~30个）。'),
    ('刷新方式',
     '每日 16:30 自动化（d7962c75）串跑：先刷新 RDKB，再驱动 RDGP。'
     '脚本 <font face="%s">analyze_sector_strength_v3.py</font>。前提：日线已盘后下载。<br/>'
     '另：交易时段可由「东财实时守护」(<font face="%s">realtime_sector_daemon.py</font>)盘中每5分钟滚动刷新，详见第九节。' % (CN, CN)),
])
story.append(PageBreak())

# ===================== 4. 热点股池 =====================
section('五、热点股池（日线 · RDGP）')
kv_table([
    ('定位', '对热点板块池(RDKB)每个强势板块，按"AI自选标准"各取前3只个股，绑定通达信自定义版面中上部框。'),
    ('数据来源', 'RDKB.blk（10个强势板块）→ 881用 tdxzs3.cfg/tdxhy.cfg 反查成分，880用 infoharbor_block.dat 反查；个股日线算指标；tnf 解析名称排雷ST。全部本地。'),
    ('筛选逻辑', '<b>三档选股</b>（每板块保证出3只，按优先级补齐）：<br/>'
     '第1档 <b>达标</b>：涨幅0.5~9.5% 且 均线多头(C&gt;MA5&gt;MA10&gt;MA20) 且 量比1.2~3.0。<br/>'
     '第2档 <b>补位</b>：涨幅0.5~9.5% 且（均线多头 或 量比1.2~3.0 任一）。<br/>'
     '第3档 <b>领涨</b>：当日上涨(&gt;0.1%) 且 非停牌/退市（仅前两档不足3只时兜底）。<br/>'
     '排序：先按档位升序(1最优)，同档按 score 降序。'),
    ('入选标准·阈值',
     'MIN_PCT=0.5 / MAX_PCT=9.5（涨幅）；MIN_VR=1.2 / MAX_VR=3.0（量比）；MIN_BARS=25；LEAD_PCT=0.1（领涨下限）。<br/>'
     'score = 涨幅% + 2.0×min(量比,3.0) + 0.5×(收盘价/MA20−1)×100×(均线多头?1:0)。'),
    ('排除项', 'ST/*ST（tnf名称本地识别剔除并顺延）；停牌(末笔量0)；本地日线根数&lt;25；下跌/平盘(涨幅≤0.1%)；涨幅&gt;9.5%（近涨停）；北交所。'),
    ('输出板块', '热点股池 RDGP.blk（每板块前3，跨板块去重）。'),
    ('刷新方式',
     '每日 16:30 自动化（d7962c75）全链路：RDKB→RDGP。'
     '脚本 <font face="%s">pick_top3_per_sector.py --apply</font>；预演 <font face="%s">pick_top3_per_sector.py</font>。<br/>'
     '交易时段「东财实时守护」亦会盘中刷新 RDGP（详见第九节）。' % (CN, CN)),
])

# ===================== 6. 龙头启动 =====================
section('六、龙头启动（日线 · LTQD）')
kv_table([
    ('定位', '捕捉"上升趋势 → 近期回踩20日线 → 重新站上 → 放量突破前高"的启动信号，是回踩确认后当天开始突破的票。纯通达信原生条件选股公式实现（不依赖投研工作台脚本）。'),
    ('数据来源', '通达信实时/日线行情；公式单只股票维度计算，板块验证用 HYBLOCK + INSUM 统计所属板块涨停占比/站上MA20占比（需先建底层指标：涨停判断、站上MA20判断、均线多头判断）。'),
    ('筛选逻辑', '分三阶段叠加判定：阶段一铺垫（趋势垫+前期涨幅确认上升）→ 阶段二启动（突破前高+突破放量拉起那一刻）→ 全程叠加企稳/收盘守住/近期回踩/守住/轻量板块验证/排雷。'),
    ('入选标准·阈值',
     '<b>趋势垫</b>：MA60 ≥ REF(MA60,1)（60日线走平或向上，排除下跌途中小反弹）。<br/>'
     '<b>前期涨幅</b>：C &gt; MA20×1.05（确有过上涨，否则不叫回踩）。<br/>'
     '<b>近期回踩</b>：近5日最低价曾落在 MA20×0.97 ~ MA20×1.03（贴20日线±3%，隐含缩量背景）。<br/>'
     '<b>收盘守住</b>：C &gt; MA20 且 C ≥ O；<b>守住</b>：近3日收盘均在MA20上方（确认非假突破）。<br/>'
     '<b>企稳</b>：C &gt; MA5 且 C &gt; O。<br/>'
     '<b>突破</b>：C &gt; REF(HHV(H,20),1)（过前20日高，不含今日，避免自我循环）。<br/>'
     '<b>突破放量</b>：V &gt; MA(V,20)×1.3。<br/>'
     '<b>板块验证(轻量)</b>：所属板块站上MA20占比 HYSG &gt; 20（原版 HYZT&gt;1且HYSG&gt;40 过严，普跌日清零所有候选）。'),
    ('排除项（排雷）', 'ST/*ST/退；停牌(量=0)；未涨停(ZL:=DYNAINFO(14)&lt;9.8)；数据不足(COUNT(C&gt;0,60)=60 不满足)；<b>短期暴涨剔除</b>：20日内曾摸过+30%（HHV(H,20)/REF(C,20)-1 &gt; 0.3 已过热，排除）；板块不热(HY_OK不达标)。'),
    ('输出板块', '龙头启动 LTQD.blk（条件选股结果经 Ctrl+T 选股后"加入板块"落盘；已用本地日线回填，通达信内可见）。'),
    ('刷新方式',
     '<b>手动</b>：Ctrl+T 条件选股 → 选「龙头启动」→ 开始选股 → 结果 Ctrl+A 全选 → 右键「加入板块」选「龙头启动」。<br/>'
     '<b>盘中自动</b>：也可挂条件预警（监控品种选盯盘池，K线周期切日线，公式挂「龙头启动」，结果输出到板块选「龙头启动」）。<br/>'
     '⚠ 通达信公式不能直接写 .blk，需手动加板块或用条件预警落盘（与盯盘信号同理）。'),
])
story.append(Paragraph('龙头启动 完整公式（<font face="%s">D:\\投研工作台\\quant\\tdx_intraday_watch\\龙头启动_修正版.txt</font>，输出行须写成完整一行）' % CN, SMALL))
story.append(Paragraph(
    'MA60:=MA(C,60);<br/>'
    '趋势垫:=MA60&gt;=REF(MA60,1);<br/>'
    'MA20:=MA(C,20);<br/>'
    '前期涨幅:=C&gt;MA20*1.05;<br/>'
    '近期回踩:=LLV(L,5)&lt;=MA20*1.03 AND LLV(L,5)&gt;=MA20*0.97;<br/>'
    '收盘守住:=C&gt;MA20 AND C&gt;=O;<br/>'
    '守住:=EVERY(C&gt;MA20,3);<br/>'
    'MA5:=MA(C,5);<br/>'
    '企稳:=C&gt;MA5 AND C&gt;O;<br/>'
    '前高:=REF(HHV(H,20),1);<br/>'
    '突破:=C&gt;前高;<br/>'
    'VMA20:=MA(V,20);<br/>'
    '突破放量:=V&gt;VMA20*1.3;<br/>'
    'HY:=HYBLOCK;<br/>'
    'HYZS:=BLOCKSETNUM(HY);<br/>'
    'HYZT:=IF(HYZS&gt;0,INSUM(HY,\'涨停判断\',1,0)/HYZS*100,0);<br/>'
    'HYSG:=IF(HYZS&gt;0,INSUM(HY,\'站上MA20判断\',1,0)/HYZS*100,0);<br/>'
    'HY_OK:=HYSG&gt;20;<br/>'
    'VOK:=VOL&gt;0;<br/>'
    'EXCL:=NOT(NAMELIKE(\'ST\')) AND NOT(NAMELIKE(\'退\'));<br/>'
    'ZL:=DYNAINFO(14)&lt;9.8;<br/>'
    '足量:=COUNT(C&gt;0,60)=60;<br/>'
    'ZF20MAX:=HHV(H,20)/REF(C,20)-1;<br/>'
    '不暴涨:=ZF20MAX&lt;=0.3;<br/>'
    'VOK AND EXCL AND ZL AND 足量 AND 趋势垫 AND 前期涨幅 AND 突破 AND 突破放量 AND 企稳 AND 收盘守住 AND 近期回踩 AND 守住 AND HY_OK AND 不暴涨;', CODE))
story.append(Paragraph(
    '⚠ <b>输出行必须写成完整一行</b>（多行用 AND 开头续写会报"最少应有1个输出"）。'
    '旧版 bug 已修正：原版把"回踩区(当日贴MA20±3%)"与"突破"同日硬AND，数学互斥→全市场0只；'
    '本版让回踩成为近期历史确认、突破为当日主信号，二者不再打架（已实测可选出，回填约10只）。', NOTE))
story.append(Paragraph(
    '<b>最重要的止损纪律</b>：信号出现后，若收盘连续2天在20日线下方，或单日收盘跌破20日线3%，'
    '说明支撑失效，立即离场——不要因"已经亏了"而死扛。', NOTE))

# ===================== 7. 盯盘信号 =====================
section('七、盯盘信号（1分钟 · DPXH）')
kv_table([
    ('定位', '盘中实时量价异动预警，触发后自动写入「盯盘信号」板块，作为当日异动观察池与次日观察候选。'),
    ('数据来源', '<b>实时盘中行情</b>（通达信条件预警引擎驱动），公式只用收盘价C与成交量V，<b>无任何 Level-2 依赖</b>。'),
    ('筛选逻辑', '条件预警引擎盘中扫描"盯盘池"全部品种，对每只在1分钟周期上判定量价异动。'),
    ('入选标准·阈值',
     '【稳健版·量价异动】满足全部条件即触发：<br/>'
     '① 可交易：成交量&gt;0 且 非ST/退 且 涨幅&lt;9.8%（排除涨停买不到）。<br/>'
     '② 分钟涨幅 &gt; 0.6%（(C−REF(C,1))/REF(C,1)×100）。<br/>'
     '③ 放量：成交量 &gt; 5日均量（V&gt;MA(V,5)）。'),
    ('排除项', 'ST/*ST/退；停牌(量=0)；已涨停(涨幅≥9.8%)；缩量(量≤5日均量)；涨幅未达0.6%。'),
    ('输出板块', '盯盘信号 DPXH.blk（条件预警"预警结果输出到自定义板块"指向它）。'),
    ('刷新方式',
     '<b>条件预警盘中实时触发（9:30-15:00）</b>，非脚本落盘。七步配置见下。'),
])
story.append(Paragraph('稳健版完整公式（<font face="%s">D:\\投研工作台\\quant\\tdx_intraday_watch\\预警-量价异动_稳健版.txt</font>）' % CN, SMALL))
story.append(Paragraph(
    'VOK:=VOL&gt;0;<br/>'
    'EXCL:=NOT(NAMELIKE(\'ST\')) AND NOT(NAMELIKE(\'退\'));<br/>'
    'PRE:=REF(C,1);<br/>'
    'ZF:=IF(PRE&gt;0,(C-PRE)/PRE*100,0);<br/>'
    'USABLE:=VOK AND EXCL AND ZF&lt;9.8;<br/>'
    'VMA:=MA(V,5);<br/>'
    'VOL_OK:=VMA&gt;0 AND V&gt;VMA;<br/>'
    'USABLE AND ZF&gt;0.6 AND VOL_OK;', CODE))
story.append(Paragraph(
    '注：稳健版已删除原 A1 的换手率条件(TO_OK:=DYNAINFO(37)&gt;1)。'
    '原因：部分券商行情源不向条件预警喂换手率值，返回0导致整链归零、永不触发。'
    '删掉后仅用"涨幅+放量"判定，盘中最稳。', NOTE))
story.append(Paragraph('条件预警七步配置（一步不能漏）', SMALL))
bullets([
    'Ctrl+F → 条件选股 → 新建「预警-量价异动」→ 粘贴上方稳健版公式 → 确定。',
    'Ctrl+Y（或 .918）打开条件预警设置。',
    '「预警品种设置」→ 添加品种 → 选「盯盘池」（最易漏，是"设了没反应"头号原因）。',
    '「预警公式设置」→ 添加公式 → 选「预警-量价异动」。',
    '「其他设置」→ 勾选：系统扬声器声音 / 弹出列表对话框 / 预警结果输出到自定义板块（选「盯盘信号」）。',
    '「功能 → 预警系统 → 条件预警开关」点一下开启（通达信不记忆，每次需确认）。',
    '「功能 → 预警系统 → 条件预警列表」随时回看触发记录。',
])
story.append(Paragraph(
    '核心判读铁律：放量(柱长)+价格不涨 → 出货别跟；放量+价格上行+涨速上翘 → 真流入可跟；'
    '缩量+涨速走平 → 退潮撤。公式使用前须把分析图周期切到「1分钟」(按F5)，否则 REF(C,1) 取值错误。', NOTE))

# ===================== 共同前提 =====================
story.append(PageBreak())
section('八、共同前提与已知限制')
bullets([
    '本地日线需更新：依赖本地 .day，须收盘且完成"盘后数据下载"后运行，否则结果是旧数据。',
    '北交所不收录：43x/83x/87x/92x 代码自动拒收（主板行情不收录）。',
    '打分是规则分不是 AI 分：规则透明可控，深度研判需另接模型。',
    '日线 MA 反映截至昨日：盘中跑时 .day 末根通常是昨日收盘，MA 反映截至昨日的趋势结构。',
    '不处理法定节假日：交易时段只按时间判断，节假日会空跑（不写脏数据）。',
    '板块需刷新：新建/更新板块后，通达信对「自选股」右键 → 刷新（或重启）才能看到。',
])
# ===================== 9. 盘中实时 =====================
section('九、盘中实时热点刷新机制（RDKB/RDGP 盘中守护）')
kv_table([
    ('定位', '把原盘后(16:30)才刷新的「热点板块 RDKB」「热点股池 RDGP」升级为盘中实时刷新，交易时段每5分钟滚动更新，与盘后批处理互补（盘中看当下、盘后定全量）。'),
    ('为什么必须外部程序', '通达信公式不能遍历板块（HYBLOCK 只返当前票），且本地 .day 盘中末根=昨日收盘、拿不到当日实时行情。故用东财 push2 实时接口在外部算，再写回板块。'),
    ('数据来源', '东财 push2（全市场个股实时涨跌幅/量比/行业 f100）+ 本地板块指数日线 .day（三日强与均线多头）。复用 datasource.py / tdx_writer.py / pick_top3_per_sector.py。'),
    ('算法口径（RDKB）', '当日强 ∪ 三日强 去重：A. 当日强=东财全市场个股按涨跌幅降序前 N 页 → 按行业 f100 分组 → 行业平均涨幅降序前10（avg&gt;0 且映射到 881/880）。B. 三日强=本地 .day 近3日涨幅 ≥ 3% 且 MA5 ≥ MA20 的前15个板块。'),
    ('算法口径（RDGP）', '对 RDKB 每个板块成员，取东财实时涨幅/量比 + 本地 MA 多头，按 AI 自选标准三档（达标/补位/领涨）各取前3，跨板块去重落盘。'),
    ('口径说明', '当日强=真盘中（东财实时）；三日强与均线多头=本地 .day（截至昨日结构）。刻意设计：盘中 .day 无当日 bar，趋势用昨日收盘代表反而更稳，与"今日启动"叠加成组合信号。'),
    ('输出板块', '热点板块 RDKB.blk / 热点股池 RDGP.blk（自动登记，通达信可见）。'),
    ('启动方式', '双击 <font face="%s">start_realtime_daemon.bat</font> 新窗口常驻（已配交易时段自动拉起）；或命令行 <font face="%s">python realtime_sector_daemon.py --loop</font>。' % (CN, CN)),
    ('刷新方式', '守护仅在交易时段（9:30-11:30 / 13:00-15:00）取数写盘，其余时段休眠；单实例锁防重复；每轮生成报告 实时热点_*.md，日志在 logs/。'),
])
story.append(Paragraph(
    '⚠ 旧版曾用东财板块列表接口(fs=b:BK0430/...)，本机实测返回的是个股名而非板块名，导致行业映射崩塌(RDKB仅2个)。'
    '现版已改用"个股池按行业分组"方案，覆盖率~90%。', NOTE))
story.append(Paragraph(
    '# 盘中实时守护 启停<br/>'
    'python realtime_sector_daemon.py --loop&nbsp;&nbsp;&nbsp;&nbsp;# 常驻循环（每300秒一轮）<br/>'
    'python realtime_sector_daemon.py --once --apply&nbsp;&nbsp;# 单轮并写盘<br/>'
    'python realtime_sector_daemon.py --once&nbsp;&nbsp;&nbsp;&nbsp;# 单轮预演（不写盘）<br/>'
    '# 交易时段自动拉起：WorkBuddy 定时任务（周一至周五 09:25 / 12:55）', CODE))

# ===================== 核心命令 =====================
section('十、核心命令索引')
story.append(Paragraph(
    '# 日线 AI自选（AIZX）盘中守护 / 单轮<br/>'
    'python run_picker.py --loop<br/>'
    'python run_picker.py --split&nbsp;&nbsp;# 额外生成4个分路明细板块<br/><br/>'
    '# 热点股池（RDGP）预演 / 落盘<br/>'
    'python pick_top3_per_sector.py&nbsp;&nbsp;&nbsp;&nbsp;# 预演<br/>'
    'python pick_top3_per_sector.py --apply&nbsp;&nbsp;# 落盘到 RDGP<br/><br/>'
    '# 周线 AI周线（AIWEEK）<br/>'
    'python weekly_picker.py --force&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# 手动跑并写入<br/>'
    'python weekly_picker.py --force --dry-run&nbsp;&nbsp;# 只看结果', CODE))

out = r'D:\投研工作台\quant\板块筛选逻辑与标准说明书.pdf'
doc = SimpleDocTemplate(out, pagesize=A4,
                        leftMargin=18*mm, rightMargin=18*mm,
                        topMargin=16*mm, bottomMargin=16*mm,
                        title='板块筛选逻辑与标准说明书',
                        author='投研工作台')

def footer(canvas, d):
    canvas.saveState()
    canvas.setFont(CN, 8)
    canvas.setFillColor(colors.HexColor('#888888'))
    canvas.drawString(18*mm, 10*mm, '板块筛选逻辑与标准说明书 · 通达信纯本地方案')
    canvas.drawRightString(A4[0]-18*mm, 10*mm, '第 %d 页' % d.page)
    canvas.restoreState()

doc.build(story, onFirstPage=footer, onLaterPages=footer)
print('PDF 生成成功：', out)
