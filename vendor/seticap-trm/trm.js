const https = require('https');

const BASE_HOST = 'proxy.set-icap.com';
const ENDPOINTS = {
  login: '/seticap/api/users/login',
  estadisticasPrecio: '/seticap/api/estadisticas/estadisticasPrecioMercado/',
  estadisticasPromedio: '/seticap/api/estadisticas/estadisticasPromedioCierre/'
};

function makeRequest(method, path, data = null, token = null) {
  return new Promise((resolve, reject) => {
    const postData = data ? JSON.stringify(data) : null;
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'Origin': 'https://dolar.set-icap.com',
      'Referer': 'https://dolar.set-icap.com/'
    };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (postData) headers['Content-Length'] = Buffer.byteLength(postData);
    const req = https.request({ hostname: BASE_HOST, port: 443, path, method, headers }, (res) => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        try { resolve({ statusCode: res.statusCode, data: JSON.parse(body) }); }
        catch { resolve({ statusCode: res.statusCode, data: body }); }
      });
    });
    req.on('error', reject);
    if (postData) req.write(postData);
    req.end();
  });
}

async function login() {
  const usr = process.env.SETICAP_USERNAME;
  const pwd = process.env.SETICAP_PASSWORD;
  if (!usr || !pwd) throw new Error('Missing SETICAP_USERNAME or SETICAP_PASSWORD');
  const result = await makeRequest('POST', ENDPOINTS.login, { usr, pwd });
  if (result.data.status === 'success' && result.data.user?.status === 'LOGGEDIN') return result.data.user.token;
  throw new Error('SET-ICAP login failed');
}

async function getTRM() {
  const token = await login();
  const precios = await makeRequest('POST', ENDPOINTS.estadisticasPrecio, { tipo: 'SPOT' }, token);
  const promedio = await makeRequest('POST', ENDPOINTS.estadisticasPromedio, { tipo: 'SPOT' }, token);
  console.log(`TRM: $${precios.data.data.trm}`);
  console.log(`Promedio: $${promedio.data.data.avg}`);
  console.log(`Cierre: $${promedio.data.data.close}`);
  console.log(`Fecha: ${new Date().toLocaleDateString('es-CO')}`);
}

getTRM().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
