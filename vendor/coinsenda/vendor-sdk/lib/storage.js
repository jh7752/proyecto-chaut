'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

/**
 * Storage - Manejo de almacenamiento local para sesiones y configuración.
 *
 * Almacena datos en ~/.coinsenda-cli/
 * - config.json: Configuración global (entorno activo, etc.)
 * - sessions/: Sesiones guardadas por entorno
 */

const CONFIG_DIR = path.join(os.homedir(), '.coinsenda-cli');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json');
const SESSIONS_DIR = path.join(CONFIG_DIR, 'sessions');

/**
 * Asegura que los directorios de configuración existan
 */
function ensureConfigDirs() {
  if (!fs.existsSync(CONFIG_DIR)) {
    fs.mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 });
  }
  if (!fs.existsSync(SESSIONS_DIR)) {
    fs.mkdirSync(SESSIONS_DIR, { recursive: true, mode: 0o700 });
  }
}

/**
 * Lee la configuración global
 * @returns {Object}
 */
function readConfig() {
  ensureConfigDirs();
  try {
    if (fs.existsSync(CONFIG_FILE)) {
      let data = fs.readFileSync(CONFIG_FILE, 'utf8');
      return JSON.parse(data);
    }
  } catch (error) {
    console.error('Error leyendo config:', error.message);
  }
  return { environment: 'local', defaultCountry: 'international' };
}

/**
 * Escribe la configuración global
 * @param {Object} config
 */
function writeConfig(config) {
  ensureConfigDirs();
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), { mode: 0o600 });
}

/**
 * Obtiene el entorno activo
 * @returns {string}
 */
function getActiveEnvironment() {
  let config = readConfig();
  return config.environment || 'local';
}

/**
 * Establece el entorno activo
 * @param {string} env
 */
function setActiveEnvironment(env) {
  let config = readConfig();
  config.environment = env;
  writeConfig(config);
}

/**
 * Genera un ID único para sesión basado en email/phone
 * @param {string} identifier - Email o teléfono
 * @param {string} env - Entorno
 * @returns {string}
 */
function generateSessionId(identifier, env) {
  let hash = crypto.createHash('sha256').update(`${identifier}:${env}`).digest('hex');
  return hash.substring(0, 16);
}

/**
 * Obtiene la ruta del archivo de sesión
 * @param {string} sessionId
 * @returns {string}
 */
function getSessionPath(sessionId) {
  return path.join(SESSIONS_DIR, `${sessionId}.json`);
}

/**
 * Guarda una sesión
 * @param {Object} session - Datos de la sesión
 * @returns {string} Session ID
 */
function saveSession(session) {
  ensureConfigDirs();
  let identifier = session.email || session.phoneNumber || 'unknown';
  let env = session.environment || 'local';
  let session_id = generateSessionId(identifier, env);

  let session_data = {
    ...session,
    sessionId: session_id,
    savedAt: new Date().toISOString()
  };

  let session_path = getSessionPath(session_id);
  fs.writeFileSync(session_path, JSON.stringify(session_data, null, 2), { mode: 0o600 });

  // Actualizar la sesión activa en config
  let config = readConfig();
  config.activeSession = session_id;
  writeConfig(config);

  return session_id;
}

/**
 * Guarda el par de llaves API en una sesión
 * @param {string} sessionId - ID de la sesión
 * @param {Object} keyPair - Par de llaves { publicKey, privateKey }
 */
function saveApiKeyPair(sessionId, keyPair) {
  let session = loadSession(sessionId);
  if (!session) {
    throw new Error('Sesión no encontrada');
  }

  session.apiKeyPair = {
    publicKey: keyPair.publicKey,
    privateKey: keyPair.privateKey,
    createdAt: new Date().toISOString()
  };
  session.hasApiKey = true;

  let session_path = getSessionPath(sessionId);
  fs.writeFileSync(session_path, JSON.stringify(session, null, 2), { mode: 0o600 });
}

/**
 * Obtiene el par de llaves API de una sesión
 * @param {string} sessionId - ID de la sesión
 * @returns {Object|null} Par de llaves o null
 */
function getApiKeyPair(sessionId) {
  let session = loadSession(sessionId);
  return session?.apiKeyPair || null;
}

/**
 * Lista las sesiones que tienen API key configurada para un entorno
 * @param {string} environment - Nombre del entorno
 * @returns {Array<Object>} Sesiones con API key
 */
function listApiKeySessions(environment) {
  let all_sessions = listSessions();
  return all_sessions.filter(s =>
    s.environment === environment &&
    loadSession(s.id)?.hasApiKey === true
  );
}

/**
 * Carga una sesión por ID
 * @param {string} sessionId
 * @returns {Object|null}
 */
function loadSession(sessionId) {
  let session_path = getSessionPath(sessionId);
  try {
    if (fs.existsSync(session_path)) {
      let data = fs.readFileSync(session_path, 'utf8');
      return JSON.parse(data);
    }
  } catch (error) {
    console.error('Error cargando sesión:', error.message);
  }
  return null;
}

/**
 * Carga la sesión activa
 * @returns {Object|null}
 */
function loadActiveSession() {
  let config = readConfig();
  if (config.activeSession) {
    return loadSession(config.activeSession);
  }
  return null;
}

/**
 * Actualiza una sesión existente
 * @param {string} sessionId
 * @param {Object} updates
 */
function updateSession(sessionId, updates) {
  let session = loadSession(sessionId);
  if (session) {
    Object.assign(session, updates, { updatedAt: new Date().toISOString() });
    let session_path = getSessionPath(sessionId);
    fs.writeFileSync(session_path, JSON.stringify(session, null, 2), { mode: 0o600 });
  }
}

/**
 * Elimina una sesión
 * @param {string} sessionId
 */
function deleteSession(sessionId) {
  let session_path = getSessionPath(sessionId);
  try {
    if (fs.existsSync(session_path)) {
      fs.unlinkSync(session_path);
    }
  } catch (error) {
    console.error('Error eliminando sesión:', error.message);
  }

  // Si era la sesión activa, limpiarla
  let config = readConfig();
  if (config.activeSession === sessionId) {
    delete config.activeSession;
    writeConfig(config);
  }
}

/**
 * Lista todas las sesiones guardadas
 * @returns {Array<Object>}
 */
function listSessions() {
  ensureConfigDirs();
  let sessions = [];

  try {
    let files = fs.readdirSync(SESSIONS_DIR);
    for (let file of files) {
      if (file.endsWith('.json')) {
        let session_id = file.replace('.json', '');
        let session = loadSession(session_id);
        if (session) {
          sessions.push({
            id: session_id,
            email: session.email,
            phoneNumber: session.phoneNumber,
            environment: session.environment,
            savedAt: session.savedAt,
            profileId: session.profileId
          });
        }
      }
    }
  } catch (error) {
    console.error('Error listando sesiones:', error.message);
  }

  return sessions;
}

/**
 * Establece la sesión activa
 * @param {string} sessionId
 */
function setActiveSession(sessionId) {
  let config = readConfig();
  config.activeSession = sessionId;
  writeConfig(config);
}

/**
 * Obtiene el ID de la sesión activa
 * @returns {string|null}
 */
function getActiveSessionId() {
  let config = readConfig();
  return config.activeSession || null;
}

/**
 * Obtiene el país por defecto
 * @returns {string}
 */
function getDefaultCountry() {
  let config = readConfig();
  return config.defaultCountry || 'international';
}

/**
 * Establece el país por defecto
 * @param {string} country
 */
function setDefaultCountry(country) {
  let config = readConfig();
  config.defaultCountry = country;
  writeConfig(config);
}

/**
 * Limpia todas las sesiones y configuración
 */
function clearAll() {
  try {
    if (fs.existsSync(CONFIG_DIR)) {
      fs.rmSync(CONFIG_DIR, { recursive: true });
    }
  } catch (error) {
    console.error('Error limpiando configuración:', error.message);
  }
}

/**
 * Busca una sesión por alias
 * @param {string} alias - Alias de la sesión
 * @param {string} [environment] - Entorno (default: activo)
 * @returns {Object|null} Sesión encontrada o null
 */
function findSessionByAlias(alias, environment) {
  let env = environment || getActiveEnvironment();
  let sessions = listSessions();
  
  for (let s of sessions) {
    let full = loadSession(s.id);
    if (full?.alias === alias && full?.environment === env) {
      return full;
    }
  }
  return null;
}

/**
 * Lista todas las sesiones con alias (keygens) para el entorno actual
 * @param {string} [environment] - Entorno (default: activo)
 * @returns {Array<Object>} Sesiones con alias
 */
function listKeygenSessions(environment) {
  let env = environment || getActiveEnvironment();
  let sessions = listSessions();
  
  return sessions.filter(s => {
    let full = loadSession(s.id);
    return full?.alias && full?.hasApiKey && full?.environment === env;
  }).map(s => {
    let full = loadSession(s.id);
    return {
      id: s.id,
      alias: full.alias,
      identifier: full.identifier,
      identifierType: full.identifierType,
      email: full.email,
      hasJwt: !!full.jwt,
      createdAt: full.apiKeyPair?.createdAt
    };
  });
}

module.exports = {
  CONFIG_DIR,
  ensureConfigDirs,
  readConfig,
  writeConfig,
  getActiveEnvironment,
  setActiveEnvironment,
  saveSession,
  loadSession,
  loadActiveSession,
  updateSession,
  deleteSession,
  listSessions,
  setActiveSession,
  getActiveSessionId,
  getDefaultCountry,
  setDefaultCountry,
  clearAll,
  saveApiKeyPair,
  getApiKeyPair,
  listApiKeySessions,
  findSessionByAlias,
  listKeygenSessions
};
