// pages/strategy/strategy.js
const app = getApp();

Page({
  data: {
    items: []
  },

  onLoad() {
    const g = app.globalData;
    const names = ['策略回测', '组合管理', '风控体系', '投资笔记'];
    const items = names.map(n => ({
      name: n,
      icon: g.subModules[n].icon,
      desc: g.subModules[n].desc
    }));
    this.setData({ items });
  },

  onTap(e) {
    const name = e.currentTarget.dataset.name;
    wx.navigateTo({ url: '/pages/detail/detail?name=' + encodeURIComponent(name) });
  }
});