// 底座包安装的失败路径：校验和不对 → 不安装、不写版本、报 BUNDLE_FAILED；中枢没有底座包 → 退回联网（这里用 BASE_ONLY 在退回前停下）。
// 运行：node agent/tests/bundle-install.mjs   （Windows PowerShell 5.1，本机假中枢，不碰真实中枢和真实用户目录）
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const installPs1 = fs.readFileSync(path.join(here, '..', 'install.ps1'), 'utf8');
let bad = 0;
const check = (label, cond, extra = '') => { if (!cond) bad++; console.log(cond ? 'PASS' : 'FAIL', label, cond ? '' : extra); };

// 一个最小的 zip（含 node.exe 占位文件），用 PowerShell 现做
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'bundle-test-'));
fs.mkdirSync(path.join(work, 'src', 'inner'), { recursive: true });
fs.writeFileSync(path.join(work, 'src', 'inner', 'node.exe'), 'fake');
const zip = path.join(work, 'node-test.zip');
await new Promise((r) => spawn('powershell.exe', ['-NoProfile', '-Command', `Compress-Archive -Path '${path.join(work, 'src', 'inner')}' -DestinationPath '${zip}'`]).on('close', r));
const zipBuf = fs.readFileSync(zip);
const goodSha = createHash('sha256').update(zipBuf).digest('hex');

function hub({ sha, withBundle = true }) {
  const srv = http.createServer((req, res) => {
    if (req.url.endsWith('/bundle/manifest.json')) {
      if (!withBundle) { res.writeHead(404); return res.end('no'); }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ base: '9.9.9', components: { node: { version: '1', file: 'node-test.zip', sha256: sha, size: zipBuf.length, strip: 'inner', dest: 'runtime/node' } } }));
    }
    if (req.url.endsWith('/bundle/files/node-test.zip')) { res.writeHead(200); return res.end(zipBuf); }
    res.writeHead(404); res.end('');
  });
  return new Promise((r) => srv.listen(0, '127.0.0.1', () => r({ url: `http://127.0.0.1:${srv.address().port}`, stop: () => srv.close() })));
}

async function run(h, extra = {}) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'bundle-home-'));
  const env = { ...process.env, USERPROFILE: home, HUB_APPS_ROOT: path.join(home, 'HubApps'), HUB_AGENT_HOME: path.join(home, 'agent'), HUB_INSTALL_NO_USER_PATH: '1',
    HUB_INSTALL_BASE_ONLY: '1', HUB_PREFLIGHT: 'skip', HUB_DEBUG: '1', ...extra };
  const ps1 = path.join(home, 'i.ps1');
  extra.pre?.(path.join(home, 'HubApps'));            // 升级测试：先摆好「老安装」的目录
  delete env.pre;
  fs.writeFileSync(ps1, installPs1.replaceAll('__HUB_URL__', h.url));
  let out = '';
  const child = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1], { env, windowsHide: true });
  child.stdout.on('data', (d) => { out += d; }); child.stderr.on('data', (d) => { out += d; });
  await new Promise((r) => child.on('close', r));
  const logFile = path.join(home, 'HubApps', 'logs', 'health-install.jsonl');
  return { out, root: path.join(home, 'HubApps'), health: fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8') : '' };
}

{ const h = await hub({ sha: goodSha }); const r = await run(h);
  check('正确的校验和 → 装好并写 BASE_VERSION', fs.existsSync(path.join(r.root, 'runtime', 'node', 'node.exe')) && fs.readFileSync(path.join(r.root, 'runtime', 'BASE_VERSION'), 'utf8') === '9.9.9', r.out.slice(-400)); h.stop(); }
{ const h = await hub({ sha: 'a'.repeat(64) }); const r = await run(h);
  check('校验和不对 → 不安装', !fs.existsSync(path.join(r.root, 'runtime', 'node')), r.out.slice(-400));
  check('校验和不对 → 不写 BASE_VERSION', !fs.existsSync(path.join(r.root, 'runtime', 'BASE_VERSION')));
  check('校验和不对 → 记 BUNDLE_FAILED', r.health.includes('BUNDLE_FAILED'), r.health);
  check('校验和不对 → 提示退回联网', /Falling back/.test(r.out), r.out.slice(-400)); h.stop(); }
{ const h = await hub({ sha: goodSha, withBundle: false }); const r = await run(h);
  check('中枢没有底座包 → 不报错、不写 BASE_VERSION', !fs.existsSync(path.join(r.root, 'runtime', 'BASE_VERSION')) && !/BUNDLE/.test(r.health), r.out.slice(-300)); h.stop(); }

// 升级：老安装把 CodeBuddy CLI 装在 runtime\node 里（npm install -g --prefix runtime\node）。换 Node 时必须带过去，否则升级会悄悄删掉它
{
  const h = await hub({ sha: goodSha });
  const oldNode = (root) => {
    const n = path.join(root, 'runtime', 'node');
    fs.mkdirSync(path.join(n, 'node_modules', '@tencent-ai', 'codebuddy-code'), { recursive: true });
    fs.mkdirSync(path.join(n, 'node_modules', 'npm'), { recursive: true });
    fs.writeFileSync(path.join(n, 'node.exe'), 'old node');
    fs.writeFileSync(path.join(n, 'codebuddy.cmd'), '@echo old shim');
    fs.writeFileSync(path.join(n, 'node_modules', '@tencent-ai', 'codebuddy-code', 'package.json'), '{"name":"codebuddy"}');
    fs.writeFileSync(path.join(n, 'node_modules', 'npm', 'package.json'), '{"name":"old-npm"}');
  };
  const r = await run(h, { pre: oldNode });
  const n = path.join(r.root, 'runtime', 'node');
  check('升级：换成了新的 node.exe', fs.readFileSync(path.join(n, 'node.exe'), 'utf8') === 'fake', r.out.slice(-300));
  check('升级：老安装里的 codebuddy 启动脚本被带过去', fs.existsSync(path.join(n, 'codebuddy.cmd')));
  check('升级：老安装里全局装的 CodeBuddy 包被带过去', fs.existsSync(path.join(n, 'node_modules', '@tencent-ai', 'codebuddy-code', 'package.json')));
  check('升级成功后不留 .prev（省几百 MB）', !fs.existsSync(path.join(r.root, 'runtime', 'node.prev')), r.out.slice(-200));
  check('升级后写了新的 BASE_VERSION', fs.readFileSync(path.join(r.root, 'runtime', 'BASE_VERSION'), 'utf8') === '9.9.9');
  h.stop();
}

console.log(bad ? `失败 ${bad} 项` : '全部通过');
process.exit(bad ? 1 : 0);
