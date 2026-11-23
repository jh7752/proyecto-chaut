# @coinsenda/sdk

NodeJS SDK for [Coinsenda](https://coinsenda.com) — a crypto exchange platform.

## Installation

```bash
npm install @coinsenda/sdk
```

## Usage

```javascript
const { CoinsendaClientV2 } = require('@coinsenda/sdk');

// 1. Create client (only domain is required)
let client = new CoinsendaClientV2({ domain: 'coinsenda.com' });

// 2. Authenticate (obtain JWT via login, OAuth, API key, etc.)
client.setJwt(jwt);       // also extracts userId from the JWT payload
client.setClientId(clientId);

// 3. Call endpoints
let accounts = await client.account.user.__get__accounts();
let deposits = await client.deposit.user.__get__deposits();
```

## API Pattern

All methods follow a three-level path:

```
client.{service}.{model}.{method}(data)
```

For example:

```javascript
await client.deposit.deposit.addNewDepositPublic({ currency: 'cop', amount: '50000' });
await client.withdraw.withdraw.addNewWithdrawPublic({ ... });
await client.swap.swap.addNewSwapPublic({ ... });
```

## Environment Configuration

The SDK derives service URLs from a base domain:

```javascript
// Production
let client = new CoinsendaClientV2({ domain: 'coinsenda.com' });

// Staging
let client = new CoinsendaClientV2({ domain: 'staging.coinsenda.com' });
```

For local development, create a `config/environments.local.js` file
(see `config/environments.local.example.js` for the template):

```javascript
let client = new CoinsendaClientV2({ environment: 'local' });
```

## License

Apache-2.0
