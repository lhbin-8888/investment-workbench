// pages/market/market.js — 对应网页端「投研分析」组
const app = getApp();

Page({
  data: {
    title: '',
    sub: '',
    items: []
  },

  onLoad() {
    const g = app.globalData;
    const group = g.navGroups.find(x => x.label === '投研分析') || { items: [] };
    const items = group.items.map(it => ({
      name: it.name,
      icon: it.icon,
      desc: (g.subModules[it.name] || {}).desc || ''
    }));
    this.setData({
      title: group.label,
      sub: '盘面速览 · 板块轮动 · 晨报',
      items
    });
  },

  onTap(e) {
    const name = e.currentTarget.dataset.name;
    wx.navigateTo({ url: '/pages/detail/detail?name=' + encodeURIComponent(name) });
  }
});
