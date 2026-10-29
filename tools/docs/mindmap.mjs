// 把一份 JSON 树画成「从左到右」的思维导图 SVG（build.mjs 会把 SVG 渲染成 PNG 放进 Word / PDF）。
//   node mindmap.mjs <树.json> <输出.svg>
// 树的格式：{ "root": "中心主题", "children": [ { "t": "分支", "children": [ { "t": "子项", "children": [...] } ] } ] }
// 也可以在代码里 import { mindmapSvg }。文字宽度按「汉字 = 字号，英文数字 = 0.58 字号」估算，不依赖字体文件。
import fs from 'node:fs';

export const COLORS = ['#4F46E5', '#0E9F6E', '#D97706', '#DB2777', '#0891B2', '#7C3AED', '#DC2626', '#475569'];
const FONT = "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif";

export const textWidth = (s, size) => [...String(s)].reduce((w, c) => w + (c.charCodeAt(0) > 255 ? size : size * 0.58), 0);
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** 按显示宽度折行：每行最多 maxW 个汉字宽（英文数字按 0.58 个汉字） */
function wrap(text, size, maxW) {
  const lines = []; let cur = '', w = 0;
  for (const c of String(text)) {
    const cw = (c.charCodeAt(0) > 255 ? 1 : 0.58);
    if (w + cw > maxW && cur) { lines.push(cur); cur = ''; w = 0; }
    cur += c; w += cw;
  }
  if (cur) lines.push(cur);
  return lines;
}

export function mindmapSvg(tree, { width = 1000, padX = 12, wrapAt = [9, 8, 13, 13, 13] } = {}) {
  // 字号偏大、长文字折行：图会被缩放到页面宽度，字号大、总宽度小，打印出来才看得清
  const SIZE = [22, 19, 17, 16, 16];
  const LH = 1.3;
  const root = { t: tree.root, children: tree.children };
  const cols = [];
  const prep = (n, d) => {
    const size = SIZE[Math.min(d, 4)];
    n.size = size; n.lines = wrap(n.t, size, wrapAt[Math.min(d, 4)]);
    n.tw = Math.max(...n.lines.map((l) => textWidth(l, size)));
    n.h = n.lines.length * size * LH + (d <= 1 ? 16 : 12);
    (cols[d] ??= []).push(n);
    (n.children ?? []).forEach((c) => prep(c, d + 1));
  };
  prep(root, 0);
  const colW = cols.map((ns, d) => Math.ceil(Math.max(...ns.map((n) => n.tw)) + padX * 2 + (d === 1 ? 8 : 0)));
  const GAP = 40, SEP = 8;
  const total = colW.reduce((a, b) => a + b, 0) + GAP * (cols.length - 1) + 40;
  let yy = 12;
  const place = (n, d, ci) => {
    n.d = d; n.ci = ci;
    if (!(n.children ?? []).length) { n.cy = yy + n.h / 2; yy += n.h + SEP; return; }
    n.children.forEach((c, i) => place(c, d + 1, d === 0 ? i : ci));
    n.cy = (n.children[0].cy + n.children[n.children.length - 1].cy) / 2;
  };
  place(root, 0, 0);
  const H = Math.max(yy + 8, root.h + 24);
  const xs = []; let x = 20;
  colW.forEach((w, d) => { xs[d] = x; x += w + GAP; });
  const out = [];
  const draw = (n) => {
    const color = COLORS[n.ci % COLORS.length];
    const w = colW[n.d], nx = xs[n.d], ny = n.cy - n.h / 2;
    for (const c of n.children ?? []) {
      const sx = nx + w, sy = n.cy, ex = xs[c.d], mx = (sx + ex) / 2;
      out.push(`<path d="M${sx} ${sy} C${mx} ${sy} ${mx} ${c.cy} ${ex} ${c.cy}" fill="none" stroke="${COLORS[c.ci % COLORS.length]}" stroke-width="${c.d === 1 ? 2.6 : 1.8}" opacity=".85"/>`);
    }
    const [fill, extra, txt] = n.d === 0 ? ['#1F2937', '', '#fff'] : n.d === 1 ? [color, '', '#fff'] : [color, ` fill-opacity=".10" stroke="${color}" stroke-opacity=".55"`, '#1F2937'];
    out.push(`<rect x="${nx}" y="${ny}" width="${w}" height="${n.h}" rx="${n.d <= 1 ? 10 : 7}" fill="${fill}"${extra}/>`);
    n.lines.forEach((l, i) => out.push(`<text x="${nx + w / 2}" y="${ny + n.h / 2 + (i - (n.lines.length - 1) / 2) * n.size * LH + 1}" text-anchor="middle" dominant-baseline="middle" font-size="${n.size}" ${n.d <= 1 ? 'font-weight="700"' : ''} fill="${txt}" font-family="${FONT}">${esc(l)}</text>`));
    (n.children ?? []).forEach(draw);
  };
  draw(root);
  const k = Math.min(1, width / total);
  const W = Math.round(total * k), Hh = Math.round(H * k);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${Hh}" viewBox="0 0 ${total} ${H}"><rect width="${total}" height="${H}" fill="#fff"/>${out.join('')}</svg>
`;
}

if (process.argv[1] && process.argv[1].endsWith('mindmap.mjs') && process.argv[2]) {
  const tree = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  fs.writeFileSync(process.argv[3], mindmapSvg(tree));
  console.log('已生成', process.argv[3]);
}
