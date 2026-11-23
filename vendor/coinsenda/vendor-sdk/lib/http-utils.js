'use strict';

/**
 * HTTP Utils - Utilidades para manejo de respuestas HTTP
 * 
 * CoinsendaClientV2 devuelve respuestas puras del servidor.
 * Estas utilidades ayudan a interpretar los códigos de estado.
 */

/**
 * Verifica si un código de estado HTTP indica éxito (2xx)
 * @param {number} status - Código de estado HTTP
 * @returns {boolean}
 */
function isHttpSuccess(status) {
  return status >= 200 && status < 300;
}

/**
 * Verifica si un código de estado HTTP indica redirect (3xx)
 * @param {number} status - Código de estado HTTP
 * @returns {boolean}
 */
function isHttpRedirect(status) {
  return status >= 300 && status < 400;
}

/**
 * Verifica si un código de estado HTTP indica error del cliente (4xx)
 * @param {number} status - Código de estado HTTP
 * @returns {boolean}
 */
function isHttpClientError(status) {
  return status >= 400 && status < 500;
}

/**
 * Verifica si un código de estado HTTP indica error del servidor (5xx)
 * @param {number} status - Código de estado HTTP
 * @returns {boolean}
 */
function isHttpServerError(status) {
  return status >= 500 && status < 600;
}

module.exports = {
  isHttpSuccess,
  isHttpRedirect,
  isHttpClientError,
  isHttpServerError
};
