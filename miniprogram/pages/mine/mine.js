// pages/mine/mine.js
const app = getApp();

Page({
  data: {
    workspace: {},
    aboutItems: []
  },

  onLoad() {
    const g = app.globalData;
    this.setData({
      workspace: g.workspace,
      aboutItems: [
        { label: '版本', value: g.workspace.version },
        { label: '数据来源', value: 'index.html（脚本自动同步）' },
        { label: '最近同步', value: g.workspace.syncedAt },
        {
          label: '模块数量',
          value: g.modules.length + ' 大模块 / ' + Object.keys(g.subModules).length + ' 子模块'
        },
        { label: '运行模式', value: '纯前端 · 无需后端' }
      ]
    });
  }
});