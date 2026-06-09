'use strict';

require('./load-env');

const {
  calculateQuote,
  createExternalId,
  insertOrder,
  openOrdersDb
} = require('./lib/orders-db');

function parseArgs(argv) {
  const args = {
    amount: null,
    client_id: 'telegram-demo',
    fee_percent: process.env.XAUT_FEE_PERCENT || '0',
    rate: process.env.XAUT_COP_PER_USDT || null,
    external_id: null
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
    throw new Error('Uso: node scripts/create-order.js --amount 100000 --client-id telegram-123 --rate 4000');
  }
  if (!args.rate) {
    throw new Error('Falta --rate o variable XAUT_COP_PER_USDT para estimar USDT.');
  }

  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const db = openOrdersDb();
  const quote = calculateQuote({
    amountCopGross: Number(args.amount),
    feePercent: Number(args.fee_percent),
    rateCopPerUsdt: Number(args.rate)
  });

  const externalId = args.external_id || createExternalId(args.client_id);
  const order = insertOrder(db, {
    external_id: externalId,
    client_id: args.client_id,
    ...quote,
    payment_status: 'draft',
    conversion_status: 'pending',
    metadata: {
      interface: 'cli',
      currency: 'cop'
    }
  });

  console.log(JSON.stringify(order, null, 2));
}

try {
  main();
} catch (err) {
  console.error(err.stack || err.message || err);
  process.exit(1);
}
