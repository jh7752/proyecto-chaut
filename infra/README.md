# Infraestructura

Pendiente de definir como IaC. Opcion inicial recomendada:

- AWS Lambda para API liviana.
- API Gateway HTTP API.
- DynamoDB para ordenes/eventos.
- SSM Parameter Store para configuracion no sensible.
- Secrets Manager para credenciales externas.

No desplegar recursos pagos sin confirmacion de Johan.
