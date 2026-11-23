'use strict';

/**
 * CoinsendaClient V2 - Using generated methods
 *
 * This client uses auto-generated methods from api-yaml definitions,
 * with custom overrides only where special logic is needed.
 */

const axios = require('axios');
const { getEnvironment, buildServiceUrls } = require('../config/environments');
const storage = require('./storage');
const { createService } = require('./service-factory');

class CoinsendaClientV2 {
  constructor(options = {}) {
    if (options.domain) {
      this._environment = options.domain;
      this._envConfig = {
        name: options.domain,
        domain: options.domain,
        services: buildServiceUrls(options.domain, { ports: options.ports })
      };
    } else {
      this._environment = options.environment || storage.getActiveEnvironment();
      this._envConfig = getEnvironment(this._environment);
    }

    if (!this._envConfig) {
      throw new Error(`Invalid environment: ${this._environment}`);
    }

    this._jwt = options.jwt || null;
    this._refreshToken = options.refreshToken || null;
    this._clientId = options.clientId || null;
    this._userId = options.userId || null;
    this._profileId = options.profileId || null;
    this._country = options.country || 'international';
    this._onTokenRefresh = options.onTokenRefresh || null;
    this._clients = {};

    // Initialize services with generated methods + overrides
    this._initServices();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // CONFIGURACIÓN
  // ═══════════════════════════════════════════════════════════════════════════

  setJwt(jwt) {
    this._jwt = jwt;
    // Extraer userId del JWT payload
    if (jwt) {
      try {
        let payload = JSON.parse(Buffer.from(jwt.split('.')[1], 'base64').toString());
        this._userId = payload.userId || payload.usr || payload.id || payload.sub;
      } catch (e) {
        // Si falla el decode, no pasa nada
      }
    }
  }
  setRefreshToken(refreshToken) { this._refreshToken = refreshToken; }
  setClientId(clientId) { this._clientId = clientId; }
  setUserId(userId) { this._userId = userId; }
  setProfileId(profileId) { this._profileId = profileId; }
  setCountry(country) { this._country = country; }

  getJwt() { return this._jwt; }
  getRefreshToken() { return this._refreshToken; }
  getClientId() { return this._clientId; }
  getUserId() { return this._userId; }
  getProfileId() { return this._profileId; }
  getCountry() { return this._country; }
  getEnvironment() { return this._environment; }
  getServiceUrl(service) { return this._envConfig.services[service] || null; }

  // ═══════════════════════════════════════════════════════════════════════════
  // HTTP REQUEST (core method)
  // ═══════════════════════════════════════════════════════════════════════════

  async request(service, method, endpoint, data = null, options = {}) {
    let baseUrl = this._envConfig.services[service];
    if (!baseUrl) {
      throw new Error(`Servicio no configurado: ${service}`);
    }

    // Replace path parameters
    let resolvedEndpoint = endpoint;
    if (endpoint.includes('{id}') && this._userId) {
      resolvedEndpoint = endpoint.replace('{id}', this._userId);
    }

    let url = `${baseUrl}${resolvedEndpoint}`;
    let headers = this._buildHeaders(options);
    let payload = options.rawPayload ? data : this._wrapPayload(data);

    // GET requests: include country in query only for authenticated requests (backend may require it)
    let getParams = method === 'GET'
      ? (this._jwt && !options.skipAuth
          ? { country: this._country, ...(data && typeof data === 'object' ? data : {}) }
          : data)
      : undefined;

    try {
      let axiosConfig = {
        method,
        url,
        headers,
        data: ['POST', 'PUT', 'PATCH'].includes(method) ? payload : undefined,
        params: getParams,
        timeout: options.timeout || 30000,
        validateStatus: () => true
      };

      // Permitir control de redirects (ej: maxRedirects: 0 para capturar 302)
      if (options.maxRedirects !== undefined) {
        axiosConfig.maxRedirects = options.maxRedirects;
      }

      let response = await axios(axiosConfig);
      return this._processResponse(response);
    } catch (error) {
      return {
        status: 0,
        data: null,
        headers: {},
        error: error.message
      };
    }
  }

  _buildHeaders(options = {}) {
    let headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    };

    if (this._jwt && !options.skipAuth) {
      headers['Authorization'] = `Bearer ${this._jwt}`;
    }
    if (this._clientId) {
      headers['client_id'] = this._clientId;
    }

    return headers;
  }

  _wrapPayload(data) {
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data);
      } catch (_) {
        data = {};
      }
    }
    if (!data || typeof data !== 'object') return { data: { country: this._country } };

    let inner = {
      country: this._country,
      recaptcha_response: 'BYPASS_RECAPTCHA_DEV',
      ...data
    };

    if (typeof inner.data === 'string') {
      try {
        let parsed = JSON.parse(inner.data);
        if (parsed !== null && typeof parsed === 'object') {
          Object.assign(inner, parsed);
          delete inner.data;
        }
      } catch (_) {
        delete inner.data;
      }
    }

    return { data: inner };
  }

  _processResponse(response) {
    // Respuesta pura del servidor, sin propiedades calculadas
    return {
      status: response.status,
      data: response.data,
      headers: response.headers
    };
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SERVICES (solo métodos generados - sin overrides)
  // La lógica de negocio está en flows/
  // ═══════════════════════════════════════════════════════════════════════════

  _initServices() {
    // Todos los servicios usan solo métodos generados
    this.auth = createService(this, 'auth');
    this.transaction = createService(this, 'transaction');
    this.account = createService(this, 'account');
    this.withdraw = createService(this, 'withdraw');
    this.deposit = createService(this, 'deposit');
    this.swap = createService(this, 'swap');
    this.identity = createService(this, 'identity');
    this.notification = createService(this, 'notification');
    this.info = createService(this, 'info');
    this.farming = createService(this, 'farming');
    this.marketplace = createService(this, 'marketplace');
    this.crypto = createService(this, 'crypto');
  }
}

module.exports = { CoinsendaClientV2 };
