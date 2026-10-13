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
  // 「行业研究」按报告日期倒序排列（不看产业链名称）；同日期再按标题、文件名兜底，保证顺序稳定
  if (manifest['行业研究']) {
    manifest['行业研究'].sort((a, b) => {
      const da = dateKey(a.file), db = dateKey(b.file);
      if (da !== db) return db.localeCompare(da);
      const t = a.title.localeCompare(b.title, 'zh-CN');
      return t !== 0 ? t : a.file.localeCompare(b.file);
    });
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
