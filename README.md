# Proyecto Chaut

Plataforma operativa para pagos en COP, conciliacion con Coinsenda y flujo controlado hacia USDT/XAUT.

## Objetivo

Construir un sistema trazable que permita:

- Crear ordenes internas de pago en COP.
- Generar o asociar PaymentRequests de Coinsenda.
- Verificar pagos recibidos contra fuente de verdad.
- Registrar eventos operativos append-only.
- Preparar conversion COP -> USDT con aprobacion humana.
- Preparar compra USDT -> XAUT con aprobacion humana.

## Principios

- No mover fondos sin aprobacion explicita.
- No confiar solo en correos: siempre verificar en Coinsenda.
- Registrar evidencia y timestamps por cada paso.
- Mantener limites de monto, tolerancia y slippage configurables.

## Estado

Bootstrap inicial. Infraestructura y API minima en construccion.

## EC2 MVP

El MVP puede correr en EC2 con Docker Compose:

- API FastAPI en puerto 80
- Postgres local solo expuesto en localhost
- Deploy manual/SSM durante bootstrap

```bash
docker compose up -d --build
```
