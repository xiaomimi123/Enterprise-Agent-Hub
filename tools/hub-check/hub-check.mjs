#!/usr/bin/env node
/**
 * 新设备上线自检（小红书运营工作台 + 企业中枢接入器）
 *
 * 用法（新机器装完后）：双击 hub-check.cmd，或
 *   "%USERPROFILE%\HubApps\runtime\node\node.exe" hub-check.mjs
 * 参数：
 *   --json     只输出 JSON（给批处理/汇总用）
 *   --quiet    只打印 FAIL/WARN
 *
 * 退出码：0 = 没有 FAIL；1 = 有 FAIL（必须处理后再交付给运营）
 * 本脚本只读，不改任何文件（唯一写操作是数据目录可写性探测，用完即删）。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { execFileSync } from 'node:child_process';

const HOME = process.env.USERPROFILE || os.homedir();
const QUIET = process.argv.includes('--quiet');
const JSON_OUT = process.argv.includes('--json');
const rows = [];
const add = (level, area, name, detail, fix) => rows.push({ level, area, name, detail: detail || '', fix: fix || '' });
const pass = (a, n, d) => add('PASS', a, n, d);
const warn = (a, n, d, f) => add('WARN', a, n, d, f);
const fail = (a, n, d, f) => add('FAIL', a, n, d, f);

const J = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; } };
const exists = (p) => { try { return fs.statSync(p).isFile(); } catch { return false; } };
const dirExists = (p) => { try { return fs.statSync(p).isDirectory(); } catch { return false; } };
const run = (file, args) => {
  try { return execFileSync(file, args, { encoding: 'utf8', timeout: 20000, windowsHide: true }).trim(); }
  catch { return ''; }
};
const num = (v) => { const m = String(v).match(/(\d+)\.(\d+)/); return m ? Number(m[1]) : NaN; };

// ---------- 1. 系统与路径 ----------
add(os.platform() === 'win32' ? 'PASS' : 'WARN', '系统', 'Windows', `${os.platform()} ${os.release()} ${os.arch()}`, os.platform() === 'win32' ? '' : '这个自检是为 Windows 员工机写的');
if (/[\u4e00-\u9fa5\s]/.test(HOME)) {
  warn('系统', '用户目录含中文或空格', HOME, '已知坑：批处理里带中文路径容易解析出错。接入器生成启动器时会把用户目录换成 %USERPROFILE%，一般没问题；若双击图标闪退，先看这条');
} else {
  pass('系统', '用户目录为纯 ASCII', HOME);
}
try {
  const st = fs.statfsSync(path.parse(HOME).root);
  const gb = (st.bavail * st.bsize) / 1024 ** 3;
  (gb >= 5 ? pass : warn)('系统', `系统盘剩余 ${gb.toFixed(1)} GB`, '', gb >= 5 ? '' : '低于 5 GB 建议先清理：出图/视频/备份都写在同一块盘');
} catch { warn('系统', '磁盘剩余空间', '读不到'); }
const mem = os.totalmem() / 1024 ** 3;
(mem >= 8 ? pass : warn)('系统', `内存 ${mem.toFixed(1)} GB`, '', mem >= 8 ? '' : '8 GB 以下同时开浏览器 + agent 会卡');

// ---------- 2. 运行时 ----------
const NODE = path.join(HOME, 'HubApps', 'runtime', 'node', 'node.exe');
if (exists(NODE)) {
  const v = run(NODE, ['-v']);
  const major = num(v.replace('v', ''));
  (major >= 22 ? pass : fail)('运行时', `Node ${v}`, NODE, major >= 22 ? '' : '需要 Node 22+：重跑中枢 setup，或让 IT 重装运行时');
} else fail('运行时', 'Node 运行时缺失', NODE, '接入器没装全：重跑  uv run hub_agent.py setup');

const UV = path.join(HOME, 'HubApps', 'runtime', 'uv', 'uv.exe');
if (exists(UV)) pass('运行时', `uv ${run(UV, ['--version'])}`, UV);
else fail('运行时', 'uv 缺失', UV, '重跑中枢安装包；uv 负责跑接入器');

const CB = path.join(HOME, 'HubApps', 'runtime', 'node', 'codebuddy.cmd');
if (exists(CB)) {
  const cv = run(CB, ['--version']) || run(path.join(HOME, 'HubApps', 'runtime', 'node', 'codebuddy-code.cmd'), ['--version']);
  pass('运行时', 'CodeBuddy CLI', `${cv || '已安装'} · ${CB}`);
}
else warn('运行时', 'CodeBuddy CLI 缺失', CB, '工作台里的对话和 agent 任务会不可用。装：npm install -g @tencent-ai/codebuddy-code，或重跑 setup');

// ---------- 3. 接入器 ----------
const AGENT = path.join(HOME, '.hub-agent', 'hub_agent.py');
let agentVer = '';
if (exists(AGENT)) {
  const head = fs.readFileSync(AGENT, 'utf8').split('\n').filter((l) => /^VERSION\s*=/.test(l))[0] || '';
  agentVer = (head.match(/"([^"]+)"/) || [])[1] || '?';
  pass('接入器', `hub_agent.py ${agentVer}`, AGENT);
} else fail('接入器', 'hub_agent.py 缺失', AGENT, '重装接入器（中枢下发的安装包），然后 setup');

const CREDS = path.join(HOME, '.hub-agent', 'credentials.json');
const creds = J(CREDS);
// 接入器版本和中枢上挂的比（0.5.8 起接入器会自己更新；更老的版本要重跑一次安装命令）
if (creds?.hub && agentVer) {
  try {
    const cfg = await (await fetch(`${creds.hub}/api/agent/config`, { signal: AbortSignal.timeout(5000) })).json();
    const vt = (v) => String(v || '').split('.').map((n) => Number(n) || 0);
    const a = vt(agentVer), b = vt(cfg.agent_version);
    const older = !!cfg.agent_version && (a[0] < b[0] || (a[0] === b[0] && (a[1] < b[1] || (a[1] === b[1] && a[2] < b[2]))));
    if (cfg.agent_version) (older ? warn : pass)('接入器', older ? `接入器比中枢上的旧（本机 ${agentVer}，中枢 ${cfg.agent_version}）` : `接入器是最新（${agentVer}）`, '',
      older ? '旧版本带着已修的缺陷（0.5.6 会出现「400 Missing session ID」）。按中枢「接入方式」页的命令重跑一次（Win+R 粘贴那一行）；0.5.8 起接入器会自己更新' : '');
  } catch { /* 中枢连不上由后面的网络检查报告 */ }
}
if (creds && (creds.refresh_token || creds.token)) pass('接入器', '已登录中枢', creds.hub || '（未记录 hub 地址）');
else fail('接入器', '没有登录凭证', CREDS, '运行 uv run hub_agent.py setup（会弹浏览器登录）');

const PROF = path.join(HOME, '.hub-agent', 'profile.json');
const prof = J(PROF);
if (prof) {
  const apps = (prof.apps || []).map((a) => a.id);
  const skills = (prof.skills || []).length;
  (apps.includes('xhs-workbench') ? pass : fail)('接入器', '岗位包里有工作台', `apps=[${apps.join(',')}] · ${skills} 个技能`, apps.includes('xhs-workbench') ? '' : '这个账号没被授权工作台，或同步没完成：uv run hub_agent.py sync');
} else fail('接入器', 'profile.json 缺失', PROF, 'uv run hub_agent.py sync');

// 中枢可达性
if (prof?.mcp_url) {
  try {
    const u = new URL(prof.mcp_url);
    const base = `${u.protocol}//${u.host}`;
    const t0 = Date.now();
    const r = await fetch(base, { method: 'GET' }).catch((e) => ({ status: 0, _e: e }));
    const ms = Date.now() - t0;
    (r.status > 0 ? pass : fail)('网络', `中枢可达 ${base}`, `HTTP ${r.status || r._e?.message || '连不上'} · ${ms}ms` + (r.status === 404 ? '（根路径没有页面，能连上就行）' : ''), r.status > 0 ? '' : '检查是否在公司网络 / 有没有开代理；中枢地址写在 profile.json 的 mcp_url');
  } catch (e) { fail('网络', '中枢地址不合法', prof.mcp_url, String(e.message)); }
  if (prof.model?.base_url) {
    try {
      const u2 = new URL(prof.model.base_url);
      const r2 = await fetch(`${u2.protocol}//${u2.host}`, { method: 'GET' }).catch(() => ({ status: 0 }));
      (r2.status > 0 ? pass : warn)('网络', `模型服务可达 ${u2.host}`, `HTTP ${r2.status}`, r2.status > 0 ? '' : 'agent 会退化成不可用；确认模型网关端口开着');
    } catch { /* 忽略 */ }
  }
}

// 能力预检
const CAP = path.join(HOME, '.hub-agent', 'capabilities', 'xhs-workbench.json');
const cap = J(CAP);
if (cap) {
  const bad = (cap.checks || []).filter((c) => !c.ok && !c.warn);
  const warns = (cap.checks || []).filter((c) => c.warn);
  (bad.length === 0 ? pass : fail)('接入器', '能力预检（agent_cli / 浏览器）', bad.length ? bad.map((c) => `${c.label}：${c.detail}`).join('；') : `全通过 · ${cap.version} · ${cap.checkedAt}`, bad.length ? '让 agent 跑 hub_agent.py app-doctor，或按 detail 里的说明装依赖' : '');
  if (warns.length) warn('接入器', '能力预检有警告', warns.map((c) => `${c.label}：${c.detail}`).join('；'));
} else warn('接入器', '还没有能力预检文件', CAP, '正常情况双击桌面图标打开工作台时由中枢生成；如果没有，检查启动是不是绕过了中枢');

if (exists(path.join(HOME, '.hub-agent', 'hub-mcp.json'))) pass('接入器', '中枢 MCP 配置', 'hub-mcp.json');
else warn('接入器', '中枢 MCP 配置缺失', '.hub-agent/hub-mcp.json', 'agent 会读不到公司知识库/出图；重跑 setup');

// ---------- 4. 启动器与桌面图标 ----------
const BIN = path.join(HOME, 'HubApps', 'bin');
const LAUNCH = path.join(BIN, 'open-xhs-workbench.cmd');
if (exists(LAUNCH)) {
  const txt = fs.readFileSync(LAUNCH, 'utf8');
  const portable = txt.includes('%USERPROFILE%');
  (portable ? pass : warn)('启动器', '启动器存在', portable ? '路径用 %USERPROFILE%（可移植）' : '路径写死成绝对路径，换机器/改用户名会失效',
    portable ? '' : '删掉这个文件，重跑 hub_agent.py setup 让它重新生成');
} else fail('启动器', '启动器缺失', LAUNCH, '重跑 hub_agent.py setup（会生成启动器和桌面图标）');

const desktopDirs = [path.join(HOME, 'Desktop'), path.join(process.env.PUBLIC || 'C:\\Users\\Public', 'Desktop')];
const lnks = desktopDirs.flatMap((d) => { try { return fs.readdirSync(d).filter((f) => f.endsWith('.lnk')); } catch { return []; } });
const xhsLnk = lnks.find((f) => f.includes('小红书'));
(xhsLnk ? pass : warn)('启动器', '桌面图标', xhsLnk || '没找到', xhsLnk ? '' : '让运营双击 HubApps\\bin\\open-xhs-workbench.cmd 也能用；或重跑 setup 生成图标');

// ---------- 5. 工作台本体 ----------
const APPS = path.join(HOME, 'HubApps', 'apps', 'xhs-workbench');
let versions = [];
const vkey = (v) => v.split('.').map((n) => Number(n) || 0);
try {
  versions = fs.readdirSync(APPS)
    .filter((v) => /^\d+\.\d+\.\d+$/.test(v) && dirExists(path.join(APPS, v)))
    .sort((a, b) => { const A = vkey(a), B = vkey(b); for (let i = 0; i < 3; i++) if (A[i] !== B[i]) return A[i] - B[i]; return 0; });
} catch { /* 无 */ }
if (!versions.length) {
  fail('工作台', '应用包没装', APPS, '双击桌面图标一次（会从中枢拉最新版本）；仍失败就看网络/权限');
} else {
  const latest = versions[versions.length - 1];
  const root = path.join(APPS, latest, 'xhs-workbench');
  const hasServer = exists(path.join(root, 'server', 'server.mjs'));
  const hasWeb = exists(path.join(root, 'web', 'app.js'));
  (hasServer && hasWeb ? pass : fail)('工作台', `应用包 ${latest}`, `共 ${versions.length} 个版本：${versions.join(' / ')}`, hasServer && hasWeb ? '' : '包不完整（缺 server/web），删掉这个版本目录让它重下');
  const pkgJson = J(path.join(root, 'package.json'));
  if (pkgJson?.version) pass('工作台', `包内版本号 ${pkgJson.version}`, '');
}

// ---------- 6. 数据目录 ----------
const DATA = process.env.XHS_WORKSPACE || path.join(HOME, 'XHS-Workbench');  // 支持自定义工作目录
if (dirExists(DATA)) {
  let writable = false;
  try { const f = path.join(DATA, `.write-test-${process.pid}`); fs.writeFileSync(f, 'ok'); fs.unlinkSync(f); writable = true; } catch { /* 只读 */ }
  const accFile = J(path.join(DATA, 'config', 'accounts.json'));
  const acc = accFile?.accounts?.[0];
  (writable ? pass : fail)('数据', '数据目录可写', DATA, writable ? '' : '权限问题：这个目录要对当前用户可写，否则笔记、素材、日志都存不下来');
  if (acc) {
    (acc.xhsId ? pass : warn)('数据', '账号已配置', `${acc.name} · 小红书号 ${acc.xhsId || '（空）'}`, acc.xhsId ? '' : '还没填小红书号。到「账号管理」填上本人账号的小红书号，否则采集/核对都会拦');
  } else warn('数据', '还没有账号配置', '首次打开工作台会自动建');
  const vf = J(path.join(DATA, 'config', 'version.json'));
  if (vf) pass('数据', `数据版本 ${vf.dataVersion} · 应用 ${vf.appVersion}`, (vf.history || []).length ? `升级记录 ${vf.history.length} 条` : '首次使用');
} else warn('数据', '数据目录还不存在', DATA, '第一次打开工作台时会创建，属于正常');

// ---------- 7. 端口与服务 ----------
const tryPort = (p) => new Promise((resolve) => {
  const s = net.createServer();
  s.once('error', (e) => resolve(e.code === 'EADDRINUSE' ? 'inuse' : 'err'));
  s.once('listening', () => s.close(() => resolve('free')));
  s.listen(p, '127.0.0.1');
});
let livePort = 0, liveVer = '';
for (let p = 17890; p <= 17910; p++) {
  if (await tryPort(p) === 'inuse') {
    try {
      const r = await fetch(`http://127.0.0.1:${p}/api/health`, { signal: AbortSignal.timeout(3000) });
      const d = await r.json();
      if (d?.name === 'xhs-workbench') { livePort = p; liveVer = d.version; break; }
    } catch { /* 不是工作台 */ }
  }
}
if (livePort) {
  pass('服务', `工作台在跑 · ${livePort} 端口 · ${liveVer}`, '');
  if (versions.length && liveVer && !versions.includes(liveVer)) {
    fail('服务', '运行版本与磁盘最新版本不一致', `在跑 ${liveVer}，磁盘最新 ${versions[versions.length - 1]}`, '关掉工作台再双击桌面图标，会换到最新版本');
  }
  const tokFile = path.join(DATA, 'run', 'token');
  if (exists(tokFile)) {
    const tok = fs.readFileSync(tokFile, 'utf8').trim();
    try {
      const r = await fetch(`http://127.0.0.1:${livePort}/api/browse/pace?account=default`, { headers: { 'x-workbench-token': tok } });
      const s = await r.json();
      if (!s || !s.limits) {
        warn('采集', '读不到采集状态', '这个端口上的实例用的可能不是当前数据目录（自检里设了 XHS_WORKSPACE）');
      } else {
        const state = s.enabled === false ? '总开关关闭（新机器默认）' : (s.status === 'go' ? '可以采集' : s.reason);
        add(s.enabled === false ? 'PASS' : 'WARN', '采集', `采集状态：${state}`,
          `上限 笔记 ${s.limits.notesPerDay}/天 · 主页 ${s.limits.profilesPerDay}/天 · 间隔 ${s.limits.gapMin} 分钟 · 时段 ${s.limits.windowStart}–${s.limits.windowEnd}` + (s.cooldown?.active ? `；冷静期至 ${String(s.cooldown.until).slice(0, 10)}` : ''),
          s.enabled === false ? '' : '交付前建议保持关闭：由运营本人确认后再打开');
      }
    } catch (e) { warn('采集', '读不到采集状态', String(e.message)); }
  }
  const bridge = J(path.join(DATA, 'config', 'bridge.json'));
  if (bridge) {
    const ok = bridge.mode === 'cli';
    (ok ? pass : warn)('服务', '对话通道', `mode=${bridge.mode} · adapter=${bridge.adapter?.id || '-'}`, ok ? '' : '「连接与设置」里应选 CodeBuddy Code（CLI 模式）');
    // 浏览器方式：必须是 WorkBuddy 插件，否则采集会被服务端直接拒（collectionRoute 只认 mode=cli && browser=workbuddy）
    const bw = bridge.browser || 'none';
    (bw === 'workbuddy' ? pass : fail)('采集能力', '浏览器方式', bw === 'workbuddy' ? 'WorkBuddy 浏览器插件' : `当前是 ${bw === 'none' ? '未选择（none）' : bw}`,
      bw === 'workbuddy' ? '' : '新机器默认是 none，采集走不了。到「连接与设置 → 执行 Agent 与浏览器」点「WorkBuddy 浏览器插件」后面的「用这个」。按钮是灰的就说明 WorkBuddy 没开浏览器操控');
    const mcpExe = bridge.adapter?.workbuddyMcp;
    if (bw === 'workbuddy') {
      (mcpExe && exists(mcpExe) ? pass : fail)('采集能力', 'WorkBuddy 浏览器桥程序', mcpExe || 'bridge.json 里没有 workbuddyMcp',
        mcpExe && exists(mcpExe) ? '' : '插件装了但桥程序没到位：在 WorkBuddy「设置 → 智能体 → 浏览器操控」打开「让 WorkBuddy 控制浏览器」，重新选一次浏览器方式');
      const bm = bridge.adapter?.browserMode;
      (bm === 'readonly' ? pass : warn)('采集能力', '权限档', `browserMode=${bm || '未设置'}`, bm === 'readonly' ? '' : '交付前建议切回「只读档」：只能看页面，不会点赞/评论/发布');
    }
  }
} else {
  warn('服务', '工作台没有在运行', '17890–17910 都没有响应', '这不是故障：双击桌面图标打开即可。自检建议在「刚打开工作台」和「关掉之后」各跑一次');
}

const edgePaths = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];
const edge = edgePaths.find(exists);
// ---------- 7.5 决定「采集能不能用」的四要素（中枢的浏览器能力就按这四项判） ----------
const CB_DIR = path.join(HOME, '.codebuddy');
const hubModel = prof?.model?.model || '';
const modelsDoc = J(path.join(CB_DIR, 'models.json'));
const cbSettings = J(path.join(CB_DIR, 'settings.json'));

const cliOnPath = (() => {
  try { return execFileSync('where', ['codebuddy'], { encoding: 'utf8', timeout: 8000 }).split('\n')[0].trim(); } catch { return ''; }
})();
(cliOnPath ? pass : fail)('采集能力', '① CodeBuddy CLI 在 PATH 里',
  cliOnPath || 'where codebuddy 找不到',
  cliOnPath ? '' : 'npm install -g @tencent-ai/codebuddy-code；装完新开一个终端再跑本检查');

const ours = (modelsDoc?.models || []).filter((m) => String(m.name || '').startsWith('公司中枢 · '));
const hasHubModel = hubModel && ours.some((m) => m.id === hubModel);
(hasHubModel ? pass : fail)('采集能力', '② 中枢模型已写进 CodeBuddy',
  hasHubModel ? `models.json 有「公司中枢 · ${hubModel}」` : (hubModel ? `models.json 里没有中枢模型 ${hubModel}（现有：${ours.map((m) => m.id).join(',') || '无'}）` : '岗位包里没取到模型配置'),
  hasHubModel ? '' : 'uv run hub_agent.py sync 重新写配置');

const defModel = cbSettings?.model;
if (hasHubModel) {
  (defModel === hubModel ? pass : warn)('采集能力', '③ 默认模型指向中枢', `settings.json model=${defModel || '(未设置)'}`,
    defModel === hubModel ? '' : `当前默认是 ${defModel}，浏览器任务可能不走中枢计量；在 CodeBuddy 里把默认模型切成「公司中枢 · ${hubModel}」`);
}

const npxPath = path.join(HOME, 'HubApps', 'runtime', 'node', 'npx.cmd');
(exists(npxPath) ? pass : fail)('采集能力', '④ npx 可用', npxPath, exists(npxPath) ? '' : '随 Node 一起装；缺了中枢会把浏览器能力判成不可用，采集直接被拦');

const sysBrowser = edge || (() => {
  const c = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  return exists(c) ? c : '';
})();
(sysBrowser ? pass : fail)('采集能力', '⑤ 系统浏览器（Edge/Chrome）', sysBrowser || '没找到', sysBrowser ? '' : '中枢把浏览器能力判成不可用；装 Edge 或 Chrome');

// ---------- 8. 浏览器与插件 ----------
(edge ? pass : warn)('浏览器', 'Edge', edge || '没找到', edge ? '' : '纯插件模式要求员工自己机器上有浏览器并登录小红书；没有 Edge 就装 Edge 或在设置里改用其它浏览器');

const EXT_ID = 'ndbfelmlimfjklodckmbalfioaehegpc';
let extHit = '';
for (const base of [
  path.join(HOME, 'AppData', 'Local', 'Microsoft', 'Edge', 'User Data'),
  path.join(HOME, 'AppData', 'Local', 'Google', 'Chrome', 'User Data'),
]) {
  if (!dirExists(base)) continue;
  for (const prof of fs.readdirSync(base)) {
    const d = path.join(base, prof, 'Extensions', EXT_ID);
    if (!dirExists(d)) continue;
    const vs = fs.readdirSync(d).filter((v) => dirExists(path.join(d, v)));
    if (vs.length) extHit = `${base.includes('Edge') ? 'Edge' : 'Chrome'} · 配置 ${prof} · 扩展版本 ${vs.sort().pop()}`;
  }
}
(extHit ? pass : fail)('浏览器', `WorkBuddy 浏览器插件（${EXT_ID}）`, extHit || '没装', extHit ? '' : '没有插件就无法用浏览器插件模式采数据。让员工在 WorkBuddy 里按提示安装/启用浏览器扩展，再重跑本检查');
const NPX = path.join(HOME, 'HubApps', 'runtime', 'node', 'npx.cmd');
if (exists(NPX)) pass('浏览器', 'npx（Playwright 兜底）', NPX);
else warn('浏览器', 'npx 缺失', NPX, '只在极端情况下才需要；不影响纯插件模式');

// ---------- 9. 可选依赖 ----------
const ff = ['ffprobe', 'ffmpeg'].map((b) => {
  try { return `${b}: ${execFileSync(b, ['-version'], { encoding: 'utf8', timeout: 8000 }).split('\n')[0].slice(0, 40)}`; }
  catch { return `${b}: 不在 PATH`; }
});
const ffOk = ff.every((x) => !x.includes('不在 PATH'));
(ffOk ? pass : warn)('媒体', 'ffmpeg / ffprobe', ff.join(' · '), ffOk ? '' : '不影响使用：视频会退化成「只做了基础校验」。要精确校验就把 ffmpeg 加进 PATH');

// ---------- 汇总 ----------
const fails = rows.filter((r) => r.level === 'FAIL');
const warns = rows.filter((r) => r.level === 'WARN');
if (JSON_OUT) {
  console.log(JSON.stringify({ home: HOME, agentVersion: agentVer, versions, livePort, liveVer, rows, summary: { pass: rows.length - fails.length - warns.length, warn: warns.length, fail: fails.length } }, null, 2));
} else {
  const color = process.stdout.isTTY;
  const mark = { PASS: color ? '\x1b[32mPASS\x1b[0m' : 'PASS', WARN: color ? '\x1b[33mWARN\x1b[0m' : 'WARN', FAIL: color ? '\x1b[31mFAIL\x1b[0m' : 'FAIL' };
  console.log('');
  console.log(`新设备上线自检 · ${HOME}`);
  console.log('─'.repeat(78));
  let area = '';
  for (const r of rows) {
    if (QUIET && r.level === 'PASS') continue;
    if (r.area !== area) { console.log(`\n[${r.area}]`); area = r.area; }
    console.log(`  ${mark[r.level]}  ${r.name}${r.detail ? '  —  ' + r.detail : ''}`);
    if (r.fix) console.log(`        → ${r.fix}`);
  }
  console.log('\n' + '─'.repeat(78));
  console.log(`通过 ${rows.length - fails.length - warns.length} · 警告 ${warns.length} · 失败 ${fails.length}`);
  if (fails.length) {
    console.log('\n必须处理的失败项：');
    fails.forEach((f, i) => console.log(`  ${i + 1}. ${f.name}${f.detail ? '（' + f.detail + '）' : ''}\n     ${f.fix || ''}`));
    console.log('\n这台机器现在不要交付给运营。');
  } else if (warns.length) {
    console.log('\n没有失败项，警告项按需处理即可交付。');
  } else {
    console.log('\n全部通过，可以交付。');
  }
  console.log('');
}
process.exit(fails.length ? 1 : 0);
