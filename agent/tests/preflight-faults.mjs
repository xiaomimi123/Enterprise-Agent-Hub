// 安装前自检的故障注入：每种失败各做一次，确认得到正确的错误码；干净环境下应没有 FAIL。
// 在 Windows 上运行：node agent/tests/preflight-faults.mjs   （用 Windows PowerShell 5.1 跑，和员工电脑一致；用一个本机假中枢，不碰真实中枢）
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'preflight.ps1');
const reportFile = path.join(os.tmpdir(), 'hub-preflight.json');
let bad = 0;
const check = (label, cond, extra = '') => { if (!cond) bad++; console.log(cond ? 'PASS' : 'FAIL', label, cond ? '' : extra); };

/** 假中枢：/api/agent/config 返回登录和 MCP 地址；可以让它慢、让它的时钟不对 */
function fakeHub({ casdoorOk = true, mcpOk = true, delayMs = 0, dateOffsetMs = 0 } = {}) {
  const live = []; // 让「通」的端口真的有人在听
  const listen = (srv) => new Promise((r) => srv.listen(0, '127.0.0.1', () => r(srv.address().port)));
  return (async () => {
    const cas = net.createServer(); const mcp = net.createServer();
    const casPort = casdoorOk ? await listen(cas) : 1; const mcpPort = mcpOk ? await listen(mcp) : 2;
    const srv = http.createServer((req, res) => {
      setTimeout(() => {
        res.writeHead(200, { 'Content-Type': 'application/json', Date: new Date(Date.now() + dateOffsetMs).toUTCString() });
        res.end(JSON.stringify({ casdoor_url: `http://127.0.0.1:${casPort}`, mcp_url: `http://127.0.0.1:${mcpPort}/mcp`, client_id: 'x', redirect_uri: 'http://127.0.0.1:27891/callback' }));
      }, delayMs);
    });
    const port = await listen(srv);
    return { url: `http://127.0.0.1:${port}`, stop: () => { for (const s of [srv, cas, mcp]) try { s.closeAllConnections?.(); s.close(); } catch {} } };
  })();
}

// 必须异步起子进程：假中枢和本脚本在同一个进程里，同步等待会把假中枢也卡住
async function run(env) {
  try { fs.unlinkSync(reportFile); } catch {}
  const child = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, '-Quiet'],
    { env: { ...process.env, HUB_PREFLIGHT_UPLOAD: 'off', ...env }, windowsHide: true });
  let err = '';
  child.stderr.on('data', (d) => { err += d; });
  child.stdout.resume();
  const timer = setTimeout(() => child.kill(), 90_000);
  await new Promise((resolve) => child.on('close', resolve));
  clearTimeout(timer);
  let rep = { results: [], summary: { fail: -1, warn: -1 } };
  try { rep = JSON.parse(fs.readFileSync(reportFile, 'utf8').replace(/^﻿/, '')); } catch { console.log('  （没有读到报告）', err.slice(0, 300)); }
  const codes = (rep.results || []).map((x) => `${x.level}:${x.code}`);
  return { codes, has: (c, level) => codes.includes(`${level}:${c}`), summary: rep.summary };
}

const clean = { HUB_APPS_ROOT: path.join(os.tmpdir(), 'hub-preflight-ok') };
{ // 干净环境：不应有 FAIL（WARN 可能来自这台机器自己，如没有 Edge）
  const hub = await fakeHub(); const r = await run({ ...clean, HUB_URL: hub.url });
  check('干净环境没有 FAIL', r.summary.fail === 0, JSON.stringify(r.codes)); hub.stop();
}
{ const r = await run({ ...clean, HUB_URL: 'http://127.0.0.1:9' });
  check('中枢连不上 → PREFLIGHT_HUB_UNREACHABLE', r.has('PREFLIGHT_HUB_UNREACHABLE', 'FAIL'), JSON.stringify(r.codes)); }
{ const hub = await fakeHub({ casdoorOk: false, mcpOk: false }); const r = await run({ ...clean, HUB_URL: hub.url });
  check('登录端口不通 → PREFLIGHT_CASDOOR_UNREACHABLE', r.has('PREFLIGHT_CASDOOR_UNREACHABLE', 'FAIL'), JSON.stringify(r.codes));
  check('MCP 端口不通 → PREFLIGHT_MCP_UNREACHABLE', r.has('PREFLIGHT_MCP_UNREACHABLE', 'FAIL'), JSON.stringify(r.codes)); hub.stop(); }
{ const hub = await fakeHub({ dateOffsetMs: -3600_000 }); const r = await run({ ...clean, HUB_URL: hub.url });
  check('时钟差 1 小时 → PREFLIGHT_CLOCK_SKEW', r.has('PREFLIGHT_CLOCK_SKEW', 'WARN'), JSON.stringify(r.codes)); hub.stop(); }
{ const hub = await fakeHub({ delayMs: 2600 }); const r = await run({ ...clean, HUB_URL: hub.url });
  check('中枢响应慢 → PREFLIGHT_HUB_SLOW', r.has('PREFLIGHT_HUB_SLOW', 'WARN'), JSON.stringify(r.codes)); hub.stop(); }
{ const hub = await fakeHub(); const holder = net.createServer(); await new Promise((r) => holder.listen(0, '127.0.0.1', r));
  const r = await run({ ...clean, HUB_URL: hub.url, HUB_PREFLIGHT_CALLBACK_PORT: String(holder.address().port) });
  check('回调端口被占 → PREFLIGHT_PORT_CALLBACK', r.has('PREFLIGHT_PORT_CALLBACK', 'FAIL'), JSON.stringify(r.codes)); holder.close(); hub.stop(); }
{ const hub = await fakeHub(); const r = await run({ ...clean, HUB_URL: hub.url, HUB_PREFLIGHT_MIN_FREE_MB: '999999999' });
  check('磁盘不够 → PREFLIGHT_DISK_LOW', r.has('PREFLIGHT_DISK_LOW', 'FAIL'), JSON.stringify(r.codes)); hub.stop(); }
{ const hub = await fakeHub(); const r = await run({ HUB_URL: hub.url, HUB_APPS_ROOT: path.join(os.tmpdir(), '中文 目录', 'HubApps') });
  check('路径含中文和空格 → PREFLIGHT_PATH_UNSAFE', r.has('PREFLIGHT_PATH_UNSAFE', 'WARN'), JSON.stringify(r.codes)); hub.stop(); }
{ const hub = await fakeHub(); const r = await run({ HUB_URL: hub.url, HUB_APPS_ROOT: 'Q:/HubApps' }); // 假设没有 Q 盘
  const hasQ = fs.existsSync('Q:/');
  check('目录不可写（Q 盘不存在）→ PREFLIGHT_NOT_WRITABLE', hasQ || r.has('PREFLIGHT_NOT_WRITABLE', 'FAIL'), JSON.stringify(r.codes)); hub.stop(); }
{ const hub = await fakeHub(); const r = await run({ ...clean, HUB_URL: hub.url, WORKBUDDY_SESSION_ID: 'x', CODEBUDDY_SERVICE_PROXY_URL: 'http://127.0.0.1:1/x' });
  check('被 agent 拉起 → PREFLIGHT_AGENT_SANDBOX', r.has('PREFLIGHT_AGENT_SANDBOX', 'WARN'), JSON.stringify(r.codes)); hub.stop(); }
{ const hub = await fakeHub(); const r = await run({ ...clean, HUB_URL: hub.url, HTTPS_PROXY: 'http://127.0.0.1:1' });
  check('代理指向没在跑的端口 → PREFLIGHT_PROXY_DEAD', r.has('PREFLIGHT_PROXY_DEAD', 'WARN'), JSON.stringify(r.codes)); hub.stop(); }

console.log(bad ? `失败 ${bad} 项` : '全部通过');
process.exit(bad ? 1 : 0);
