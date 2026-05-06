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

Primer modulo funcional en EC2 dev: checkout COP -> PaymentRequest USDT -> instrucciones Bre-B. La API crea ordenes internas, genera PaymentRequests reales de Coinsenda, inspecciona Bre-B y deja eventos auditables para conciliacion.

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

- `POST /checkout` - crea orden, consulta sell price, crea PaymentRequest USDT e inspecciona Bre-B en una sola llamada.
- `GET /health` - estado del servicio.
- `POST /orders` - crea orden draft, calcula comision y estimado USDT opcional.
- `GET /orders/{external_id}` - consulta orden guardada.
- `GET /orders/{external_id}/events` - lista eventos auditables de la orden.
- `POST /orders/{external_id}/payment-request` - crea/asocia PaymentRequest en modo seguro.
- `POST /orders/{external_id}/reconcile-payment` - concilia contra Coinsenda y confirma/falla/ambigua el pago.
- `POST /orders/{external_id}/payment-instructions` - inspecciona el front del PaymentRequest y extrae metodos/direcciones visibles.

Estado actual: persistencia local en volumen Docker para MVP/test.

La comisión ya no se descuenta en COP. El usuario paga el COP digitado; la comisión se aplicará después sobre XAUT cuando exista el módulo de compra.

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

## Inspeccion De Instrucciones De Pago

Chaut porta los scripts legacy de Playwright para inspeccionar el front del PaymentRequest COP. El objetivo no es cobrar USDT al usuario, sino detectar instrucciones utiles del flujo COP (metodos como DCOP/PSE y posibles direcciones/QR/datos que el front expone) para guardarlas y mostrarlas de forma simple.

Endpoint:

```bash
POST /orders/{external_id}/payment-instructions
{ "click_text": "DCOP" }
```

El resultado queda auditado con evento `payment_instructions.inspected`.

## PaymentRequest USDT Valorado En COP

Para que el usuario digite COP y pague por Bre-B, Chaut usa el flujo probado con Coinsenda:

1. Consultar el par `USDT/COP` en Coinsenda.
2. Usar `sell_price`, no `buy_price`.
3. Calcular `payment_amount = amount_cop_gross / sell_price`, redondeado a 6 decimales.
4. Crear PaymentRequest con `currency=usdt`.
5. Inspeccionar/crear provider Bre-B y validar que el COP devuelto por Coinsenda coincida con el COP digitado.

Prueba de referencia: con `sell_price=3527.5`, `5000 COP / 3527.5 = 1.417434 USDT`, y Bre-B pidió `4,999.98 COP`.

## Checkout Unificado

`POST /checkout` es el endpoint de producto para bot o mini-app. Recibe el COP que quiere pagar el usuario y devuelve instrucciones listas:

```json
{
  "client_id": "telegram-271173673",
  "amount_cop": 5000,
  "method": "Bre-B",
  "expiration_minutes": 60,
  "max_price_slippage_cop": 1,
  "max_retries": 1
}
```

Internamente consulta `sell_price` actual de Coinsenda, crea PaymentRequest `usdt`, inspecciona Bre-B y devuelve `pay_amount_cop`, `pay_to`, `payment_url` y auditoria asociada.

Respuesta de referencia en EC2 dev:

```json
{
  "external_id": "chaut-15139052cfc2",
  "amount_cop": 5000,
  "pay_amount_cop": "5,000",
  "pay_to": "@coinsendanIlCsO5N",
  "method": "Bre-B",
  "payment_currency": "usdt",
  "payment_amount": 1.414147,
  "sell_price_cop_per_usdt": 3535.69,
  "payment_request_id": "69fab714e6ca61002b829622",
  "payment_url": "https://app.coinsenda.com/paymentRequest?paymentRequestId=69fab714e6ca61002b829622",
  "status": "pending"
}
```

### Cierre Del Primer Modulo

El primer modulo queda concluido como MVP operativo:

- Fuente de verdad interna: orden Chaut con `external_id`, montos, PaymentRequest y eventos.
- Cobro real: PaymentRequest de Coinsenda en `usdt`, calculado desde COP con `sell_price`.
- UX de pago: instrucciones Bre-B listas para bot/mini-app (`pay_amount_cop`, `pay_to`, `payment_url`).
- Seguridad operativa: sin movimientos de fondos automaticos y sin comision descontada en COP.
- Conciliacion: endpoint separado para verificar estado contra Coinsenda antes de confirmar pagos.

Validacion de precio: `/checkout` compara `pay_amount_cop` contra `amount_cop`. Si el deslizamiento supera `max_price_slippage_cop`, registra `checkout.price_mismatch` y reintenta hasta `max_retries`. Si el ultimo intento sigue fuera de tolerancia, responde `checkout_status=price_mismatch` para no entregar instrucciones como listas.
