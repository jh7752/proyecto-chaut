#!/usr/bin/env node
'use strict';

async function main() {
  const response = await fetch('https://swap.coinsenda.com/api/pairs/get-all-pairs-for-public', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      Origin: 'https://app.coinsenda.com',
      Referer: 'https://app.coinsenda.com/',
      'User-Agent': 'Chaut Payments/1.0'
    },
    body: JSON.stringify({ data: {} }),
    signal: AbortSignal.timeout(20000)
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(`coinsenda_pairs_${response.status}:${JSON.stringify(payload)}`);
  }
  const pairs = payload?.data || payload;
  if (!Array.isArray(pairs)) {
    throw new Error('Coinsenda pairs response is not an array');
  }
  const pair = pairs.find((item) => item.primary_currency === 'usdt' && item.secondary_currency === 'cop');
  if (!pair) {
    throw new Error('USDT/COP pair not found');
  }
  console.log(JSON.stringify(pair));
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
