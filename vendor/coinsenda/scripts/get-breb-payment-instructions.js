'use strict';

function parseArgs(argv) {
  const args = { payment_request_id: null, currency: 'cop', provider_type: 'breb', country: 'international' };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2).replace(/-/g, '_');
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) args[key] = true;
    else { args[key] = next; i += 1; }
  }
  if (!args.payment_request_id) {
    throw new Error('Uso: node get-breb-payment-instructions.js --payment-request-id <id>');
  }
  return args;
}

async function coinsendaPublicPost(pathname, data) {
  const origin = process.env.COINSENDA_APP_ORIGIN || 'https://app.coinsenda.com';
  const timeoutMs = Number(process.env.COINSENDA_PUBLIC_TIMEOUT_MS || 45000);
  const startedAt = Date.now();
  console.error(JSON.stringify({ event: 'coinsenda_public.request', pathname, started_at: new Date(startedAt).toISOString() }));
  try {
    const response = await fetch(`https://deposit.coinsenda.com/api/${pathname}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Origin: origin,
        Referer: origin,
        'User-Agent': 'Chaut Payments/1.0'
      },
      body: JSON.stringify({ data }),
      signal: AbortSignal.timeout(timeoutMs)
    });
    const body = await response.json().catch(() => null);
    console.error(JSON.stringify({ event: 'coinsenda_public.response', pathname, status: response.status, elapsed_ms: Date.now() - startedAt }));
    if (!response.ok) {
      throw new Error(`coinsenda_public_${response.status}:${JSON.stringify(body)}`);
    }
    return body?.data || body;
  } catch (err) {
    console.error(JSON.stringify({ event: 'coinsenda_public.error', pathname, elapsed_ms: Date.now() - startedAt, message: String(err?.message || err) }));
    throw err;
  }
}

function firstString(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return null;
}

function extractInstructions(payload) {
  const provider = payload?.depositProvider || payload?.deposit_provider || payload?.provider || {};
  const account = provider.account || payload?.account || {};
  const accountId = account.account_id || account.accountId || {};
  const qr = account.qr_code || account.qrCode || payload?.qr_code || {};
  const alias = firstString(
    accountId.account_id,
    accountId.id,
    account.alias,
    account.address,
    account.wallet_address,
    provider.alias,
    payload?.alias,
    payload?.address
  );
  const amount = firstString(
    payload?.amount,
    payload?.amount_cop,
    payload?.pay_amount,
    provider.amount,
    provider.amount_cop,
    account.amount
  );

  return {
    deposit_provider_id: firstString(payload?.deposit_provider_id, provider.id),
    breb_alias: alias,
    amount_cop_text: amount,
    qr_string: firstString(qr.qr_string),
    qr_handle: firstString(qr.handle),
    raw_provider_state: firstString(provider.state, payload?.state)
  };
}

(async () => {
  const args = parseArgs(process.argv.slice(2));
  const request = {
    currency: args.currency,
    provider_type: args.provider_type,
    payment_request_id: args.payment_request_id,
    country: args.country
  };
  const paymentRequest = await coinsendaPublicPost('paymentRequests/get-payment-request-details-public', {
    payment_request_id: args.payment_request_id
  });
  const raw = await coinsendaPublicPost('paymentRequests/create-deposit-provider-for-payment-request', request);
  const instructions = extractInstructions(raw);
  if (!instructions.amount_cop_text) {
    instructions.amount_cop_text = firstString(paymentRequest?.amount, paymentRequest?.paymentRequest?.amount);
  }
  const text = instructions.breb_alias && instructions.amount_cop_text
    ? `Envia ${instructions.amount_cop_text} COP a ${instructions.breb_alias}`
    : '';
  console.log(JSON.stringify({
    mode: 'coinsenda_public_provider',
    payment_request_id: args.payment_request_id,
    clickText: 'Bre-B',
    provider_endpoint: 'paymentRequests/create-deposit-provider-for-payment-request',
    provider_request: request,
    payment_request: paymentRequest,
    provider_response: raw,
    instructions,
    after: { text },
    events: []
  }, null, 2));
})().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
