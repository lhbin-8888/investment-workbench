// pages/templates/templates.js
const app = getApp();

Page({
  data: {
    items: []
  },

  onLoad() {
    const g = app.globalData;
    const names = ['日报模板', '周报模板', '复盘模板'];
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