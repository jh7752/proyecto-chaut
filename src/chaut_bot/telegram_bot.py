import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

TOKEN = os.environ["CHAUT_TELEGRAM_BOT_TOKEN"]
API_BASE = os.environ.get("CHAUT_API_BASE", "http://api:8000").rstrip("/")
TG_BASE = f"https://api.telegram.org/bot{TOKEN}"
MIN_COP = 5000


def main() -> None:
    offset = 0
    while True:
        try:
            updates = tg("getUpdates", {"timeout": 30, "offset": offset, "allowed_updates": json.dumps(["message", "callback_query"])})
            for update in updates.get("result", []):
                offset = max(offset, update["update_id"] + 1)
                handle_update(update)
        except Exception as exc:
            print(f"bot loop error: {exc}", flush=True)
            time.sleep(3)


def handle_update(update: dict[str, Any]) -> None:
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return
    if text.startswith("/ahorros"):
        send_savings_menu(chat_id)
    elif text.startswith("/saldo"):
        send_balance(chat_id, message.get("from", {}))
    elif text.startswith("/movimientos"):
        send_movements(chat_id, message.get("from", {}))
    elif text.startswith("/estado"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            send_order_status(chat_id, parts[1].strip())
        else:
            send_text(chat_id, "Enviame /estado chaut-... para revisar una orden especifica.")
    elif text.isdigit() and int(text) >= MIN_COP:
        create_checkout(chat_id, message.get("from", {}), int(text))
    else:
        send_text(chat_id, "Usa /ahorros para comprar oro digital o /saldo para ver tu cuenta.")


def handle_callback(callback: dict[str, Any]) -> None:
    data = callback.get("data") or ""
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    user = callback.get("from", {})
    callback_id = callback.get("id")
    if callback_id:
        tg("answerCallbackQuery", {"callback_query_id": callback_id})
    if not chat_id:
        return
    if data == "ahorros:5000":
        create_checkout(chat_id, user, 5000)
    elif data == "ahorros:10000":
        create_checkout(chat_id, user, 10000)
    elif data == "ahorros:custom":
        send_text(chat_id, "Escribeme el monto en COP, minimo 5000. Ejemplo: 25000")
    elif data.startswith("paid:"):
        settle_order(chat_id, data.split(":", 1)[1])
    elif data == "saldo":
        send_balance(chat_id, user)
    elif data == "movimientos":
        send_movements(chat_id, user)


def send_savings_menu(chat_id: int) -> None:
    send_text(
        chat_id,
        "Cuanto quieres ahorrar en oro digital?",
        buttons=[
            [{"text": "5.000 COP", "callback_data": "ahorros:5000"}, {"text": "10.000 COP", "callback_data": "ahorros:10000"}],
            [{"text": "Otra cantidad", "callback_data": "ahorros:custom"}, {"text": "Ver saldo", "callback_data": "saldo"}],
        ],
    )


def create_checkout(chat_id: int, user: dict[str, Any], amount_cop: int) -> None:
    if amount_cop < MIN_COP:
        send_text(chat_id, "El minimo para ahorrar es 5.000 COP.")
        return
    send_text(chat_id, "Dame un momento, estoy creando tu orden y buscando la llave Bre-B para pagar.")
    payload = {
        "client_id": f"telegram:{user.get('id', chat_id)}",
        "identity": identity(chat_id, user),
        "amount_cop": amount_cop,
        "method": "Bre-B",
        "expiration_minutes": 60,
    }
    checkout = api("POST", "/checkout", payload)
    external_id = checkout["external_id"]
    text = (
        "Listo. Envia exactamente:\n\n"
        f"{checkout.get('pay_amount_cop') or amount_cop} COP\n"
        f"a la llave Bre-B:\n{checkout.get('pay_to')}\n\n"
        f"Orden: {external_id}\n"
        f"USDT estimado: {checkout.get('payment_amount')}\n\n"
        "Cuando pagues, toca el boton para confirmar y comprar el oro."
    )
    send_text(chat_id, text, buttons=[[{"text": "Ya pague", "callback_data": f"paid:{external_id}"}], [{"text": "Ver saldo", "callback_data": "saldo"}]])


def settle_order(chat_id: int, external_id: str) -> None:
    try:
        result = api("POST", f"/orders/{external_id}/settle-xaut?confirm=EXECUTE_HTX_XAUT_BUY")
    except Exception as exc:
        send_text(chat_id, f"Todavia no pude confirmar esa orden. Intenta de nuevo en un momento.\n\nDetalle: {exc}")
        return
    if not result.get("executed") and result.get("status") == "payment_not_confirmed":
        send_text(chat_id, "Todavia no veo el pago confirmado en Coinsenda. Espera un poco y toca 'Ya pague' otra vez.")
        return
    summary = result.get("user_summary") or {}
    send_text(chat_id, summary.get("message") or "Compra procesada. Usa /saldo para ver tu cuenta.")


def send_balance(chat_id: int, user: dict[str, Any]) -> None:
    try:
        portfolio = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}/portfolio")
    except Exception:
        send_text(chat_id, "Aun no tienes saldo registrado. Usa /ahorros para empezar.")
        return
    send_text(
        chat_id,
        "Tu saldo en oro digital:\n\n"
        f"{portfolio['gold_grams_net']:.12f} gramos\n"
        f"{portfolio['xaut_net']:.18f} XAUT neto\n"
        f"COP invertido: {portfolio['cop_invested']:,.0f}\n"
        f"Movimientos: {portfolio['entries_count']}",
        buttons=[[{"text": "Ahorrar mas", "callback_data": "ahorros:5000"}, {"text": "Movimientos", "callback_data": "movimientos"}]],
    )


def send_movements(chat_id: int, user: dict[str, Any]) -> None:
    try:
        portfolio = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}/portfolio")
    except Exception:
        send_text(chat_id, "Aun no tienes movimientos.")
        return
    entries = portfolio.get("entries", [])[-5:]
    if not entries:
        send_text(chat_id, "Aun no tienes movimientos.")
        return
    lines = ["Ultimos movimientos:"]
    for entry in entries:
        lines.append(f"- {entry['external_id']}: {entry['gold_grams']:.12f} g / {entry['cop_gross']:,.0f} COP")
    send_text(chat_id, "\n".join(lines))


def send_order_status(chat_id: int, external_id: str) -> None:
    order = api("GET", f"/orders/{external_id}")
    send_text(chat_id, f"Orden {external_id}\nPago: {order['payment_status']}\nXAUT: {order['conversion_status']}\nCOP: {order['amount_cop_gross']:,.0f}")


def identity(chat_id: int, user: dict[str, Any]) -> dict[str, Any]:
    first = user.get("first_name") or ""
    last = user.get("last_name") or ""
    return {
        "provider": "telegram",
        "provider_user_id": str(user.get("id", chat_id)),
        "chat_id": str(chat_id),
        "username": user.get("username"),
        "display_name": (first + " " + last).strip() or user.get("username") or str(chat_id),
        "first_name": first or None,
        "last_name": last or None,
    }


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode())


def tg(method: str, params: dict[str, Any]) -> dict[str, Any]:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{TG_BASE}/{method}", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.loads(response.read().decode())


def send_text(chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None) -> None:
    params: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    tg("sendMessage", params)


if __name__ == "__main__":
    main()
