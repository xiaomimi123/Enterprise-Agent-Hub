// 一个够用的 Markdown 子集解析器：把 docs/架构文档/*.md 解析成块（标题、段落、列表、表格、代码、图片、提示框……），
// 供 build.mjs 渲染成 Word 和 PDF。代码片段不手抄：用 {{code 路径::函数名 | 说明}} 在构建时从仓库源码里取，保证和代码一致。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

/** 行内：**粗体**、`代码`，其余是普通文字。返回 [{t, b, c}] */
export function inline(text) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push({ t: text.slice(last, m.index) });
    const s = m[0];
    if (s.startsWith('**')) out.push({ t: s.slice(2, -2), b: true });
    else out.push({ t: s.slice(1, -1), c: true });
    last = m.index + s.length;
  }
  if (last < text.length) out.push({ t: text.slice(last) });
  return out.length ? out : [{ t: '' }];
}

const plain = (runs) => runs.map((r) => r.t).join('');

/** 取 Python 源码里一个顶层函数 / 类（含前面的装饰器），最多 max 行 */
export function pyBlock(file, name, max = 60) {
  const lines = fs.readFileSync(path.join(REPO, file), 'utf8').replace(/\r\n/g, '\n').split('\n');
  const re = new RegExp(`^(async\\s+def|def|class)\\s+${name}\\b`);
  let start = lines.findIndex((l) => re.test(l));
  if (start < 0) throw new Error(`代码片段找不到 ${file}::${name}`);
  while (start > 0 && /^@/.test(lines[start - 1])) start--;
  let end = start + 1;
  while (end < lines.length) {
    const l = lines[end];
    if (l.trim() && !/^\s/.test(l) && !/^@/.test(l) && !/^#/.test(l)) break; // 下一个顶层语句
    end++;
  }
  while (end > start && !lines[end - 1].trim()) end--;
  let body = lines.slice(start, end);
  if (body.length > max) body = [...body.slice(0, max), '    …（以下省略）'];
  return body.join('\n');
}

export function lineRange(file, a, b) {
  const lines = fs.readFileSync(path.join(REPO, file), 'utf8').replace(/\r\n/g, '\n').split('\n');
  return lines.slice(a - 1, b).join('\n');
}

function codeDirective(spec) {
  const [ref, caption = ''] = spec.split('|').map((s) => s.trim());
  let max = 60;
  let r = ref.replace(/\s+max=(\d+)/, (_, n) => { max = Number(n); return ''; }).trim();
  if (r.includes('::')) {
    const [file, name] = r.split('::');
    return { type: 'code', caption: caption || file, text: pyBlock(file, name, max) };
  }
  const m = r.match(/^(.+)#(\d+)-(\d+)$/);
  if (m) return { type: 'code', caption: caption || m[1], text: lineRange(m[1], Number(m[2]), Number(m[3])) };
  throw new Error(`看不懂的代码指令：${spec}`);
}

/** 解析一个 Markdown 文件为块列表 */
export function parse(src, baseDir) {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  const isTable = (l) => /^\s*\|/.test(l);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) { blocks.push({ type: 'h', level: m[1].length, text: m[2].trim() }); i++; continue; }
    if ((m = line.match(/^\{\{pagebreak\}\}$/))) { blocks.push({ type: 'pagebreak' }); i++; continue; }
    if ((m = line.match(/^\{\{code\s+(.+)\}\}$/))) { blocks.push(codeDirective(m[1])); i++; continue; }
    if ((m = line.match(/^```(\S*)\s*(.*)$/))) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      blocks.push({ type: 'code', caption: m[2].trim(), text: buf.join('\n') });
      continue;
    }
    if ((m = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/))) { blocks.push({ type: 'image', caption: m[1], file: path.resolve(baseDir, m[2]) }); i++; continue; }
    if (isTable(line)) {
      const rows = [];
      while (i < lines.length && isTable(lines[i])) { rows.push(lines[i]); i++; }
      const cells = (l) => l.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|').replace(/<br>/g, '\n'));
      const head = cells(rows[0]);
      const body = rows.slice(2).map(cells);
      blocks.push({ type: 'table', head: head.map(inline), rows: body.map((r) => head.map((_, k) => inline(r[k] ?? ''))) });
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
      blocks.push({ type: 'callout', runs: inline(buf.join(' ').trim()) });
      continue;
    }
    if (/^\s*(-|\d+\.)\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*(-|\d+\.)\s+/.test(lines[i])) {
        const mm = lines[i].match(/^(\s*)(-|\d+\.)\s+(.*)$/);
        items.push({ level: mm[1].length >= 2 ? 1 : 0, ordered: /\d/.test(mm[2]), runs: inline(mm[3]) });
        i++;
      }
      blocks.push({ type: 'list', items });
      continue;
    }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|```|\{\{|!\[|\||>|\s*(-|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
    blocks.push({ type: 'p', runs: inline(buf.join('')) });
  }
  return blocks;
}

export { plain };
