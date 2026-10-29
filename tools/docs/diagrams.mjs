// 老板介绍文档里的两张示意图（联动架构、一次运营任务的联动流程）。node diagrams.mjs → docs/老板介绍/图/*.svg
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { textWidth } from './mindmap.mjs';

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', '老板介绍', '图');
const FONT = "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif";
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const INK = '#1F2937', MUTED = '#6B7280';

class Svg {
  constructor(w, h) { this.w = w; this.h = h; this.p = [`<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#475569"/></marker></defs>`]; }
  rect(x, y, w, h, { fill = '#fff', stroke = '#CBD5E1', r = 8, sw = 1.2 } = {}) { this.p.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`); }
  text(x, y, s, { size = 14, bold = false, fill = INK, anchor = 'middle' } = {}) {
    String(s).split('\n').forEach((line, i, a) => this.p.push(`<text x="${x}" y="${y + (i - (a.length - 1) / 2) * (size + 4)}" text-anchor="${anchor}" dominant-baseline="middle" font-size="${size}" ${bold ? 'font-weight="700"' : ''} fill="${fill}" font-family="${FONT}">${esc(line)}</text>`));
  }
  box(x, y, w, h, s, o = {}) { this.rect(x, y, w, h, { fill: o.fill, stroke: o.stroke, r: o.r }); this.text(x + w / 2, y + h / 2, s, { size: o.size ?? 14, bold: o.bold, fill: o.color }); }
  arrow(x1, y1, x2, y2, label, { both = false, dash = false, lx = 0, ly = -9 } = {}) {
    this.p.push(`<path d="M${x1} ${y1} L${x2} ${y2}" stroke="#475569" stroke-width="1.6" fill="none" ${dash ? 'stroke-dasharray="6 4"' : ''} marker-end="url(#a)" ${both ? 'marker-start="url(#a)"' : ''}/>`);
    if (label) { const mx = (x1 + x2) / 2 + lx, my = (y1 + y2) / 2 + ly; const w = textWidth(label, 14) + 12; this.p.push(`<rect x="${mx - w / 2}" y="${my - 10}" width="${w}" height="20" rx="4" fill="#fff" opacity=".92"/>`); this.text(mx, my, label, { size: 14, fill: '#374151' }); }
  }
  svg() { return `<svg xmlns="http://www.w3.org/2000/svg" width="${this.w}" height="${this.h}" viewBox="0 0 ${this.w} ${this.h}"><rect width="${this.w}" height="${this.h}" fill="#fff"/>${this.p.join('')}</svg>\n`; }
}

// ---------- 图 2：联动架构 ----------
{
  const s = new Svg(1000, 640);
  const IND = { fill: '#EEF2FF', stroke: '#6366F1' }, GRN = { fill: '#ECFDF5', stroke: '#10B981' }, AMB = { fill: '#FFFBEB', stroke: '#F59E0B' }, GRY = { fill: '#F8FAFC', stroke: '#94A3B8' };
  // 顶层：老板 / 管理员
  s.rect(20, 16, 960, 96, { fill: '#FDF2F8', stroke: '#EC4899', r: 12 });
  s.text(40, 34, '管理层（浏览器打开控制台）', { size: 16, bold: true, anchor: 'start', fill: '#9D174D' });
  ['总览与工作看板', '成员与岗位包', '技能库 / 知识库', '模型与成本', '应用与接入', '审计与应用健康'].forEach((t, i) => s.box(40 + i * 156, 56, 144, 40, t, { ...GRY, size: 15 }));
  // 中枢
  s.rect(20, 190, 960, 218, { fill: '#F5F3FF', stroke: '#6366F1', r: 12 });
  s.text(40, 208, '企业智能体中枢（部署在公司内网）', { size: 16, bold: true, anchor: 'start', fill: '#3730A3' });
  s.box(40, 234, 280, 52, '中枢 MCP 服务\n身份识别 · 岗位包过滤 · 全程审计', { ...IND, size: 15 });
  s.box(340, 234, 200, 52, '技能库 · 知识库\n版本与审核', { ...IND, size: 15 });
  s.box(560, 234, 200, 52, '模型网关\n按人计量 · 月度额度', { ...IND, size: 15 });
  s.box(780, 234, 180, 52, 'GPU 出图 / 出视频\n任务队列', { ...IND, size: 15 });
  s.box(40, 306, 280, 52, '统一账号与组织（Casdoor）', { ...GRY, size: 15 });
  s.box(340, 306, 200, 52, '审计与工作成果库', { ...GRY, size: 15 });
  s.box(560, 306, 200, 52, '应用分发\n下载校验 · 版本与灰度', { ...GRY, size: 15 });
  s.box(780, 306, 180, 52, '应用健康与在线\n错误自动回传', { ...GRY, size: 15 });
  s.arrow(500, 112, 500, 190, '管理 / 查看', { both: true, lx: 56 });
  // 员工电脑
  s.rect(20, 478, 960, 146, { fill: '#F0FDF4', stroke: '#10B981', r: 12 });
  s.text(40, 496, '员工电脑（每人一台，数据留在本机）', { size: 16, bold: true, anchor: 'start', fill: '#065F46' });
  s.box(40, 520, 240, 80, '员工自己的 AI 助手\nWorkBuddy · CodeBuddy\nHermes · Cursor …', { ...GRN, size: 15 });
  s.box(330, 520, 240, 80, '本机接入器（MCP 桥）\n自动登录 · 续期 · 同步技能\n报到 · 错误回传', { ...GRN, size: 15 });
  s.box(620, 520, 340, 80, '小红书运营工作台（本机网页）\n对标 · 选题 · 文案 · 封面 · 视频 · 复盘\n只读分析，不自动发布', { ...AMB, size: 15, bold: false });
  s.arrow(280, 560, 330, 560, '', { both: true });
  s.arrow(570, 560, 620, 560, '', { both: true });
  s.arrow(450, 478, 450, 408, 'MCP：技能 / 知识 / 出图 / 成果上报', { both: true, lx: 110 });
  s.arrow(790, 478, 640, 408, '模型调用（走中枢网关）', { lx: 70, ly: 6 });
  s.arrow(900, 478, 880, 408, '', { dash: true });
  s.text(902, 440, '应用分发', { size: 14, fill: MUTED, anchor: 'start' });
  fs.writeFileSync(path.join(OUT, '图2-联动架构.svg'), s.svg());
}

// ---------- 图 4：一次运营任务的联动流程 ----------
{
  const steps = [
    ['①', '员工说「打开小红书工作台」', '员工', '中枢按岗位包校验并记审计，本机下载、校验 SHA-256 后启动'],
    ['②', '对标：只读采集博主和爆款', '工作台', '在员工自己的浏览器里完成；总开关默认关，有每日上限、间隔与冷静期'],
    ['③', '开始写选题 / 文案', '联动', '工作台通过 MCP 读公司技能（选题、写作、合规）并检索知识库（产品卖点、品牌调性、违禁词）'],
    ['④', 'AI 助手生成内容', '联动', '模型调用走中枢网关：按人计量、受岗位包额度限制'],
    ['⑤', '封面 / 视频', '联动', '提交到中枢的出图出视频队列，本机 GPU、第三方 API 或 H3 网关任一通道完成'],
    ['⑥', '人工确认并自己发布', '员工', '红线：工作台不会自动发布；员工确认内容后自己发'],
    ['⑦', '成果与问题回到中枢', '联动', '成果上报进老板看板；报错自动回传到应用健康；AI 助手发现技能或知识有误只能提「改进建议」，由主管审核后才生效'],
  ];
  const W = 1000, rowH = 76, top = 56, H = top + steps.length * rowH + 20;
  const s = new Svg(W, H);
  const lane = { 员工: ['#ECFDF5', '#10B981'], 工作台: ['#FFFBEB', '#F59E0B'], 联动: ['#EEF2FF', '#6366F1'] };
  s.text(40, 28, '步骤', { size: 15, bold: true, anchor: 'start', fill: MUTED });
  s.text(120, 28, '做什么', { size: 15, bold: true, anchor: 'start', fill: MUTED });
  s.text(420, 28, '工作台与中枢怎么联动', { size: 15, bold: true, anchor: 'start', fill: MUTED });
  steps.forEach(([n, what, who, how], i) => {
    const y = top + i * rowH, [bg, bd] = lane[who];
    s.rect(20, y, 960, rowH - 10, { fill: bg, stroke: bd, r: 10 });
    s.text(52, y + (rowH - 10) / 2, n, { size: 24, bold: true, fill: bd });
    s.text(96, y + (rowH - 10) / 2, what.replace(/(.{13})/g, '$1\n').trim(), { size: 16, bold: true, anchor: 'start' });
    const wrapped = how.replace(/(.{28})/g, '$1\n').trim();
    s.text(420, y + (rowH - 10) / 2, wrapped, { size: 15, anchor: 'start', fill: '#374151' });
    s.p.push(`<rect x="${920 - 8}" y="${y + 10}" width="52" height="22" rx="11" fill="${bd}"/>`);
    s.text(938 + 0, y + 21, who === '联动' ? '联动' : who, { size: 14, fill: '#fff' });
  });
  fs.writeFileSync(path.join(OUT, '图4-一次运营任务的联动流程.svg'), s.svg());
}
console.log('已生成 图2、图4');
