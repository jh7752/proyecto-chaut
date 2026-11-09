'use strict';

require('./load-env');

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { createPaymentRequest, getPaymentRequests } = require('./coinsenda-deposit-http');

function parseArgs(argv) {
  const args = {
    amount: null,
    currency: 'cop',
    external_id: null,
    expiration: 60,
    client_id: null,
    ledger: path.join(__dirname, '..', 'data', 'payment-requests.jsonl')
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2).replace(/-/g, '_');
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      args[key] = true;
    } else {
      args[key] = next;
      i += 1;
    }
  }

  if (!args.amount) {
    throw new Error('Uso: npm run payment-request:create -- --amount 10 [--currency usdt] [--external-id id] [--expiration 60] [--client-id cliente]');
  }

  args.expiration = Number(args.expiration);
  if (!Number.isFinite(args.expiration) || args.expiration <= 0) {
    throw new Error('--expiration debe ser un numero positivo de minutos.');
  }

  if (!args.external_id) {
    const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
    args.external_id = `xaut-${args.client_id || 'test'}-${stamp}`;
  }

  return args;
}

function userIdFromJwt(jwt) {
  const payload = JSON.parse(Buffer.from(jwt.split('.')[1], 'base64').toString());
  const userId = payload.usr || payload.userId || payload.id || payload.sub;
  if (!userId) throw new Error('JWT sin userId en payload (usr/userId/id/sub).');
  return String(userId);
}

function runAuthScript() {
  const authScript = path.join(__dirname, 'auth-jwt-from-private-key.js');
  return execFileSync(process.execPath, [authScript], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit']
  }).trim();
}

function appendLedger(filePath, event) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.appendFileSync(filePath, `${JSON.stringify(event)}\n`);
}

function summarize(row) {
  return row && {
    id: row.id,
    state: row.state,
    external_id: row.external_id,
    amount: row.amount,
    currency: row.currency,
    createdAt: row.createdAt || row.created_at
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const jwt = runAuthScript();
  if (!jwt) throw new Error('El script de auth no devolvio JWT.');

  const userId = userIdFromJwt(jwt);
  const payload = {
    userId,
    amount: String(args.amount),
    currency: String(args.currency).toLowerCase(),
    expiration: args.expiration,
    external_id: args.external_id
  };

  let existing = [];
  try {
    existing = await getPaymentRequests(jwt, userId, { where: { external_id: args.external_id } });
  } catch (err) {
    console.error(JSON.stringify({ event: 'payment_request.lookup_failed', message: String(err?.message || err) }));
  }
  const reusable = existing.find((row) => !['expired', 'cancelled', 'canceled', 'failed', 'rejected'].includes(String(row?.state || '').toLowerCase()));
  const body = reusable || await createPaymentRequest(jwt, payload);
  const paymentRequestId = body?.id;
  if (!paymentRequestId) {
    throw new Error(`Respuesta sin id de PaymentRequest: ${JSON.stringify(body)}`);
  }

  let byId = reusable ? [reusable] : [];
  let byExternal = existing;
  try {
    [byId, byExternal] = await Promise.all([
      getPaymentRequests(jwt, userId, { where: { id: paymentRequestId } }),
      getPaymentRequests(jwt, userId, { where: { external_id: args.external_id } })
    ]);
  } catch (err) {
    console.error(JSON.stringify({ event: 'payment_request.verification_failed', payment_request_id: paymentRequestId, message: String(err?.message || err) }));
  }
  const appOrigin = (process.env.COINSENDA_APP_ORIGIN || 'https://app.coinsenda.com').replace(/\/$/, '');
  const url = `${appOrigin}/paymentRequest?paymentRequestId=${encodeURIComponent(String(paymentRequestId))}`;
  const payUrl = `${appOrigin}/paymentRequest/${encodeURIComponent(String(paymentRequestId))}`;

  const record = {
    event_type: reusable ? 'payment_request_reused' : 'payment_request_created',
    source: 'coinsenda_api',
    created_at: new Date().toISOString(),
    external_id: args.external_id,
    client_id: args.client_id || null,
    payment_request_id: paymentRequestId,
    amount: String(args.amount),
    currency: payload.currency,
    expiration_minutes: args.expiration,
    status: summarize(byId[0])?.state || body?.state || 'created',
    url,
    pay_url: payUrl,
    verification: {
      by_id_count: byId.length,
      by_external_count: byExternal.length,
      by_id: byId.map(summarize),
      by_external: byExternal.map(summarize)
    }
  };

  appendLedger(args.ledger, record);
  console.log(JSON.stringify(record, null, 2));
}

main().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
