'use strict';

/**
 * Local development port configuration (TEMPLATE).
 *
 * Copy this file to environments.local.js and adjust ports as needed:
 *   cp environments.local.example.js environments.local.js
 *
 * This file IS published to npm as a reference.
 * environments.local.js is NOT published (excluded via .npmignore).
 */

module.exports = {
  ports: {
    auth: 3000,
    transaction: 3001,
    identity: 3002,
    info: 3010,
    notification: 4002,
    crypto: 4003,
    withdraw: 4005,
    deposit: 4006,
    account: 4007,
    swap: 4008,
    billing: 4015,
    farming: 4016,
    marketplace: 4020
  }
};
