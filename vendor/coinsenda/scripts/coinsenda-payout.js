'use strict';

require('./load-env');

const { execFileSync } = require('child_process');
const path = require('path');
const { CoinsendaClientV2, isHttpSuccess } = require('@coinsenda/sdk');

function parseArgs(argv) {
  const action = argv[0];
  const args = {};
  for (let i = 1; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2).replace(/-/g, '_');
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) args[key] = true;
    else {
      args[key] = next;
      i += 1;
    }
  }
  return { action, args };
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

function unwrap(result, label) {
  if (!isHttpSuccess(result.status)) {
    throw new Error(`${label} fallo (${result.status}): ${JSON.stringify(result.data)}`);
  }
  return result.data && result.data.data ? result.data.data : result.data;
}

function firstId(payload) {
  if (!payload) return null;
  if (payload.id) return payload.id;
  if (payload.withdraw_id) return payload.withdraw_id;
  if (payload.swap_id) return payload.swap_id;
  if (payload.data && payload.data.id) return payload.data.id;
  return null;
}

function pickNumber(payload, keys) {
  for (const key of keys) {
    const value = payload && payload[key];
    if (value !== undefined && value !== null && value !== '') return Number(value);
  }
  return null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollById(fetcher, id, acceptedStates = ['accepted'], attempts = 8, delayMs = 1500) {
  let current = null;
  for (let index = 0; index < attempts; index += 1) {
    current = await fetcher(id);
    if (current && acceptedStates.includes(current.state || current.status)) return current;
    await sleep(delayMs);
  }
  return current;
}

async function main() {
  const { action, args } = parseArgs(process.argv.slice(2));
  if (!action) throw new Error('Uso: node coinsenda-payout.js <pair|self-transfer|swap|breb-withdraw|withdraw-status> [args]');

  const jwt = runAuthScript();
  if (!jwt) throw new Error('El script de auth no devolvio JWT.');

  const userId = userIdFromJwt(jwt);
  const client = new CoinsendaClientV2({ environment: process.env.COINSENDA_ENV || 'prod' });
  client.setJwt(jwt);
  client.setClientId('');
  client.setUserId(userId);

  let body;
  if (action === 'pair') {
    const pairs = unwrap(await client.swap.pair.getAllPairsForPublic({}), 'getAllPairsForPublic');
    body = pairs.find((pair) => pair.primary_currency === 'usdt' && pair.secondary_currency === 'cop');
    if (!body) throw new Error('USDT/COP pair not found');
    console.log(JSON.stringify(body, null, 2));
    return;
  }

  if (action === 'self-transfer') {
    const payload = {
      account_id: args.from_account_id,
      account_to: args.to_account_id,
      amount: String(args.amount),
      country: 'international'
    };
    body = unwrap(await client.withdraw.withdraw.addNewSelfTransferPublic(payload), 'addNewSelfTransferPublic');
    const withdrawId = firstId(body);
    if (!withdrawId) throw new Error(`Self-transfer response without id: ${JSON.stringify(body)}`);

    const confirmed = unwrap(await client.withdraw.withdraw.addUpdateWithdraw({
      withdraw_id: withdrawId,
      state: 'confirmed',
      country: 'international'
    }), 'addUpdateWithdraw');
    console.log(JSON.stringify({
      id: withdrawId,
      status: confirmed.state || confirmed.status || body.state || 'confirmed',
      amount: args.amount,
      currency: confirmed.currency || body.currency || 'usdt',
      raw: confirmed,
      created: body
    }, null, 2));
    return;
  }

  if (action === 'swap') {
    const pairs = unwrap(await client.swap.pair.getAllPairsForPublic({}), 'getAllPairsForPublic');
    const pair = pairs.find((item) => item.primary_currency === 'usdt' && item.secondary_currency === 'cop');
    if (!pair) throw new Error('USDT/COP pair not found');
    const payload = {
      want_to_spend: String(args.amount),
      pair_id: pair.id,
      account_from: args.from_account_id,
      country: 'international'
    };
    body = unwrap(await client.swap.swap.addNewSwapPublic(payload), 'addNewSwapPublic');
    const swapId = firstId(body);
    const finalSwap = swapId ? await pollById(async (id) => {
      const rows = unwrap(await client.swap.user.__get__swaps(JSON.stringify({ where: { id } })), '__get__swaps');
      return Array.isArray(rows) ? rows[0] : rows;
    }, swapId) : body;
    const result = finalSwap || body;
    const copReceived = pickNumber(result, ['real_bought', 'bought', 'secondary_amount', 'to_amount', 'amount_received', 'received_amount', 'cop_received']);
    const sellPrice = pickNumber(result, ['action_price', 'sell_price', 'price', 'rate']) || pickNumber(pair, ['sell_price']);
    console.log(JSON.stringify({ id: swapId, status: result.state || result.status || body.state || 'submitted', cop_received: copReceived, sell_price: sellPrice, pair, raw: result, created: body }, null, 2));
    return;
  }

  if (action === 'breb-withdraw') {
    const brebKey = String(args.breb_key || '').trim();
    const resolved = unwrap(await client.withdraw.withdrawAccount.resolveBrebAliasPublic({
      alias: brebKey,
      country: 'international'
    }), 'resolveBrebAliasPublic');
    const providers = unwrap(await client.withdraw.withdrawProvider.find(JSON.stringify({
      where: { provider_type: 'breb' },
      limit: 20
    })), 'withdrawProvider.find');
    const brebProvider = providers.find((item) => item.provider_type === 'breb' && item.currency === 'cop');
    if (!brebProvider) throw new Error('Bre-B withdraw provider not found');

    const withdrawAccount = unwrap(await client.withdraw.withdrawAccount.addNewWithdrawAccount({
      country: 'international',
      currency: 'cop',
      provider_type: 'breb',
      internal: false,
      info_needed: {
        label: brebKey,
        account_id: brebKey.replace(/^@/, ''),
        country: 'colombia'
      }
    }), 'addNewWithdrawAccount');
    const withdrawAccountId = firstId(withdrawAccount);
    if (!withdrawAccountId) throw new Error(`Bre-B withdraw account response without id: ${JSON.stringify(withdrawAccount)}`);

    body = unwrap(await client.withdraw.withdraw.addNewWithdrawPublic({
      country: 'international',
      account_id: args.from_account_id,
      amount: String(args.amount),
      withdraw_account_id: withdrawAccountId,
      withdraw_provider_id: brebProvider.id
    }), 'addNewWithdrawPublic');
    const withdrawId = firstId(body);
    if (!withdrawId) throw new Error(`Bre-B withdraw response without id: ${JSON.stringify(body)}`);

    const confirmed = unwrap(await client.withdraw.withdraw.addUpdateWithdraw({
      withdraw_id: withdrawId,
      state: 'confirmed',
      country: 'international'
    }), 'addUpdateWithdraw');
    console.log(JSON.stringify({
      id: withdrawId,
      status: confirmed.state || confirmed.status || body.state || 'confirmed',
      amount: args.amount,
      currency: confirmed.currency || body.currency || 'cop',
      fee: pickNumber(confirmed, ['cost']) || pickNumber(body, ['cost']),
      net_amount: pickNumber(confirmed, ['amount_neto']) || pickNumber(body, ['amount_neto']),
      resolved,
      withdraw_account: withdrawAccount,
      raw: confirmed,
      created: body
    }, null, 2));
    return;
  }

  if (action === 'withdraw-status') {
    const rows = unwrap(await client.withdraw.user.__get__withdraws(JSON.stringify({ where: { id: args.withdraw_id } })), '__get__withdraws');
    const row = Array.isArray(rows) ? rows[0] : rows;
    console.log(JSON.stringify(row || { id: args.withdraw_id, status: 'not_found' }, null, 2));
    return;
  }

  throw new Error(`Accion no soportada: ${action}`);
}

main().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
