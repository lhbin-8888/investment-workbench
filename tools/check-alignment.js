#!/usr/bin/env node
/**
 * check-alignment.js — 核对网页端与小程序端结构是否一致
 *
 * 用法：node tools/check-alignment.js
 * 检查项：
 *   1. 网页端 NAV/README 中的子模块，是否全部同步到小程序 subModules
 *   2. 小程序三个功能页引用的子模块名，是否都能在 subModules 中查到（防止 undefined 报错）
 *   3. 晨报快照是否存在
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

function extractVar(src, name) {
  const re = new RegExp('var\\s+' + name + '\\s*=\\s*');
  const m = re.exec(src);
  if (!m) throw new Error('未找到变量: ' + name);
  const start = m.index + m[0].length;
  let depth = 0, quote = null;
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
  throw new Error('变量 ' + name + ' 括号未闭合');
}

// ---- 网页端数据源 ----
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
// eslint-disable-next-line no-eval
const NAV = eval('(' + extractVar(html, 'NAV') + ')');
// eslint-disable-next-line no-eval
const README = eval('(' + extractVar(html, 'README') + ')');

const webSubs = new Set();
Object.keys(README).forEach(k => webSubs.add(k.split('|||')[1]));
NAV.forEach(g => g.items.forEach(it => {
  if (it.children) it.children.forEach(c => webSubs.add(c));
  else webSubs.add(it.name);
}));

// ---- 小程序端数据 ----
const appSrc = fs.readFileSync(path.join(ROOT, 'miniprogram', 'app.js'), 'utf8');
const body = appSrc.replace(/^[\s\S]*?App\(/, '').replace(/\);\s*$/, '');
// eslint-disable-next-line no-eval
const G = eval('(' + body + ')').globalData;

const mpSubs = new Set(Object.keys(G.subModules));

// ---- 1. 子模块覆盖对比 ----
const missing = [...webSubs].filter(n => !mpSubs.has(n));
const extra = [...mpSubs].filter(n => !webSubs.has(n));

console.log('【1】子模块覆盖对比');
console.log('  网页端子模块：' + webSubs.size + ' 个');
console.log('  小程序子模块：' + mpSubs.size + ' 个');
console.log(missing.length ? '  ✗ 小程序缺失：' + missing.join('、') : '  ✔ 无缺失');
console.log(extra.length ? '  △ 小程序多余：' + extra.join('、') : '  ✔ 无多余');

// ---- 2. 页面引用有效性 ----
console.log('\n【2】页面引用有效性');
const groups = ['投研分析', '交易管理', '投研研究'];
let totalRefs = 0;
let badRefs = [];

groups.forEach(label => {
  const group = G.navGroups.find(x => x.label === label);
  if (!group) { badRefs.push('分组缺失: ' + label); return; }
  const names = [];
  group.items.forEach(it => {
    if (it.children && it.children.length) names.push(...it.children);
    else names.push(it.name);
  });
  totalRefs += names.length;
  const bad = names.filter(n => !G.subModules[n]);
  console.log('  ' + label + '：' + names.length + ' 项' + (bad.length ? '  ✗ 无效引用: ' + bad.join('、') : '  ✔'));
  bad.forEach(n => badRefs.push(n));
});

// ---- 3. 晨报 ----
console.log('\n【3】每日晨报');
if (G.briefing) {
  console.log('  ✔ 已内嵌快照：' + G.briefing.date + '（' + G.briefing.content.length + ' 字符）');
  console.log('  ✔ 子模块已注册：' + (G.subModules['每日晨报'] ? '是' : '否'));
} else {
  console.log('  ✗ 未找到晨报快照');
  badRefs.push('briefing');
}

// ---- 结论 ----
console.log('\n【结论】共校验 ' + totalRefs + ' 处页面引用');
const ok = !missing.length && !extra.length && !badRefs.length && !!G.briefing;
console.log(ok ? '✔ 两端结构完全一致' : '✗ 存在差异，请检查上述项目');
process.exit(ok ? 0 : 1);
