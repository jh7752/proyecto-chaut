# Arquitectura Inicial

## Componentes

- API backend: endpoints para healthcheck, ordenes, pagos y callbacks.
- Base de datos: DynamoDB en AWS para ordenes y eventos operativos.
- Secrets: AWS Secrets Manager o SSM Parameter Store para credenciales externas.
- Logs: CloudWatch Logs para auditoria tecnica.
- CI/CD: GitHub Actions para validar y desplegar.

## Flujo Base

1. Cliente solicita depositar COP.
2. API crea orden interna con `external_id` unico.
3. Sistema crea PaymentRequest en Coinsenda.
4. Usuario paga exactamente el monto esperado.
5. Senal por correo/callback dispara verificacion.
6. Sistema verifica en Coinsenda.
7. Se registra pago confirmado y evento append-only.
8. Conversion y compra quedan en modo asistido hasta autorizacion humana.
