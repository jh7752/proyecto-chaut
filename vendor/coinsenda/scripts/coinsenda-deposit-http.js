'use strict';

const DEFAULT_COUNTRY = 'international';

function serviceOrigin() {
  const environment = process.env.COINSENDA_ENV || 'prod';
  const domain = environment === 'prod' || environment === 'production'
    ? 'coinsenda.com'
    : environment === 'staging'
      ? 'bitsenda.com'
      : environment;
  return `https://deposit.${domain}/api`;
}

async function parseResponse(response) {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(`coinsenda_deposit_${response.status}:${JSON.stringify(payload)}`);
  }
  return payload?.data ?? payload;
}

async function depositRequest(pathname, { method = 'GET', jwt, data, query = {}, timeoutMs = 30000 } = {}) {
  const url = new URL(`${serviceOrigin()}${pathname}`);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  const headers = {
    Accept: 'application/json',
    'User-Agent': 'Chaut Payments/1.0'
  };
  if (jwt) headers.Authorization = `Bearer ${jwt}`;
  const options = {
    method,
    headers,
    signal: AbortSignal.timeout(timeoutMs)
  };
  if (data !== undefined) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify({ data: { country: DEFAULT_COUNTRY, ...data } });
  }
  return parseResponse(await fetch(url, options));
}

function rowsFromResponse(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.rows)) return payload.rows;
  return [];
}

async function getPaymentRequests(jwt, userId, filter) {
  const payload = await depositRequest(`/users/${encodeURIComponent(userId)}/paymentRequests`, {
    jwt,
    query: {
      country: DEFAULT_COUNTRY,
      filter: JSON.stringify(filter)
    }
  });
  return rowsFromResponse(payload);
}

async function createPaymentRequest(jwt, data) {
  return depositRequest('/paymentRequests/add-new-payment-request', {
    method: 'POST',
    jwt,
    data
  });
}

module.exports = {
  createPaymentRequest,
  depositRequest,
  getPaymentRequests,
  rowsFromResponse,
  serviceOrigin
};
