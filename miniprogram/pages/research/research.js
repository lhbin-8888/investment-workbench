// pages/research/research.js — 对应网页端「投研研究」组
// 按父模块（01/02/05/06/07）自动分组，与网页端侧边栏结构保持一致
const app = getApp();

Page({
  data: {
    title: '',
    sub: '',
    sections: []
  },

  onLoad() {
    const g = app.globalData;
    const group = g.navGroups.find(x => x.label === '投研研究') || { items: [] };

    const sections = [];
    const map = {};

    group.items.forEach(it => {
      const pid = it.id;
      if (!map[pid]) {
        const mod = g.modules.find(m => m.id === pid);
        map[pid] = {
          id: pid,
          name: mod ? mod.name : pid.replace(/^\d+-/, ''),
          items: []
        };
        sections.push(map[pid]);
      }
      const push = name => {
        map[pid].items.push({
          name,
          icon: (g.subModules[name] || {}).icon || it.icon,
          desc: (g.subModules[name] || {}).desc || ''
        });
      };
      // 「工具与模板」在网页端是带 children 的聚合入口，此处展开为独立子项
      if (it.children && it.children.length) {
        it.children.forEach(push);
      } else {
        push(it.name);
      }
    });

    this.setData({
      title: group.label,
      sub: '宏观 · 政策 · 研报 · 商品 · 资金 · 行业 · 策略 · 模板',
      sections
    });
  },

  onTap(e) {
    const name = e.currentTarget.dataset.name;
    wx.navigateTo({ url: '/pages/detail/detail?name=' + encodeURIComponent(name) });
  }
});
