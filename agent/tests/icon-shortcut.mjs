// 桌面 / 开始菜单快捷方式的图标：从 install.ps1 里取出创建快捷方式的那一段，用本机假中枢、临时目录真实创建 .lnk，再读回 IconLocation。
// 运行：node agent/tests/icon-shortcut.mjs   （Windows PowerShell 5.1；不碰真实桌面和中枢）
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = fs.readFileSync(path.join(root, 'install.ps1'), 'utf8');
const a = src.indexOf('# App icons come from the hub');
const b = src.indexOf("Write-Host ''", a);
if (a < 0 || b < 0) { console.log('FAIL 找不到快捷方式那一段'); process.exit(1); }
const block = src.slice(a, b);
const icoBytes = fs.readFileSync(path.join(root, 'icons', 'xhs-workbench.ico'));
let bad = 0; const check = (l, c, x = '') => { if (!c) bad++; console.log(c ? 'PASS' : 'FAIL', l, c ? '' : x); };

async function run(hubHasIcon) {
  const srv = http.createServer((req, res) => {
    if (hubHasIcon && req.url === '/api/agent/icons/demo-app.ico') { res.writeHead(200, { 'Content-Type': 'image/x-icon' }); return res.end(icoBytes); }
    res.writeHead(404); res.end('no');
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'icon-test-'));
  const launcher = path.join(base, 'open-demo.cmd'); fs.writeFileSync(launcher, '@echo off\r\n');
  const desk = path.join(base, 'desk');
  const fwd = (p) => p.split(path.sep).join('/');            // 路径统一成正斜杠（PowerShell 都认），脚本里就不会出现反斜杠
  const script = `$ErrorActionPreference='Stop'
$Hub='http://127.0.0.1:${srv.address().port}'; $Root='${fwd(base)}'
$items=@([pscustomobject]@{ id='demo-app'; name='Demo App'; path='${fwd(launcher)}' })
$dirs=@('${fwd(desk)}'); $ws = New-Object -ComObject WScript.Shell
${block}
$l = $ws.CreateShortcut('${fwd(path.join(desk, 'Demo App.lnk'))}')
Write-Output ('ICON=' + $l.IconLocation)`;
  const f = path.join(base, 't.ps1'); fs.writeFileSync(f, script, 'utf8');
  let out = '';
  const child = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', f], { windowsHide: true });
  child.stdout.on('data', (d) => { out += d; }); child.stderr.on('data', (d) => { out += d; });
  await new Promise((r) => child.on('close', r)); srv.close();
  return { out, base };
}

{ const r = await run(true);
  const m = r.out.match(/ICON=(.*)/);
  check('中枢有图标：快捷方式的图标指向下载到本机的 .ico', !!m && m[1].toLowerCase().includes('bin') && m[1].toLowerCase().includes('demo-app.ico'), r.out.slice(-300));
  check('图标文件真的下载成功且是 ICO', fs.existsSync(path.join(r.base, 'bin', 'icons', 'demo-app.ico')) && fs.readFileSync(path.join(r.base, 'bin', 'icons', 'demo-app.ico')).subarray(0, 4).equals(Buffer.from([0, 0, 1, 0]))); }
{ const r = await run(false);
  const m = r.out.match(/ICON=(.*)/);
  check('中枢没有这个图标：不报错，快捷方式照常创建（没有自定义图标）', !!m && !m[1].toLowerCase().includes('demo-app.ico') && !fs.existsSync(path.join(r.base, 'bin', 'icons', 'demo-app.ico')), r.out.slice(-300)); }
console.log(bad ? `失败 ${bad} 项` : '全部通过');
process.exit(bad ? 1 : 0);
