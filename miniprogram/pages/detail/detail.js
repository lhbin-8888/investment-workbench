// pages/detail/detail.js
const app = getApp();

Page({
  data: {
    name: '',
    parent: '',
    desc: '',
    isTemplate: false,
    isBriefing: false,
    briefingDate: '',
    briefingNote: '',
    html: ''
  },

  onLoad(options) {
    const name = decodeURIComponent(options.name || '');
    const g = app.globalData;
    const sub = g.subModules[name] || {};
    const tpl = g.templates[name];

    // 每日晨报：渲染内嵌的文本快照（小程序沙箱无法读取本地 PDF）
    const isBriefing = name === '每日晨报' && !!g.briefing;
    let html = '';
    if (isBriefing) {
      html = this.markdownToHtml(g.briefing.content);
    } else if (tpl) {
      html = this.markdownToHtml(tpl);
    }

    this.setData({
      name,
      parent: sub.parent || '',
      desc: sub.desc || '',
      isTemplate: !!tpl,
      isBriefing,
      briefingDate: isBriefing ? g.briefing.date : '',
      briefingNote: isBriefing ? g.briefing.note : '',
      html
    });
    wx.setNavigationBarTitle({ title: name });
  },

  // 简易 Markdown -> HTML 渲染（支持标题/列表/表格/加粗/分割线）
  markdownToHtml(md) {
    if (!md) return '';
    let lines = md.split('\n');
    let html = '';
    let inTable = false;
    let inList = false;

    const esc = s => s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    const inline = s => s
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>');

    for (let i = 0; i < lines.length; i++) {
      let line = lines[i].trim();

      // 表格行
      if (line.startsWith('|')) {
        const cells = line.split('|').filter(c => c.trim() !== '');
        if (!inTable) {
          html += '<table style="width:100%;border-collapse:collapse;margin:16rpx 0;">';
          inTable = true;
        }
        // 分隔行（---）跳过
        if (cells.every(c => /^:?-{2,}:?$/.test(c.trim()))) continue;
        const tag = inTable && !this._tableHeaderDone ? 'th' : 'td';
        html += '<tr>';
        cells.forEach(c => {
          html += '<' + tag + ' style="border:1rpx solid #374151;padding:10rpx 12rpx;font-size:24rpx;">' + inline(esc(c.trim())) + '</' + tag + '>';
        });
        html += '</tr>';
        if (tag === 'th') this._tableHeaderDone = true;
        continue;
      } else if (inTable) {
        html += '</table>';
        inTable = false;
        this._tableHeaderDone = false;
      }

      // 标题
      if (/^#{1,6}\s/.test(line)) {
        const level = line.match(/^(#{1,6})\s/)[1].length;
        const size = [40, 36, 32, 30, 28, 26][level - 1];
        html += '<h' + level + ' style="font-size:' + size + 'rpx;color:#FFFFFF;margin:20rpx 0 12rpx;font-weight:700;">' + inline(esc(line.replace(/^#{1,6}\s/, ''))) + '</h' + level + '>';
        continue;
      }

      // 无序列表
      if (/^[-*]\s/.test(line)) {
        if (!inList) { html += '<ul style="margin:12rpx 0;padding-left:32rpx;">'; inList = true; }
        html += '<li style="margin:8rpx 0;color:#D1D5DB;">' + inline(esc(line.replace(/^[-*]\s/, ''))) + '</li>';
        continue;
      } else if (inList) {
        html += '</ul>';
        inList = false;
      }

      // 有序列表
      if (/^\d+\.\s/.test(line)) {
        if (!inList) { html += '<ol style="margin:12rpx 0;padding-left:32rpx;">'; inList = true; }
        html += '<li style="margin:8rpx 0;color:#D1D5DB;">' + inline(esc(line.replace(/^\d+\.\s/, ''))) + '</li>';
        continue;
      } else if (inList) {
        html += '</ol>';
        inList = false;
      }

      // 分割线
      if (/^---+$/.test(line)) {
        html += '<hr style="border:none;border-top:1rpx solid #374151;margin:20rpx 0;">';
        continue;
      }

      // 空行
      if (line === '') {
        html += '<br/>';
        continue;
      }

      // 普通段落
      html += '<p style="margin:8rpx 0;color:#D1D5DB;">' + inline(esc(line)) + '</p>';
    }

    if (inTable) html += '</table>';
    if (inList) html += '</ul>';

    return html;
  }
});