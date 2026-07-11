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
    body = unwrap(await client.swap.pair.getPairForPublic({
      primary_currency: 'usdt',
      secondary_currency: 'cop'
    }), 'getPairForPublic');
    console.log(JSON.stringify(body, null, 2));
    return;
  }

  if (action === 'self-transfer') {
    const payload = {
      userId,
      currency: 'usdt',
      amount: String(args.amount),
      fromAccountId: args.from_account_id,
      toAccountId: args.to_account_id,
      from_account_id: args.from_account_id,
      to_account_id: args.to_account_id
    };
    body = unwrap(await client.withdraw.withdraw.addNewSelfTransferPublic(payload), 'addNewSelfTransferPublic');
    console.log(JSON.stringify({ id: firstId(body), status: body.state || body.status || 'submitted', amount: args.amount, currency: 'usdt', raw: body }, null, 2));
    return;
  }

  if (action === 'swap') {
    const payload = {
      userId,
      primary_currency: 'usdt',
      secondary_currency: 'cop',
      from_currency: 'usdt',
      to_currency: 'cop',
      amount: String(args.amount),
      primary_amount: String(args.amount),
      fromAccountId: args.from_account_id,
      toAccountId: args.to_account_id,
      from_account_id: args.from_account_id,
      to_account_id: args.to_account_id
    };
    body = unwrap(await client.swap.swap.addNewSwapPublic(payload), 'addNewSwapPublic');
    const copReceived = pickNumber(body, ['secondary_amount', 'to_amount', 'amount_received', 'received_amount', 'cop_received']);
    const sellPrice = pickNumber(body, ['sell_price', 'price', 'rate']);
    console.log(JSON.stringify({ id: firstId(body), status: body.state || body.status || 'submitted', cop_received: copReceived, sell_price: sellPrice, raw: body }, null, 2));
    return;
  }

  if (action === 'breb-withdraw') {
    const resolved = unwrap(await client.withdraw.withdrawAccount.resolveBrebAliasPublic({ alias: args.breb_key }), 'resolveBrebAliasPublic');
    const withdrawAccountId = firstId(resolved) || resolved.withdrawAccountId || resolved.withdraw_account_id;
    const payload = {
      userId,
      currency: 'cop',
      amount: String(args.amount),
      withdrawProvider: 'breb',
      provider: 'breb',
      alias: args.breb_key,
      breb_alias: args.breb_key,
      withdrawAccountId,
      withdraw_account_id: withdrawAccountId,
      fromAccountId: args.from_account_id,
      from_account_id: args.from_account_id
    };
    body = unwrap(await client.withdraw.withdraw.addNewWithdrawPublic(payload), 'addNewWithdrawPublic');
    console.log(JSON.stringify({ id: firstId(body), status: body.state || body.status || 'submitted', amount: args.amount, currency: 'cop', resolved, raw: body }, null, 2));
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
