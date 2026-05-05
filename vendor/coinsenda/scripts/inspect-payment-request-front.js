'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const targetUrl = process.argv[2];
if (!targetUrl) {
  console.error('Uso: node scripts/inspect-payment-request-front.js <payment-request-url>');
  process.exit(1);
}

const outDir = path.join(__dirname, '..', 'data', 'front-inspections');
fs.mkdirSync(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
const base = path.join(outDir, stamp);
const browserPath = process.env.PLAYWRIGHT_CHROMIUM_PATH || path.join(process.env.HOME, '.cache/ms-playwright/chromium-1217/chrome-linux/chrome');

function safeBody(body) {
  if (!body) return null;
  if (body.length > 5000) return `${body.slice(0, 5000)}...[truncated ${body.length}]`;
  return body;
}

(async () => {
  const events = [];
  const browser = await chromium.launch({
    headless: true,
    executablePath: browserPath,
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  });
  const page = await context.newPage();

  page.on('console', (msg) => events.push({ type: 'console', level: msg.type(), text: msg.text() }));
  page.on('pageerror', (err) => events.push({ type: 'pageerror', message: err.message, stack: err.stack }));
  page.on('request', (req) => {
    const method = req.method();
    const url = req.url();
    if (/coinsenda|payment|deposit|provider|pay|wompi|pse|checkout/i.test(url)) {
      events.push({
        type: 'request',
        method,
        url,
        postData: safeBody(req.postData())
      });
    }
  });
  page.on('response', async (res) => {
    const url = res.url();
    if (!/coinsenda|payment|deposit|provider|pay|wompi|pse|checkout/i.test(url)) return;
    const headers = res.headers();
    const ct = headers['content-type'] || '';
    let body = null;
    if (/json|text|html/.test(ct)) {
      try { body = safeBody(await res.text()); } catch (_) {}
    }
    events.push({ type: 'response', status: res.status(), url, contentType: ct, body });
  });

  await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 60000 });
  await page.screenshot({ path: `${base}.png`, fullPage: true });

  const snapshot = await page.evaluate(() => ({
    title: document.title,
    url: location.href,
    bodyText: document.body ? document.body.innerText.slice(0, 5000) : '',
    buttons: Array.from(document.querySelectorAll('button, a, input, select')).map((el) => ({
      tag: el.tagName,
      text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 200),
      href: el.href || null,
      type: el.type || null,
      name: el.name || null,
      id: el.id || null,
      classes: el.className || null
    })).slice(0, 200)
  }));

  // Try one pass over visible clickable controls to trigger provider setup without submitting bank credentials.
  const clickTexts = ['pagar', 'continuar', 'pay', 'banco', 'pse', 'transferencia'];
  for (const text of clickTexts) {
    const locator = page.getByText(new RegExp(text, 'i')).first();
    try {
      if (await locator.isVisible({ timeout: 1000 })) {
        await locator.click({ timeout: 5000 });
        await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
        await page.screenshot({ path: `${base}-after-${text}.png`, fullPage: true }).catch(() => {});
      }
    } catch (_) {}
  }

  const finalSnapshot = await page.evaluate(() => ({
    title: document.title,
    url: location.href,
    bodyText: document.body ? document.body.innerText.slice(0, 5000) : '',
    buttons: Array.from(document.querySelectorAll('button, a, input, select')).map((el) => ({
      tag: el.tagName,
      text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 200),
      href: el.href || null,
      type: el.type || null,
      name: el.name || null,
      id: el.id || null,
      classes: el.className || null
    })).slice(0, 200)
  }));

  await browser.close();
  const result = { targetUrl, base, snapshot, finalSnapshot, events };
  fs.writeFileSync(`${base}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ out: `${base}.json`, screenshot: `${base}.png`, snapshot, finalSnapshot, eventsCount: events.length }, null, 2));
})().catch((err) => {
  console.error(err.stack || err);
  process.exit(1);
});
