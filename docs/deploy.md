# Deploy EC2

Produccion de Chaut corre en EC2 y se despliega desde `main` con GitHub Actions y AWS SSM.

## Recursos activos

- API, bot y Caddy: instancia `chaut-dev` (`i-09127c011f918a30e`) en `us-east-1`.
- Base de datos: SQLite persistente en el volumen Docker `chaut_data`.
- Worker de exchanges: `chaut-exchange-worker-mumbai` (`i-02a3c86e7d934c601`) en `ap-south-1`.
- IP de salida del worker: `15.207.32.153`.

HTX y KuCoin se conectan al worker por su instance ID mediante SSM. El nombre/tag del worker puede cambiar sin afectar la integracion, pero el instance ID y la IP autorizada deben conservarse.

## Flujo

El workflow `.github/workflows/deploy-ec2.yml` asume `chaut-github-deploy-role`, ejecuta el despliegue por SSM y serializa despliegues con `flock`.

El stack serverless inicial (Lambda, API Gateway y DynamoDB) fue retirado el 2026-08-31 después de confirmar que no tenia trafico, datos ni dependencias de produccion.
