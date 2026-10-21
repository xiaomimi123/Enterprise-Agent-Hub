// 生成《开发与架构文档》：node build.mjs
// 源文件：docs/架构文档/*.md（按文件名排序；00-封面.md 是封面信息）→ docs/<标题>.docx 和 .pdf
// Word 用 docx 库生成；PDF 用本机 Chrome / Edge（puppeteer-core）把同一份内容渲染成 HTML 后打印，目录页码用两遍渲染填好。
import fs from 'node:fs';
import path from 'node:path';
import {
  AlignmentType, BorderStyle, Document, Footer, Header, HeadingLevel, ImageRun, InternalHyperlink, Bookmark, LevelFormat, Packer, PageBreak,
  PageNumber, Paragraph, ShadingType, Table, TableCell, TableRow, TextRun, WidthType, TabStopType,
} from 'docx';
import puppeteer from 'puppeteer-core';
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs';
import { PDFDocument, rgb } from 'pdf-lib';
import { REPO, parse, plain } from './md.mjs';

const SRC = path.join(REPO, 'docs', '架构文档');
const OUT = path.join(REPO, 'docs');
const BODY_FONT = 'Microsoft YaHei';
const CODE_FONT = 'Consolas';
const INK = '1F2937';
const MUTED = '6B7280';
const ACCENT = '4F46E5';

// ---------- 读源文件 ----------
const files = fs.readdirSync(SRC).filter((f) => f.endsWith('.md')).sort();
const meta = {};
const blocks = [];
for (const f of files) {
  const text = fs.readFileSync(path.join(SRC, f), 'utf8');
  if (f.startsWith('00-')) {
    for (const line of text.split(/\r?\n/)) {
      const m = line.match(/^([^:：#\s][^:：]*)[:：]\s*(.*)$/);
      if (m) meta[m[1].trim()] = m[2].trim();
    }
    continue;
  }
  blocks.push(...parse(text, SRC));
}
const TITLE = `${meta['公司'] || ''}${meta['标题'] || '开发与架构文档'}`;
const FILE_BASE = meta['文件名'] || '开发与架构文档';

// 标题编号 → 锚点；目录条目
const headings = blocks.filter((b) => b.type === 'h' && b.level <= 2).map((b, i) => ({ ...b, id: `h${i}` }));
let hi = 0;
for (const b of blocks) if (b.type === 'h' && b.level <= 2) b.id = headings[hi++].id;

// ---------- HTML / PDF ----------
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const runsHtml = (runs) => runs.map((r) => (r.c ? `<code>${esc(r.t)}</code>` : r.b ? `<strong>${esc(r.t)}</strong>` : esc(r.t).replace(/\n/g, '<br>'))).join('');

function tableWeights(b) {
  const cols = b.head.length;
  const w = new Array(cols).fill(8);
  const consider = (cells) => cells.forEach((c, k) => { w[k] = Math.max(w[k], Math.min(36, plain(c).length + 3)); });
  consider(b.head);
  b.rows.forEach(consider);
  const sum = w.reduce((a, x) => a + x, 0);
  return w.map((x) => x / sum);
}

function html(tocPages) {
  const out = [];
  const toc = headings.map((h) => {
    const pg = tocPages?.[h.id] ?? '';
    return `<div class="toc l${h.level}"><a href="#${h.id}"><span class="tt">${esc(h.text)}</span><span class="dots"></span><span class="pg">${pg}</span></a></div>`;
  }).join('');
  out.push(`<section class="cover">
    <div class="c1">${esc(meta['公司'] || '')}</div><div class="c2">${esc(meta['产品'] || '')}</div><div class="c3">${esc(meta['标题'] || '')}</div>
    <div class="c4">${esc(meta['副标题'] || '')}</div>
    <table class="meta">${['文档版本', '发布日期', '适用阶段', '代码仓库', '密级'].filter((k) => meta[k]).map((k) => `<tr><td>${k}</td><td>${esc(meta[k])}</td></tr>`).join('')}</table>
  </section>
  <section class="tocpage"><h1 class="toch">目录</h1>${toc}</section>`);
  for (const b of blocks) {
    switch (b.type) {
      case 'h': out.push(`<h${b.level}${b.id ? ` id="${b.id}"` : ''}>${esc(b.text)}</h${b.level}>`); break;
      case 'p': out.push(`<p>${runsHtml(b.runs)}</p>`); break;
      case 'callout': out.push(`<div class="callout">${runsHtml(b.runs)}</div>`); break;
      case 'code': out.push(`<div class="codewrap">${b.caption ? `<div class="cap">${esc(b.caption)}</div>` : ''}<pre>${esc(b.text)}</pre></div>`); break;
      case 'image': out.push(`<figure><img src="file:///${b.file.replace(/\\/g, '/')}"><figcaption>${esc(b.caption)}</figcaption></figure>`); break;
      case 'pagebreak': out.push('<div class="pb"></div>'); break;
      case 'list': {
        let open = null;
        for (const it of b.items) {
          const tag = it.ordered ? 'ol' : 'ul';
          if (open !== tag) { if (open) out.push(`</${open}>`); out.push(`<${tag}>`); open = tag; }
          out.push(`<li class="lv${it.level}">${runsHtml(it.runs)}</li>`);
        }
        if (open) out.push(`</${open}>`);
        break;
      }
      case 'table': {
        const w = tableWeights(b);
        out.push(`<table class="data"><colgroup>${w.map((x) => `<col style="width:${(x * 100).toFixed(1)}%">`).join('')}</colgroup><thead><tr>${b.head.map((c) => `<th>${runsHtml(c)}</th>`).join('')}</tr></thead><tbody>${b.rows.map((r) => `<tr>${r.map((c) => `<td>${runsHtml(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
        break;
      }
      default: break;
    }
  }
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(TITLE)}</title><style>
  @page { size: A4; margin: 22mm 20mm 20mm 20mm; }
  @page :first { margin: 0; }
  * { box-sizing: border-box; }
  body { font-family: '${BODY_FONT}', 'Microsoft JhengHei', sans-serif; font-size: 10.5pt; line-height: 1.75; color: #${INK}; margin: 0; }
  h1 { font-size: 20pt; margin: 0 0 14pt; padding-bottom: 6pt; border-bottom: 2px solid #${ACCENT}; break-before: page; color: #111827; }
  h2 { font-size: 14pt; margin: 20pt 0 8pt; color: #111827; break-after: avoid; }
  h3 { font-size: 11.5pt; margin: 14pt 0 6pt; color: #${ACCENT}; break-after: avoid; }
  p { margin: 0 0 8pt; text-align: justify; }
  code { font-family: '${CODE_FONT}', 'Microsoft YaHei', monospace; font-size: 9pt; background: #F3F4F6; padding: 0 3px; border-radius: 3px; }
  ul, ol { margin: 0 0 8pt; padding-left: 20pt; } li { margin: 0 0 3pt; } li.lv1 { margin-left: 16pt; }
  .callout { background: #EEF2FF; border-left: 3px solid #${ACCENT}; padding: 7pt 10pt; margin: 8pt 0 10pt; break-inside: avoid; }
  .codewrap { margin: 6pt 0 10pt; }
  .cap { font-size: 8.5pt; color: #${MUTED}; margin-bottom: 2pt; font-family: '${CODE_FONT}', 'Microsoft YaHei', monospace; }
  pre { font-family: '${CODE_FONT}', 'Microsoft YaHei', monospace; font-size: 8pt; line-height: 1.45; background: #F8FAFC; border: 1px solid #E5E7EB; border-radius: 4px; padding: 7pt 9pt; margin: 0; white-space: pre-wrap; word-break: break-all; }
  table.data { width: 100%; border-collapse: collapse; margin: 6pt 0 12pt; font-size: 9pt; line-height: 1.5; table-layout: fixed; }
  table.data th { background: #EEF2FF; color: #3730A3; text-align: left; border: 1px solid #D1D5DB; padding: 4pt 6pt; }
  table.data td { border: 1px solid #E5E7EB; padding: 4pt 6pt; vertical-align: top; word-break: break-word; }
  table.data tr { break-inside: avoid; }
  figure { margin: 8pt 0 12pt; text-align: center; break-inside: avoid; } figure img { max-width: 100%; max-height: 120mm; } figcaption { font-size: 9pt; color: #${MUTED}; }
  .cover { height: 297mm; padding: 70mm 28mm 0; page-break-after: always; border-left: 6px solid #${ACCENT}; margin-left: 0; }
  .c1 { font-size: 16pt; letter-spacing: 3pt; color: #${MUTED}; } .c2 { font-size: 34pt; font-weight: 700; color: #111827; margin-top: 6pt; } .c3 { font-size: 26pt; color: #${ACCENT}; margin-top: 4pt; }
  .c4 { font-size: 11pt; color: #${MUTED}; margin: 14pt 0 50pt; }
  table.meta { border-collapse: collapse; font-size: 10.5pt; } table.meta td { padding: 5pt 16pt 5pt 0; } table.meta td:first-child { color: #${MUTED}; }
  .tocpage { page-break-after: always; } .toch { break-before: auto; }
  .toc a { display: flex; align-items: baseline; color: inherit; text-decoration: none; }
  .toc.l1 { font-weight: 700; margin-top: 7pt; } .toc.l2 { padding-left: 18pt; font-size: 9.5pt; color: #374151; line-height: 1.55; }
  .dots { flex: 1; border-bottom: 1px dotted #9CA3AF; margin: 0 6pt; transform: translateY(-3px); } .pg { min-width: 20pt; text-align: right; font-variant-numeric: tabular-nums; }
  .pb { break-after: page; }
  </style></head><body>${out.join('\n')}</body></html>`;
}

function chromePath() {
  const c = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/google-chrome', '/usr/bin/chromium']
    .find((p) => fs.existsSync(p));
  if (!c) throw new Error('没找到 Chrome / Edge，无法生成 PDF 和矢量图');
  return c;
}
const launch = () => puppeteer.launch({ executablePath: chromePath(), headless: true, args: ['--no-sandbox', '--allow-file-access-from-files'] });

/** 把 .svg 图片渲染成 PNG（2 倍分辨率），Word 和 PDF 都用 PNG */
async function prepareImages() {
  const svgs = blocks.filter((b) => b.type === 'image' && b.file.endsWith('.svg'));
  if (!svgs.length) return;
  const dir = path.join(OUT, '.arch-img');
  fs.mkdirSync(dir, { recursive: true });
  const browser = await launch();
  for (const b of svgs) {
    const text = fs.readFileSync(b.file, 'utf8');
    const w = Number(text.match(/<svg[^>]*\swidth="(\d+)/)?.[1] || 960);
    const h = Number(text.match(/<svg[^>]*\sheight="(\d+)/)?.[1] || 540);
    const page = await browser.newPage();
    await page.setViewport({ width: w, height: h, deviceScaleFactor: 2 });
    await page.setContent(`<body style="margin:0;background:#fff">${text}</body>`);
    const png = path.join(dir, path.basename(b.file).replace(/\.svg$/, '.png'));
    await page.screenshot({ path: png, clip: { x: 0, y: 0, width: w, height: h } });
    await page.close();
    b.file = png;
  }
  await browser.close();
}

async function pdfPages(buf) {
  const doc = await pdfjs.getDocument({ data: new Uint8Array(buf), useSystemFonts: true }).promise;
  const texts = [];
  for (let p = 1; p <= doc.numPages; p++) {
    const c = await (await doc.getPage(p)).getTextContent();
    texts.push(c.items.map((i) => i.str).join('').replace(/\s+/g, ''));
  }
  return texts;
}

/** 封面不要页眉页脚：Chrome 的页眉页脚模板没法按页关闭，这里在第一页上下各盖一条白色（封面背景是纯白，看不出来） */
async function coverClean(buf) {
  const doc = await PDFDocument.load(buf);
  const page = doc.getPage(0);
  const { width, height } = page.getSize();
  page.drawRectangle({ x: 0, y: height - 56, width, height: 56, color: rgb(1, 1, 1) });
  page.drawRectangle({ x: 0, y: 0, width, height: 56, color: rgb(1, 1, 1) });
  return Buffer.from(await doc.save());
}

async function buildPdf() {
  const browser = await launch();
  const tmp = path.join(OUT, '.arch-build.html');
  const render = async (tocPages) => {
    fs.writeFileSync(tmp, html(tocPages));
    const page = await browser.newPage();
    await page.goto(`file:///${tmp.replace(/\\/g, '/')}`, { waitUntil: 'load' });
    const buf = await page.pdf({
      preferCSSPageSize: true, printBackground: true, displayHeaderFooter: true, outline: true, tagged: true,
      headerTemplate: `<div style="width:100%;font-size:8px;color:#9CA3AF;padding:0 20mm;font-family:'${BODY_FONT}'"><span>${esc(TITLE)}</span><span style="float:right">v${esc(meta['文档版本'] || '')}</span></div>`,
      footerTemplate: `<div style="width:100%;font-size:8px;color:#9CA3AF;text-align:center;font-family:'${BODY_FONT}'">第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</div>`,
    });
    await page.close();
    return buf;
  };
  // 第一遍：不带页码，找出每个标题在哪一页；第二遍：把页码填进目录（目录行数不变，分页不受影响）
  const pass1 = await render(null);
  const texts = await pdfPages(pass1);
  const norm = (s) => s.replace(/\s+/g, '');
  const tocPages = {};
  const isTocPage = (t) => headings.filter((h) => t.includes(norm(h.text))).length >= 8;
  const firstBody = texts.findIndex((t, i) => i > 0 && !isTocPage(t) && !t.startsWith(norm('目录')));
  let from = Math.max(firstBody, 0);
  for (const h of headings) {
    const idx = texts.findIndex((t, i) => i >= from && t.includes(norm(h.text)) && !isTocPage(t));
    if (idx >= 0) { tocPages[h.id] = idx + 1; from = idx; }
  }
  const pdf = await coverClean(await render(tocPages));
  await browser.close();
  fs.rmSync(tmp, { force: true });
  const missing = headings.filter((h) => !tocPages[h.id]);
  if (missing.length) console.warn('目录里没找到页码的标题：', missing.map((h) => h.text).join('、'));
  return { pdf, pages: (await pdfPages(pdf)).length };
}

// ---------- Word ----------
const W = 9412; // 内容宽度（DXA）：A4 − 左右各 2.2cm
const runsDocx = (runs, base = {}) => runs.map((r) => new TextRun({
  text: r.t, bold: r.b || base.bold, font: r.c ? { ascii: CODE_FONT, eastAsia: BODY_FONT, hAnsi: CODE_FONT } : undefined,
  size: r.c ? 18 : base.size, shading: r.c ? { type: ShadingType.CLEAR, fill: 'F3F4F6', color: 'auto' } : undefined, color: base.color,
}));

const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: 'D1D5DB' };
const borders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };

function docxBlocks() {
  const out = [];
  // 封面
  const para = (text, o = {}) => new Paragraph({ spacing: { before: o.before ?? 0, after: o.after ?? 0 }, alignment: o.align, children: [new TextRun({ text, size: o.size, bold: o.bold, color: o.color, characterSpacing: o.spacing })] });
  out.push(para('', { before: 2600 }), para(meta['公司'] || '', { size: 32, color: MUTED, spacing: 60 }), para(meta['产品'] || '', { size: 68, bold: true, before: 120 }),
    para(meta['标题'] || '', { size: 52, color: ACCENT, before: 80 }), para(meta['副标题'] || '', { size: 22, color: MUTED, before: 280, after: 900 }));
  for (const k of ['文档版本', '发布日期', '适用阶段', '代码仓库', '密级']) {
    if (!meta[k]) continue;
    out.push(new Paragraph({ spacing: { after: 100 }, tabStops: [{ type: TabStopType.LEFT, position: 1800 }], children: [new TextRun({ text: k, color: MUTED, size: 21 }), new TextRun({ text: `\t${meta[k]}`, size: 21 })] }));
  }
  out.push(new Paragraph({ children: [new PageBreak()] }));
  // 目录（带内部链接，不含页码：Word 的导航窗格与标题样式同样可用）
  out.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: false, children: [new TextRun('目录')] }));
  for (const h of headings) {
    out.push(new Paragraph({
      spacing: { before: h.level === 1 ? 100 : 0, after: 20 }, indent: { left: h.level === 1 ? 0 : 360 },
      children: [new InternalHyperlink({ anchor: h.id, children: [new TextRun({ text: h.text, bold: h.level === 1, size: h.level === 1 ? 22 : 19, color: h.level === 1 ? INK : '374151' })] })],
    }));
  }
  out.push(new Paragraph({ children: [new PageBreak()] }));
  let firstH1 = true;
  for (const b of blocks) {
    switch (b.type) {
      case 'h': {
        const level = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][b.level - 1];
        const children = [new TextRun(b.text)];
        out.push(new Paragraph({
          heading: level, pageBreakBefore: b.level === 1 && !firstH1,
          children: b.id ? [new Bookmark({ id: b.id, children })] : children,
        }));
        if (b.level === 1) firstH1 = false;
        break;
      }
      case 'p': out.push(new Paragraph({ spacing: { after: 120, line: 340 }, alignment: AlignmentType.JUSTIFIED, children: runsDocx(b.runs) })); break;
      case 'callout': out.push(new Paragraph({
        spacing: { before: 100, after: 160, line: 320 }, indent: { left: 160, right: 80 },
        border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 8 } }, shading: { type: ShadingType.CLEAR, fill: 'EEF2FF', color: 'auto' },
        children: runsDocx(b.runs),
      })); break;
      case 'code': {
        if (b.caption) out.push(new Paragraph({ spacing: { before: 100, after: 30 }, keepNext: true, children: [new TextRun({ text: b.caption, size: 16, color: MUTED, font: { ascii: CODE_FONT, eastAsia: BODY_FONT, hAnsi: CODE_FONT } })] }));
        const lines = b.text.split('\n');
        lines.forEach((ln, k) => out.push(new Paragraph({
          spacing: { after: 0, line: 250 }, keepLines: true, shading: { type: ShadingType.CLEAR, fill: 'F8FAFC', color: 'auto' },
          border: { left: { style: BorderStyle.SINGLE, size: 6, color: 'CBD5E1', space: 6 } },
          indent: { left: 120 },
          children: [new TextRun({ text: ln.replace(/\t/g, '    ') || ' ', size: 16, font: { ascii: CODE_FONT, eastAsia: BODY_FONT, hAnsi: CODE_FONT } })],
          ...(k === lines.length - 1 ? { spacing: { after: 160, line: 250 } } : {}),
        })));
        break;
      }
      case 'image': {
        const data = fs.readFileSync(b.file);
        const dim = pngSize(data);
        const width = Math.min(560, dim.w);
        out.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 100 }, children: [new ImageRun({ type: 'png', data, transformation: { width, height: Math.round(width * dim.h / dim.w) }, altText: { title: b.caption, description: b.caption, name: b.caption } })] }));
        out.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 }, children: [new TextRun({ text: b.caption, size: 18, color: MUTED })] }));
        break;
      }
      case 'pagebreak': out.push(new Paragraph({ children: [new PageBreak()] })); break;
      case 'list':
        for (const it of b.items) {
          out.push(new Paragraph({ numbering: { reference: it.ordered ? 'num' : 'bullet', level: it.level }, spacing: { after: 60, line: 330 }, children: runsDocx(it.runs) }));
        }
        out.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
        break;
      case 'table': {
        const w = tableWeights(b);
        const cols = w.map((x) => Math.max(900, Math.round(x * W)));
        const total = cols.reduce((a, x) => a + x, 0);
        cols[cols.length - 1] += W - total;
        const cell = (runs, i, head) => new TableCell({
          width: { size: cols[i], type: WidthType.DXA }, borders, margins: { top: 50, bottom: 50, left: 90, right: 90 },
          shading: head ? { type: ShadingType.CLEAR, fill: 'EEF2FF', color: 'auto' } : undefined,
          children: [new Paragraph({ spacing: { line: 290 }, children: runsDocx(runs, { size: 18, bold: head, color: head ? '3730A3' : undefined }) })],
        });
        out.push(new Table({
          width: { size: W, type: WidthType.DXA }, columnWidths: cols,
          rows: [new TableRow({ tableHeader: true, cantSplit: true, children: b.head.map((c, i) => cell(c, i, true)) }), ...b.rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, i, false)) }))],
        }));
        out.push(new Paragraph({ spacing: { after: 140 }, children: [] }));
        break;
      }
      default: break;
    }
  }
  return out;
}

function pngSize(buf) { return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) }; }

async function buildDocx() {
  const style = (id, name, size, color, before, after, extra = {}) => ({ id, name, basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size, bold: true, color, font: BODY_FONT }, paragraph: { spacing: { before, after }, ...extra } });
  const doc = new Document({
    creator: meta['公司'] || '', title: TITLE, description: meta['副标题'] || '',
    styles: {
      default: { document: { run: { font: { ascii: BODY_FONT, eastAsia: BODY_FONT, hAnsi: BODY_FONT }, size: 21, color: INK } } },
      paragraphStyles: [
        style('Heading1', 'Heading 1', 40, '111827', 0, 240, { outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: ACCENT, space: 4 } }, keepNext: true }),
        style('Heading2', 'Heading 2', 28, '111827', 360, 140, { outlineLevel: 1, keepNext: true }),
        style('Heading3', 'Heading 3', 23, ACCENT, 240, 100, { outlineLevel: 2, keepNext: true }),
      ],
    },
    numbering: {
      config: [
        { reference: 'bullet', levels: [0, 1].map((l) => ({ level: l, format: LevelFormat.BULLET, text: l ? '–' : '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 420 + l * 360, hanging: 260 } } } })) },
        { reference: 'num', levels: [0, 1].map((l) => ({ level: l, format: LevelFormat.DECIMAL, text: `%${l + 1}.`, alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460 + l * 360, hanging: 320 } } } })) },
      ],
    },
    sections: [{
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1247, bottom: 1134, left: 1247, right: 1247, header: 600, footer: 500 } } },
      headers: { default: new Header({ children: [new Paragraph({ tabStops: [{ type: TabStopType.RIGHT, position: W }], children: [new TextRun({ text: TITLE, size: 16, color: '9CA3AF' }), new TextRun({ text: `\tv${meta['文档版本'] || ''}`, size: 16, color: '9CA3AF' })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['第 ', PageNumber.CURRENT, ' 页 / 共 ', PageNumber.TOTAL_PAGES, ' 页'], size: 16, color: '9CA3AF' })] })] }) },
      children: docxBlocks(),
    }],
  });
  return Packer.toBuffer(doc);
}

// ---------- 主流程 ----------
const only = process.argv[2]; // docx | pdf | 空=都做
await prepareImages();
if (!only || only === 'docx') {
  const buf = await buildDocx();
  fs.writeFileSync(path.join(OUT, `${FILE_BASE}.docx`), buf);
  console.log(`已生成 docs/${FILE_BASE}.docx（${(buf.length / 1024).toFixed(0)} KB）`);
}
if (!only || only === 'pdf') {
  const { pdf, pages } = await buildPdf();
  fs.writeFileSync(path.join(OUT, `${FILE_BASE}.pdf`), pdf);
  console.log(`已生成 docs/${FILE_BASE}.pdf（${pages} 页，${(pdf.length / 1024).toFixed(0)} KB）`);
}
fs.rmSync(path.join(OUT, '.arch-img'), { recursive: true, force: true });
console.log(`章节 ${headings.filter((h) => h.level === 1).length} 个，小节 ${headings.filter((h) => h.level === 2).length} 个，块 ${blocks.length} 个`);
