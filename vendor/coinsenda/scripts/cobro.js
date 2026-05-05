'use strict';

require('./load-env');

/**
 * Cobro vía @coinsenda/sdk (sin client.request ni HTTP crudo):
 *   - deposit.paymentRequest.addNewPaymentRequest
 *   - deposit.user.__get__paymentRequests(filter) — filter = JSON.stringify({ where: ... })
 *
 * Config en `.env` en la raíz del proyecto. Subproceso auth lee el mismo .env.
 */

const { execFileSync } = require('child_process');
const path = require('path');
const { CoinsendaClientV2, isHttpSuccess } = require('@coinsenda/sdk');

// ─── Cobro (editar aquí) ─────────────────────────────────────────────────────
let new_payment_request = {
  amount: '10',
  currency: 'usdt',
  external_id: 'order_id_en_spicy_meet', // idempotencia: debe ser único por orden
  expiration: 60
};

let app_origin = process.env.COINSENDA_APP_ORIGIN || 'https://app.coinsenda.com';

function user_id_from_jwt(jwt) {
  let payload = JSON.parse(Buffer.from(jwt.split('.')[1], 'base64').toString());
  let user_id = payload.usr || payload.userId || payload.id || payload.sub;
  if (!user_id) {
    throw new Error('JWT sin userId en payload (usr/userId/id/sub).');
  }
  return String(user_id);
}

function run_auth_script() {
  let auth_script = path.join(__dirname, 'auth-jwt-from-private-key.js');
  return execFileSync(process.execPath, [auth_script], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit']
  }).trim();
}

/**
 * GET /users/{id}/paymentRequests con filtro LoopBack (@coinsenda/sdk ≥1.2.0: __get__paymentRequests(filter)).
 * @param {Object} client - CoinsendaClientV2 (JWT + userId)
 * @param {Object} filter_obj - ej. { where: { id: '...' } } → se envía como JSON string en query
 */
async function get_user_payment_requests(client, filter_obj) {
  let result = await client.deposit.user.__get__paymentRequests(
    JSON.stringify(filter_obj)
  );

  if (!isHttpSuccess(result.status)) {
    throw new Error(
      `paymentRequests GET falló (${result.status}): ${JSON.stringify(result.data)}`
    );
  }

  let raw = result.data;
  if (Array.isArray(raw)) return raw;
  if (raw && Array.isArray(raw.data)) return raw.data;
  return [];
}

function log_payment_request_rows(label, pr_rows) {
  if (pr_rows.length === 0) {
    console.log(`${label}: sin resultados`);
    return;
  }
  console.log(
    `${label}:`,
    JSON.stringify(
      pr_rows.map((row) => ({ id: row.id, state: row.state, external_id: row.external_id })),
      null,
      2
    )
  );
}

async function main() {
  let jwt = run_auth_script();
  if (!jwt) {
    throw new Error('El script de auth no devolvió JWT.');
  }

  let user_id = user_id_from_jwt(jwt);

  let client = new CoinsendaClientV2();
  client.setJwt(jwt);
  client.setClientId('');
  client.setUserId(user_id);

  let pr_payload = {
    userId: user_id,
    amount: new_payment_request.amount,
    currency: new_payment_request.currency,
    expiration: new_payment_request.expiration
  };
  if (new_payment_request.external_id) {
    pr_payload.external_id = new_payment_request.external_id;
  }

  let result = await client.deposit.paymentRequest.addNewPaymentRequest(pr_payload);

  if (!isHttpSuccess(result.status)) {
    throw new Error(
      `addNewPaymentRequest falló (${result.status}): ${JSON.stringify(result.data)}`
    );
  }

  let body = result.data?.data || result.data;
  let payment_request_id = body && body.id;
  if (!payment_request_id) {
    throw new Error(`Respuesta sin id de PaymentRequest: ${JSON.stringify(body)}`);
  }

  let base = app_origin.replace(/\/$/, '');
  let url = `${base}/paymentRequest?paymentRequestId=${encodeURIComponent(String(payment_request_id))}`;
  console.log(url);

  let by_id = await get_user_payment_requests(client, {
    where: { id: payment_request_id }
  });
  log_payment_request_rows('paymentRequests (filtro where.id)', by_id);

  if (new_payment_request.external_id) {
    let by_external = await get_user_payment_requests(client, {
      where: { external_id: new_payment_request.external_id }
    });
    log_payment_request_rows(
      'paymentRequests (filtro where.external_id)',
      by_external
    );
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
