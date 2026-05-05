'use strict';

require('./load-env');

const { execFileSync } = require('child_process');
const path = require('path');
const { getOrder, openOrdersDb, updateOrderPayment } = require('./lib/orders-db');

function parseArgs(argv) {
  const args = {
    external_id: null,
    expiration: 60
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

  if (!args.external_id) {
    throw new Error('Uso: node scripts/create-order-payment-request.js --external-id xaut-... [--expiration 60]');
  }

  return args;
}

function runCreatePaymentRequest(order, expiration) {
  const script = path.join(__dirname, 'create-payment-request.js');
  const output = execFileSync(process.execPath, [
    script,
    '--amount', String(order.amount_cop_gross),
    '--currency', 'cop',
    '--external-id', order.external_id,
    '--expiration', String(expiration),
    '--client-id', order.client_id
  ], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit']
  });
  return JSON.parse(output);
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const db = openOrdersDb();
  const order = getOrder(db, args.external_id);
  if (!order) throw new Error(`Orden no encontrada: ${args.external_id}`);
  if (order.payment_request_id) {
    throw new Error(`La orden ya tiene PaymentRequest: ${order.payment_request_id}`);
  }

  const payment = runCreatePaymentRequest(order, args.expiration);
  const updated = updateOrderPayment(db, order.external_id, {
    payment_request_id: payment.payment_request_id,
    payment_url: payment.url,
    payment_status: payment.status || 'pending',
    coinsenda_record: payment
  });

  console.log(JSON.stringify({ order: updated, payment }, null, 2));
}

try {
  main();
} catch (err) {
  console.error(err.stack || err.message || err);
  process.exit(1);
}
