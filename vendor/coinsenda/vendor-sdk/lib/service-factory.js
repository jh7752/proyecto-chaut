'use strict';

/**
 * SERVICE FACTORY
 * 
 * Combines generated methods with custom overrides for special logic.
 * 
 * Usage:
 *   const authService = createService(client, 'auth', {
 *     // Override login to save JWT
 *     login: async (email, password) => {
 *       let result = await client.request('auth', 'POST', '/local', {...});
 *       if (result.success) client.setJwt(result.data.jwt);
 *       return result;
 *     }
 *   });
 */

const generated = require('./generated');

/**
 * Create a service object with generated methods + custom overrides
 * 
 * @param {Object} client - CoinsendaClient instance
 * @param {string} serviceName - Service name (auth, account, etc.)
 * @param {Object} overrides - Custom method implementations
 * @returns {Object} Service object with all methods
 */
function createService(client, serviceName, overrides = {}) {
  let generatedModule = generated[serviceName];
  
  if (!generatedModule) {
    throw new Error(`No generated methods for service: ${serviceName}`);
  }
  
  // Get base methods from generated
  let baseMethods = generatedModule.createMethods(client);
  
  // Add low-level request helpers
  let helpers = {
    get: (endpoint, options) => client.request(serviceName, 'GET', endpoint, null, options),
    post: (endpoint, data, options) => client.request(serviceName, 'POST', endpoint, data, options),
    put: (endpoint, data, options) => client.request(serviceName, 'PUT', endpoint, data, options),
    delete: (endpoint, options) => client.request(serviceName, 'DELETE', endpoint, null, options)
  };
  
  // Combine: helpers + generated + overrides (overrides win)
  return {
    ...helpers,
    ...baseMethods,
    ...overrides
  };
}

/**
 * Create all services for a client
 * 
 * @param {Object} client - CoinsendaClient instance
 * @param {Object} allOverrides - Object with overrides per service
 * @returns {Object} Object with all services
 */
function createAllServices(client, allOverrides = {}) {
  let services = {};
  
  for (let serviceName of Object.keys(generated)) {
    services[serviceName] = createService(
      client, 
      serviceName, 
      allOverrides[serviceName] || {}
    );
  }
  
  return services;
}

module.exports = {
  createService,
  createAllServices
};
