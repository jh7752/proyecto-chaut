# Runbook Operativo

## Reglas Minimas Antes De Mover Fondos

- `external_id` unico por orden.
- Monto esperado y recibido deben coincidir exactamente salvo regla explicita.
- Estado confirmado en Coinsenda.
- Tasa COP/USDT dentro del rango permitido.
- Slippage maximo definido antes de comprar XAUT.
- Registro de evento antes y despues de cada accion.

## Ambiguedades

Detener y pedir confirmacion humana si:

- Hay diferencia de monto.
- Falta referencia o `external_id`.
- Coinsenda no confirma el pago.
- La tasa o fees no son claros.
- Hay error parcial en conversion/orden.
