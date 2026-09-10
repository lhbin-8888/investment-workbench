// pages/analysis/analysis.js
const app = getApp();

Page({
  data: {
    items: []
  },

  onLoad() {
    const g = app.globalData;
    const names = ['行业研究', '个股深度', '财务分析', '估值模型'];
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