// 把生成的 PDF 某几页渲染成 PNG，用来目视检查版式：node preview.mjs <pdf> <输出目录> <页码...>
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer-core';

const [pdf, outDir, ...pages] = process.argv.slice(2);
const here = path.dirname(fileURLToPath(import.meta.url));
const chrome = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const lib = pathToFileURL(path.join(here, 'node_modules/pdfjs-dist/build/pdf.min.mjs')).href;
const worker = pathToFileURL(path.join(here, 'node_modules/pdfjs-dist/build/pdf.worker.min.mjs')).href;
const b64 = fs.readFileSync(pdf).toString('base64');
fs.mkdirSync(outDir, { recursive: true });

const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ['--no-sandbox', '--allow-file-access-from-files'] });
const page = await browser.newPage();
const htmlFile = path.join(here, '.preview.html');
fs.writeFileSync(htmlFile, `<!doctype html><body style="margin:0"><canvas id="c"></canvas><script type="module">
import * as pdfjs from '${lib}';
pdfjs.GlobalWorkerOptions.workerSrc = '${worker}';
const data = Uint8Array.from(atob('${b64}'), (c) => c.charCodeAt(0));
const doc = await pdfjs.getDocument({ data }).promise;
window.total = doc.numPages;
window.render = async (n) => {
  const p = await doc.getPage(n);
  const vp = p.getViewport({ scale: 1.25 });
  const c = document.getElementById('c');
  c.width = vp.width; c.height = vp.height;
  await p.render({ canvasContext: c.getContext('2d'), viewport: vp }).promise;
  return c.toDataURL('image/png');
};
window.ready = true;
</script></body>`);
await page.goto(pathToFileURL(htmlFile).href);
await page.waitForFunction('window.ready === true', { timeout: 60000 });
const total = await page.evaluate('window.total');
console.log('总页数', total);
for (const n of pages.map(Number)) {
  if (n < 1 || n > total) continue;
  const url = await page.evaluate((k) => window.render(k), n);
  fs.writeFileSync(path.join(outDir, `p${String(n).padStart(2, '0')}.png`), Buffer.from(url.split(',')[1], 'base64'));
}
await browser.close();
fs.rmSync(htmlFile, { force: true });
