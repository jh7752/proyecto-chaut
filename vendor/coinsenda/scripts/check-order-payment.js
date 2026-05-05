'use strict';

require('./load-env');

const { execFileSync } = require('child_process');
const path = require('path');
const { getOrder, openOrdersDb, updateOrderPayment } = require('./lib/orders-db');

function parseArgs(argv) {
  const args = { external_id: null };

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

  if (!args.external_id) {
    throw new Error('Uso: node scripts/check-order-payment.js --external-id xaut-...');
  }

  return args;
}

function runCheckPaymentRequest(externalId) {
  const script = path.join(__dirname, 'check-payment-request.js');
  const output = execFileSync(process.execPath, [script, '--external-id', externalId], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  });
  return JSON.parse(output);
}

function mapEventToStatus(eventType) {
  if (eventType === 'payment_confirmed') return 'confirmed';
  if (eventType === 'payment_terminal_not_paid') return 'failed';
  if (eventType === 'payment_request_not_found') return 'not_found';
  return 'pending';
}

function validateMatch(order, paymentRequest) {
  if (!paymentRequest) return { ok: false, reason: 'Coinsenda no devolvio PaymentRequest.' };
  if (String(paymentRequest.external_id) !== String(order.external_id)) {
    return { ok: false, reason: 'external_id no coincide.' };
  }
  if (Number(paymentRequest.amount) !== Number(order.amount_cop_gross)) {
    return { ok: false, reason: 'monto COP no coincide.' };
  }
  if (String(paymentRequest.currency || '').toLowerCase() !== 'cop') {
    return { ok: false, reason: 'moneda no es cop.' };
  }
  return { ok: true, reason: 'coincide external_id, monto y moneda.' };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const db = openOrdersDb();
  const order = getOrder(db, args.external_id);
  if (!order) throw new Error(`Orden no encontrada: ${args.external_id}`);

  let check;
  try {
    check = runCheckPaymentRequest(order.external_id);
  } catch (err) {
    const stdout = err.stdout && String(err.stdout).trim();
    if (!stdout) throw err;
    check = JSON.parse(stdout);
  }

  const match = validateMatch(order, check.payment_request);
  const status = match.ok ? mapEventToStatus(check.event_type) : 'ambiguous';
  const updated = updateOrderPayment(db, order.external_id, {
    payment_status: status,
    coinsenda_check: check,
    validation: match
  });

  console.log(JSON.stringify({ order: updated, check, validation: match }, null, 2));
}

try {
  main();
} catch (err) {
  console.error(err.stack || err.message || err);
  process.exit(1);
}
