'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const targetUrl = process.argv[2];
const clickText = process.argv[3] || 'DCOP';
if (!targetUrl) {
  console.error('Uso: node scripts/inspect-payment-request-click.js <url> [text]');
  process.exit(1);
}

const outDir = path.join(__dirname, '..', 'data', 'front-inspections');
fs.mkdirSync(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
const base = path.join(outDir, `${stamp}-click-${clickText.replace(/[^a-z0-9]+/gi, '-')}`);
const browserPath = process.env.PLAYWRIGHT_CHROMIUM_PATH || path.join(process.env.HOME, '.cache/ms-playwright/chromium-1217/chrome-linux/chrome');
const FINAL_INSTRUCTIONS_RE = /(?:Envía|Envia|Enviar)\s+[0-9.,]+\s+COP[\s\S]{0,400}@[A-Za-z0-9._-]{6,64}/i;
const CLICK_SETTLE_TIMEOUT_MS = Number(process.env.CHAUT_INSPECT_CLICK_SETTLE_TIMEOUT_MS || 25000);

function safeBody(body) {
  if (!body) return null;
  return body.length > 12000 ? `${body.slice(0, 12000)}...[truncated ${body.length}]` : body;
}


async function waitForFinalInstructions(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastText = '';
  while (Date.now() < deadline) {
    lastText = await page.evaluate(() => document.body.innerText || '').catch(() => '');
    if (FINAL_INSTRUCTIONS_RE.test(lastText)) return true;
    if (/No disponible|expirad[ao]|cancelad[ao]|rechazad[ao]/i.test(lastText)) return false;
    await page.waitForTimeout(1000);
  }
  return FINAL_INSTRUCTIONS_RE.test(lastText);
}

(async () => {
  const events = [];
  const browser = await chromium.launch({ headless: true, executablePath: browserPath, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.on('request', (req) => {
    if (/coinsenda|payment|deposit|provider|pse|wompi/i.test(req.url())) {
      events.push({ type: 'request', method: req.method(), url: req.url(), postData: safeBody(req.postData()) });
    }
  });
  page.on('response', async (res) => {
    if (!/coinsenda|payment|deposit|provider|pse|wompi/i.test(res.url())) return;
    const ct = res.headers()['content-type'] || '';
    let body = null;
    if (/json|text|html/.test(ct)) {
      try { body = safeBody(await res.text()); } catch (_) {}
    }
    events.push({ type: 'response', status: res.status(), url: res.url(), contentType: ct, body });
  });
  page.on('console', (msg) => events.push({ type: 'console', level: msg.type(), text: msg.text() }));

  await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 60000 });
  await page.screenshot({ path: `${base}-before.png`, fullPage: true });

  const before = await page.evaluate(() => document.body.innerText);
  const clicked = await page.evaluate((text) => {
    const nodes = Array.from(document.querySelectorAll('body *'));
    const target = nodes.find((el) => (el.innerText || el.textContent || '').trim() === text && el.getBoundingClientRect().width > 0);
    if (!target) return false;
    const row = target.closest('.listView') || target.closest('div') || target;
    row.click();
    return true;
  }, clickText);
  if (!clicked) throw new Error(`No visible row found for ${clickText}`);
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  const finalInstructionsReady = await waitForFinalInstructions(page, CLICK_SETTLE_TIMEOUT_MS);
  await page.screenshot({ path: `${base}-after.png`, fullPage: true });

  const after = await page.evaluate(() => ({
    url: location.href,
    text: document.body.innerText,
    inputs: Array.from(document.querySelectorAll('input, select, textarea, button, a')).map((el) => ({
      tag: el.tagName,
      text: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim(),
      href: el.href || null,
      name: el.name || null,
      id: el.id || null,
      type: el.type || null
    }))
  }));
  const result = { targetUrl, clickText, before, after, finalInstructionsReady, events };
  fs.writeFileSync(`${base}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ out: `${base}.json`, before: before.slice(0, 1000), after: { ...after, text: after.text.slice(0, 3000) }, finalInstructionsReady, eventsCount: events.length }, null, 2));
  await browser.close();
})().catch((err) => { console.error(err.stack || err); process.exit(1); });
