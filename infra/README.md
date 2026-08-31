# Infraestructura activa

Chaut opera sobre dos instancias EC2:

- `chaut-dev` en `us-east-1`: API, bot, Caddy y SQLite persistente.
- `chaut-htx-worker-mumbai` en `ap-south-1`: salida estable para la API privada de HTX mediante SSM.

El despliegue se realiza desde GitHub Actions con OIDC y SSM. El stack serverless inicial fue retirado el 2026-08-31 al comprobar que Lambda, API Gateway y las tablas DynamoDB no tenian trafico, datos ni dependencias activas.

No crear recursos pagos nuevos sin confirmacion de Johan.
