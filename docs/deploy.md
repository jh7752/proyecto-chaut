# Deploy Dev

El deploy de `main` usa GitHub Actions con OIDC hacia AWS.

## Recursos

- Stack OIDC: `chaut-github-oidc`
- Stack app dev: `chaut-dev`
- Lambda: `chaut-dev-api`
- DynamoDB: `chaut-dev-orders`, `chaut-dev-events`
- API Gateway HTTP API con stage `dev`

## Seguridad

GitHub no guarda llaves AWS permanentes. Usa OIDC para asumir `chaut-github-deploy-role`.
