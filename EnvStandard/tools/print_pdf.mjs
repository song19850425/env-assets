// 把构造报告 HTML 打印成 PDF（A4，保留文本层）。
// 用 Node 的 playwright-core —— 本机已有 Chromium，不必再装 Python 版 playwright。
//
// 跑法：node EnvStandard/tools/print_pdf.mjs

import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const require = createRequire(import.meta.url);
const { chromium } = require(
  'C:/Users/jingh/.workbuddy-ai/binaries/node/workspace/node_modules/playwright-core');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const HTML = process.env.PDF_SRC
  || path.join(REPO, 'EnvStandard', 'extract', 'sample', 'sample-report.html');
const PDF = process.env.PDF_OUT
  || path.join(REPO, 'EnvStandard', 'extract', 'sample', 'sample-report.pdf');
const CHROME = process.env.CHROME_EXE
  || 'C:/Users/jingh/AppData/Local/ms-playwright/chromium-1187/chrome-win/chrome.exe';

if (!fs.existsSync(HTML)) {
  console.error('[pdf] 找不到 ' + HTML + '，先跑 make_sample_report.py');
  process.exit(1);
}

const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage();
await page.goto('file:///' + HTML.replace(/\\/g, '/').replace(/ /g, '%20'), { waitUntil: 'load' });
await page.pdf({ path: PDF, format: 'A4', printBackground: true,
                 margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' } });
await browser.close();
console.log('[pdf] ' + PDF + '  ' + fs.statSync(PDF).size + ' bytes');
