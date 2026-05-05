'use strict';

const fs = require('fs');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');

const DEFAULT_DB_PATH = path.join(__dirname, '..', '..', 'data', 'orders.sqlite');

function openOrdersDb(dbPath = process.env.XAUT_ORDERS_DB || DEFAULT_DB_PATH) {
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec(`
    CREATE TABLE IF NOT EXISTS orders (
      external_id TEXT PRIMARY KEY,
      client_id TEXT NOT NULL,
      amount_cop_gross INTEGER NOT NULL,
      fee_percent REAL NOT NULL,
      fee_cop INTEGER NOT NULL,
      amount_cop_net INTEGER NOT NULL,
      estimated_rate_cop_per_usdt REAL NOT NULL,
      estimated_usdt REAL NOT NULL,
      payment_request_id TEXT,
      payment_url TEXT,
      payment_status TEXT NOT NULL DEFAULT 'draft',
      conversion_status TEXT NOT NULL DEFAULT 'pending',
      final_usdt REAL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      metadata_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS order_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      external_id TEXT NOT NULL,
      event_type TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      FOREIGN KEY (external_id) REFERENCES orders(external_id)
    );
  `);
  return db;
}

function nowIso() {
  return new Date().toISOString();
}

function createExternalId(clientId, date = new Date()) {
  const safeClient = String(clientId || 'telegram')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32) || 'client';
  const stamp = date.toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
  const random = Math.random().toString(36).slice(2, 8);
  return `xaut-${safeClient}-${stamp}-${random}`;
}

function calculateQuote({ amountCopGross, feePercent, rateCopPerUsdt }) {
  const gross = Number(amountCopGross);
  const fee = Number(feePercent);
  const rate = Number(rateCopPerUsdt);

  if (!Number.isInteger(gross) || gross <= 0) {
    throw new Error('amountCopGross debe ser un entero positivo en COP.');
  }
  if (!Number.isFinite(fee) || fee < 0 || fee > 100) {
    throw new Error('feePercent debe ser un numero entre 0 y 100.');
  }
  if (!Number.isFinite(rate) || rate <= 0) {
    throw new Error('rateCopPerUsdt debe ser un numero positivo.');
  }

  const feeCop = Math.round(gross * (fee / 100));
  const netCop = gross - feeCop;
  const estimatedUsdt = Number((netCop / rate).toFixed(6));

  return {
    amount_cop_gross: gross,
    fee_percent: fee,
    fee_cop: feeCop,
    amount_cop_net: netCop,
    estimated_rate_cop_per_usdt: rate,
    estimated_usdt: estimatedUsdt
  };
}

function insertOrder(db, order) {
  const timestamp = nowIso();
  const payload = {
    ...order,
    payment_status: order.payment_status || 'draft',
    conversion_status: order.conversion_status || 'pending',
    created_at: order.created_at || timestamp,
    updated_at: order.updated_at || timestamp,
    metadata_json: JSON.stringify(order.metadata || {})
  };

  db.prepare(`
    INSERT INTO orders (
      external_id, client_id, amount_cop_gross, fee_percent, fee_cop, amount_cop_net,
      estimated_rate_cop_per_usdt, estimated_usdt, payment_request_id, payment_url,
      payment_status, conversion_status, final_usdt, created_at, updated_at, metadata_json
    ) VALUES (
      :external_id, :client_id, :amount_cop_gross, :fee_percent, :fee_cop, :amount_cop_net,
      :estimated_rate_cop_per_usdt, :estimated_usdt, :payment_request_id, :payment_url,
      :payment_status, :conversion_status, :final_usdt, :created_at, :updated_at, :metadata_json
    )
  `).run({
    external_id: payload.external_id,
    client_id: payload.client_id,
    amount_cop_gross: payload.amount_cop_gross,
    fee_percent: payload.fee_percent,
    fee_cop: payload.fee_cop,
    amount_cop_net: payload.amount_cop_net,
    estimated_rate_cop_per_usdt: payload.estimated_rate_cop_per_usdt,
    estimated_usdt: payload.estimated_usdt,
    payment_request_id: payload.payment_request_id || null,
    payment_url: payload.payment_url || null,
    payment_status: payload.payment_status,
    conversion_status: payload.conversion_status,
    final_usdt: payload.final_usdt || null,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
    metadata_json: payload.metadata_json
  });

  appendOrderEvent(db, payload.external_id, 'order_created', payload);
  return getOrder(db, payload.external_id);
}

function getOrder(db, externalId) {
  const row = db.prepare('SELECT * FROM orders WHERE external_id = ?').get(externalId);
  if (!row) return null;
  return normalizeOrder(row);
}

function updateOrderPayment(db, externalId, patch) {
  const current = getOrder(db, externalId);
  if (!current) throw new Error(`Orden no encontrada: ${externalId}`);

  const next = {
    payment_request_id: patch.payment_request_id ?? current.payment_request_id,
    payment_url: patch.payment_url ?? current.payment_url,
    payment_status: patch.payment_status ?? current.payment_status,
    updated_at: nowIso()
  };

  db.prepare(`
    UPDATE orders
    SET payment_request_id = :payment_request_id,
        payment_url = :payment_url,
        payment_status = :payment_status,
        updated_at = :updated_at
    WHERE external_id = :external_id
  `).run({ ...next, external_id: externalId });

  appendOrderEvent(db, externalId, 'order_payment_updated', patch);
  return getOrder(db, externalId);
}

function appendOrderEvent(db, externalId, eventType, payload = {}) {
  db.prepare(`
    INSERT INTO order_events (external_id, event_type, payload_json, created_at)
    VALUES (?, ?, ?, ?)
  `).run(externalId, eventType, JSON.stringify(payload), nowIso());
}

function normalizeOrder(row) {
  return {
    ...row,
    metadata: safeJson(row.metadata_json),
    metadata_json: undefined
  };
}

function safeJson(value) {
  try {
    return JSON.parse(value || '{}');
  } catch (_) {
    return {};
  }
}

module.exports = {
  calculateQuote,
  createExternalId,
  getOrder,
  insertOrder,
  openOrdersDb,
  updateOrderPayment
};
