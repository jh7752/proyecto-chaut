#!/usr/bin/env node
const { CoinsendaClientV2 } = require('@coinsenda/sdk');

async function main() {
  const client = new CoinsendaClientV2({ environment: process.env.COINSENDA_ENV || 'prod' });
  const result = await client.swap.pair.getAllPairsForPublic({});
  const pairs = result?.data?.data || result?.data || result;
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
