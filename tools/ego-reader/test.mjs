// ego-reader 测试：先测参数校验和保护（不需要浏览器），加 --live 再用真实 ego lite 读（需要用户已在 ego lite 里登录小红书；会读 2 篇，间隔 20 秒）。
//   node tools/ego-reader/test.mjs [--live]
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const server = path.join(path.dirname(fileURLToPath(import.meta.url)), 'server.mjs');
const live = process.argv.includes('--live');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ego-reader-test-'));
const env = { ...process.env, EGO_READER_STATE: path.join(tmp, 'state.json'), EGO_READER_STOP_FILE: path.join(tmp, 'STOP'), EGO_READER_MAX_PER_HOUR: '3' };
if (!live) env.EGO_BROWSER_BIN = 'definitely-not-installed-ego';   // 校验类测试不应该走到浏览器
const child = spawn('node', [server], { env, stdio: ['pipe', 'pipe', 'inherit'] });
let buf = ''; const waiters = new Map(); let nextId = 1;
child.stdout.on('data', (d) => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { const l = buf.slice(0, i); buf = buf.slice(i + 1); try { const m = JSON.parse(l); waiters.get(m.id)?.(m); } catch {} } });
const rpc = (method, params) => new Promise((res) => { const id = nextId++; waiters.set(id, res); child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); });
const call = async (name, args) => JSON.parse((await rpc('tools/call', { name, arguments: args })).result.content[0].text);
let bad = 0; const check = (label, cond, extra = '') => { if (!cond) bad++; console.log(cond ? 'PASS' : 'FAIL', label, cond ? '' : extra); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const init = await rpc('initialize', { protocolVersion: '2024-11-05' });
check('initialize 返回 serverInfo', init.result.serverInfo.name === 'ego-reader');
const tools = (await rpc('tools/list', {})).result.tools;
check('只有四个只读工具', tools.map((t) => t.name).sort().join() === 'xhs_check_login,xhs_read_feed,xhs_read_me,xhs_read_note');
check('工具参数只有 scrolls / id / scroll_note（没有脚本、命令、选择器、网址、文字输入）', JSON.stringify(tools.flatMap((t) => Object.keys(t.inputSchema.properties)).sort()) === JSON.stringify(['id', 'scroll_note', 'scrolls']), JSON.stringify(tools.map((t) => Object.keys(t.inputSchema.properties))));

// 参数校验：注入、越界、类型错误都应在启动浏览器之前被拒绝
for (const [label, args] of [['id 带引号注入', { id: 'x"]; process.exit(1); //' }], ['id 太短', { id: 'abc' }], ['id 大写', { id: 'ABCDEF0123456789ABCDEF01' }], ['id 是数字', { id: 123 }], ['缺少 id', {}]]) {
  const r = await call('xhs_read_note', args); check('xhs_read_note 拒绝：' + label, r.ok === false && r.error === 'bad_argument', JSON.stringify(r));
}
for (const [label, args] of [['scroll_note=9', { id: 'a'.repeat(24), scroll_note: 9 }], ['scroll_note=1.5', { id: 'a'.repeat(24), scroll_note: 1.5 }]]) {
  const r = await call('xhs_read_note', args); check('xhs_read_note 拒绝：' + label, r.error === 'bad_argument', JSON.stringify(r));
}
for (const [label, args] of [['scrolls=4', { scrolls: 4 }], ['scrolls=-1', { scrolls: -1 }], ['scrolls="2"', { scrolls: '2' }]]) {
  const r = await call('xhs_read_feed', args); check('xhs_read_feed 拒绝：' + label, r.error === 'bad_argument', JSON.stringify(r));
}
check('xhs_read_me 不接受参数', (await call('xhs_read_me', { id: 'x' })).error === 'bad_argument');
check('xhs_check_login 不接受参数', (await call('xhs_check_login', { x: 1 })).error === 'bad_argument');
// 回归：脚本是写在模板字符串里的，正则里的单个反斜杠（\s、\d）会被吃成字母，必须写成两个。2026-10-28 就因此把「小红书号」的兜底正则写成了 [^s]+
{
  const src = fs.readFileSync(server, 'utf8');
  const region = src.slice(src.indexOf('const COMMON = `'), src.indexOf('// ---------------- 运行 ego-browser'));
  const BS = String.fromCharCode(92);                       // 反斜杠；不在正则里直接写，避免再被转义吃掉
  const bad = [];
  for (let i = 0; i < region.length; i++) {
    if (region[i] !== BS) continue;
    if (region[i + 1] === BS) { i++; continue; }              // 两个反斜杠：正确写法
    if ('sdwSDW./?+*()[]^$|-'.includes(region[i + 1] || '')) bad.push(region.slice(Math.max(0, i - 15), i + 10).split(String.fromCharCode(10)).join(' '));
  }
  check('模板字符串里的正则没有会被吃掉的单反斜杠', bad.length === 0, JSON.stringify(bad));
}
check('未知工具被拒绝', (await call('xhs_like', {})).error === 'unknown_tool');

if (!live) {
  // 保护：找不到浏览器时，第一次读笔记会走到“找不到 ego-browser”（并记一次），第二次立刻被间隔保护拦住
  const id = 'a'.repeat(24);
  const r1 = await call('xhs_read_note', { id }); check('第 1 次：走到浏览器层（这里被替换成不存在的程序）', r1.error === 'ego_browser_not_found', JSON.stringify(r1));
  const r2 = await call('xhs_read_note', { id }); check('第 2 次立刻读：被间隔保护拦住', r2.error === 'too_soon' && r2.retry_after_ms > 0, JSON.stringify(r2));
  fs.writeFileSync(env.EGO_READER_STOP_FILE, 'x');
  const r3 = await call('xhs_read_feed', {}); check('停止文件存在：连读信息流也拒绝', r3.error === 'stopped', JSON.stringify(r3));
  const r4 = await call('xhs_read_note', { id }); check('停止文件存在：读笔记拒绝', r4.error === 'stopped', JSON.stringify(r4));
  fs.rmSync(env.EGO_READER_STOP_FILE);
  // 每小时上限：把状态改成 3 篇都在 30 分钟前（间隔已满足，但已达上限）
  fs.writeFileSync(env.EGO_READER_STATE, JSON.stringify({ notes: [Date.now() - 1800_000, Date.now() - 1790_000, Date.now() - 1780_000] }));
  const r5 = await call('xhs_read_note', { id }); check('每小时上限：达到后拒绝', r5.error === 'hourly_limit', JSON.stringify(r5));
} else {
  const login = await call('xhs_check_login', {});
  check('live：xhs_check_login 返回布尔的 loggedIn / guest', login.ok && typeof login.loggedIn === 'boolean', JSON.stringify(login));
  console.log('  登录状态 loggedIn =', login.loggedIn, ' guest =', login.guest, login.loggedIn ? '' : '（游客：下面读到的是公开内容，不是登录后的内容）');
  const feed = await call('xhs_read_feed', { scrolls: 1 });
  check('live：信息流结果带登录状态', typeof feed.loggedIn === 'boolean', JSON.stringify(feed).slice(0, 200));
  check('live：读到信息流（已登录且有卡片）', feed.ok && feed.cards.length >= 1, JSON.stringify(feed).slice(0, 300));
  console.log('  滚动位置', feed.scrollY, '卡片数', feed.cards?.length, '前 3 个标题：', (feed.cards || []).slice(0, 3).map((c) => c.title).join(' | '));
  const first = feed.cards?.[0];
  const n1 = await call('xhs_read_note', { id: first.id, scroll_note: 1 });
  check('live：读到笔记 1（标题 + 正文）', n1.ok && n1.title && n1.text !== undefined, JSON.stringify(n1).slice(0, 300));
  console.log('  笔记 1', JSON.stringify({ title: n1.title, textLen: (n1.text || '').length, tags: (n1.tags || []).length, author: n1.author, date: n1.date, images: n1.images, hasVideo: n1.hasVideo, likes: n1.likes, collects: n1.collects, comments: n1.comments, scrollTop: n1.scrollTop }));
  const tooSoon = await call('xhs_read_note', { id: feed.cards[1].id });
  check('live：紧接着再读被间隔保护拦住', tooSoon.error === 'too_soon', JSON.stringify(tooSoon));
  await sleep(Number(tooSoon.retry_after_ms || 20000) + 500);
  const n2 = await call('xhs_read_note', { id: feed.cards[1].id });
  check('live：间隔后读到笔记 2', n2.ok && n2.title !== undefined, JSON.stringify(n2).slice(0, 300));
  console.log('  笔记 2', JSON.stringify({ title: n2.title, textLen: (n2.text || '').length, author: n2.author, likes: n2.likes }));
  const gone = await call('xhs_read_note', { id: 'f'.repeat(24) });
  check('live：不在可见卡片里的 id 被拒绝（间隔保护或 card_not_visible）', gone.ok === false, JSON.stringify(gone));
}
child.stdin.end(); child.kill();
console.log(bad ? `失败 ${bad} 项` : '全部通过');
process.exit(bad ? 1 : 0);
