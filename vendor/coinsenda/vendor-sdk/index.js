'use strict';

const { CoinsendaClientV2 } = require('./lib/client');
const { isHttpSuccess, isHttpRedirect, isHttpClientError, isHttpServerError } = require('./lib/http-utils');
const { getEnvironment, buildServiceUrls, isValidEnvironment, listEnvironments } = require('./config/environments');
const storage = require('./lib/storage');
const { createService, createAllServices } = require('./lib/service-factory');

module.exports = {
  // Clients
  CoinsendaClient: CoinsendaClientV2,
  CoinsendaClientV2,

  // HTTP utils
  isHttpSuccess,
  isHttpRedirect,
  isHttpClientError,
  isHttpServerError,

  // Environment config
  getEnvironment,
  buildServiceUrls,
  isValidEnvironment,
  listEnvironments,
  storage,

  // Service factory
  createService,
  createAllServices
};
