// pages/review/review.js — 对应网页端「交易管理」组
const app = getApp();

Page({
  data: {
    title: '',
    sub: '',
    items: []
  },

  onLoad() {
    const g = app.globalData;
    const group = g.navGroups.find(x => x.label === '交易管理') || { items: [] };
    const items = group.items.map(it => ({
      name: it.name,
      icon: it.icon,
      desc: (g.subModules[it.name] || {}).desc || ''
    }));
    this.setData({
      title: group.label,
      sub: '交易记录 · 日度复盘 · 周度复盘 · 月度复盘',
      items
    });
  },

  onTap(e) {
    const name = e.currentTarget.dataset.name;
    wx.navigateTo({ url: '/pages/detail/detail?name=' + encodeURIComponent(name) });
  }
});
