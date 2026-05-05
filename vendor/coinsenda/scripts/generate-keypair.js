'use strict';

/**
 * Generates the same RSA key pair shape as coinsenda-mcp flows.generateKeyPair /
 * pairMcpAgent: NodeRSA 2048-bit, PKCS#8 PEM for private and public.
 *
 * @see Backend/AI/coinsenda-mcp/lib/flows/auth/index.js — generateKeyPair()
 */

const fs = require('fs');
const path = require('path');
const NodeRSA = require('node-rsa');

let keys_dir = path.join(__dirname, '..', 'keys');
let private_path = path.join(keys_dir, 'private.pem');
let public_path = path.join(keys_dir, 'public.pem');

let force = process.argv.includes('--force');

if (!force && (fs.existsSync(private_path) || fs.existsSync(public_path))) {
  console.error('Keys already exist. Use --force to overwrite.');
  process.exit(1);
}

fs.mkdirSync(keys_dir, { recursive: true });

let key = new NodeRSA({ b: 2048 });
let private_pem = key.exportKey('pkcs8-private-pem');
let public_pem = key.exportKey('pkcs8-public-pem');

fs.writeFileSync(private_path, private_pem, { mode: 0o600 });
fs.writeFileSync(public_path, public_pem, { mode: 0o644 });

console.log('RSA 2048 key pair written (same format as MCP pairMcpAgent / generateKeyPair):');
console.log('  Private:', private_path);
console.log('  Public: ', public_path);
