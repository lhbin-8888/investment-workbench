import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const moduleDirs = [
  '01-投研信息收集',
  '02-资本市场信息',
  '03-A股盘面信息',
  '04-投资复盘',
  '05-行业与个股分析',
  '06-投资策略分析'
];
const skipFiles = new Set(['README.md', 'manifest.json', 'sector-rotation-data.json']);

function relativePosix(file) {
  return path.relative(root, file).split(path.sep).join('/');
}

// 从文件名提取日期键（YYYYMMDD）：优先 YYYY-MM-DD，其次连续 8 位数字
function dateKey(file) {
  const base = path.basename(file, path.extname(file));
  let m = base.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) return m[1] + m[2] + m[3];
  m = base.match(/(\d{8})/);
  return m ? m[1] : '';
}

function detectType(file) {
  const ext = path.extname(file).toLowerCase();
  if (ext === '.pdf') return 'pdf';
  if (ext === '.json') return 'json';
  if (ext === '.html' || ext === '.htm') return 'html';
  if (['.xlsx', '.xls', '.csv', '.docx', '.doc', '.pptx', '.ppt'].includes(ext)) return ext.slice(1);
  return 'md';
}

function listLeafDirs(moduleDir) {
  const base = path.join(root, moduleDir);
  if (!fs.existsSync(base)) return [];
  return fs.readdirSync(base, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(base, entry.name));
}

function collectDocs() {
  const manifest = {};
  const add = (section, file) => {
    if (!manifest[section]) manifest[section] = [];
    const title = path.basename(file, path.extname(file));
    manifest[section].push({
      title,
      file: relativePosix(file),
      type: detectType(file),
      desc: ''
    });
  };

  for (const moduleDir of moduleDirs) {
    for (const dir of listLeafDirs(moduleDir)) {
      const leaf = path.basename(dir);
      const template = `${leaf}.md`;
      const files = fs.readdirSync(dir, { withFileTypes: true })
        .filter((entry) => entry.isFile())
        .filter((entry) => !skipFiles.has(entry.name))
        .filter((entry) => entry.name !== template)
        // 全部 .md 仅本地留档、不推线上（见 .gitignore），清单只收 PDF / HTML / 数据文件
        .filter((entry) => !entry.name.toLowerCase().endsWith('.md'))
        .map((entry) => path.join(dir, entry.name));

      for (const file of files) {
        const name = path.basename(file, path.extname(file));
        if (leaf === '每日晨报' && name.includes('行业板块龙头股分析')) {
          add('行业板块龙头股分析', file);
          add('每日盘面', file);
        } else {
          add(leaf, file);
        }
      }
    }
  }

  for (const section of Object.keys(manifest)) {
    manifest[section].sort((a, b) => b.title.localeCompare(a.title, 'zh-CN'));
  }
  // 时间流板块统一按报告日期倒序（不看名称归类，避免被产业链名/前缀打乱）；
  // 同日期内按标题、文件名兜底，保证顺序稳定。其余板块维持标题排序。
  const DATE_SORTED = ['行业研究', '每日晨报', '宏观研究', '行业板块龙头股分析', '板块轮动'];
  for (const section of DATE_SORTED) {
    if (!manifest[section]) continue;
    manifest[section].sort((a, b) => {
      const da = dateKey(a.file), db = dateKey(b.file);
      if (da !== db) return db.localeCompare(da);
      const t = a.title.localeCompare(b.title, 'zh-CN');
      return t !== 0 ? t : a.file.localeCompare(b.file);
    });
  }
  // 命名规范自检（2026-10-13 彬哥哥确认口径）：时间流板块的报告/记录类条目必须带日期，
  // 否则会掉到列表末尾。只提示、不改动生成结果。工具/脚本/配置/代码类不在此列。
  // 豁免：日报型的「当期固定入口」（供页面 iframe 实时引用）不带日期属预期，
  // 日期由同目录下同名的带日期归档副本承载。
  const UNDATED_OK = new Set([
    '03-A股盘面信息/板块轮动/板块轮动与主线确定每日报告.html'
  ]);
  const undated = [];
  for (const section of DATE_SORTED) {
    if (!manifest[section]) continue;
    for (const doc of manifest[section]) {
      if (!dateKey(doc.file) && !UNDATED_OK.has(doc.file)) {
        undated.push(`${section} / ${doc.file}`);
      }
    }
  }
  if (undated.length) {
    console.warn(`⚠️ 命名规范自检：${undated.length} 个条目文件名不含日期，请按「YYYY-MM-DD-主题」补日期`);
    for (const item of undated) console.warn(`   - ${item}`);
  } else {
    console.log('命名规范自检通过：时间流板块条目均带日期');
  }
  return manifest;
}

const manifest = collectDocs();
const outputPath = path.join(root, 'data', 'manifest.json');
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(manifest, null, 2) + '\n', 'utf8');

const total = Object.values(manifest).reduce((sum, docs) => sum + docs.length, 0);
console.log(`manifest 已生成: ${total} 个文档, ${Object.keys(manifest).length} 个板块`);
for (const [section, docs] of Object.entries(manifest)) {
  console.log(`  ${section}: ${docs.length}`);
}
