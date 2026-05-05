# Coinsenda SDK Runtime

Vendored helper scripts adapted from the prior tested Coinsenda integration.

Secrets are not stored here. Runtime expects:

- `.env` with `COINSENDA_EMAIL` and `COINSENDA_APP_ORIGIN`
- `keys/private.pem` registered with Coinsenda pubkey auth

The EC2 bootstrap copies these from the legacy local workspace for now.
