#!/usr/bin/env node
/**
 * sync-miniprogram.js — 投研工作台「网页端 → 小程序端」数据同步脚本
 *
 * 作用：从 index.html 提取 NAV / README / TM 三个数据块，并从 data/ 读取最新晨报，
 *      生成 miniprogram/app.js，保证两端模块结构、描述文案、模板内容完全一致。
 *
 * 用法：node tools/sync-miniprogram.js
 *
 * 约定：index.html 是唯一数据源（single source of truth）。
 *      小程序端任何模块/文案调整，都改 index.html 后重跑本脚本，不要手改 app.js。
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const HTML_PATH = path.join(ROOT, 'index.html');
const DATA_DIR = path.join(ROOT, 'data');
const OUT_PATH = path.join(ROOT, 'miniprogram', 'app.js');

/* ---------------- 1. 从 index.html 提取 JS 变量 ---------------- */

// 括号平衡法：从 "var X = " 后开始扫描，直到括号归零且遇到分号
function extractVar(src, name) {
  const re = new RegExp('var\\s+' + name + '\\s*=\\s*');
  const m = re.exec(src);
  if (!m) throw new Error('index.html 中未找到变量: ' + name);
  const start = m.index + m[0].length;
  let depth = 0;
  let quote = null;
  for (let i = start; i < src.length; i++) {
    const c = src[i];
    if (quote) {
      if (c === '\\') { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue; }
    if (c === '{' || c === '[') depth++;
    else if (c === '}' || c === ']') depth--;
    else if (c === ';' && depth === 0) return src.slice(start, i);
  }
  throw new Error('变量 ' + name + ' 解析失败：括号未闭合');
}

const html = fs.readFileSync(HTML_PATH, 'utf8');

// eslint-disable-next-line no-eval
const NAV = eval('(' + extractVar(html, 'NAV') + ')');
// eslint-disable-next-line no-eval
const README = eval('(' + extractVar(html, 'README') + ')');
// eslint-disable-next-line no-eval
const TM = eval('(' + extractVar(html, 'TM') + ')');

/* ---------------- 2. 模块与图标映射 ---------------- */

// 7 大模块 → 小程序页面路由
const MODULES = [
  { id: '01-投研信息收集', name: '投研信息收集', icon: '📡', page: '/pages/research/research' },
  { id: '02-资本市场信息', name: '资本市场信息', icon: '🌐', page: '/pages/research/research' },
  { id: '03-A股盘面信息', name: 'A股盘面信息', icon: '📈', page: '/pages/market/market' },
  { id: '04-投资复盘', name: '投资复盘', icon: '📝', page: '/pages/review/review' },
  { id: '05-行业与个股分析', name: '行业与个股分析', icon: '🔍', page: '/pages/analysis/analysis' },
  { id: '06-投资策略分析', name: '投资策略分析', icon: '🧠', page: '/pages/strategy/strategy' },
  { id: '07-工具与模板', name: '工具与模板', icon: '🛠️', page: '/pages/templates/templates' }
];

// 子模块 emoji（网页端用 SVG，小程序无 SVG 组件故用 emoji 对应）
const ICONS = {
  宏观研究: '🏛️', 券商研报: '📊', 每日晨报: '📰',
  资金流向: '💰',
  每日盘面: '📈', 板块轮动: '🎡', 行业板块龙头股分析: '🐲',
  日度复盘: '📅', 月度复盘: '📆',
  行业研究: '🏭', 个股深度: '🎯', 财务分析: '📉', 估值模型: '⚖️',
  策略回测: '🧪', 组合管理: '💼', 风控体系: '🛡️', 投资笔记: '📓',
  日报模板: '📋', 周报模板: '🗂️', 复盘模板: '🔁'
};

/* ---------------- 3. 由 README 生成子模块表 ---------------- */

const subModules = {};
Object.keys(README).forEach(key => {
  const [parent, name] = key.split('|||');
  if (!parent || !name) return;
  subModules[name] = {
    parent,
    icon: ICONS[name] || '📄',
    desc: README[key]
  };
});

// 工具与模板的 3 个子项在 NAV 中以 children 形式存在，README 里也有，此处确保齐全
const TOOLS_CHILD = { 日报模板: 1, 周报模板: 1, 复盘模板: 1 };
Object.keys(TOOLS_CHILD).forEach(n => {
  if (!subModules[n]) {
    subModules[n] = { parent: '07-工具与模板', icon: ICONS[n], desc: README['07-工具与模板|||' + n] || '' };
  }
});

/* ---------------- 4. 由 NAV 生成导航分组（对齐网页端三组） ---------------- */

const navGroups = NAV.map(group => ({
  label: group.label,
  items: group.items.map(it => ({
    id: it.id,
    name: it.name,
    icon: ICONS[it.name] || '📄',
    children: it.children || null
  }))
}));

/* ---------------- 5. 读取最新晨报正文（小程序无法 fetch 本地 PDF，故内嵌文本快照） ---------------- */

function loadLatestBriefing() {
  // 晨报可能落在 data/ 或 01-投研信息收集/每日晨报/，两处都要扫，取日期最新的一份
  const dirs = [
    DATA_DIR,
    path.join(ROOT, '01-投研信息收集', '每日晨报')
  ].filter(fs.existsSync);

  const found = [];
  for (const dir of dirs) {
    for (const f of fs.readdirSync(dir)) {
      if (/^\d{4}-\d{2}-\d{2}-晨报\.md$/.test(f)) {
        found.push({ dir, file: f });
      }
    }
  }
  if (!found.length) return null;

  // 取日期最大的一份（文件名即日期，字典序等于时间序）
  found.sort((a, b) => a.file < b.file ? -1 : a.file > b.file ? 1 : 0);
  const { dir, file: latest } = found[found.length - 1];
  const date = latest.replace('-晨报.md', '');
  const relDir = path.relative(ROOT, dir).replace(/\\/g, '/');
  const content = fs.readFileSync(path.join(dir, latest), 'utf8')
    .replace(/\r\n/g, '\n')
    .trim();

  return {
    date,
    file: latest,
    content,
    note: '本页为晨报文本快照，同步自 ' + relDir + '/' + latest + '。完整 PDF 版请在网页端工作台查看（小程序沙箱无法读取本地 PDF 文件）。'
  };
}

const briefing = loadLatestBriefing();

/* ---------------- 6. 生成 app.js ---------------- */

const now = new Date();
const pad = n => ('0' + n).slice(-2);
const stamp = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) +
  ' ' + pad(now.getHours()) + ':' + pad(now.getMinutes());

// slogan 同样取自 index.html，避免两端文案不一致
const sloganMatch = html.match(/<span class="header-sub">([^<]*)<\/span>/);
const slogan = sloganMatch && sloganMatch[1].trim() ? sloganMatch[1].trim() : '投研工作台';

const data = {
  workspace: {
    name: '投研工作台',
    slogan,
    version: '1.1.0',
    syncStatus: '本地数据 · 已同步',
    syncedAt: stamp,
    dataSource: 'index.html'
  },
  modules: MODULES,
  subModules,
  navGroups,
  templates: TM,
  briefing
};

const out = `// app.js - 投研工作台全局数据
//
// ⚠️ 本文件由 tools/sync-miniprogram.js 自动生成，请勿手工编辑。
//    数据源：index.html（NAV / README / TM）+ data/ 最新晨报
//    生成时间：${stamp}
//    修改模块结构或文案请改 index.html 后重跑：node tools/sync-miniprogram.js

App({
  globalData: ${JSON.stringify(data, null, 2)},

  onLaunch() {
    // 小程序启动时执行
  }
});
`;

fs.writeFileSync(OUT_PATH, out, 'utf8');

/* ---------------- 6.5 自动刷新「行业研究」页最新一期周报区块 ---------------- */
// 扫描 05-行业与个股分析/行业研究/ 下 *_盘面产业链资金面周报_YYYYMMDD.md，
// 按板块归并取最新一期，注入 index.html 的 WEEKLY_REPORTS_START/END 标记区间。
// 这样每周一同步脚本运行后，网页端行业研究页始终展示最新一期，无需手工维护。

function syncWeeklyReports(srcHtml) {
  const reportDir = path.join(ROOT, '05-行业与个股分析', '行业研究');
  if (!fs.existsSync(reportDir)) return srcHtml;

  const SECTORS = ['AI', '人形机器人', '半导体', '智能电网', '生物制药', '电力', '自动驾驶'];
  const map = {};
  for (const f of fs.readdirSync(reportDir)) {
    const m = f.match(/^(.+?)_盘面产业链资金面周报_(\d{8})\.md$/);
    if (!m) continue;
    const sector = m[1];
    const date = m[2];
    if (!map[sector] || date > map[sector].date) map[sector] = { date, file: f };
  }

  const items = SECTORS
    .filter(s => map[s])
    .map(s => {
      const { date, file } = map[s];
      const disp = date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6, 8);
      return '<div class="report-item"><a href="05-行业与个股分析/行业研究/' + file +
        '" target="_blank">&#128196; ' + s + '产业链周报（' + disp + '）</a>' +
        '<span class="report-desc">' + s + ' · 盘面+产业链+资金面</span></div>';
    })
    .join('\n    ');

  const startTag = '<!-- WEEKLY_REPORTS_START -->';
  const endTag = '<!-- WEEKLY_REPORTS_END -->';
  const si = srcHtml.indexOf(startTag);
  const ei = srcHtml.indexOf(endTag);
  if (si === -1 || ei === -1) return srcHtml;
  return srcHtml.slice(0, si + startTag.length) + '\n    ' + items + '\n    ' + srcHtml.slice(ei);
}

const updatedHtml = syncWeeklyReports(html);
if (updatedHtml !== html) {
  fs.writeFileSync(HTML_PATH, updatedHtml, 'utf8');
  const cnt = (updatedHtml.match(/_盘面产业链资金面周报_/g) || []).length;
  console.log('✔ 已刷新「行业研究」页最新一期周报区块（' + cnt + ' 份）');
}

/* ---------------- 7. 输出核对报告 ---------------- */

console.log('✔ 已生成 ' + path.relative(ROOT, OUT_PATH));
console.log('  子模块数量：' + Object.keys(subModules).length);
console.log('  导航分组  ：' + navGroups.map(g => g.label + '(' + g.items.length + ')').join(' / '));
console.log('  模板数量  ：' + Object.keys(TM).length);
console.log('  晨报快照  ：' + (briefing ? briefing.date + '（' + briefing.content.length + ' 字符）' : '无'));
