// 构建「底座包」：固定版本的 Node.js + uv + Python，逐个校验后放进 bundle/，并生成 manifest.json。
// 在有外网的 Windows x64 机器上运行：node tools/build-bundle/build.mjs [--base 1.0.0] [--node 22.x.y] [--python 3.12]
// 产物（不进 git）：bundle/manifest.json、bundle/wheels-<hash>.zip（接入器依赖）、bundle/node-<v>-win-x64.zip、bundle/uv-x86_64-pc-windows-msvc.zip、bundle/python-<v>-win-x64.zip
// 中枢把 bundle/ 挂载为 /data/bundle，员工端 install.ps1 优先从中枢下载并按 manifest 校验 SHA-256。
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const out = path.join(root, 'bundle');
const args = Object.fromEntries(process.argv.slice(2).reduce((a, x, i, all) => (x.startsWith('--') ? [...a, [x.slice(2), all[i + 1]]] : a), []));
const BASE = args.base || '1.0.1';
const PY = args.python || '3.12';
const UV_ZIP = 'uv-x86_64-pc-windows-msvc.zip';

const sha256 = (f) => createHash('sha256').update(fs.readFileSync(f)).digest('hex');
async function get(url, file) {
  const r = await fetch(url, { redirect: 'follow' });
  if (!r.ok) throw new Error(`${url} -> HTTP ${r.status}`);
  if (file) fs.writeFileSync(file, Buffer.from(await r.arrayBuffer())); else return r.text();
}
function run(cmd, a, opt = {}) {
  const r = spawnSync(cmd, a, { encoding: 'utf8', ...opt });
  if (r.status !== 0) throw new Error(`${cmd} ${a.join(' ')} 失败：${(r.stderr || r.stdout || '').slice(0, 400)}`);
  return r.stdout;
}
const ps = (script) => run('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script]);
const zipDir = (dir, zip) => { fs.rmSync(zip, { force: true }); ps(`Compress-Archive -Path '${dir}\\*' -DestinationPath '${zip}' -CompressionLevel Optimal`); };
const unzip = (zip, dir) => ps(`Expand-Archive -Path '${zip}' -DestinationPath '${dir}' -Force`);

fs.mkdirSync(out, { recursive: true });
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'hub-bundle-'));
const components = {};

// ---- Node.js：官方便携 zip，对照官方 SHASUMS256.txt
let nodeVer = args.node;
if (!nodeVer) {
  const index = await (await fetch('https://nodejs.org/dist/index.json')).json();
  nodeVer = index.find((x) => x.lts && /^v22\./.test(x.version))?.version?.slice(1);   // 固定 22 线，不跟最新 LTS
  if (!nodeVer) throw new Error('找不到 Node 22 LTS');
}
{
  const name = `node-v${nodeVer}-win-x64.zip`;
  const sums = await get(`https://nodejs.org/dist/v${nodeVer}/SHASUMS256.txt`);
  const want = sums.split('\n').find((l) => l.includes(name))?.trim().split(/\s+/)[0];
  if (!want) throw new Error(`SHASUMS256.txt 里没有 ${name}`);
  const file = path.join(out, name);
  await get(`https://nodejs.org/dist/v${nodeVer}/${name}`, file);
  if (sha256(file) !== want) { fs.rmSync(file); throw new Error(`${name} 校验失败`); }
  // 官方 zip 里多一层 node-v..-win-x64/，员工端解压时去掉；这里记下目录名
  components.node = { version: nodeVer, file: name, sha256: want, size: fs.statSync(file).size, strip: `node-v${nodeVer}-win-x64`, dest: 'runtime/node' };
  console.log('node', nodeVer, 'ok');
}

// ---- uv：GitHub 发布页，对照同名 .sha256
const uvBase = 'https://github.com/astral-sh/uv/releases/latest/download';
const uvZip = path.join(out, UV_ZIP);
await get(`${uvBase}/${UV_ZIP}`, uvZip);
const uvWant = (await get(`${uvBase}/${UV_ZIP}.sha256`)).trim().split(/\s+/)[0].toLowerCase();
if (sha256(uvZip) !== uvWant) { fs.rmSync(uvZip); throw new Error('uv 校验失败'); }
const uvDir = path.join(work, 'uv');
unzip(uvZip, uvDir);
const uvVer = run(path.join(uvDir, 'uv.exe'), ['--version']).trim().replace(/^uv\s+/, '').split(' ')[0];
components.uv = { version: uvVer, file: UV_ZIP, sha256: uvWant, size: fs.statSync(uvZip).size, strip: '', dest: 'runtime/uv' };
console.log('uv', uvVer, 'ok');

// ---- Python：用 uv 装一份便携 Python（接入器要求 >=3.11,<3.14），整目录打成 zip；员工端设 UV_PYTHON_INSTALL_DIR 指到它
{
  const pyDir = path.join(work, 'python');
  run(path.join(uvDir, 'uv.exe'), ['python', 'install', PY, '--install-dir', pyDir, '--no-bin'], { env: { ...process.env, UV_PYTHON_INSTALL_DIR: pyDir } });
  const found = fs.readdirSync(pyDir).find((d) => d.startsWith('cpython-'));
  if (!found) throw new Error('uv 没有装出 cpython 目录');
  const pyVer = found.split('-')[1];
  const name = `python-${pyVer}-win-x64.zip`;
  const file = path.join(out, name);
  zipDir(pyDir, file);
  components.python = { version: pyVer, file: name, sha256: sha256(file), size: fs.statSync(file).size, strip: '', dest: 'runtime/python' };
  console.log('python', pyVer, 'ok');
}

// ---- 接入器依赖：把 hub_agent.py 头部声明的依赖（及其依赖）下载成 wheel，员工端装机时用本地 wheel，不再访问 PyPI
{
  const src = fs.readFileSync(path.join(root, 'agent', 'hub_agent.py'), 'utf8');
  const deps = JSON.parse((src.match(/^# dependencies = (\[.*\])$/m) || [])[1] || 'null');
  if (!deps) throw new Error('hub_agent.py 头部没有 dependencies');
  const wh = path.join(work, 'wheels');
  fs.mkdirSync(wh);
  run('python', ['-m', 'pip', 'download', '--quiet', '--dest', wh, '--platform', 'win_amd64', '--python-version', PY, '--implementation', 'cp', '--only-binary=:all:', ...deps]);
  const files = fs.readdirSync(wh).sort();
  const digest = createHash('sha256').update(files.join('\n')).digest('hex').slice(0, 8);   // 依赖集合变了，文件名就变
  const name = `wheels-${digest}.zip`;
  const file = path.join(out, name);
  zipDir(wh, file);
  components.wheels = { version: files.length + ' wheels', file: name, sha256: sha256(file), size: fs.statSync(file).size, strip: '', dest: 'runtime/wheels', deps };
  console.log('wheels', files.length, 'ok');
}

// 旧版本的组件文件不留（manifest 只认当前这一套）
const keep = new Set(['manifest.json', ...Object.values(components).map((c) => c.file)]);
for (const f of fs.readdirSync(out)) if (!keep.has(f)) fs.rmSync(path.join(out, f), { recursive: true, force: true });

const manifest = { base: BASE, built_at: new Date().toISOString(), platform: 'win-x64', components };
fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
fs.rmSync(work, { recursive: true, force: true });
console.log(`底座包 ${BASE} 已生成：${out}`);
console.log(Object.entries(components).map(([k, c]) => `  ${k} ${c.version}  ${(c.size / 1048576).toFixed(1)} MB`).join('\n'));
