from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .models import OrderResponse


@dataclass(frozen=True)
class PaymentReconciliation:
    payment_status: str
    event_type: str
    validation: dict


def reconcile_payment_status(order: OrderResponse, coinsenda_record: dict) -> PaymentReconciliation:
    payment_request = coinsenda_record.get("payment_request")
    validation = validate_payment_request_match(order, payment_request)
    coinsenda_event_type = str(coinsenda_record.get("event_type") or "payment_pending_or_ambiguous")

    if not validation["ok"]:
        return PaymentReconciliation(
            payment_status="ambiguous",
            event_type="payment.reconciliation_ambiguous",
            validation={**validation, "coinsenda_event_type": coinsenda_event_type},
        )

    if coinsenda_event_type == "payment_confirmed":
        return PaymentReconciliation(
            payment_status="confirmed",
            event_type="payment.confirmed",
            validation={**validation, "coinsenda_event_type": coinsenda_event_type},
        )
    if coinsenda_event_type == "payment_terminal_not_paid":
        return PaymentReconciliation(
            payment_status="failed",
            event_type="payment.failed",
            validation={**validation, "coinsenda_event_type": coinsenda_event_type},
        )
    if coinsenda_event_type == "payment_request_not_found":
        return PaymentReconciliation(
            payment_status="not_found",
            event_type="payment.not_found",
            validation={**validation, "coinsenda_event_type": coinsenda_event_type},
        )

    return PaymentReconciliation(
        payment_status="pending",
        event_type="payment.pending_or_ambiguous",
        validation={**validation, "coinsenda_event_type": coinsenda_event_type},
    )


def validate_payment_request_match(order: OrderResponse, payment_request: dict | None) -> dict:
    if not payment_request:
        return {"ok": False, "reason": "Coinsenda did not return a PaymentRequest"}

    expected_id = str(order.payment_request_id or "")
    actual_id = str(payment_request.get("id") or "")
    if expected_id and actual_id and actual_id != expected_id:
        return {"ok": False, "reason": "payment_request_id mismatch", "expected": expected_id, "actual": actual_id}

    expected_external_id = str(order.external_id)
    actual_external_id = str(payment_request.get("external_id") or "")
    if actual_external_id != expected_external_id:
        return {
            "ok": False,
            "reason": "external_id mismatch",
            "expected": expected_external_id,
            "actual": actual_external_id,
        }

    expected_currency = str(order.payment_currency or "cop").lower()
    expected_amount_source = order.payment_amount if expected_currency == "usdt" else order.amount_cop_gross
    if expected_amount_source is None:
        return {"ok": False, "reason": "order payment_amount is missing", "expected_currency": expected_currency}

    try:
        expected_amount = Decimal(str(expected_amount_source))
        actual_amount = Decimal(str(payment_request.get("amount")))
    except (InvalidOperation, TypeError):
        return {"ok": False, "reason": "amount is not numeric", "expected": str(expected_amount_source)}
    if actual_amount != expected_amount:
        return {
            "ok": False,
            "reason": "amount mismatch",
            "expected": str(expected_amount),
            "actual": str(actual_amount),
        }

    currency = str(payment_request.get("currency") or "").lower()
    if currency != expected_currency:
        return {
            "ok": False,
            "reason": "currency mismatch",
            "expected": expected_currency,
            "actual": currency,
        }

    return {
        "ok": True,
        "reason": "payment_request matches order",
        "confirmed_currency": expected_currency,
        "confirmed_amount": str(expected_amount),
    }
