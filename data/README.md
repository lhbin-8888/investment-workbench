# data 数据目录说明

本目录只存放网页版 `index.html` 读取的文档清单，不再保存文档副本。

## 目录用途

- `manifest.json`：网页版各板块的文档清单，路径指向各模块目录中的真实文件
- 文档正文统一归档到对应模块目录，例如 `01-投研信息收集/每日晨报/`、`05-行业与个股分析/行业研究/`

## 更新清单

新增或移动文档后，在工作台根目录执行：

```powershell
node scripts/sync-manifest.mjs
```

脚本会扫描 `01-07` 各模块子目录，跳过 README 和同名模板，自动生成 `data/manifest.json`。

## 网页访问

网页版使用 `fetch` 读取相对路径文件，不能直接双击 `index.html` 以 `file://` 方式使用。请在根目录启动本地服务：

```powershell
node scripts/serve.mjs
```

然后访问 `http://localhost:8000/index.html`。
