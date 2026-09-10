// pages/index/index.js
const app = getApp();

Page({
  data: {
    today: '',
    slogan: '',
    modules: [],
    quickLinks: [],
    briefing: null
  },

  onLoad() {
    const g = app.globalData;
    const now = new Date();
    const week = ['日', '一', '二', '三', '四', '五', '六'];
    const today = now.getFullYear() + '年' + (now.getMonth() + 1) + '月' + now.getDate() +
      '日 星期' + week[now.getDay()];

    // 快捷入口 = 网页端「投研分析」+「交易管理」两组，直接取同步数据，避免两端不一致
    const quick = ['投研分析', '交易管理'].reduce((acc, label) => {
      const group = g.navGroups.find(x => x.label === label);
      if (group) {
        group.items.forEach(it => acc.push({ name: it.name, icon: it.icon }));
      }
      return acc;
    }, []);

    this.setData({
      today,
      slogan: g.workspace.slogan,
      modules: g.modules,
      quickLinks: quick,
      briefing: g.briefing
    });
  },

  onShow() {
    // 从子页返回时刷新晨报状态
    const b = app.globalData.briefing;
    if (b) this.setData({ briefing: b });
  },

  onModuleTap(e) {
    wx.navigateTo({ url: e.currentTarget.dataset.page });
  },

  onQuickTap(e) {
    const name = e.currentTarget.dataset.name;
    wx.navigateTo({ url: '/pages/detail/detail?name=' + encodeURIComponent(name) });
  },

  onBriefingTap() {
    wx.navigateTo({ url: '/pages/detail/detail?name=' + encodeURIComponent('每日晨报') });
  }
});
