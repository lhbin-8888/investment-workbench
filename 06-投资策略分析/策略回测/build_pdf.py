# -*- coding: utf-8 -*-
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, ListFlowable, ListItem)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from xml.sax.saxutils import escape as _esc

pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
FONT = 'STSong-Light'

OUT = r"D:\投研工作台\06-投资策略分析\策略回测\三策略对比分析.pdf"

CN = colors.HexColor('#ED7D31')
GRID = colors.HexColor('#BFBFBF')
ALT = colors.HexColor('#FBE9DD')
HDR = colors.HexColor('#7A3B12')

title = ParagraphStyle('t', fontName=FONT, fontSize=17, leading=22,
                       textColor=colors.HexColor('#7A3B12'), spaceAfter=4, alignment=TA_CENTER)
sub = ParagraphStyle('s', fontName=FONT, fontSize=9, leading=13,
                     textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)
h2 = ParagraphStyle('h2', fontName=FONT, fontSize=12.5, leading=17,
                    textColor=CN, spaceBefore=12, spaceAfter=6)
body = ParagraphStyle('b', fontName=FONT, fontSize=9.3, leading=13.5, spaceAfter=4)
cell = ParagraphStyle('c', fontName=FONT, fontSize=8.2, leading=11)
cellh = ParagraphStyle('ch', fontName=FONT, fontSize=8.6, leading=11.5,
                       textColor=colors.white, alignment=TA_CENTER)
bullet = ParagraphStyle('bl', fontName=FONT, fontSize=9.2, leading=13.5)

def P(t, st=cell): return Paragraph(_esc(str(t)), st)

def make_table(data, col_widths, header=True):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ('GRID', (0,0), (-1,-1), 0.5, GRID),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]
    if header:
        style += [
            ('BACKGROUND', (0,0), (-1,0), CN),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ]
        for r in range(2, len(data), 2):
            style.append(('BACKGROUND', (0,r), (-1,r), ALT))
    t.setStyle(TableStyle(style))
    return t

doc = SimpleDocTemplate(OUT, pagesize=A4,
                        leftMargin=16*mm, rightMargin=16*mm,
                        topMargin=15*mm, bottomMargin=15*mm,
                        title='三套热点追踪策略对比分析')
E = []

E.append(Paragraph('三套热点追踪策略对比分析', title))
E.append(Paragraph('分析区间：2026-05-06 ~ 2026-06-30 ｜ 对象：热点早盘001 V4.11 / 热点追踪lhb888 v3 / 热点追踪早盘1030 v8.1', sub))

# ---- 一、核心参数速查表 ----
E.append(Paragraph('一、核心参数速查表', h2))
param_rows = [
    [P('维度', cellh), P('001 V4.11', cellh), P('lhb888 v3', cellh), P('早盘1030 v8.1', cellh)],
    ['建仓时点', '09:32 盘前快照限价', '10:30', '10:30'],
    ['热点板块判定', '板块强度分(涨停率/上涨率/MA20比/均值) + 主线取3 + 剔除标签/连败冷却', '申万一级行业平均涨幅排名 Top10', '无独立题材榜，靠个股涨幅区间 + 板块共振(默认 OFF)'],
    ['信号日涨幅带', '窄带 [4%, 5%]', '主板 3%~4% / 科创·创业 6%~8%', '主板 3%~4% / 科创·创业 6%~8%'],
    ['量比下限', '≥ 1.2', '≥ 1.5', '≥ 1.5'],
    ['站线要求', '站 MA20', '站 MA20 + MA60，均线多头 shape≥2', '站 MA20，回踩 cur≥open'],
    ['总仓上限', '6 只', '5 只', '6 只'],
    ['每日新建上限', '≤ 1 笔', '封顶到 5 只余额', '≤ 2 笔(回收轮)'],
    ['单票仓位', '启动 15% / 扩散 12%', '18%(强度加权, 上限30%)', '17% × score^1.6(上限22%)'],
    ['止损', 'ATR 带 clamp [4%, 6%]', '硬止损分板 -4% / -7%', '固定 -5%(盘中放宽 -8%)'],
    ['止盈', '分批 +15% 减半；移动止盈武装5%/回撤15%', '分批 +6%/8% 减半(至1/4)，+30% 全清；保本止损', '+10% 减半 / +15% 清仓；峰值回撤8% 武装5%'],
    ['破均线出场', '破 10 日线(14:45 后确认)', '破 20 日线', '破 3 日线 + 破 20 日线兜底'],
    ['大市择时/避险', '中证1000<MA20 或 MA5<MA20 → halt 全停；涨停<25 停开仓', '沪深300<MA20 → 暂停建仓；无情绪闸门', '情绪闸门 HALF(预算×0.5、候选减半)；8 巡检时点'],
    ['风控指数', '000852 中证1000', '000300 沪深300', '情绪指标(非宽基 MA 为主)'],
]
# wrap long cells
wrapped = [param_rows[0]]
for row in param_rows[1:]:
    wrapped.append([P(row[0]), P(row[1]), P(row[2]), P(row[3])])
E.append(make_table(wrapped, [28*mm, 48*mm, 50*mm, 50*mm]))

# ---- 二、相同点 ----
E.append(Paragraph('二、相同点', h2))
same = [
    '策略本质一致：都是「热点/强势股动量」打法——盘前或盘中识别强势方向，买入已启动、未封板的个股。',
    '都不追涨停：三套均剔除已封板股，避免次日接力风险。',
    '都要求站上 MA20：把「趋势向上」作为硬门槛，过滤下降通道个股。',
    '量比作动量确认：001 用 ≥1.2，lhb888/1030 用 ≥1.5，都以放量确认强度。',
    '强度评分同构：均采用 涨幅 + 连板×k + min(量比,3)×m + 均线形态×n 的打分公式排序。',
    '都含「分批止盈 + 破均线出场 + 峰值回撤 + 时间止损」四件套，且都剔除 ST、设最小上市天数与最小成交额门槛。',
    '都有大盘择时/避险层：不会在系统性风险中无条件满仓。',
]
E.append(ListFlowable([ListItem(Paragraph(x, bullet), leftIndent=6) for x in same],
                      bulletType='bullet', start='•'))

# ---- 三、关键不同点 ----
E.append(Paragraph('三、关键不同点（设计取向差异）', h2))
diff = [
    '热点识别粒度：001 最精细(板块强度分+主线取3+衰退判据+连败冷却)；lhb888 用申万行业平均涨幅排名，偏行业级；1030 默认不做主线筛选，靠个股涨幅间接圈定，最粗。',
    '信号日涨幅带宽：001 用极窄 [4%,5%](精准抓启动，但易空仓)；另两套用 [3%,4%]/[6%,8%](覆盖更广，候选更多)。',
    '止损哲学：001 用 ATR 自适应带 [4%,6%](波动大时给更大容错)；lhb888/1030 用固定百分比(简单可预期，但震荡市易被洗)。',
    '大市避险激进度：001 的 halt 是「主跌段全停建仓」最果断；lhb888 仅暂停新建、已持仓照常；1030 用情绪闸门 HALF 只减仓不空仓，最温和。',
    '建仓节奏：001 每日新建≤1笔+3天冷静期(最克制)；1030 有额度回收顺延可补建≤2笔；lhb888 当日平仓即释放额度(最灵活)。',
    '注：lhb888 文件名带 lhb 但代码无龙虎榜接口，热点纯靠价格/行业强度；001 用中证1000、lhb888 用沪深300 作风控指数，对「市」的感知口径不同。',
]
E.append(ListFlowable([ListItem(Paragraph(x, bullet), leftIndent=6) for x in diff],
                      bulletType='bullet', start='•'))

# ---- 四、不同大市环境优缺点 ----
E.append(Paragraph('四、不同大市环境下的优缺点', h2))
regime_defs = [
    ('1. 上升市（板块轮动活跃、趋势明确）', [
        ['001 V4.11', '✅ 窄带抓启动精准，halt 只在主跌触发不误伤，ATR 让利润奔跑', '❌ 每日≤1笔+冷静期建仓慢，易踏空连续强势连涨，窄带可能长期空仓'],
        ['lhb888 v3', '✅ 行业共振+无情绪闸门，上升市敢满仓5只、吃满主升', '❌ 破20日线才出，单票-4%硬止损在上升洗盘中可能频繁被洗'],
        ['早盘1030 v8.1', '✅ 情绪闸门HALF过热只减仓不空仓，8时点巡检锁利，强度加权抓最强', '❌ 固定-5%在洗盘易被洗，板块共振默认OFF错失主线加成'],
    ]),
    ('2. 震荡市（区间反复、板块快速轮动）', [
        ['001 V4.11', '✅ 每日≤1笔+窄带过滤杂波，ATR[4,6%]容错适中', '❌ 频繁halt/冷静期长期低仓位空耗，震荡中难盈利'],
        ['lhb888 v3', '✅ 站MA20+MA60+均线多头过滤，假突破少', '❌ 无情绪闸门，行业轮动快易追高点；硬止损-4%震荡磨损大'],
        ['早盘1030 v8.1', '✅ 情绪闸门HALF冰点保护，8巡检时点及时发现转弱', '❌ 固定-5%+破3日线震荡中频繁触发，回收机制反复进出'],
    ]),
    ('3. 下跌市 / 主跌段', [
        ['001 V4.11', '✅ halt 全停最果断，主跌段不新建，回撤最小', '❌ 已持仓破10日线需14:45后确认，主跌次日低开仍有暴露'],
        ['lhb888 v3', '✅ 沪深300<MA20暂停新建，减少新亏', '❌ 已持仓破20日线才清，主跌回撤最大；无情绪闸门反应慢'],
        ['早盘1030 v8.1', '✅ 情绪闸门冰点判定+多时点巡检，较早降仓', '❌ 固定-5%暴跌可能一字板无法执行；破3日线主跌连续快速止损'],
    ]),
]
for title_txt, rows in regime_defs:
    E.append(Paragraph(title_txt, ParagraphStyle('rt', fontName=FONT, fontSize=10.5,
                                                 leading=14, textColor=HDR, spaceBefore=6, spaceAfter=3)))
    data = [[P('策略', cellh), P('优点', cellh), P('缺点', cellh)]] + \
           [[P(r[0]), P(r[1]), P(r[2])] for r in rows]
    E.append(make_table(data, [30*mm, 67*mm, 67*mm]))

# ---- 五、回测实证 ----
E.append(Paragraph('五、回测实证印证（2026-05-06 ~ 06-30）', h2))
back = [
    [P('策略', cellh), P('起点', cellh), P('终点', cellh), P('区间收益', cellh), P('峰值', cellh), P('最大回撤特征', cellh)],
    [P('001 V4.11'), P('100,058'), P('107,004'), P('+7.0%'), P('107,799 (6/26)'), P('最小，多次回踩 97,669(6/2) 约 -2.3%')],
    [P('lhb888 v3'), P('100,000'), P('115,362'), P('+15.4%'), P('117,777 (6/18)'), P('最平滑，峰值后仅回吐约 2%')],
    [P('早盘1030 v8.1'), P('100,000'), P('101,176'), P('+1.2%'), P('112,489 (6/2)'), P('最大，6月从峰值回撤近 10%')],
]
E.append(make_table(back, [30*mm, 22*mm, 22*mm, 20*mm, 27*mm, 43*mm]))
E.append(Spacer(1, 6))
E.append(Paragraph(
    '结论：001 最防御(回撤最小)；lhb888 收益最强且平滑(风险调整收益最佳)；早盘1030 高波动低收益，'
    '在「由强转弱」市况磨损最大。注：三套总资产口径不一致(001 为盘后净值，另两套为买入时快照)，'
    '横向绝对数值仅供趋势参考，不可直接相减。', body))

doc.build(E)
print('PDF saved ->', OUT)
