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

## API MVP

Endpoints principales:

- `GET /health` - estado del servicio.
- `POST /orders` - crea orden draft, calcula comision y estimado USDT opcional.
- `GET /orders/{external_id}` - consulta orden guardada.
- `GET /orders/{external_id}/events` - lista eventos auditables de la orden.
- `POST /orders/{external_id}/payment-request` - crea/asocia PaymentRequest en modo seguro.
- `POST /orders/{external_id}/reconcile-payment` - concilia contra Coinsenda y confirma/falla/ambigua el pago.

Estado actual: persistencia local en volumen Docker para MVP/test.

## Coinsenda Modo Seguro

La integracion inicia en `CHAUT_COINSENDA_MODE=mock`. Este modo no llama a Coinsenda real ni mueve fondos; solo genera un PaymentRequest simulado para validar flujo, persistencia y auditoria.

Antes de activar modo real faltan secrets y prueba controlada contra Coinsenda:

- email de Coinsenda autorizado
- llave privada/pubkey registrada
- verificacion de respuesta real de PaymentRequest
- confirmacion humana antes de crear cobros reales

## Reconciliacion De Pagos

La conciliacion porta la regla probada en el proyecto legacy `coinsenda-docs/SpicyMeet`:

- `accepted`, `paid`, `confirmed`, `completed`, `success`, `approved` => pago confirmado.
- `expired`, `cancelled`, `canceled`, `failed`, `rejected` => pago terminal no pagado.
- Otros estados => pendiente o ambiguo.

Antes de confirmar, Chaut valida que Coinsenda devuelva el mismo `payment_request_id`, `external_id`, monto bruto COP y moneda `cop`. Cualquier diferencia queda como `ambiguous` y no avanza.
