# -*- coding: utf-8 -*-
"""
hotspot_trader_v1_ptrade.py
=====================================================================
自选股 · 热点短线突破策略（Ptrade / QMT 托管机骨架  v1.7）
---------------------------------------------------------------------
设计目标（与彬哥哥商定）：
  选股 = 热点板块追踪结果 ∩ 股价站上5/10日线（多头排列）∩ 连续两天放量上涨 ∩ 非涨停
  出场 = ATR 自适应移动止盈 + 固定百分比硬止损 + 保本线 + 分批减仓 + 时间止损
  执行 = 自有资金波短，T+1，单票风险预算控仓
  v1.3 硬性剔除：ST/*ST、次新股(上市<250交易日)；只买 WATCHLIST；换手率<20%(百分比单位)；同板块≤40% 集中度
  v1.7 硬性剔除追加：科创板(688开头)——8个月回测 688019 一笔 -24.8%(隔夜跳空击穿5%止损)，方案A直接剔除；时间止损日志补盈利%
  v1.3 修正(山西证券官方API文档核对)：
    . before_trading_start(context, data) 两参 OK；run_daily 回调只收 context(无 data) -> 现价改由 get_snapshot(交易)/get_history(回测) 兜底
    . get_history(is_dict=True) 返回 2D 数组(行=K线,列=字段)，_hist 已转成 {字段:array} 供 df['close'] 访问，修掉必崩
    . 换手率主用 volume(股)/流通股本(股)*100；流通股本经 get_fundamentals('valuation') 多候选字段探测；get_snapshot 仅交易可用
    . valuation 表字段名以券商实盘为准(探针打印实际列名)，a_floats/turnover_rate 为 JOINQUANT 命名 PTrade 未必一致
  v1.4 修正(回测实跑暴露，逐条对回官方文档)：
    . run_daily 真实签名=run_daily(context, func, time='9:31')(官方 line 916)；原写 run_daily(func, time) -> 平台把字符串当回调 -> 'str' object is not callable(致命崩溃)
    . 日志兼容层：平台 log.* 只收【单条字符串】、不替我做 % 格式化(官方示例均为 '...' % x)，已包 _Log 预格式化层，回测异常/列名才可见
    . 探针改为先 fields=None+上一交易日 拉 valuation 全部列名，再逐候选字段兜底探测，把真机可用列缓存到 _DISC_FLOAT_COL/_DISC_TURN_COL

平台铁律（来自 ptrade-strategy-dev 技能，违反即静默错）：
  R1 可交易性优先  R2 信号只用已完成数据  R3 经济性先于策略  R4 接口降级必告警
  - Python 3.5：无 f-string / 无类型注解 / 无 os 模块 / 无外网
  - get_history(count, frequency, field, security_list, fq, include, fill, is_dict)
    末根=昨收（盘前 include=False）；volume 单位=股；单股传字符串/多股传列表返回结构不同
    is_dict=True 返回 OrderedDict({代码: 2D数组[(日期,开,高,低,收,量,额,最新价),...]})，列序=所请字段(可能前置日期列)
  - get_fundamentals(security, table, fields=...)：流通股本/换手率用 table='valuation'；不传 date 取上一交易日(回测无未来函数)
    valuation 表字段名以券商为准(见探针日志)；get_snapshot.circulation_amount=流通股本(股)、turnover_ratio=换手率(ratio,*100=%) 为交易专属
  - before_trading_start(context, data) 两参；run_daily 回调只收 context(无 data) -> 现价勿依赖 data，用 get_history(include=True)/get_snapshot 兜底
  - 持仓 get_positions() 返回 dict[str:Position]，必须判形态
  - 当日价：handle_data 用 data[code].price；run_daily 用 get_snapshot(交易,last_px)/get_history(include=True,回测)
  - 涨跌幅按板：30/68->20%  8/4->30%  ST->5%  其余10%
  - 代码后缀 .SS / .SZ / .BJ

==== 上线前必做（详见同目录 hotspot_trader_v1_部署清单.md）====
  1. 核对你所在券商的 get_history / 持仓 / 快照口径（国金 vs 山西口径见技能文档）
  2. 填 WATCHLIST（你的自选股，6位代码）
  3. 填 HOT_SECTORS（热点板块追踪技能的输出）或保持 MOMENTUM_FALLBACK=True
  4. 用 >=1 年历史做回测，含牛/熊/震荡，扣手续费滑点，标定 TRAIL_K / STOP_LOSS_PCT
  5. 默认 TRADE_ENABLED=False，先信号模式跑 3~5 日核对日志，再模拟盘，最后小资金实盘
=====================================================================
"""

import datetime

# ============================ 日志兼容层 ============================
# 山西证券 PTrade 的 log.* 只接受【单条字符串】，不替我做 % 格式化
# （官方文档示例均为 '...%s' % x 预格式化）。这里包一层，统一预格式化后
# 再交给平台真实 log，保证回测日志里的异常/列名可见。
try:
    __ptrade_log__ = log   # 捕获平台注入的真实 log（在 shadow 之前）
except NameError:
    __ptrade_log__ = None


class _Log(object):
    def _emit(self, meth, msg, args):
        if args:
            try:
                msg = msg % args
            except Exception:
                pass
        rl = globals().get('__ptrade_log__')
        if rl is not None:
            try:
                getattr(rl, meth)(msg)
            except Exception:
                pass
        else:
            # 托管机禁用 sys 模块，无 log 环境静默丢弃
            pass

    def info(self, msg, *args):
        self._emit('info', msg, args)

    def warning(self, msg, *args):
        self._emit('warning', msg, args)

    def error(self, msg, *args):
        self._emit('error', msg, args)

    def debug(self, msg, *args):
        self._emit('debug', msg, args)

    def critical(self, msg, *args):
        self._emit('critical', msg, args)


log = _Log()

FLOAT_CANDIDATES = ['a_floats', 'float_a_shares', 'circulation_amount', 'float_shares',
                    'circulating_shares', 'free_shares', 'free_float_shares']
TURNOVER_CANDIDATES = ['turnover_rate', 'turnover_ratio', 'turnover']
_DISC_FLOAT_COL = None
_PROBE_DONE = False      # 盘前探针只跑一次（初始化阶段禁 get_fundamentals）
_DISC_TURN_COL = None    # 探针发现的换手率列名（优先于 TURNOVER_CANDIDATES）

# ============================ 参数区（上线前必调）============================
WATCHLIST = [
    '002747', '688019', '603345', '300866', '600298', '688322', '002338', '600004',
    '688235', '688525', '600989', '600845', '002151', '002371', '000737', '600111',
    '603009', '300580', '300957', '002594', '300070', '920493', '603596', '688333',
    '605376', '002297', '600707', '000408', '600497', '002866', '603233', '301068',
    '002236', '002606', '601006', '002008', '300073', '300409', '002920', '300776',
    '688818', '300054', '301377', '688668', '920593', '300059', '603606', '002167',
    '002384', '600673', '600295', '002812', '600563', '000629', '600516', '300602',
    '300395', '002027', '600498', '603686', '301529', '600660', '600196', '300497',
    '002460', '300034', '002414', '300499', '603588', '002241', '002340', '601398',
    '601138', '002741', '300620', '002625', '300699', '002281', '002967', '688548',
    '001389', '301095', '600519', '300285', '600406', '688027', '002768', '301526',
    '002074', '002311', '688041', '002415', '301292', '600515', '601882', '603288',
    '002320', '600060', '600583', '688256', '300007', '600323', '002430', '600893',
    '000738', '002389', '002025', '600879', '600343', '000547', '000901', '603260',
    '600487', '600346', '601100', '600276', '603985', '600885', '603256', '688088',
    '600316', '002541', '603267', '002463', '300012', '300676', '301269', '000963',
    '688629', '688200', '000988', '688120', '600521', '688639', '002645', '688347',
    '600426', '603296', '688396', '601688', '688268', '002185', '003043', '002906',
    '603799', '601231', '300124', '688388', '601939', '301308', '300666', '002484',
    '600919', '600362', '002353', '300829', '300748', '300999', '688676', '688111',
    '603505', '000725', '601816', '600577', '688627', '600160', '600699', '300223',
    '301338', '002821', '688065', '600552', '300759', '300601', '603662', '002422',
    '300662', '002518', '300418', '688008', '688018', '002979', '301071', '300184',
    '002475', '300343', '688271', '688400', '002601', '603993', '688017', '300760',
    '002851', '000333', '601677', '603728', '300346', '601009', '601018', '002142',
    '300750', '600377', '605123', '002938', '300438', '600312', '603605', '603659',
    '002439', '002557', '603027', '000837', '688331', '002493', '300339', '300442',
    '301293', '603938', '002050', '300408', '601360', '688336', '600031', '600549',
    '688778', '600547', '000803', '601225', '600018', '601727', '600009', '600315',
    '300236', '600104', '000021', '002916', '300454', '000062', '000089', '601139',
    '600183', '300661', '002299', '688117', '300476', '688820', '002446', '688082',
    '603688', '002602', '603881', '002472', '002585', '002273', '002352', '002028',
    '300179', '601126', '300331', '688072', '601689', '300607', '600089', '301219',
    '002709', '300394', '002466', '002009', '002354', '688234', '002156', '603650',
    '601233', '301217', '000630', '600309', '002034', '002801', '000338', '002372',
    '002130', '603773', '300142', '002886', '000858', '603667', '688122', '601168',
    '000762', '000960', '300450', '002015', '688630', '688037', '600596', '000997',
    '301076', '002001', '300502', '300037', '002294', '300136', '301536', '600141',
    '000426', '000425', '000400', '000526', '002409', '000792', '002847', '600188',
    '300373', '600486', '603259', '002922', '600887', '603236', '300014', '301171',
    '603308', '688087', '002846', '000795', '301021', '002837', '000967', '300143',
    '002925', '600105', '002326', '600206', '603217', '600233', '688498', '000538',
    '002428', '600096', '002120', '300604', '600584', '601869', '688048', '600900',
    '001965', '601872', '600036', '603986', '002266', '603338', '600352', '600320',
    '300224', '601877', '000519', '002080', '600685', '688146', '003031', '002896',
    '688295', '300814', '600150', '601669', '003816', '600938', '601985', '601611',
    '601117', '600176', '601600', '601868', '601318', '601628', '601088', '600028',
    '601857', '601601', '601698', '600118', '000831', '000066', '601888', '601808',
    '002179', '600760', '000768', '002364', '000039', '300308', '600489', '000060',
    '600872', '300496', '000970', '603019', '002738', '000157', '600138', '300684',
    '002092', '600522', '688012', '000657', '688297', '600259', '688981', '000099',
    '000708', '600030', '000063', '301150', '300327', '601919', '600026', '600961',
    '002049', '601899',
]

# 热点板块：由「热点板块追踪技能」产出后填这里（行业名需与 INDUSTRY_MAP 一致）
# 留空 + MOMENTUM_FALLBACK=True 时，自动用自选股内动量最强的票当伪热点
HOT_SECTORS = []
INDUSTRY_MAP = {
    '002747': '机械设备', '688019': '电子', '603345': '食品饮料', '300866': '电子',
    '600298': '食品饮料', '688322': '电子', '002338': '国防军工', '600004': '交通运输',
    '688235': '医药生物', '688525': '电子', '600989': '基础化工', '600845': '计算机',
    '002151': '国防军工', '002371': '电子', '000737': '有色金属', '600111': '有色金属',
    '603009': '汽车', '300580': '汽车', '300957': '美容护理', '002594': '汽车',
    '300070': '环保', '920493': '计算机', '603596': '汽车', '688333': '机械设备',
    '605376': '有色金属', '002297': '国防军工', '600707': '电子', '000408': '基础化工',
    '600497': '有色金属', '002866': '电子', '603233': '医药生物', '301068': '环保',
    '002236': '计算机', '002606': '电力设备', '601006': '交通运输', '002008': '机械设备',
    '300073': '电力设备', '300409': '电力设备', '002920': '汽车', '300776': '电力设备',
    '688818': '国防军工', '300054': '电子', '301377': '机械设备', '688668': '通信',
    '920593': '机械设备', '300059': '非银金融', '603606': '电力设备', '002167': '有色金属',
    '002384': '电子', '600673': '综合', '600295': '钢铁', '002812': '电力设备',
    '600563': '电子', '000629': '有色金属', '600516': '钢铁', '300602': '电子',
    '300395': '建筑材料', '002027': '传媒', '600498': '通信', '603686': '环保',
    '301529': '汽车', '600660': '汽车', '600196': '医药生物', '300497': '医药生物',
    '002460': '有色金属', '300034': '国防军工', '002414': '国防军工', '300499': '机械设备',
    '603588': '环保', '002241': '电子', '002340': '电力设备', '601398': '银行',
    '601138': '电子', '002741': '电子', '300620': '通信', '002625': '国防军工',
    '300699': '基础化工', '002281': '通信', '002967': '社会服务', '688548': '电子',
    '001389': '电子', '301095': '电子', '600519': '食品饮料', '300285': '电子',
    '600406': '电力设备', '688027': '通信', '002768': '基础化工', '301526': '建筑材料',
    '002074': '电力设备', '002311': '农林牧渔', '688041': '电子', '002415': '计算机',
    '301292': '电力设备', '600515': '交通运输', '601882': '机械设备', '603288': '食品饮料',
    '002320': '交通运输', '600060': '家用电器', '600583': '石油石化', '688256': '电子',
    '300007': '机械设备', '600323': '环保', '002430': '机械设备', '600893': '国防军工',
    '000738': '国防军工', '002389': '国防军工', '002025': '国防军工', '600879': '国防军工',
    '600343': '机械设备', '000547': '国防军工', '000901': '汽车', '603260': '基础化工',
    '600487': '通信', '600346': '石油石化', '601100': '机械设备', '600276': '医药生物',
    '603985': '电力设备', '600885': '电力设备', '603256': '建筑材料', '688088': '计算机',
    '600316': '国防军工', '002541': '建筑装饰', '603267': '国防军工', '002463': '电子',
    '300012': '社会服务', '300676': '医药生物', '301269': '电子', '000963': '医药生物',
    '688629': '国防军工', '688200': '电子', '000988': '机械设备', '688120': '电子',
    '600521': '医药生物', '688639': '基础化工', '002645': '环保', '688347': '电子',
    '600426': '基础化工', '603296': '电子', '688396': '电子', '601688': '非银金融',
    '688268': '电子', '002185': '电子', '003043': '电子', '002906': '汽车',
    '603799': '有色金属', '601231': '电子', '300124': '机械设备', '688388': '电力设备',
    '601939': '银行', '301308': '电子', '300666': '电子', '002484': '电子',
    '600919': '银行', '600362': '有色金属', '002353': '机械设备', '300829': '基础化工',
    '300748': '有色金属', '300999': '农林牧渔', '688676': '电力设备', '688111': '计算机',
    '603505': '基础化工', '000725': '电子', '601816': '交通运输', '600577': '电力设备',
    '688627': '机械设备', '600160': '基础化工', '600699': '汽车', '300223': '电子',
    '301338': '机械设备', '002821': '医药生物', '688065': '基础化工', '600552': '电子',
    '300759': '医药生物', '300601': '医药生物', '603662': '机械设备', '002422': '医药生物',
    '300662': '社会服务', '002518': '电力设备', '300418': '传媒', '688008': '电子',
    '688018': '电子', '002979': '机械设备', '301071': '基础化工', '300184': '电子',
    '002475': '电子', '300343': '基础化工', '688271': '医药生物', '688400': '机械设备',
    '002601': '基础化工', '603993': '有色金属', '688017': '机械设备', '300760': '医药生物',
    '002851': '电力设备', '000333': '家用电器', '601677': '有色金属', '603728': '电力设备',
    '300346': '电子', '601009': '银行', '601018': '交通运输', '002142': '银行',
    '300750': '电力设备', '600377': '交通运输', '605123': '国防军工', '002938': '电子',
    '300438': '电力设备', '600312': '电力设备', '603605': '美容护理', '603659': '电力设备',
    '002439': '计算机', '002557': '食品饮料', '603027': '食品饮料', '000837': '机械设备',
    '688331': '医药生物', '002493': '基础化工', '300339': '计算机', '300442': '计算机',
    '301293': '医药生物', '603938': '基础化工', '002050': '家用电器', '300408': '电子',
    '601360': '计算机', '688336': '医药生物', '600031': '机械设备', '600549': '有色金属',
    '688778': '电力设备', '600547': '有色金属', '000803': '环保', '601225': '煤炭',
    '600018': '交通运输', '601727': '电力设备', '600009': '交通运输', '600315': '美容护理',
    '300236': '电子', '600104': '汽车', '000021': '电子', '002916': '电子',
    '300454': '计算机', '000062': '电子', '000089': '交通运输', '601139': '公用事业',
    '600183': '电子', '300661': '电子', '002299': '农林牧渔', '688117': '医药生物',
    '300476': '电子', '688820': '电子', '002446': '国防军工', '688082': '电子',
    '603688': '基础化工', '002602': '传媒', '603881': '计算机', '002472': '汽车',
    '002585': '基础化工', '002273': '电子', '002352': '交通运输', '002028': '电力设备',
    '300179': '机械设备', '601126': '电力设备', '300331': '电子', '688072': '电子',
    '601689': '汽车', '300607': '机械设备', '600089': '电力设备', '301219': '有色金属',
    '002709': '电力设备', '300394': '通信', '002466': '有色金属', '002009': '机械设备',
    '002354': '传媒', '688234': '电子', '002156': '电子', '603650': '基础化工',
    '601233': '基础化工', '301217': '有色金属', '000630': '有色金属', '600309': '基础化工',
    '002034': '环保', '002801': '电力设备', '000338': '汽车', '002372': '建筑材料',
    '002130': '电子', '603773': '电子', '300142': '医药生物', '002886': '基础化工',
    '000858': '食品饮料', '603667': '机械设备', '688122': '有色金属', '601168': '有色金属',
    '000762': '有色金属', '000960': '有色金属', '300450': '电力设备', '002015': '公用事业',
    '688630': '机械设备', '688037': '电子', '600596': '基础化工', '000997': '计算机',
    '301076': '基础化工', '002001': '基础化工', '300502': '通信', '300037': '电力设备',
    '002294': '医药生物', '300136': '电子', '301536': '电子', '600141': '基础化工',
    '000426': '有色金属', '000425': '机械设备', '000400': '电力设备', '000526': '社会服务',
    '002409': '电子', '000792': '基础化工', '002847': '食品饮料', '600188': '煤炭',
    '300373': '电子', '600486': '基础化工', '603259': '医药生物', '002922': '电力设备',
    '600887': '食品饮料', '603236': '通信', '300014': '电力设备', '301171': '传媒',
    '603308': '机械设备', '688087': '环保', '002846': '轻工制造', '000795': '有色金属',
    '301021': '机械设备', '002837': '机械设备', '000967': '环保', '300143': '医药生物',
    '002925': '电子', '600105': '通信', '002326': '基础化工', '600206': '电子',
    '603217': '基础化工', '600233': '交通运输', '688498': '电子', '000538': '医药生物',
    '002428': '有色金属', '600096': '基础化工', '002120': '交通运输', '300604': '电子',
    '600584': '电子', '601869': '通信', '688048': '电子', '600900': '公用事业',
    '001965': '交通运输', '601872': '交通运输', '600036': '银行', '603986': '电子',
    '002266': '环保', '603338': '机械设备', '600352': '基础化工', '600320': '机械设备',
    '300224': '有色金属', '601877': '电力设备', '000519': '国防军工', '002080': '建筑材料',
    '600685': '国防军工', '688146': '电子', '003031': '电子', '002896': '机械设备',
    '688295': '基础化工', '300814': '电子', '600150': '国防军工', '601669': '建筑装饰',
    '003816': '公用事业', '600938': '石油石化', '601985': '公用事业', '601611': '建筑装饰',
    '601117': '建筑装饰', '600176': '建筑材料', '601600': '有色金属', '601868': '建筑装饰',
    '601318': '非银金融', '601628': '非银金融', '601088': '煤炭', '600028': '石油石化',
    '601857': '石油石化', '601601': '非银金融', '601698': '国防军工', '600118': '国防军工',
    '000831': '有色金属', '000066': '计算机', '601888': '社会服务', '601808': '石油石化',
    '002179': '国防军工', '600760': '国防军工', '000768': '国防军工', '002364': '电力设备',
    '000039': '机械设备', '300308': '通信', '600489': '有色金属', '000060': '有色金属',
    '600872': '食品饮料', '300496': '计算机', '000970': '有色金属', '603019': '计算机',
    '002738': '有色金属', '000157': '机械设备', '600138': '社会服务', '300684': '电子',
    '002092': '基础化工', '600522': '通信', '688012': '电子', '000657': '有色金属',
    '688297': '国防军工', '600259': '有色金属', '688981': '电子', '000099': '交通运输',
    '000708': '钢铁', '600030': '非银金融', '000063': '通信', '301150': '电力设备',
    '300327': '电子', '601919': '交通运输', '600026': '交通运输', '600961': '有色金属',
    '002049': '电子', '601899': '有色金属',
}
MOMENTUM_FALLBACK = True
MOM_TOP_N = 15  # 动量兜底时取前 N 名

# ---- 选股阈值 ----
VOL_UP_RATIO = 1.2      # 量能较前一日放大倍数（连续两天）
VOL_MA5_RATIO = 1.3     # 当日量 > 5日均量倍数
NON_LIMIT_PAD = 0.98    # 非涨停：涨幅 < 涨停幅度*该系数
STAGE_GAIN_CAP = 0.40   # 防追高：20日涨幅上限

# ---- 仓位 / 资金 ----
MAX_POSITIONS = 6        # 最大同时持仓数
MAX_BUYS_PER_DAY = 2     # 每日最多新开仓（防过度交易）
RISK_PER_TRADE = 0.02    # 单票最大亏损占本金（风险预算）
MAX_POSITION_PCT = 0.30  # 单票仓位上限（占净值）
MARKET_GATE = True       # 市场开关：沪深300跌破MA20则暂停新开仓

# ---- 出场（核心：科学移动止盈止损）----
STOP_LOSS_PCT = 0.05     # 初始硬止损（占成本）
BE_TRIGGER_PCT = 0.05    # 浮盈达此比例 -> 止损上移至保本
BE_GUARD = 0.01          # 保本线上浮（微利保护）
TRAIL_K = 2.5            # ATR 移动止盈倍数（k）；回测标定 2~3
TRAIL_MIN_PCT = 0.06     # ATR 缺失时的回撤百分比兜底
TP1_PCT = 0.08           # 第一批减仓盈利阈值
TP2_PCT = 0.15           # 第二批减仓盈利阈值
MAX_HOLD_DAYS = 8        # 时间止损：持仓上限天数（仍亏损才砍）

# ---- 硬性剔除 / 过滤（彬哥哥要求 v1.1）----
EXCLUDE_ST = True            # 剔除 ST / *ST
EXCLUDE_NEW_STOCK = True     # 剔除次新股
EXCLUDE_STAR = True          # 剔除科创板(688开头)：20cm波动配5%固定止损易被隔夜跳空击穿(彬哥哥拍板 方案A 2026-09-24)
NEW_STOCK_DAYS = 250         # 次新判定：上市不足 N 个交易日视为次新
TURNOVER_CAP = 20             # 换手率上限（20%，百分比单位），防庄股爆量
SECTOR_CAP = 0.40            # 同板块集中度上限（占净值）
FLOAT_SHARES = {}            # { '600519': 流通股本(股) } 换手率静态兜底；不填则运行时 get_fundamentals('valuation', a_floats)+turnover_rate 直读 + 快照兜底（见 _probe_float_source 启动自测）

TRADE_ENABLED = True     # 安全开关：False=只出信号不真下单；上线前改 True

LOG_TAG = 'HOTSPOT-V1'


# ============================ 平台兼容封装 ============================
def _canon(code):
    """任意形态代码 -> 6位纯数字。内部比较只用它。"""
    s = str(code)
    if '.' in s:
        s = s.split('.')[0]
    dig = ''.join([ch for ch in s if ch.isdigit()])
    return dig[-6:] if len(dig) >= 6 else dig


def _suffix(code):
    """6位代码 -> 带后缀（调平台API用）。指数 .SS。"""
    c = _canon(code)
    if not c:
        return code
    if '.' in str(code):
        return str(code)  # 已是带后缀的指数等
    if c[0] == '6':
        return c + '.SS'
    if c[0] in ('0', '3'):
        return c + '.SZ'
    if c[0] in ('8', '4') or c[:2] == '92':  # 北交所（含 92x 新股）
        return c + '.BJ'
    return c + '.SH' if c[0] == '5' else c + '.SZ'


def _limit_pct(code):
    """涨停幅度（小数）。ST 需名称判断，骨架默认主板10%。"""
    c = _canon(code)
    if not c:
        return 0.10
    if c[0] in ('3', '6') and c[:2] in ('30', '68'):
        return 0.20
    if c[0] in ('8', '4') or c[:2] == '92':  # 北交所（含 92x 新股）30%
        return 0.30
    # TODO: 如需精确 ST 判定，传入名称经 NAMELIKE 判断
    return 0.10


def _hist(codes, count, fields):
    """批量取历史，返回 {6位代码: {字段: 1D-array}}。失败降级逐票并告警。
    统一 is_dict=True 取数(更快)，再把 2D 数组按 fields 顺序转成字段字典，
    与下游 df['close']/df['volume']/df['high'] 访问保持一致。"""
    if isinstance(codes, str):
        codes = [codes]
    if isinstance(fields, str):
        fields = [fields]
    secs = [_suffix(c) for c in codes]
    out = {}

    def _to_dict(v):
        # is_dict 返回 2D 数组(行=K线,列=字段)；可能含前置日期列；也可能 1D(单字段)
        try:
            rows = list(v)
        except Exception:
            rows = [v]
        if not rows:
            return {fields[0]: []}
        first = rows[0]
        is_2d = (hasattr(first, '__len__') and not isinstance(first, str)) or hasattr(first, 'dtype')
        if not is_2d:
            return {fields[0]: rows}
        n = len(first)
        if n == len(fields):
            return {fields[i]: [row[i] for row in rows] for i in range(n)}
        if n == len(fields) + 1:  # 列0为日期时间，其余为字段
            return {fields[i]: [row[i + 1] for row in rows] for i in range(len(fields))}
        return {fields[i]: [row[i] for row in rows] for i in range(min(len(fields), n))}

    try:
        raw = get_history(count, '1d', fields, secs, fq='pre',
                          include=False, fill='nan', is_dict=True)
        if isinstance(raw, dict):
            for k, v in raw.items():
                out[_canon(k)] = _to_dict(v)
        else:
            out[_canon(codes[0])] = _to_dict(raw)
    except Exception as e:
        log.warning('[%s][hist] 批量取数失败: %s，降级逐票', LOG_TAG, e)
    # 缺失补单票
    for c in codes:
        if _canon(c) in out:
            continue
        try:
            r = get_history(count, '1d', fields, [_suffix(c)], fq='pre',
                            include=False, fill='nan', is_dict=True)
            if isinstance(r, dict) and r:
                for k, v in r.items():
                    out[_canon(k)] = _to_dict(v)
            elif r is not None:
                out[_canon(c)] = _to_dict(r)
        except Exception as e:
            log.warning('[%s][hist] 单票 %s 取数失败: %s', LOG_TAG, c, e)
    return out


def _get_positions(context):
    """持仓读取：兼容 dict / list[dict] / Position 对象，归一成统一字典列表。"""
    try:
        poss = get_positions()
    except Exception as e:
        log.warning('[%s][pos] get_positions 失败: %s', LOG_TAG, e)
        return []
    if poss is None:
        return []
    items = list(poss.items()) if isinstance(poss, dict) else poss
    out = []
    for it in items:
        if isinstance(it, tuple):
            code_key, p = it
        else:
            p, code_key = it, None
        if isinstance(p, dict):
            code = p.get('stock_code') or p.get('sid') or code_key
            amount = float(p.get('current_amount', p.get('amount', 0)) or 0)
            enable = float(p.get('enable_amount', 0) or 0)
            cost = float(p.get('cost_price', p.get('cost_basis', 0)) or 0)
        else:
            code = getattr(p, 'sid', None) or code_key
            amount = float(getattr(p, 'amount', 0) or 0)
            enable = float(getattr(p, 'enable_amount', 0) or 0)
            cost = float(getattr(p, 'cost_basis', 0) or 0)
        out.append({'code': _canon(code), 'amount': amount,
                    'enable_amount': enable, 'cost_basis': cost})
    return out


def _account(context):
    """账户信息：PTrade 无 get_account，读 context.portfolio。"""
    pf = context.portfolio
    return {'value': float(pf.portfolio_value or 0),
            'cash': float(pf.cash or 0),
            'positions_value': float(pf.positions_value or 0)}


def _cur_price(code, data=None):
    """当日价(带后缀代码)。优先级：handle_data 的 data[code].price -> get_history(include=True,
    回测/实盘通用，避免回测调 get_snapshot 刷 WARNING) -> get_snapshot.last_px(仅交易兜底)。返回 0 表示取不到。"""
    try:
        if data is not None and code in data:
            return float(data[code].price)
    except Exception:
        pass
    try:
        h = get_history(1, '1d', 'close', [code], fq='pre',
                        include=True, fill='nan', is_dict=True)
        if isinstance(h, dict) and code in h:
            rows = list(h[code])
            if rows:
                last = rows[-1]
                if hasattr(last, '__len__') and len(last) >= 1:
                    return float(last[-1])  # 末列=close（可能前置日期列）
                return float(last)
    except Exception:
        pass
    try:
        snap = get_snapshot([code])
        if snap and code in snap:
            d = snap[code]
            px = d.get('last_px', d.get('last_price', 0))
            if px:
                return float(px)
    except Exception:
        pass
    return 0.0


def _atr(high, low, close, n=14):
    """Wilder ATR。返回 0 表示数据不足。"""
    if len(close) < 2:
        return 0.0
    trs = []
    for i in range(1, len(close)):
        tr = max(high[i] - low[i],
                 abs(high[i] - close[i - 1]),
                 abs(low[i] - close[i - 1]))
        trs.append(tr)
    if len(trs) < n:
        return trs[-1] if trs else 0.0
    val = sum(trs[:n]) / float(n)
    for t in trs[n:]:
        val = (val * (n - 1) + t) / float(n)
    return val


# ============================ 硬剔除 / 过滤 / 板块 ============================
def _dt_now(context):
    """可靠时钟：优先 context.blotter.current_dt（技能提示 context.current_dt 不可靠）。"""
    for src in (getattr(context, 'blotter', None), context):
        dt = getattr(src, 'current_dt', None)
        if dt is not None:
            return dt
    return None


def _sec_info(code):
    """证券静态信息（名称/上市日）。失败降级告警。"""
    try:
        return get_security_info(_suffix(code))
    except Exception as e:
        log.warning('[%s][sec] %s 证券信息取数失败: %s', LOG_TAG, code, e)
        return None


def _parse_date(d):
    if d is None:
        return None
    if isinstance(d, datetime.datetime) or isinstance(d, datetime.date):
        return d
    if isinstance(d, str):
        s = d[:10]
        for fmt in ('%Y-%m-%d', '%Y%m%d'):
            try:
                return datetime.datetime.strptime(s, fmt)
            except Exception:
                pass
    return None


def _is_st(code):
    """剔除 ST / *ST（基于证券名称）。取不到名称则告警并保守按非ST处理。"""
    if not EXCLUDE_ST:
        return False
    name = ''
    info = _sec_info(code)
    if info is not None:
        name = getattr(info, 'name', '') or getattr(info, 'sec_name', '') or ''
    if not name:
        try:
            snap = get_snapshot([_suffix(code)])
            if snap and _suffix(code) in snap:
                name = snap[_suffix(code)].get('name', '') or ''
        except Exception:
            pass
    if not name:
        log.warning('[%s][st] %s 名称取不到，按非ST处理(无法剔除)', LOG_TAG, code)
        return False
    u = name.upper()
    return u.startswith('ST') or u.startswith('*ST') or ('*ST' in u)


def _listing_date(code):
    info = _sec_info(code)
    if info is not None:
        d = getattr(info, 'list_date', None) or getattr(info, 'start_date', None)
        return _parse_date(d)
    return None


def _bars_count(code):
    """取该股日线根数（次新股兜底判定用）。取不到返回 None。"""
    try:
        h = _hist([code], NEW_STOCK_DAYS + 2, ['close'])
        df = h.get(_canon(code))
        if not df:
            return None
        cl = df.get('close') or []
        cl = [x for x in cl if x is not None and x == x]
        return len(cl)
    except Exception:
        return None


def _is_new_stock(code, now_dt):
    """剔除次新股：上市不足 NEW_STOCK_DAYS 个交易日。取不到上市日则告警按非次新。"""
    if not EXCLUDE_NEW_STOCK:
        return False
    ld = _listing_date(code)
    if ld is None:
        # 回测环境 get_security_info 常缺上市日期：用日线根数兜底（不足 NEW_STOCK_DAYS 根≈次新）
        n = _bars_count(code)
        if n is None:
            log.warning('[%s][new] %s 上市日期/日线根数均取不到，按非次新处理(无法剔除)', LOG_TAG, code)
            return False
        if n < NEW_STOCK_DAYS:
            log.info('[%s][new] %s 日线仅%d根(<%d)，判定次新剔除', LOG_TAG, code, n, NEW_STOCK_DAYS)
            return True
        return False
    try:
        days = (now_dt - ld).days
    except Exception:
        return False
    return days < NEW_STOCK_DAYS


def _num(x):
    """尽力转 float；'%'字符串(如"3.5%")、千分位、nan 都兼容。失败返回 None。"""
    try:
        if x is None:
            return None
        if isinstance(x, str):
            t = x.replace('%', '').replace(',', '').strip()
            if t == '' or t in ('nan', 'None'):
                return None
            return float(t)
        if hasattr(x, 'item'):  # numpy scalar
            x = x.item()
        f = float(x)
        if f != f:  # nan
            return None
        return f
    except Exception:
        return None


def _extract_scalar(df, col=None):
    """从 get_fundamentals 多形态返回里抠出标量值。col 指定优先列名。取不到返回 None。
    PTrade get_fundamentals('valuation') 返回 pandas DataFrame：index=股票, columns=字段。"""
    try:
        if df is None:
            return None
        if isinstance(df, dict):
            if col and col in df:
                return _extract_scalar(df[col], col)
            for k in df:
                v = df[k]
                if v is not None:
                    return _extract_scalar(v, col)
            return None
        if isinstance(df, (list, tuple)):
            if not df:
                return None
            return _extract_scalar(df[0], col)
        if hasattr(df, 'iloc'):  # pandas Series / DataFrame
            if hasattr(df, 'columns'):  # DataFrame
                c = col if (col and col in list(df.columns)) else df.columns[0]
                return _num(df[c].iloc[0])
            return _num(df.iloc[0])
        return _num(df)
    except Exception:
        return None


def _float_shares(code):
    """流通股本(股)。静态表 -> 探针发现列 -> get_fundamentals('valuation') 多候选字段 -> get_snapshot(交易) 兜底。
    取不到返回 None。valuation 表字段名以券商实盘为准；单位按股(参考 snapshot.circulation_amount=股)。"""
    fs = FLOAT_SHARES.get(_canon(code))
    if fs:
        return float(fs)
    cand = []
    if _DISC_FLOAT_COL:
        cand.append(_DISC_FLOAT_COL)
    cand += FLOAT_CANDIDATES
    for name in cand:
        try:
            df = get_fundamentals([_suffix(code)], 'valuation', fields=[name])
        except Exception:
            continue
        v = _extract_scalar(df, name)
        if v and v > 0:
            return float(v)  # 股（PTrade 流通字段均为股，不乘1e4）
    # 快照兜底（仅交易；circulation_amount=股）
    try:
        snap = get_snapshot([_suffix(code)])
        d = snap.get(_suffix(code)) if snap else None
        if d:
            fv = _num(d.get('circulation_amount'))
            if fv and fv > 0:
                return fv
    except Exception:
        pass
    return None


def _turnover_rate(code, vol):
    """换手率(%)。主用 volume(股)/流通股本(股)*100（回测可用，单位自校）；
    备用 get_fundamentals('valuation') 直读(实测 turnover_rate 已是百分比，直读不×100、异常量纲自愈)。取不到返回 None。"""
    # 主路径：量 / 流通股本（最可靠，依赖 get_history volume 单位为股）
    fs = _float_shares(code)
    if fs and fs > 0 and vol and vol > 0:
        to = vol / fs * 100.0
        if to > 100 and to / 1e4 <= 100:  # 单位疑似万股(流通偏小1e4) -> 放大1e4
            to = to / 1e4
        if 0 < to <= 100:
            return to
    # 备路径：估值表直读（探针发现列优先）
    cand = []
    if _DISC_TURN_COL:
        cand.append(_DISC_TURN_COL)
    cand += TURNOVER_CANDIDATES
    for name in cand:
        try:
            df = get_fundamentals([_suffix(code)], 'valuation', fields=[name])
        except Exception:
            continue
        tv = _extract_scalar(df, name)
        if tv is not None and tv >= 0:
            # 实测山西证券 turnover_rate 已是百分比(4.2310=4.23%)：直读不再×100；
            # >100 物理不可能(换手率<=100%) -> 按 ratio 误读 ÷100 自愈；
            # <0.05 大概率是 ratio(0.0042=0.42%) -> ×100 自愈
            if tv > 100.0 and tv / 100.0 <= 100.0:
                tv = tv / 100.0
            elif tv < 0.05 and tv * 100.0 <= 100.0:
                tv = tv * 100.0
            return tv
    return None


def _sector_of(code):
    """行业映射：返回板块名或 None。"""
    return INDUSTRY_MAP.get(_canon(code))


def _sector_exposure(context, sector):
    """某板块当前持仓市值 + 当日已买市值。"""
    val = 0.0
    for p in _get_positions(context):
        if p['amount'] <= 0:
            continue
        if _sector_of(p['code']) == sector:
            val += p['cost_basis'] * p['amount']
    val += context.day_sector_buy.get(sector, 0.0)
    return val


# ============================ 选股 ============================
def _ma(arr, n):
    if len(arr) < n:
        return 0.0
    return sum(arr[-n:]) / float(n)


def _is_candidate(df, code, now_dt):
    """热点短线突破入场条件（全部基于已完成数据）。"""
    need = ('open', 'high', 'low', 'close', 'volume')
    for f in need:
        if f not in df:
            return False
    if len(df['close']) < 22:
        return False
    close = list(df['close'])
    vol = list(df['volume'])
    # 昨收 = 前一根收盘（避免依赖 get_history 的 preclose 字段；盘前 preclose=close[-2]）
    pre = [close[max(0, i - 1)] for i in range(len(close))]
    c0, c1, c2 = close[-1], close[-2], close[-3]

    # 1) 5/10日线多头排列 + 价格站上双线 + 均线拐头向上
    ma5_now = _ma(close, 5)
    ma5_prev = _ma(close[:-1], 5)
    ma10_now = _ma(close, 10)
    if not (ma5_now > ma10_now):
        return False
    if not (c0 > ma5_now and c0 > ma10_now):
        return False
    if not (ma5_now > ma5_prev):
        return False

    # 2) 连续两天放量上涨
    if not (c1 > c2 and c0 > c1):
        return False
    if not (vol[-1] > vol[-2] * VOL_UP_RATIO and vol[-2] > vol[-3] * VOL_UP_RATIO):
        return False
    vma5 = _ma(vol, 5)
    if vma5 <= 0 or vol[-1] <= vma5 * VOL_MA5_RATIO:
        return False

    # 3) 非涨停（按板区分）
    if pre[-1] <= 0:
        return False
    pct = c0 / pre[-1] - 1.0
    if pct >= _limit_pct(code) * NON_LIMIT_PAD:
        return False

    # 4) 防追高（阶段涨幅上限）
    if c0 / close[-21] - 1.0 >= STAGE_GAIN_CAP:
        return False

    # 5) 硬性剔除：科创板 / ST / 次新股 / 换手率超限（彬哥哥要求）
    if EXCLUDE_STAR and code.startswith('688'):
        return False
    if _is_st(code):
        return False
    if _is_new_stock(code, now_dt):
        return False
    turn = _turnover_rate(code, vol[-1])
    if turn is None:
        log.warning('[%s][turn] %s 换手率无法计算，保守剔除', LOG_TAG, code)
        return False
    if turn >= TURNOVER_CAP:
        return False
    return True


def _hot_universe(context):
    """热点 + 动量兜底，返回待选代码列表。"""
    codes = list(WATCHLIST)
    if HOT_SECTORS and INDUSTRY_MAP:
        codes = [c for c in codes if INDUSTRY_MAP.get(_canon(c)) in HOT_SECTORS]
    if MOMENTUM_FALLBACK or not codes:
        scored = []
        hists = _hist(codes, 6, ['close'])
        for c in codes:
            df = hists.get(_canon(c))
            if df is None or len(df['close']) < 6:
                continue
            cl = list(df['close'])
            scored.append((c, cl[-1] / cl[0] - 1.0))
        scored.sort(key=lambda x: x[1], reverse=True)
        codes = [c for c, _ in scored[:MOM_TOP_N]]
    return codes


def _market_open(context):
    """组合级风控：沪深300跌破MA20则暂停新开仓。"""
    if not MARKET_GATE:
        return True
    df = _hist(['000300.SS'], 21, ['close']).get('000300')
    if df is None or len(df['close']) < 21:
        log.warning('[%s][mkt] 指数取数缺失，按可开仓处理', LOG_TAG)
        return True
    cl = list(df['close'])
    ma20 = _ma(cl, 20)
    return cl[-1] >= ma20


# ============================ 生命周期 ============================
def _probe_float_source():
    """启动自测：探测 valuation 真实列名并验证换手率可达，避免静默零成交。
    关键：山西证券 PTrade 的 valuation 字段名未公开枚举，必须在实盘首跑时"探"出来，
    存到 _DISC_FLOAT_COL / _DISC_TURN_COL 供 _float_shares/_turnover_rate 优先使用。"""
    global _DISC_FLOAT_COL, _DISC_TURN_COL
    probe = WATCHLIST[0] if WATCHLIST else None
    if not probe:
        log.warning('[%s][probe] WATCHLIST 为空，无法自测换手率' % LOG_TAG)
        return
    cols = []
    # 策略1：fields=None + 上一交易日，拿 valuation 全部列（文档要求 fields=None 时必传 date）
    try:
        prev = get_trading_day(-1)
        pdate = prev.strftime('%Y%m%d') if hasattr(prev, 'strftime') else ''.join(ch for ch in str(prev) if ch.isdigit())[:8]
        df_all = get_fundamentals([_suffix(probe)], 'valuation', date=pdate)
        if hasattr(df_all, 'columns'):
            cols = [str(c) for c in df_all.columns]
        log.info('[%s][probe] valuation 实际列(%s): %s' % (LOG_TAG, pdate, cols))
    except Exception as e:
        log.warning('[%s][probe] valuation 全列探测失败(date=%s): %s' % (LOG_TAG, pdate if 'pdate' in dir() else '?', repr(e)))
    # 策略2：全列没拿到，逐候选字段探测，确认哪些字段名在真机可用
    if not cols:
        for name in FLOAT_CANDIDATES + TURNOVER_CANDIDATES:
            try:
                dfx = get_fundamentals([_suffix(probe)], 'valuation', fields=[name])
                ok = dfx is not None and hasattr(dfx, 'columns') and len(list(dfx.columns)) > 0
                if ok:
                    log.info('[%s][probe] 字段[%s]可达' % (LOG_TAG, name))
                    cols.append(name)
                else:
                    log.warning('[%s][probe] 字段[%s]返回空' % (LOG_TAG, name))
            except Exception as e2:
                log.warning('[%s][probe] 字段[%s]异常: %s' % (LOG_TAG, name, repr(e2)))
    # 从探测到的列里挑流通股本列 / 换手率列（优先于写死的候选）
    for c in cols:
        cl = str(c).lower()
        if 'value' in cl or 'cap' in cl:
            continue  # 市值类列(元/万元)不是股本，不能当流通股本用（实测 float_value=流通市值）
        if _DISC_FLOAT_COL is None and any(k in cl for k in ('float', 'circ', 'free')):
            _DISC_FLOAT_COL = c
        if _DISC_TURN_COL is None and 'turn' in cl:
            _DISC_TURN_COL = c
    log.info('[%s][probe] 选用 流通列=%s 换手列=%s' % (LOG_TAG, _DISC_FLOAT_COL, _DISC_TURN_COL))
    # 验证换手率可达
    tr = _turnover_rate(probe, 0)  # vol=0：仅验证直读/字段可达
    if tr is not None:
        log.info('[%s][probe] 换手率可取(%s 直读≈%.2f%%)；<%.0f%% 过滤生效' % (LOG_TAG, probe, tr, TURNOVER_CAP))
    else:
        fs = _float_shares(probe)
        if fs and fs > 0:
            log.info('[%s][probe] 流通股本可取(%.0f股)，volume/股本路径可算换手率' % (LOG_TAG, fs))
        else:
            log.error('[%s][probe] !! 流通股本/换手率均取不到(%s) !! 换手率过滤会"保守剔除"全部候选=零成交！'
                      '请按上方[probe]日志的 valuation 实际列名告知，我再据实钉死 FLOAT_CANDIDATES；'
                      '或填 FLOAT_SHARES 静态表(股)' % (LOG_TAG, probe))


def initialize(context):
    context.candidates = []
    context.hold_state = {}
    context.buys_today = 0
    run_daily(context, before_trading_start, '09:00')
    run_daily(context, _buy, '09:31')
    run_daily(context, _risk_control, '14:50')
    log.info('★%s★ 初始化完成 TRADE_ENABLED=%s', LOG_TAG, TRADE_ENABLED)
    # PTrade 禁止在[程序初始化]阶段调 get_fundamentals（实测 RuntimeError），探针已推迟到 before_trading_start 首跑


def before_trading_start(context, data=None):
    global _PROBE_DONE
    context.buys_today = 0
    context.day_sector_buy = {}
    # 首个交易日盘前执行探针：初始化阶段禁 get_fundamentals，只能在这里探测；
    # 之后 _DISC_* 列名已缓存，不再重复探测
    if not _PROBE_DONE:
        _PROBE_DONE = True
        try:
            _probe_float_source()
        except Exception as _pe:
            log.warning('[%s][probe] 盘前探针异常(不影响交易): %s' % (LOG_TAG, repr(_pe)))
    now = _dt_now(context)
    # 跨重启安全：用真实持仓重建状态
    for p in _get_positions(context):
        if p['amount'] > 0:
            st = context.hold_state.setdefault(_canon(p['code']), {})
            st.setdefault('entry', p['cost_basis'])
            st.setdefault('highest', p['cost_basis'])
            st.setdefault('atr', 0.0)
            st.setdefault('stage', 0)
            st.setdefault('entry_day', now)

    universe = _hot_universe(context)
    hists = _hist(universe, 22, ['open', 'high', 'low', 'close', 'volume'])
    cands = []
    for c in universe:
        df = hists.get(_canon(c))
        if df is not None and _is_candidate(df, c, now):
            cands.append(c)
    context.candidates = cands
    log.info('[%s] 候选数=%d 候选=%s', LOG_TAG, len(cands), cands)


def _do_sell(code, amount, limit_price=None):
    """限价卖出（止损用 limit_price 收敛滑点；股票限价须 2 位小数，文档 order 接口）。"""
    if not TRADE_ENABLED:
        return
    sh = int(round(amount / 100.0) * 100)
    if sh <= 0:
        return
    try:
        if limit_price and limit_price > 0:  # nan>0 为 False，自动降级市价
            order(code, -sh, limit_price=round(limit_price, 2))
        else:
            order(code, -sh)
    except Exception as e:
        log.warning('[%s][sell] %s 下单失败: %s', LOG_TAG, code, e)


def _buy(context, data=None):
    if not _market_open(context):
        log.info('[%s] 市场关口关闭，今日不开新仓', LOG_TAG)
        return
    acct = _account(context)
    value = acct['value']
    if value <= 0:
        return
    held = set(_canon(p['code']) for p in _get_positions(context) if p['amount'] > 0)
    for c in context.candidates:
        if context.buys_today >= MAX_BUYS_PER_DAY:
            break
        if _canon(c) in held:
            continue
        if len(held) >= MAX_POSITIONS:
            break
        raw = min(RISK_PER_TRADE / STOP_LOSS_PCT, MAX_POSITION_PCT)
        size = value * raw
        if size <= 0:
            continue
        # 同板块集中度上限（彬哥哥要求 ≤40%）
        sector = _sector_of(_canon(c))
        if sector is not None:
            cur = _sector_exposure(context, sector)
            if (cur + size) / value > SECTOR_CAP:
                log.info('[%s] %s 板块[%s]集中度 %.0f%%>%.0f%%，跳过',
                         LOG_TAG, c, sector, (cur + size) / value * 100, SECTOR_CAP * 100)
                continue
            context.day_sector_buy[sector] = context.day_sector_buy.get(sector, 0.0) + size
        else:
            log.warning('[%s][sector] %s 无行业映射，未计入板块上限', LOG_TAG, c)
        if TRADE_ENABLED:
            try:
                order_target_value(_suffix(c), size)
                context.buys_today += 1
                held.add(_canon(c))
                log.info('[%s] 买入 %s 目标市值=%.0f', LOG_TAG, _suffix(c), size)
            except Exception as e:
                log.warning('[%s][buy] %s 下单失败: %s', LOG_TAG, c, e)
        else:
            log.info('[%s][信号] 应买入 %s 目标市值=%.0f', LOG_TAG, _suffix(c), size)


def _risk_control(context, data=None):
    """持仓管理：硬止损 / 保本 / ATR移动止盈 / 分批减仓 / 时间止损。"""
    for p in _get_positions(context):
        code = _canon(p['code'])
        amount = p['amount']
        enable = p['enable_amount']
        if amount <= 0:
            continue
        if enable <= 0:
            continue  # T+1 当日买入不可卖，跳过所有卖出判定
        cost = p['cost_basis']
        if cost <= 0:
            continue
        price = _cur_price(_suffix(p['code']), data)
        if price <= 0:
            continue

        st = context.hold_state.setdefault(code, {
            'entry': cost, 'highest': cost, 'atr': 0.0, 'stage': 0,
            'entry_day': _dt_now(context)})

        # 刷新 ATR
        h = _hist([_suffix(p['code'])], 15, ['high', 'low', 'close']).get(code)
        if h is not None and len(h['close']) >= 2:
            st['atr'] = _atr(list(h['high']), list(h['low']), list(h['close']), 14)

        highest = max(st['highest'], price)
        st['highest'] = highest
        profit = price / cost - 1.0

        # 止损价自上而下取最宽（保护最强）
        stop_price = cost * (1.0 - STOP_LOSS_PCT)
        if profit >= BE_TRIGGER_PCT:
            stop_price = max(stop_price, cost * (1.0 + BE_GUARD))
        trail = (highest - TRAIL_K * st['atr']) if st['atr'] > 0 else highest * (1.0 - TRAIL_MIN_PCT)
        stop_price = max(stop_price, trail)

        # 分批减仓（零股保护：剩余<=300股时 amount/3 不足一手卖不出，直接一次性清仓）
        if st['stage'] == 0 and profit >= TP1_PCT:
            if amount <= 300:
                _do_sell(_suffix(p['code']), amount)
                st['stage'] = 2
                log.info('[%s] %s 止盈清仓(余量小全清) 盈利=%.1f%%', LOG_TAG, _suffix(p['code']), profit * 100)
            else:
                _do_sell(_suffix(p['code']), amount / 3.0)
                st['stage'] = 1
                log.info('[%s] %s 减仓1 盈利=%.1f%%', LOG_TAG, _suffix(p['code']), profit * 100)
            continue
        if st['stage'] == 1 and profit >= TP2_PCT:
            if amount <= 300:
                _do_sell(_suffix(p['code']), amount)
            else:
                _do_sell(_suffix(p['code']), amount / 3.0)
            st['stage'] = 2
            log.info('[%s] %s 减仓2 盈利=%.1f%%', LOG_TAG, _suffix(p['code']), profit * 100)
            continue

        # 触发止损/止盈（当日低点提前判定：盘中触及止损价即离场，减少拖到尾盘的跳空/滑点）
        day_low = 0.0
        try:
            r = get_history(1, '1d', 'low', [_suffix(p['code'])], fq='pre',
                            include=True, fill='nan', is_dict=True)
            if isinstance(r, dict) and _suffix(p['code']) in r:
                rows = list(r[_suffix(p['code'])])
                if rows:
                    last = rows[-1]
                    v = float(last[-1]) if hasattr(last, '__len__') and len(last) >= 1 else float(last)
                    if v == v and v > 0:  # 过滤 nan
                        day_low = v
        except Exception:
            day_low = 0.0
        if price <= stop_price or (day_low > 0 and day_low <= stop_price):
            # 限价=min(现价, 止损价)：现价已在止损下方按现价走(不再等更低)，
            # 盘中触及后回收则按止损价挂单，成交价不会差于止损价
            lp = min(price, stop_price) if price > 0 else stop_price
            _do_sell(_suffix(p['code']), amount, limit_price=lp)
            context.hold_state.pop(code, None)
            log.info('[%s] %s 离场 盈利=%.1f%% 止损价=%.2f 限价=%.2f 当日低=%.2f',
                     LOG_TAG, _suffix(p['code']), profit * 100, stop_price, lp, day_low)
            continue

        # 时间止损（亏损仓）；底仓闭环：两批止盈吃完后剩余底仓到限即清，让交易完整闭环
        try:
            held_days = (_dt_now(context) - st['entry_day']).days
        except Exception:
            held_days = 0
        if held_days >= MAX_HOLD_DAYS and (profit < 0 or st['stage'] >= 2):
            _do_sell(_suffix(p['code']), amount)
            context.hold_state.pop(code, None)
            if profit < 0:
                log.info('[%s] %s 时间止损 盈利=%.1f%% 持仓=%d日', LOG_TAG, _suffix(p['code']), profit * 100, held_days)
            else:
                log.info('[%s] %s 底仓闭环(止盈后到期清仓) 盈利=%.1f%% 持仓=%d日',
                         LOG_TAG, _suffix(p['code']), profit * 100, held_days)


def handle_data(context, data):
    """Ptrade 要求实现；本策略用 run_daily 驱动，这里留空。"""
    pass
