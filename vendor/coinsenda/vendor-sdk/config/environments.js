'use strict';

/**
 * Environment configuration for Coinsenda SDK.
 *
 * No URLs are hardcoded here. The SDK derives service URLs from a base domain:
 *   - Remote: https://{subdomain}.{domain}/api
 *   - Local:  http://localhost:{port}/api  (ports from environments.local.js)
 *
 * Usage:
 *   buildServiceUrls('coinsenda.com')   → production URLs
 *   buildServiceUrls('bitsenda.com')    → staging URLs
 *   buildServiceUrls('localhost')       → local dev URLs (requires environments.local.js)
 *   buildServiceUrls('localhost', { ports: { auth: 4000 } })  → local with override
 */

const ALIASES = {
  prod: 'coinsenda.com',
  production: 'coinsenda.com',
  staging: 'bitsenda.com'
};

const SUBDOMAIN_MAP = {
  transaction: 'tx',
  farming: 'farm'
};

const PATH_MAP = {
  auth: '/auth'
};

const SERVICES = [
  'auth', 'transaction', 'identity', 'info', 'notification',
  'crypto', 'withdraw', 'deposit', 'account', 'swap',
  'billing', 'farming', 'marketplace'
];

/**
 * Load local port configuration from environments.local.js.
 * This file is NOT published to npm (excluded via .npmignore).
 *
 * @param {Object} [port_overrides] - Optional port overrides
 * @returns {Object} Port map { auth: 3000, deposit: 4006, ... }
 * @throws {Error} If environments.local.js is not found
 */
function loadLocalPorts(port_overrides = {}) {
  let local_config;
  try {
    local_config = require('./environments.local');
  } catch (e) {
    throw new Error(
      'Local environment requires config/environments.local.js. '
      + 'Copy environments.local.example.js to environments.local.js and adjust ports if needed.'
    );
  }
  return { ...local_config.ports, ...port_overrides };
}

/**
 * Build service URLs from a base domain.
 *
 * @param {string} domain - Base domain ('coinsenda.com', 'bitsenda.com', 'localhost')
 * @param {Object} [opts] - Options
 * @param {Object} [opts.ports] - Port overrides for localhost
 * @returns {Object} Map of service name → base URL
 */
function buildServiceUrls(domain, opts = {}) {
  let is_local = domain === 'localhost' || domain.startsWith('localhost:');
  let ports = is_local ? loadLocalPorts(opts.ports) : null;

  let services = {};

  for (let service of SERVICES) {
    let path = PATH_MAP[service] || '/api';

    if (is_local) {
      let port = ports[service];
      if (!port) {
        throw new Error(`No port configured for service "${service}" in environments.local.js`);
      }
      services[service] = `http://localhost:${port}${path}`;
    } else {
      let subdomain = SUBDOMAIN_MAP[service] || service;
      services[service] = `https://${subdomain}.${domain}${path}`;
    }
  }

  return services;
}

/**
 * Backward-compatible: resolve an environment name to service URLs.
 * 'local' loads from environments.local.js.
 * Any other name is treated as a domain.
 *
 * @param {string} env_or_domain - Environment name or domain
 * @param {Object} [opts] - Options (passed to buildServiceUrls)
 * @returns {{ name: string, domain: string, services: Object }}
 */
function getEnvironment(env_or_domain, opts = {}) {
  let resolved = ALIASES[env_or_domain] || env_or_domain;

  if (resolved === 'local') {
    return {
      name: 'Local Development',
      domain: 'localhost',
      services: buildServiceUrls('localhost', opts)
    };
  }

  return {
    name: env_or_domain,
    domain: resolved,
    services: buildServiceUrls(resolved, opts)
  };
}

/**
 * Check if an environment/domain value is usable.
 *
 * @param {string} env - Environment name or domain
 * @returns {boolean}
 */
function isValidEnvironment(env) {
  if (env === 'local') return true;
  if (ALIASES[env]) return true;
  if (typeof env === 'string' && env.includes('.')) return true;
  return false;
}

/**
 * List well-known environment names.
 *
 * @returns {string[]}
 */
function listEnvironments() {
  return ['local', ...Object.keys(ALIASES)];
}

module.exports = {
  ALIASES,
  SERVICES,
  SUBDOMAIN_MAP,
  PATH_MAP,
  buildServiceUrls,
  getEnvironment,
  isValidEnvironment,
  listEnvironments
};
