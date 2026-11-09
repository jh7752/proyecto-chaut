'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  createPaymentRequest,
  getPaymentRequests
} = require('../scripts/coinsenda-deposit-http');

test('createPaymentRequest sends the clean Coinsenda schema', async () => {
  const originalFetch = global.fetch;
  let captured;
  global.fetch = async (url, options) => {
    captured = { url: String(url), options };
    return new Response(JSON.stringify({ data: { id: 'pr-test', state: 'pending' } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
  try {
    const result = await createPaymentRequest('jwt-test', {
      userId: 'usr-test',
      amount: '1.234567',
      currency: 'usdt',
      expiration: 45,
      external_id: 'chaut-test'
    });
    assert.equal(result.id, 'pr-test');
    assert.equal(captured.options.method, 'POST');
    assert.equal(captured.options.headers.Authorization, 'Bearer jwt-test');
    assert.deepEqual(JSON.parse(captured.options.body), {
      data: {
        country: 'international',
        userId: 'usr-test',
        amount: '1.234567',
        currency: 'usdt',
        expiration: 45,
        external_id: 'chaut-test'
      }
    });
    assert.equal(captured.options.body.includes('recaptcha_response'), false);
  } finally {
    global.fetch = originalFetch;
  }
});

test('getPaymentRequests uses authenticated GET with serialized filter', async () => {
  const originalFetch = global.fetch;
  let captured;
  global.fetch = async (url, options) => {
    captured = { url: new URL(url), options };
    return new Response(JSON.stringify({ data: [{ id: 'pr-test' }] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
  try {
    const rows = await getPaymentRequests('jwt-test', 'usr-test', { where: { external_id: 'chaut-test' } });
    assert.deepEqual(rows, [{ id: 'pr-test' }]);
    assert.equal(captured.options.method, 'GET');
    assert.equal(captured.options.headers.Authorization, 'Bearer jwt-test');
    assert.equal(captured.url.searchParams.get('country'), 'international');
    assert.deepEqual(JSON.parse(captured.url.searchParams.get('filter')), { where: { external_id: 'chaut-test' } });
  } finally {
    global.fetch = originalFetch;
  }
});
