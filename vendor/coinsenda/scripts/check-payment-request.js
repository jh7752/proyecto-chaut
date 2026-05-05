'use strict';

require('./load-env');

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { CoinsendaClientV2, isHttpSuccess } = require('@coinsenda/sdk');

function parseArgs(argv) {
  const args = {
    id: null,
    external_id: null,
    ledger: path.join(__dirname, '..', 'data', 'payment-events.jsonl')
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

  if (!args.id && !args.external_id) {
    throw new Error('Uso: npm run payment-request:check -- --external-id xaut-test-... o --id paymentRequestId');
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

async function getPaymentRequests(client, filterObj) {
  const result = await client.deposit.user.__get__paymentRequests(JSON.stringify(filterObj));
  if (!isHttpSuccess(result.status)) {
    throw new Error(`paymentRequests GET fallo (${result.status}): ${JSON.stringify(result.data)}`);
  }

  const raw = result.data;
  if (Array.isArray(raw)) return raw;
  if (raw && Array.isArray(raw.data)) return raw.data;
  return [];
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
    createdAt: row.createdAt || row.created_at,
    updatedAt: row.updatedAt || row.updated_at,
    expiresAt: row.expiresAt || row.expires_at
  };
}

function classifyState(state) {
  const value = String(state || '').toLowerCase();
  if (['accepted', 'paid', 'confirmed', 'completed', 'success', 'approved'].includes(value)) return 'payment_confirmed';
  if (['expired', 'cancelled', 'canceled', 'failed', 'rejected'].includes(value)) return 'payment_terminal_not_paid';
  return 'payment_pending_or_ambiguous';
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const jwt = runAuthScript();
  if (!jwt) throw new Error('El script de auth no devolvio JWT.');

  const userId = userIdFromJwt(jwt);
  const client = new CoinsendaClientV2(process.env.COINSENDA_ENV || 'prod');
  client.setJwt(jwt);
  client.setClientId('');
  client.setUserId(userId);

  const where = args.id ? { id: args.id } : { external_id: args.external_id };
  const rows = await getPaymentRequests(client, { where });
  const summarized = rows.map(summarize);
  const first = summarized[0] || null;
  const eventType = rows.length === 0 ? 'payment_request_not_found' : classifyState(first.state);

  const record = {
    event_type: eventType,
    source: 'coinsenda_api',
    checked_at: new Date().toISOString(),
    query: where,
    count: rows.length,
    payment_request: first,
    all_matches: summarized
  };

  appendLedger(args.ledger, record);
  console.log(JSON.stringify(record, null, 2));

  if (rows.length !== 1) process.exitCode = 2;
}

main().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
