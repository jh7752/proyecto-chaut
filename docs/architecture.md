# Arquitectura Operativa

## Componentes

- API y bot: contenedores Docker en la instancia EC2 `chaut-dev` de `us-east-1`.
- Proxy HTTPS: Caddy en la misma instancia.
- Base de datos: SQLite persistente en el volumen Docker de producción.
- Worker HTX: EC2 `chaut-htx-worker-mumbai` en `ap-south-1`, accedido por instance ID mediante SSM y sin puertos públicos entrantes.
- Secrets: variables de entorno y parámetros seguros usados por los procesos autorizados.
- Logs: logs de Docker y eventos append-only en la base de datos.
- CI/CD: GitHub Actions despliega `main` en EC2 mediante SSM.

## Flujo Base

1. Cliente solicita depositar COP.
2. API crea orden interna con `external_id` unico.
3. Sistema crea PaymentRequest en Coinsenda.
4. Usuario paga exactamente el monto esperado.
5. Senal por correo/callback dispara verificacion.
6. Sistema verifica en Coinsenda.
7. Se registra pago confirmado y evento append-only.
8. Conversion y compra quedan en modo asistido hasta autorizacion humana.
