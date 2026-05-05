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

    try:
        expected_amount = Decimal(str(order.amount_cop_gross))
        actual_amount = Decimal(str(payment_request.get("amount")))
    except (InvalidOperation, TypeError):
        return {"ok": False, "reason": "amount is not numeric", "expected": order.amount_cop_gross}
    if actual_amount != expected_amount:
        return {
            "ok": False,
            "reason": "amount mismatch",
            "expected": str(expected_amount),
            "actual": str(actual_amount),
        }

    currency = str(payment_request.get("currency") or "").lower()
    if currency != "cop":
        return {"ok": False, "reason": "currency is not cop", "expected": "cop", "actual": currency}

    return {"ok": True, "reason": "payment_request matches order"}
