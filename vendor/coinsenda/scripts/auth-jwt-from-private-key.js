'use strict';

require('./load-env');

/**
 * Happy path: firma RS256 con keys/private.pem y POST /pubkey.
 * Config: variables en `.env` en la raíz. Completá COINSENDA_EMAIL con tu email real de Coinsenda.
 */

const fs = require('fs');
const path = require('path');
const NodeRSA = require('node-rsa');
const jwtLib = require('jsonwebtoken');
const { CoinsendaClientV2 } = require('@coinsenda/sdk');

let private_pem = fs.readFileSync(path.join(__dirname, '..', 'keys', 'private.pem'), 'utf8');
let email = process.env.COINSENDA_EMAIL || null;

async function main() {
  if (!email) {
    throw new Error('Completá COINSENDA_EMAIL en .env con tu email real de Coinsenda.');
  }

  let client = new CoinsendaClientV2({ environment: process.env.COINSENDA_ENV || 'prod' });
  client.setClientId('');

  let jwt_payload = {
    iat: Math.floor(Date.now() / 1000)
  };

  jwt_payload.email = email;

  let key = new NodeRSA(private_pem, 'pkcs8-private-pem');
  let signed_token = jwtLib.sign(jwt_payload, key.exportKey('private'), {
    algorithm: 'RS256',
    expiresIn: '5m'
  });

  let response = await client.auth.passport.authPubkey({ data: { signed_token } });
  let session_jwt = response.data.data.jwt;
  if (!session_jwt) {
    throw new Error(
      `No jwt in response (status ${response.status}). Body: ${JSON.stringify(response.data)}`
    );
  }
  console.log(session_jwt);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
