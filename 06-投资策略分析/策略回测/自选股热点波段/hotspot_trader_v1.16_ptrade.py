# -*- coding: utf-8 -*-
"""
hotspot_trader_v1_ptrade.py
=====================================================================
自选股 · 热点短线突破策略（Ptrade / QMT 托管机骨架  v1.16）
---------------------------------------------------------------------
设计目标（与彬哥哥商定）：
  选股 = 热点板块追踪结果 ∩ 股价站上5/10日线（多头排列）∩ 连续两天放量上涨 ∩ 非涨停
  出场 = ATR 自适应移动止盈 + 固定百分比硬止损 + 保本线 + 分批减仓 + 时间止损
  执行 = 自有资金波短，T+1，单票风险预算控仓
  v1.3 硬性剔除：ST/*ST、次新股(上市<250交易日)；只买 WATCHLIST；换手率<20%(百分比单位)；同板块≤40% 集中度
  v1.7 硬性剔除追加：科创板(688开头)——8个月回测 688019 一笔 -24.8%(隔夜跳空击穿5%止损)，方案A直接剔除；时间止损日志补盈利%
  v1.8 数据更新(2026-09-29)：WATCHLIST 整体替换为《行业龙头.xlsx》——278只行业龙头(较旧池418只精简：剔除187只、新增47只)；INDUSTRY_MAP 同步重建覆盖全部278只(47只新增按申万一级补全)；算法与参数未变；科创板688仍由 EXCLUDE_STAR 剔除
  v1.9 融合优化(2026-09-29)：结合《长线股三层量化V2.0》与《热点追踪》两策略已验证有效方法——
    ① 组合级风控：市场开关升级(沪深300破MA60->v1.11起停新开、破MA120连续确认->砍现有仓两成) + 组合断路器(自高点回撤-8%暂停新开/-12%砍1/3/-18%减半)
    ② 热点阶段纪律：仅扩散可买(连续3日站上10日线且10>20日线) + 退潮破20日线一票否决清仓
    ③ 止盈与护栏：动态移动止盈(峰值回撤>8%清,下限4%) + 不追高护栏(v1.11升级:高开>2%改挂昨收+1%限价单回踩成交/走弱<昨收-1.5%不接刀)
    ④ 估值性价比排序：候选池同行业按PE_TTM/PB横向低优先(降级版历史分位,取数失败安全降级)
  v1.9b 缺陷修复(2026-09-29，13个月回测复盘定位)：
    . 【P0】组合断路器阈值符号与 _drawdown() 口径不一致——阈值写作负值(CB_STAGE1/2/3 = -0.08/-0.12/-0.18)，
      而 _drawdown() 返回的是【正向】回撤(0~1)，判定式 `dd <= -0.08` 恒为假 -> 三级断路器全程 0 次触发、形同虚设；
      现改为正向阈值 0.08/0.12/0.18，判定翻转为 `dd >= CB_STAGEn`(回测日志中无任何[断路器]记录即直接证据)。
    . 断路器复位条件 `dd > CB_STAGE1 and cb_stage == 1` 改为 `dd < CB_STAGE1 and cb_stage > 0`：
      原逻辑一旦进入 stage2/stage3，即使回撤收敛也永不解除暂停(永久停摆)。
    . 市场开关日志由 _noise_once(整个回测只打一次) 改为状态变迁打印(g['mkt_short_state'])，
      使「破/回 MA60」全过程可追溯(原写法导致 2025-11 之后再无额度状态日志)。
    . 其余选股/出场/参数/WATCHLIST 与 v1.9 完全一致——纯缺陷修复，不含策略变更。
  v1.11 融合优化(2026-09-29，13个月回测复盘P1/P2)：
    . 【P1】不追高护栏升级：高开>2% 由「一律放弃」改为「挂 昨收+1% 限价单、日内回踩则成交」——
      解决原护栏把87%入场机会(86/98候选)挡在门外导致样本过少、统计不可信的硬伤；
      仅当 px>=昨收*1.02 走限价路径(order限价=昨收*1.01)，盘中回落至该价即成交，否则不建仓；
      仍保留「走弱(<昨收-1.5%)不接刀」护栏。
    . 【P2】市场开关升级：沪深300破MA60 由「降档半仓(额度x0.5)」改为「直接停新开(额度=0)」——
      跟随复盘结论「弱市(破MA60)直接停新开」；破MA120连续确认砍两成减现有仓逻辑不变。
    . 其余选股/出场/参数/WATCHLIST 与 v1.9b 完全一致。
  v1.12 执行层放开(2026-09-29，13个月回测诊断「四重漏斗」)：
    . 【P0-A】高开两段式追单：高开>2%% 挂「昨收+1%%」限价单后【不再占用 held/buys_today】(修复v1.11挂单即占当日额度的bug)；
      10:00 检查(_chase_check)：已回踩成交则确认持仓；现价仍在昨收+2%%上方 -> 按现价【市价追首仓一半】(CHASE_HALF_PCT=0.5)；
      现价处于限价与高开线之间 -> 保持挂单等日内回踩；未成交次日重试(上限 CHASE_RETRY_DAYS=3 日，期间走弱<昨收-1.5%%即撤销)。
      依据：v1.11 回测 50 笔限价单 45 笔全天未成交(高开25.2%%/18.7%%/17.7%%的主升浪股全部买不到)，且挂单即占额度致信号一次性作废。
    . 【P0-B】市场开关：破MA60 新开额度由 0(停新开) 改回 0.5(半档)——v1.11 一刀切曾造成 2026-07-13 起连续约78天零新开，
      整段错过结构性主线(31天有候选零动作)；破MA120连续确认砍现有仓两成不变。
    . 【P1】时间止损：MAX_HOLD_DAYS 8->15 且仅对亏损仓生效(profit<0)；盈利底仓不再「到期限清」，
      交给 ATR/动态移动止盈、退潮破20日线一票否决、保本线兜底——
      依据：002074(+21.1%%)/600362(+28.3%%)均在第8天被底仓闭环清掉，主升浪典型20~60个交易日吃不满。
    . 选股逻辑/仓位规模/WATCHLIST/其余出场 与 v1.11 完全一致——纯执行层放开，不引入新选股alpha。
  v1.13 执行层放开完整版(2026-09-29，彬哥哥逐项拍板 P0~P3)：
    . 【P0-A】高开两段式追单(v1.12基础上升级)：高开>2%% 挂「昨收+1%%」限价吃回踩，不占 held/buys_today；
      10:00 仍未成交且现价仍在昨收+2%%上方 -> 【按现价市价成交全额首仓】(v1.12为追一半)；
      限价与高开线之间保持挂单等回踩；未成交次日重试(上限3日，期间走弱<昨收-1.5%%即撤)。
    . 【P0-B】破MA60 半档额度x0.5 + 【连续限开>10个交易日自动降级】恢复全额额度(防长期空转；
      指数收复MA60后救济解除、回归正常开关逻辑；计数器/救济标志随之清零)。
    . 【P1】时间止损仅对亏损仓生效(MAX_HOLD_DAYS 8->15)；盈利底仓交给 ATR/动态移动止盈 + 退潮破20日线，让利润跑完主升浪。
    . 【P2】提高实际仓位：单票上限 30%%->40%%(与风险预算2%%/止损5%%自洽) + 最大同时持仓 6->10(实际并发受现金约束)。
    . 【P3】候选打分排序取前10：量比 + 3日涨幅 + 10日线上乖离 综合分，信号过多时只做最强前 CAND_TOP_N 只。
    . 选股条件/WATCHLIST/其余出场纪律 与 v1.12 一致。
  v1.14 砍掉追单腿(2026-09-29，v1.12同区间实证逐路径归因)：
    . 【P0-A修正】撤销 10:00 市价追单——v1.12 同区间实证：追单 50 笔胜率仅 20%%、均值 -4.19%%(合计-209%%)，
      追入时中位数高开 6.1%%(最大 25.2%%) = 买在日内情绪顶，均值回归+5%%止损 = 系统性负期望；
      而「限价等回踩」成交 50%% 胜率、+3.0%% 均值，期望为正。
      高开>2%% 仅挂「昨收+1%%」限价等回踩(不占额度、次日重试<=3日、走弱即撤)，10:00 仅确认成交/清理僵尸挂单，不再追价。
    . 保留 v1.13：P0-B 半档+连续限开>10日自动降级、P1 时间止损15天仅砍亏损仓、P2 单票40%%/持仓10只、P3 打分前10。
    . 附注：v1.12 中 603596 -34.6%% 为主板除权未调成本的假亏损(单日-35%%不可能)，非真实滑点。
  v1.15 风控与出场优化(2026-09-29，v1.14 十三个月+22.45%复盘逐笔归因)：
    . 【①20cm仓位】300/301/688(20cm涨跌幅)单票仓位 x0.5(40%->20%)——300395 一笔 -14.1%、止损限价滑点约9pct，
      20cm 票止损滑点天然比 10cm 高一倍，40% 仓位下单笔可拖累组合约 -5.6pct；按波动归一仓位压尾部风险。
    . 【②退潮分层】浮盈>RETREAT_TIER_PROFIT(10%) 后，破 MA10 先行减半(每票一次)，破 MA20 仍强制清仓——
      v1.14 实测退潮清仓 7 笔中 6 笔在 -6~-10% 才出场(确认滞后)；分层保护利润、不动底仓退潮逻辑(002074 +25.8% 那类好出场保留)。
    . 【③限价微升】限价挂单重试的最后一日(第 CHASE_RETRY_DAYS 日)挂价由 昨收+1% 上浮 0.5pct 至 昨收+1.5%——
      v1.14 限价成交率仅 42%(69挂29成)；不恢复已被实证负期望的追价，仅最后一日温和让价提升成交。
    . 其余选股/市场开关/断路器/止盈体系 与 v1.14 完全一致。
  v1.16 组合额度与弱市纪律(2026-09-29深夜，v1.15 +23.47%%/回撤12.62%%复盘)：
    . 【P0救济封顶】弱市限开连续>10日的「自动降级恢复全额」改为「额度封顶 MKT_RELIEF_CAP=0.5」——
      v1.15 实证：2026-07-20 救济恢复全额与「破MA120砍仓」同日触发，指数深度弱市满额开仓，
      8月集中吃5笔止损(≈组合-8~-9pct)是回撤升至12.62%%的主因；救济只防「额度归零式空转」(v1.11教训)，
      半档0.5本就可交易，指数收复MA60后由正常分支回归全额。
    . 【P1让价弱市禁用】限价重试最后一日的挂价上浮(+1.5%%)仅在沪深300处于MA60上方(额度=全额)时生效；
      弱市中末日直接撤销挂单——v1.15 让价在8月顶部多成交两笔接刀(600733 -7.7%%/300759 -7.4%%)。
    . 【P2分层放宽】RETREAT_TIER_PROFIT 10%%->5%%——v1.15 分层减半仅2次触发(窗口太窄)，放宽让利润保护真正跑起来。
    . 其余选股/断路器/止盈体系/20cm减半 与 v1.15 完全一致。
    . 选股条件/WATCHLIST/出场纪律 与 v1.13 一致。
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
    '301269', '603773', '600707', '600879', '601633', '002549', '002612', '600760',
    '300829', '301171', '002299', '600004', '002896', '301301', '002311', '601698',
    '600050', '600580', '300015', '688363', '002223', '000768', '603505', '000157',
    '601919', '600085', '002179', '601607', '601689', '002594', '600887', '600089',
    '000099', '600660', '001696', '601728', '600104', '002837', '600690', '600803',
    '688639', '600895', '688271', '600741', '000651', '600350', '603338', '300760',
    '300124', '002352', '002236', '002050', '688629', '600486', '600845', '000895',
    '600583', '600276', '601100', '603881', '600196', '601117', '002130', '002472',
    '000333', '600588', '002920', '000538', '600036', '600563', '601808', '000963',
    '002241', '301076', '001965', '600406', '601088', '002938', '600699', '601939',
    '002273', '601898', '600018', '600577', '000708', '002484', '300759', '603288',
    '601816', '603686', '002320', '002457', '600919', '601009', '600352', '600399',
    '600031', '300285', '600298', '601601', '600258', '002001', '000970', '002142',
    '300499', '002422', '600900', '600060', '002028', '002847', '002230', '600141',
    '002049', '000997', '603027', '600733', '603233', '000034', '600009', '600143',
    '002027', '002430', '002906', '002475', '601727', '300957', '688268', '600028',
    '601882', '601888', '300662', '600885', '688065', '002080', '603345', '601139',
    '601877', '600552', '603596', '600326', '600938', '002202', '000967', '002967',
    '600172', '002555', '600547', '603236', '688018', '002846', '601231', '603799',
    '603259', '000969', '688070', '300999', '000526', '688017', '300395', '603019',
    '300394', '002340', '601318', '300442', '000338', '603728', '300339', '002415',
    '600206', '002041', '300750', '600875', '600295', '600315', '300887', '002372',
    '300059', '002851', '688036', '603605', '601225', '002025', '600188', '002886',
    '600256', '600426', '300748', '688117', '002541', '600522', '601688', '300496',
    '300408', '600105', '600685', '600893', '300034', '600872', '000725', '600489',
    '600309', '002916', '000062', '300073', '002741', '601600', '601899', '002602',
    '600030', '600989', '688297', '300327', '600233', '002463', '600176', '600584',
    '603993', '600521', '002120', '000858', '002768', '688981', '002338', '603197',
    '601138', '000408', '000100', '300014', '600362', '000938', '300058', '600111',
    '301095', '600549', '002585', '002439', '000089', '600346', '000792', '002092',
    '300343', '600026', '600150', '601360', '002557', '603260', '000519', '300454',
    '300184', '000629', '600516', '300418', '601872', '601628', '600839', '688111',
    '301071', '002185', '600596', '000977', '002074', '601233', '002156', '002645',
    '688295', '300223', '000762', '688235', '002414', '300676', '002493', '002460',
    '600661', '002738', '002747', '688525', '002466', '002389',
]

# 热点板块：由「热点板块追踪技能」产出后填这里（行业名需与 INDUSTRY_MAP 一致）
# 留空 + MOMENTUM_FALLBACK=True 时，自动用自选股内动量最强的票当伪热点
HOT_SECTORS = []
INDUSTRY_MAP = {
    '000034': '计算机', '000062': '电子', '000089': '交通运输', '000099': '交通运输',
    '000100': '电子', '000157': '机械设备', '000333': '家用电器', '000338': '汽车',
    '000408': '基础化工', '000519': '国防军工', '000526': '社会服务', '000538': '医药生物',
    '000629': '有色金属', '000651': '家用电器', '000708': '钢铁', '000725': '电子',
    '000762': '有色金属', '000768': '国防军工', '000792': '基础化工', '000858': '食品饮料',
    '000895': '食品饮料', '000938': '计算机', '000963': '医药生物', '000967': '环保',
    '000969': '有色金属', '000970': '有色金属', '000977': '计算机', '000997': '计算机',
    '001696': '机械设备', '001965': '交通运输', '002001': '基础化工', '002025': '国防军工',
    '002027': '传媒', '002028': '电力设备', '002041': '农林牧渔', '002049': '电子',
    '002050': '家用电器', '002074': '电力设备', '002080': '建筑材料', '002092': '基础化工',
    '002120': '交通运输', '002130': '电子', '002142': '银行', '002156': '电子',
    '002179': '国防军工', '002185': '电子', '002202': '电力设备', '002223': '医药生物',
    '002230': '计算机', '002236': '计算机', '002241': '电子', '002273': '电子',
    '002299': '农林牧渔', '002311': '农林牧渔', '002320': '交通运输', '002338': '国防军工',
    '002340': '电力设备', '002352': '交通运输', '002372': '建筑材料', '002389': '国防军工',
    '002414': '国防军工', '002415': '计算机', '002422': '医药生物', '002430': '机械设备',
    '002439': '计算机', '002457': '建筑材料', '002460': '有色金属', '002463': '电子',
    '002466': '有色金属', '002472': '汽车', '002475': '电子', '002484': '电子',
    '002493': '基础化工', '002541': '建筑装饰', '002549': '基础化工', '002555': '传媒',
    '002557': '食品饮料', '002585': '基础化工', '002594': '汽车', '002602': '传媒',
    '002612': '美容护理', '002645': '环保', '002738': '有色金属', '002741': '电子',
    '002747': '机械设备', '002768': '基础化工', '002837': '机械设备', '002846': '轻工制造',
    '002847': '食品饮料', '002851': '电力设备', '002886': '基础化工', '002896': '机械设备',
    '002906': '汽车', '002916': '电子', '002920': '汽车', '002938': '电子',
    '002967': '社会服务', '300014': '电力设备', '300015': '医药生物', '300034': '国防军工',
    '300058': '传媒', '300059': '非银金融', '300073': '电力设备', '300124': '机械设备',
    '300184': '电子', '300223': '电子', '300285': '电子', '300327': '电子',
    '300339': '计算机', '300343': '基础化工', '300394': '通信', '300395': '建筑材料',
    '300408': '电子', '300418': '传媒', '300442': '计算机', '300454': '计算机',
    '300496': '计算机', '300499': '机械设备', '300662': '社会服务', '300676': '医药生物',
    '300748': '有色金属', '300750': '电力设备', '300759': '医药生物', '300760': '医药生物',
    '300829': '基础化工', '300887': '社会服务', '300957': '美容护理', '300999': '农林牧渔',
    '301071': '基础化工', '301076': '基础化工', '301095': '电子', '301171': '传媒',
    '301269': '电子', '301301': '医药生物', '600004': '交通运输', '600009': '交通运输',
    '600018': '交通运输', '600026': '交通运输', '600028': '石油石化', '600030': '非银金融',
    '600031': '机械设备', '600036': '银行', '600050': '通信', '600060': '家用电器',
    '600085': '医药生物', '600089': '电力设备', '600104': '汽车', '600105': '通信',
    '600111': '有色金属', '600141': '基础化工', '600143': '基础化工', '600150': '国防军工',
    '600172': '机械设备', '600176': '建筑材料', '600188': '煤炭', '600196': '医药生物',
    '600206': '电子', '600233': '交通运输', '600256': '石油石化', '600258': '社会服务',
    '600276': '医药生物', '600295': '钢铁', '600298': '食品饮料', '600309': '基础化工',
    '600315': '美容护理', '600326': '建筑装饰', '600346': '石油石化', '600350': '交通运输',
    '600352': '基础化工', '600362': '有色金属', '600399': '钢铁', '600406': '电力设备',
    '600426': '基础化工', '600486': '基础化工', '600489': '有色金属', '600516': '钢铁',
    '600521': '医药生物', '600522': '通信', '600547': '有色金属', '600549': '有色金属',
    '600552': '电子', '600563': '电子', '600577': '电力设备', '600580': '电力设备',
    '600583': '石油石化', '600584': '电子', '600588': '计算机', '600596': '基础化工',
    '600660': '汽车', '600661': '社会服务', '600685': '国防军工', '600690': '家用电器',
    '600699': '汽车', '600707': '电子', '600733': '汽车', '600741': '汽车',
    '600760': '国防军工', '600803': '公用事业', '600839': '家用电器', '600845': '计算机',
    '600872': '食品饮料', '600875': '电力设备', '600879': '国防军工', '600885': '电力设备',
    '600887': '食品饮料', '600893': '国防军工', '600895': '房地产', '600900': '公用事业',
    '600919': '银行', '600938': '石油石化', '600989': '基础化工', '601009': '银行',
    '601088': '煤炭', '601100': '机械设备', '601117': '建筑装饰', '601138': '电子',
    '601139': '公用事业', '601225': '煤炭', '601231': '电子', '601233': '基础化工',
    '601318': '非银金融', '601360': '计算机', '601600': '有色金属', '601601': '非银金融',
    '601607': '医药生物', '601628': '非银金融', '601633': '汽车', '601688': '非银金融',
    '601689': '汽车', '601698': '国防军工', '601727': '电力设备', '601728': '通信',
    '601808': '石油石化', '601816': '交通运输', '601872': '交通运输', '601877': '电力设备',
    '601882': '机械设备', '601888': '社会服务', '601898': '煤炭', '601899': '有色金属',
    '601919': '交通运输', '601939': '银行', '603019': '计算机', '603027': '食品饮料',
    '603197': '汽车', '603233': '医药生物', '603236': '通信', '603259': '医药生物',
    '603260': '基础化工', '603288': '食品饮料', '603338': '机械设备', '603345': '食品饮料',
    '603505': '基础化工', '603596': '汽车', '603605': '美容护理', '603686': '环保',
    '603728': '电力设备', '603773': '电子', '603799': '有色金属', '603881': '计算机',
    '603993': '有色金属', '688017': '机械设备', '688018': '电子', '688036': '电子',
    '688065': '基础化工', '688070': '国防军工', '688111': '计算机', '688117': '医药生物',
    '688235': '医药生物', '688268': '电子', '688271': '医药生物', '688295': '基础化工',
    '688297': '国防军工', '688363': '美容护理', '688525': '电子', '688629': '国防军工',
    '688639': '基础化工', '688981': '电子',
}
MOMENTUM_FALLBACK = True
MOM_TOP_N = 15  # 动量兜底时取前 N 名

# ---- 选股阈值 ----
VOL_UP_RATIO = 1.2      # 量能较前一日放大倍数（连续两天）
VOL_MA5_RATIO = 1.3     # 当日量 > 5日均量倍数
NON_LIMIT_PAD = 0.98    # 非涨停：涨幅 < 涨停幅度*该系数
STAGE_GAIN_CAP = 0.40   # 防追高：20日涨幅上限

# ---- 仓位 / 资金 ----
MAX_POSITIONS = 10       # v1.13 P2：最大同时持仓 6->10(实际并发受现金约束)
MAX_BUYS_PER_DAY = 2     # 每日最多新开仓（防过度交易）
RISK_PER_TRADE = 0.02    # 单票最大亏损占本金（风险预算）
MAX_POSITION_PCT = 0.40  # v1.13 P2：单票仓位上限 30%->40%(与风险预算2%/止损5%自洽)
CM20_POS_RATIO = 0.50      # v1.15①：20cm票(300/301/688)单票仓位再乘此系数，压止损滑点尾部
MARKET_GATE = True       # 市场开关总闸：False=完全关闭新市场开关逻辑
# ---- v1.9 市场开关(融合长线股V2.0：MA60降档 + MA120砍仓) ----
INDEX_CODE = '000300.SS'   # 沪深300 作为市场开关标的
MKT_MA_SHORT = 60          # 沪深300 跌破 -> 新开仓额度降档
MKT_MA_LONG = 120          # 沪深300 跌破(连续确认) -> 砍现有仓两成
MKT_DEGRADE_RATIO = 0.5    # v1.12 P0-B：破MA60改回半档额度(0.5)——v1.11归零曾造成连续78天零新开、整段错过结构性主线；破MA120连续确认砍两成不变
MKT_CUT_CONFIRM_DAYS = 3   # 连续N日破120日线才砍(防单日假跌破打摆)
MKT_RESET_CONFIRM_DAYS = 3 # 连续N日回到120日线上方才复位(机动仓不回补)
MKT_BLOCK_RELIEF_DAYS = 10 # v1.13 P0-B：弱市限开连续超过N个交易日 -> 自动降级恢复全额额度(防长期空转)
MKT_RELIEF_CAP = 0.5    # v1.16 P0：救济生效期额度上限(不再恢复全额；指数收复MA60后回归正常)
# ---- v1.9 组合断路器(融合长线股V2.0) ----
CB_STAGE1, CB_STAGE2, CB_STAGE3 = 0.08, 0.12, 0.18   # v1.9b修正：与 _drawdown() 正向回撤(0~1)口径对齐
CB_CUT1, CB_CUT2 = 1.0 / 3.0, 0.50
# ---- v1.9 热点阶段纪律(融合热点追踪V4.5/退潮一票否决) ----
REQUIRE_TREND_CONFIRM = True   # 仅扩散可买：连续3日站上10日线且10>20日线
TREND_CONFIRM_DAYS = 3
RETREAT_MA = 20                # 退潮一票否决：持仓破此均线强制清仓
RETREAT_TIER_PROFIT = 0.05  # v1.16 P2：分层阈值 10%->5%(v1.15 仅2次触发，窗口太窄)
RETREAT_MA_EARLY = 10       # v1.15②：分层退潮的先行均线
# ---- v1.9 动态移动止盈(融合热点追踪V4.6) ----
TRAIL_PCT = 0.08              # 峰值回撤>此比例清仓
TRAIL_PCT_FLOOR = 0.04        # 浮盈达此才启动(下限，防微利误清)
# ---- v1.9 不追高护栏(热点通用护栏) ----
OPEN_CHASE_PCT = 0.02         # 高开>此比例(原一律放弃)
LIMIT_CHASE_PCT = 0.01        # v1.11 P1：高开超限时改挂 昨收+1% 限价单，日内回踩成交
BUY_DROP_PCT = 0.015          # 走弱(价<昨收-1.5%)不接刀
CHASE_RETRY_DAYS = 3          # v1.13 P0-A：限价挂单未成交的次日重试上限(超过即撤销，信号过期)
CHASE_LIFT_PCT = 0.005     # v1.15③：限价重试最后一日挂价上浮(昨收+1.5%)，温和提升成交率
# ---- v1.9 估值性价比排序(热点漏斗第3层，降级版历史分位) ----
VALUATION_RANK = True         # 候选池同行业按PE_TTM/PB横向低优先(取数失败安全降级)
SCORE_RANK = True             # v1.13 P3：候选打分排序(量比+3日涨幅+10日线乖离综合分)
CAND_TOP_N = 10               # v1.13 P3：打分后仅取前N只进入当日买入队列

# ---- 出场（核心：科学移动止盈止损）----
STOP_LOSS_PCT = 0.05     # 初始硬止损（占成本）
BE_TRIGGER_PCT = 0.05    # 浮盈达此比例 -> 止损上移至保本
BE_GUARD = 0.01          # 保本线上浮（微利保护）
TRAIL_K = 2.5            # ATR 移动止盈倍数（k）；回测标定 2~3
TRAIL_MIN_PCT = 0.06     # ATR 缺失时的回撤百分比兜底
TP1_PCT = 0.08           # 第一批减仓盈利阈值
TP2_PCT = 0.15           # 第二批减仓盈利阈值
MAX_HOLD_DAYS = 15       # v1.12 P1：时间止损 8->15 且仅对亏损仓生效(盈利底仓交给移动止盈跑完主升浪)

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

# ============================ 组合级状态（跨 run_daily 持久）============================
g = {
    'peak_value': 0.0, 'cb_stage': 0, 'circuit_halt': False,
    'mkt_stage': 0, 'mkt_below_days': 0, 'mkt_above_days': 0,
    'mkt_cut_seq': -999, 'mkt_degrade_ratio': 1.0, 'market_off_days': 0, 'mkt_block_days': 0, 'mkt_relief': False,
    '_noise': set(),
}


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
def _round_lot(amount, code):
    """整手：688/889/8xx/4xx/92x -> 200股，其余100股。"""
    c = _canon(code)
    lot = 200 if (c[:2] in ('68', '88', '92') or c[0] in ('4', '8')) else 100
    sh = int(amount // lot) * lot
    return sh


def _index_below_ma(code, n):
    """指数 code 收盘是否低于 n 日线；取数不足返回 None（维持现状不误判）。"""
    df = _hist([code], n + 1, ['close']).get(_canon(code))
    if df is None or len(df.get('close', [])) < n:
        return None
    cl = list(df['close'])
    return cl[-1] < _ma(cl, n)


def _noise_once(key, tag):
    """去重日志：同一 (key,tag) 全周期只打一次，避免每日刷屏。"""
    s = g.setdefault('_noise', set())
    k = (key, tag)
    if k in s:
        return False
    s.add(k)
    return True


def _pre_close(code):
    """昨收（include=False 取倒数第二根）。"""
    h = _hist([code], 2, ['close']).get(_canon(code))
    if h is None or len(h.get('close', [])) < 2:
        return 0.0
    cl = list(h['close'])
    return float(cl[-2])


def _update_peak(context):
    v = _account(context)['value']
    if v > g['peak_value']:
        g['peak_value'] = v


def _drawdown(context):
    v = _account(context)['value']
    if g['peak_value'] <= 0 or v <= 0:
        return 0.0
    return (g['peak_value'] - v) / g['peak_value']


def _cut_all(context, frac):
    """组合减仓：按可卖量比例整手卖出（市价，应急用）。"""
    for p in _get_positions(context):
        if p['amount'] <= 0:
            continue
        qty = _round_lot(p['enable_amount'] * frac, p['code'])
        if qty > 0:
            _do_sell(p['code'], qty)


def _circuit_breaker(context, total, dd):
    """三级组合断路器（融合长线股V2.0）：自高点回撤 -8%暂停/-12%砍1/3/-18%减半。"""
    if dd >= CB_STAGE3 and g['cb_stage'] < 3:
        g['cb_stage'] = 3
        g['circuit_halt'] = True
        log.warning('[%s][断路器-3级] 回撤%.1f%% 全组合减半' % (LOG_TAG, dd * 100))
        _cut_all(context, CB_CUT2)
    elif dd >= CB_STAGE2 and g['cb_stage'] < 2:
        g['cb_stage'] = 2
        g['circuit_halt'] = True
        log.warning('[%s][断路器-2级] 回撤%.1f%% 砍1/3高位仓' % (LOG_TAG, dd * 100))
        _cut_all(context, CB_CUT1)
    elif dd >= CB_STAGE1 and g['cb_stage'] < 1:
        g['cb_stage'] = 1
        g['circuit_halt'] = True
        log.warning('[%s][断路器-1级] 回撤%.1f%% 暂停一切新开仓' % (LOG_TAG, dd * 100))
    if dd < CB_STAGE1 and g['cb_stage'] > 0:
        g['cb_stage'] = 0
        g['circuit_halt'] = False
        log.info('[%s][断路器] 回撤收敛至%.1f%%，解除交易暂停' % (LOG_TAG, dd * 100))


def _market_switch(context):
    """市场开关（融合长线股V2.0，双向可复位）：
    - 破MA60 -> 弱市限开(额度xMKT_DEGRADE_RATIO=0.5)；连续限开超过 MKT_BLOCK_RELIEF_DAYS -> 自动降级恢复全额(防长期空转)；
    - 破MA120连续确认 -> 砍现有仓两成（机动仓，回升只复位不回补）。"""
    below_short = _index_below_ma(INDEX_CODE, MKT_MA_SHORT)
    below_long = _index_below_ma(INDEX_CODE, MKT_MA_LONG)
    if below_short is None:
        if _noise_once('__mkt__', 'nomkt'):
            log.warning('[%s][mkt] 指数数据不足，跳过市场开关判定' % LOG_TAG)
    elif below_short:
        g['market_off_days'] = g.get('market_off_days', 0) + 1
        if g.get('mkt_relief'):
            # v1.16 P0：救济生效期额度封顶 MKT_RELIEF_CAP——只防「额度归零式空转」，不再恢复全额；
            # v1.15 实证：深度弱市(破MA120)恢复全额致8月集中止损、回撤12.62%。指数收复MA60后回归正常。
            g['mkt_degrade_ratio'] = MKT_RELIEF_CAP
        else:
            g['mkt_degrade_ratio'] = MKT_DEGRADE_RATIO
            g['mkt_block_days'] = g.get('mkt_block_days', 0) + 1
            if g['mkt_block_days'] > MKT_BLOCK_RELIEF_DAYS:
                g['mkt_relief'] = True
                g['mkt_degrade_ratio'] = MKT_RELIEF_CAP
                log.warning('[%s][mkt] 弱市限开连续%d日(>%d) -> 救济触发：额度封顶%.0f%%(不再恢复全额，收复MA60后回归正常)'
                            % (LOG_TAG, g['mkt_block_days'], MKT_BLOCK_RELIEF_DAYS, MKT_RELIEF_CAP * 100))
        if g.get('mkt_short_state') != 'below':
            g['mkt_short_state'] = 'below'
            log.warning('[%s][mkt] 沪深300破%d日线 -> 弱市限开(额度x%.0f%%)' % (LOG_TAG, MKT_MA_SHORT, g['mkt_degrade_ratio'] * 100))
    else:
        g['mkt_degrade_ratio'] = 1.0
        g['mkt_block_days'] = 0
        if g.get('mkt_relief'):
            g['mkt_relief'] = False
            log.info('[%s][mkt] 沪深300回到%d日线上方 -> 降级救济解除，回归正常开关逻辑' % (LOG_TAG, MKT_MA_SHORT))
        if g.get('mkt_short_state') != 'above':
            g['mkt_short_state'] = 'above'
            log.info('[%s][mkt] 沪深300回到%d日线上方 -> 额度恢复全额' % (LOG_TAG, MKT_MA_SHORT))
    if below_long is None:
        return
    if below_long:
        g['mkt_below_days'] = g.get('mkt_below_days', 0) + 1
        g['mkt_above_days'] = 0
        if g['mkt_stage'] < 1 and g['mkt_below_days'] >= MKT_CUT_CONFIRM_DAYS:
            g['mkt_stage'] = 1
            log.warning('[%s][mkt] 沪深300连续%d日破%d日线 -> 砍现有仓两成' % (LOG_TAG, g['mkt_below_days'], MKT_MA_LONG))
            _cut_all(context, 0.2)
    else:
        g['mkt_below_days'] = 0
        g['mkt_above_days'] = g.get('mkt_above_days', 0) + 1
        if g['mkt_stage'] >= 1 and g['mkt_above_days'] >= MKT_RESET_CONFIRM_DAYS:
            g['mkt_stage'] = 0
            log.info('[%s][mkt] 沪深300回到%d日线上方(连续%d日) -> 开关复位(机动仓不回补)' % (LOG_TAG, MKT_MA_LONG, g['mkt_above_days']))


def _valuation_metrics(code):
    """取估值 (pe_ttm, pb)。取不到返回 (None, None)。"""
    try:
        df = get_fundamentals([_suffix(code)], 'valuation', fields=['pe_ttm', 'pb'])
    except Exception:
        return (None, None)
    return (_extract_scalar(df, 'pe_ttm'), _extract_scalar(df, 'pb'))


def _valuation_rank(cands):
    """候选池估值性价比排序（热点漏斗第3层，降级版历史分位）：
    按行业分组，组内 PE_TTM 低者优先（亏损/缺失置后）；组间保持原动量序。"""
    if not cands:
        return cands
    scored = []
    for c in cands:
        pe, _ = _valuation_metrics(c)
        sec = _sector_of(c)
        score = pe if (pe is not None and pe > 0) else 1e9
        scored.append((c, sec, score))
    gmap = {}
    order = []
    for c, sec, score in scored:
        if sec not in gmap:
            gmap[sec] = []
            order.append(sec)
        gmap[sec].append((c, score))
    out = []
    for sec in order:
        items = gmap[sec]
        items.sort(key=lambda x: x[1])
        out.extend([c for c, _ in items])
    return out


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

    # v1.9 仅扩散可买：趋势已确认（规避"追滞后热点"这一亏损首因）
    if REQUIRE_TREND_CONFIRM:
        ma20c = _ma(close, 20)
        if ma20c <= 0 or not (c0 > ma20c):
            return False
        above10 = 0
        for i in range(len(close) - 1, max(0, len(close) - 1 - TREND_CONFIRM_DAYS), -1):
            if close[i] > _ma(close[:i + 1], 10):
                above10 += 1
            else:
                break
        if above10 < TREND_CONFIRM_DAYS:
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
    """组合级风控闸门：市场开关总闸关闭 或 组合断路器暂停时不开新仓。
    具体降档(额度x0.5)由 g['mkt_degrade_ratio'] 在 _buy 应用。"""
    if not MARKET_GATE:
        return True
    if g.get('circuit_halt', False):
        return False
    return True


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
    global g
    g = {
        'peak_value': 0.0, 'cb_stage': 0, 'circuit_halt': False,
        'mkt_stage': 0, 'mkt_below_days': 0, 'mkt_above_days': 0,
        'mkt_cut_seq': -999, 'mkt_degrade_ratio': 1.0, 'market_off_days': 0, 'mkt_block_days': 0, 'mkt_relief': False,
        '_noise': set(),
    }
    context.candidates = []
    context.hold_state = {}
    context.buys_today = 0
    context.pending_chase = {}   # v1.12 P0-A：高开限价追单跟踪(未成交不占当日额度，允许次日重试)
    run_daily(context, before_trading_start, '09:00')
    run_daily(context, _buy, '09:31')
    run_daily(context, _chase_check, '10:00')
    run_daily(context, _risk_control, '14:50')
    set_volume_ratio(volume_ratio=1.0)  # 解除 PTrade 默认 0.25 成交比例限制;1.0=允许吃满本周期真实成交量(物理合理上限),避免部分成交低估收益
    log.info('★%s★ 初始化完成 TRADE_ENABLED=%s', LOG_TAG, TRADE_ENABLED)
    # PTrade 禁止在[程序初始化]阶段调 get_fundamentals（实测 RuntimeError），探针已推迟到 before_trading_start 首跑


def _score_rank(cands, hists):
    """v1.13 P3：候选打分排序取前 N——量比 + 3日涨幅 + 10日线上乖离 综合分。
    信号过多时只做最强前 CAND_TOP_N 只，避免按原顺序全收、资金被摊薄。"""
    scored = []
    for c in cands:
        df = hists.get(_canon(c))
        if df is None:
            continue
        try:
            closes = df['close']
            vols = df['volume']
            if len(closes) < 6 or len(vols) < 6:
                continue
            v5 = sum(vols[-6:-1]) / 5.0
            vr = (vols[-1] / v5) if v5 > 0 else 0.0
            chg3 = (closes[-1] / closes[-4] - 1.0) if closes[-4] > 0 else 0.0
            n10 = min(10, len(closes))
            ma10 = sum(closes[-n10:]) / float(n10)
            spread = (closes[-1] / ma10 - 1.0) if ma10 > 0 else 0.0
            score = vr + chg3 * 10.0 + spread * 5.0
            scored.append((score, c))
        except Exception:
            continue
    scored.sort(reverse=True)
    top = [c for _sc, c in scored[:CAND_TOP_N]]
    log.info('[%s] 打分排序 %d 候选 -> 取前%d: %s', LOG_TAG, len(cands), len(top), top)
    return top


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

    # v1.12 P0-A：盘前对账——追高限价单若已成交(出现在持仓)，移出跟踪
    _held_now = set(_canon(p['code']) for p in _get_positions(context) if p['amount'] > 0)
    for _pc in list(context.pending_chase.keys()):
        if _pc in _held_now:
            context.pending_chase.pop(_pc, None)
            log.info('[%s] %s 追高限价单已成交(盘前对账)', LOG_TAG, _pc)

    # ---- v1.9 组合级风控：市场开关 + 断路器（盘前基于昨收净值判定）----
    _update_peak(context)
    _market_switch(context)
    _circuit_breaker(context, _account(context)['value'], _drawdown(context))

    universe = _hot_universe(context)
    hists = _hist(universe, 22, ['open', 'high', 'low', 'close', 'volume'])
    cands = []
    for c in universe:
        df = hists.get(_canon(c))
        if df is not None and _is_candidate(df, c, now):
            cands.append(c)
    context.candidates = cands
    if VALUATION_RANK:
        context.candidates = _valuation_rank(cands)
    # v1.13 P3：候选打分排序取前 N——信号过多时只做最强前 CAND_TOP_N 只
    if SCORE_RANK and len(context.candidates) > CAND_TOP_N:
        context.candidates = _score_rank(context.candidates, hists)
    log.info('[%s] 候选数=%d 候选=%s', LOG_TAG, len(context.candidates), context.candidates)


def _do_sell(code, amount, limit_price=None):
    """限价卖出（止损用 limit_price 收敛滑点；股票限价须 2 位小数，文档 order 接口）。"""
    if not TRADE_ENABLED:
        return
    sh = _round_lot(amount, code)
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
    # v1.12 P0-A：昨日及更早未成交的追高限价单——重试(按今日昨收更新限价)，超限或走弱则撤销
    for pc in list(context.pending_chase.keys()):
        pend = context.pending_chase[pc]
        if pc in held:
            context.pending_chase.pop(pc, None)
            continue
        pend['days'] += 1
        if pend['days'] > CHASE_RETRY_DAYS:
            context.pending_chase.pop(pc, None)
            log.info('[%s] %s 追高限价单 %d 日未成交，撤销(信号过期)', LOG_TAG, pc, pend['days'] - 1)
            continue
        pxr = _cur_price(_suffix(pc), data)
        pcr = _pre_close(_suffix(pc))
        if pxr > 0 and pcr and pxr < pcr * (1.0 - BUY_DROP_PCT):
            context.pending_chase.pop(pc, None)
            log.info('[%s] %s 追高挂单期间走弱(<昨收-1.5%%)，撤销', LOG_TAG, pc)
            continue
        # v1.16 P1：弱市(额度<全额)末日不再让价，直接撤销挂单——8月顶部接刀教训
        if g.get('mkt_degrade_ratio', 1.0) < 1.0 and pend['days'] >= CHASE_RETRY_DAYS:
            context.pending_chase.pop(pc, None)
            log.info('[%s] %s 弱市(额度x%.0f%%)末日不再让价，撤销挂单'
                     % (LOG_TAG, pc, g.get('mkt_degrade_ratio', 1.0) * 100))
            continue
        if pcr:
            eff_pct = LIMIT_CHASE_PCT + (CHASE_LIFT_PCT if (pend['days'] >= CHASE_RETRY_DAYS and g.get('mkt_degrade_ratio', 1.0) >= 1.0) else 0.0)
            lpn = round(pcr * (1.0 + eff_pct), 2)
            shn = int(pend['size'] / lpn // 100) * 100
            if shn > 0 and TRADE_ENABLED:
                try:
                    order(_suffix(pc), shn, limit_price=lpn)
                    pend['lp'] = lpn
                    pend['shares'] = shn
                    pend['pre_close'] = pcr
                    log.info('[%s] %s 追高限价单重试 第%d次 昨收+%.1f%%=%.2f', LOG_TAG, pc, pend['days'], eff_pct * 100, lpn)
                except Exception as e:
                    log.warning('[%s][buy-retry] %s 下单失败: %s', LOG_TAG, pc, e)
    for c in context.candidates:
        if context.buys_today >= MAX_BUYS_PER_DAY:
            break
        if _canon(c) in held:
            continue
        if len(held) >= MAX_POSITIONS:
            break
        # 现价与昨收（护栏判定用）
        px = _cur_price(_suffix(c), data)
        if px <= 0:
            continue
        pre_close = _pre_close(_suffix(c))
        # 仓位规模（含市场开关降档：破MA60=0停新开 / 正常=全额）
        raw = min(RISK_PER_TRADE / STOP_LOSS_PCT, MAX_POSITION_PCT)
        raw *= g.get('mkt_degrade_ratio', 1.0)
        # v1.15①：20cm 高波动票(300/301/688)单票仓位减半——止损滑点比10cm高一倍(300395 -14.1%教训)
        if c.startswith(('300', '301', '688')):
            raw *= CM20_POS_RATIO
            log.info('[%s] %s 20cm票 仓位x%.1f(=%.0f%%)', LOG_TAG, c, CM20_POS_RATIO, raw * 100)
        size = value * raw
        if size <= 0:
            continue
        # 同板块集中度上限（彬哥哥要求 ≤40%)
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
        # v1.12 P0-A：高开两段式——挂「昨收+1%」限价单等回踩；【不占 held/buys_today】，
        # 10:00 _chase_check 仅确认成交/清理僵尸挂单，【不追价】(v1.14)，未成交次日重试
        if pre_close and px >= pre_close * (1.0 + OPEN_CHASE_PCT):
            lp = round(pre_close * (1.0 + LIMIT_CHASE_PCT), 2)
            shares = int(size / lp // 100) * 100
            if shares > 0:
                if TRADE_ENABLED:
                    try:
                        order(_suffix(c), shares, limit_price=lp)
                    except Exception as e:
                        log.warning('[%s][buy-limit] %s 下单失败: %s', LOG_TAG, c, e)
                        continue
                context.pending_chase[_canon(c)] = {'lp': lp, 'shares': shares, 'size': size,
                                                    'pre_close': pre_close, 'days': 0}
                log.info('[%s] %s 高开%.1f%% 挂限价 昨收+%.1f%%=%.2f 回踩等成交(目标%.0f/股%d)，不占当日额度'
                         % (LOG_TAG, c, (px / pre_close - 1) * 100, LIMIT_CHASE_PCT * 100, lp, size, shares))
            else:
                log.info('[%s] %s 高开%.1f%% 限价单手数不足(目标%.0f)，跳过', LOG_TAG, c, (px / pre_close - 1) * 100, size)
            continue
        # v1.9 不接刀护栏：走弱(价<昨收-1.5%)放弃
        if pre_close and px < pre_close * (1.0 - BUY_DROP_PCT):
            log.info('[%s] %s 走弱(价<昨收-%.1f%%) 不接刀' % (LOG_TAG, c, BUY_DROP_PCT * 100))
            continue
        # 常规市价买入（非高开）
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


def _chase_check(context, data=None):
    """v1.14 P0-A：10:00 检查高开限价挂单——只确认回踩成交/清理僵尸挂单，不追价(v1.12实证追单20%胜率)。"""
    if not context.pending_chase:
        return
    held = set(_canon(p['code']) for p in _get_positions(context) if p['amount'] > 0)
    value = _account(context)['value']
    for pc in list(context.pending_chase.keys()):
        pend = context.pending_chase[pc]
        if pc in held:
            context.pending_chase.pop(pc, None)
            log.info('[%s] %s 追高限价单已回踩成交，确认持仓', LOG_TAG, pc)
            continue
        px = _cur_price(_suffix(pc), data)
        pc_close = pend.get('pre_close')
        if px <= 0 or not pc_close:
            continue
        if px <= pend['lp']:
            # 已回落到限价下方但持仓未出现：视同回踩成交(限价单应已撮合)，移出跟踪防僵尸挂单
            context.pending_chase.pop(pc, None)
            log.info('[%s] %s 现价%.2f<=限价%.2f 视同回踩成交，移出跟踪', LOG_TAG, pc, px, pend['lp'])
            continue
        # v1.14：撤销"10:00市价追单"腿——v1.12 同区间实证 50 笔追单胜率仅 20%、均值 -4.19%(合计-209%)，
        # 追高 = 负期望。高开>2% 只挂「昨收+1%」限价等回踩，不成交就等次日重试(<=CHASE_RETRY_DAYS 日)
        log.info('[%s] %s 10:00仍高开%.1f%% 未回踩，维持限价挂单等回踩(不追价)',
                 LOG_TAG, pc, (px / pc_close - 1) * 100)
        # 其余情形(限价与高开线之间)：保持挂单等日内回踩


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
        h = _hist([_suffix(p['code'])], 21, ['high', 'low', 'close']).get(code)
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

        # v1.9/v1.15② 退潮一票否决 + 分层：浮盈>阈值后破先行均线(MA10)减半一次，破20日线仍强制清仓
        closes20 = list(h['close'])
        ma20p = _ma(closes20, 20) if len(closes20) >= 20 else 0.0
        ma10p = _ma(closes20, 10) if len(closes20) >= 10 else 0.0
        if ma20p > 0 and price <= ma20p:
            _do_sell(_suffix(p['code']), amount)
            context.hold_state.pop(code, None)
            log.info('[%s] %s 退潮清仓(破%d日线) 盈利=%.1f%%' % (LOG_TAG, _suffix(p['code']), RETREAT_MA, profit * 100))
            continue
        if (ma10p > 0 and profit >= RETREAT_TIER_PROFIT and price <= ma10p
                and not st.get('retreat_cut')):
            _do_sell(_suffix(p['code']), amount / 2.0)
            st['retreat_cut'] = True
            log.info('[%s] %s 退潮分层减半(浮盈%.1f%% 破%d日线) 盈利=%.1f%%'
                     % (LOG_TAG, _suffix(p['code']), profit * 100, RETREAT_MA_EARLY, profit * 100))
            continue
        # v1.9 动态移动止盈：峰值回撤>TRAIL_PCT 清仓（下限TRAIL_PCT_FLOOR，浮盈越大锁越紧）
        peak_rt = highest / cost - 1.0
        if peak_rt >= TRAIL_PCT_FLOOR and price <= highest * (1.0 - TRAIL_PCT):
            _do_sell(_suffix(p['code']), amount)
            context.hold_state.pop(code, None)
            log.info('[%s] %s 动态止盈(峰值回撤%.1f%%) 盈利=%.1f%%' % (LOG_TAG, _suffix(p['code']), TRAIL_PCT * 100, profit * 100))
            continue

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

        # v1.12 P1：时间止损仅对亏损仓生效(MAX_HOLD_DAYS 8->15)；盈利底仓不再「到期限清」——
        # 交给 ATR/动态移动止盈、退潮破20日线一票否决、保本线兜底，让利润跑完主升浪
        try:
            held_days = (_dt_now(context) - st['entry_day']).days
        except Exception:
            held_days = 0
        if held_days >= MAX_HOLD_DAYS and profit < 0:
            _do_sell(_suffix(p['code']), amount)
            context.hold_state.pop(code, None)
            log.info('[%s] %s 时间止损 盈利=%.1f%% 持仓=%d日', LOG_TAG, _suffix(p['code']), profit * 100, held_days)


def handle_data(context, data):
    """Ptrade 要求实现；本策略用 run_daily 驱动，这里留空。"""
    pass


