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
PENDING_NAMES: dict[int, bool] = {}
PENDING_CUSTOM_AMOUNTS: set[int] = set()
PENDING_SETTLEMENTS: set[str] = set()


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
    user = message.get("from", {})
    if not chat_id:
        return
    if PENDING_NAMES.get(chat_id) and text and not text.startswith("/"):
        register_name(chat_id, user, text)
    elif PENDING_CUSTOM_AMOUNTS.__contains__(chat_id) and text and not text.startswith("/"):
        handle_custom_amount(chat_id, user, text)
    elif text.startswith("/start"):
        welcome_or_onboard(chat_id, user)
    elif text.startswith("/ahorros"):
        welcome_or_onboard(chat_id, user, savings=True)
    elif text.startswith("/saldo"):
        send_balance(chat_id, user)
    elif text.startswith("/movimientos"):
        send_movements(chat_id, user)
    elif text.startswith("/estado"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            send_order_status(chat_id, parts[1].strip())
        else:
            send_text(chat_id, "Enviame /estado chaut-... para revisar una orden especifica.")
    elif text.isdigit() and int(text) >= MIN_COP:
        if not account_exists(user.get("id", chat_id)):
            ask_name(chat_id)
        else:
            create_checkout(chat_id, user, int(text))
    elif text.lower() in {"hola", "buenas", "hello", "hi"}:
        welcome_or_onboard(chat_id, user)
    else:
        send_text(chat_id, "Hola. Soy tu bot de ahorros en oro digital. Usa /ahorros para empezar o /saldo para ver tu cuenta.")


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
    if data == "register":
        if account_exists(user.get("id", chat_id)):
            welcome_existing_user(chat_id, user)
        else:
            ask_name(chat_id)
    elif data == "menu:ahorros":
        send_savings_menu(chat_id, "Cuanto quieres ahorrar hoy en OD?")
    elif data.startswith("ahorros:") and not account_exists(user.get("id", chat_id)):
        send_text(chat_id, "Con mucho gusto. Primero dime tu nombre para dejar tu cuenta bien organizada.")
        ask_name(chat_id)
    elif data == "ahorros:5000":
        create_checkout(chat_id, user, 5000)
    elif data == "ahorros:10000":
        create_checkout(chat_id, user, 10000)
    elif data == "ahorros:custom":
        PENDING_CUSTOM_AMOUNTS.add(chat_id)
        send_text(chat_id, "Cuanto quieres ahorrar en COP? Minimo 5.000. Ejemplo: 25.000")
    elif data.startswith("paid:"):
        settle_order(chat_id, data.split(":", 1)[1])
    elif data == "saldo":
        send_balance(chat_id, user)
    elif data == "movimientos":
        send_movements(chat_id, user)


def handle_custom_amount(chat_id: int, user: dict[str, Any], text: str) -> None:
    amount = parse_cop_input(text)
    if amount is None:
        send_text(chat_id, "No pude leer ese monto. Escribelo asi, porfa: 25.000")
        return
    if amount < MIN_COP:
        send_text(chat_id, "El minimo para ahorrar es 5.000 COP. Escribe otro monto, porfa.")
        return
    PENDING_CUSTOM_AMOUNTS.discard(chat_id)
    if not account_exists(user.get("id", chat_id)):
        send_text(chat_id, "Con mucho gusto. Primero dime tu nombre para dejar tu cuenta bien organizada.")
        ask_name(chat_id)
        return
    create_checkout(chat_id, user, amount)


def parse_cop_input(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def welcome_or_onboard(chat_id: int, user: dict[str, Any], savings: bool = False) -> None:
    if account_exists(user.get("id", chat_id)):
        account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
        name = account.get("display_name") or "de vuelta"
        if savings:
            send_savings_menu(chat_id, f"Que gusto tenerte de vuelta, {name} 🥇\n\nCuanto quieres ahorrar hoy en OD?")
        else:
            send_savings_menu(chat_id, f"Que gusto tenerte de vuelta, {name} 🥇\n\nQue quieres hacer hoy?")
        return
    start_onboarding(chat_id)


def welcome_existing_user(chat_id: int, user: dict[str, Any]) -> None:
    account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
    name = account.get("display_name") or "de vuelta"
    send_savings_menu(chat_id, f"Que gusto tenerte de vuelta, {name} 🥇\n\nQue quieres hacer hoy?")


def start_onboarding(chat_id: int) -> None:
    PENDING_NAMES[chat_id] = True
    send_text(
        chat_id,
        "Hola, que gusto tenerte por aqui 🥇\n\nSoy tu asistente de ahorro en OD (oro digital).\n\nPara crear tu cuenta, dime tu nombre y apellido.",
    )


def ensure_account_then_menu(chat_id: int, user: dict[str, Any]) -> None:
    if account_exists(user.get("id", chat_id)):
        account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
        name = account.get("display_name") or "de vuelta"
        send_savings_menu(chat_id, f"Que gusto tenerte de vuelta, {name}. Que quieres hacer hoy?")
    else:
        send_text(
            chat_id,
            "Hola, que gusto tenerte por aqui. Para atenderte mejor, dime tu nombre y apellido.",
            buttons=[[{"text": "Registrar mi nombre", "callback_data": "register"}]],
        )
        PENDING_NAMES[chat_id] = True


def ask_name(chat_id: int) -> None:
    PENDING_NAMES[chat_id] = True
    send_text(chat_id, "Escribeme tu nombre y apellido, porfa.\n\nEjemplo: Pepito Perez")


def register_name(chat_id: int, user: dict[str, Any], display_name: str) -> None:
    if account_exists(user.get("id", chat_id)):
        PENDING_NAMES.pop(chat_id, None)
        welcome_existing_user(chat_id, user)
        return
    clean_name = " ".join(display_name.split())
    if len(clean_name) < 3:
        send_text(chat_id, "Me regalas tu nombre un poquito mas completo, porfa? Nombre y apellido estaria perfecto.")
        return
    api("POST", "/accounts/identify", identity(chat_id, user, clean_name))
    PENDING_NAMES.pop(chat_id, None)
    send_text(
        chat_id,
        f"Listo, {clean_name} 🥇\n\nTu cuenta quedo lista.\n\nQue quieres hacer hoy?",
        buttons=[
            [{"text": "🥇 5.000 COP", "callback_data": "ahorros:5000"}, {"text": "🥇 10.000 COP", "callback_data": "ahorros:10000"}],
            [{"text": "✍️ Otro monto", "callback_data": "ahorros:custom"}, {"text": "📊 Ver saldo", "callback_data": "saldo"}],
        ],
    )


def account_exists(provider_user_id: Any) -> bool:
    try:
        api("GET", f"/accounts/by-identity/telegram/{provider_user_id}")
        return True
    except Exception:
        return False


def send_savings_menu(chat_id: int, message: str = "Que quieres hacer hoy?") -> None:
    send_text(
        chat_id,
        message,
        buttons=[
            [{"text": "🥇 5.000 COP", "callback_data": "ahorros:5000"}, {"text": "🥇 10.000 COP", "callback_data": "ahorros:10000"}],
            [{"text": "✍️ Otro monto", "callback_data": "ahorros:custom"}, {"text": "📊 Ver saldo", "callback_data": "saldo"}],
        ],
    )


def create_checkout(chat_id: int, user: dict[str, Any], amount_cop: int) -> None:
    if amount_cop < MIN_COP:
        send_text(chat_id, "El minimo para ahorrar es 5.000 COP.")
        return
    send_text(chat_id, "Dame un momento, estoy creando tu orden y buscando la llave Bre-B para pagar.")
    account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
    payload = {
        "client_id": f"telegram:{user.get('id', chat_id)}",
        "identity": identity(chat_id, user, account.get("display_name")),
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
        f"Orden: {external_id}\n\n"
        "Cuando pagues, toca el boton para confirmar y comprar el oro."
    )
    send_text(chat_id, text, buttons=[[{"text": "✅ Ya pague", "callback_data": f"paid:{external_id}"}], [{"text": "📊 Ver saldo", "callback_data": "saldo"}]])


def settle_order(chat_id: int, external_id: str) -> None:
    if external_id in PENDING_SETTLEMENTS:
        send_text(chat_id, "Ya estoy revisando ese pago. Dame un momento, por favor.")
        return
    PENDING_SETTLEMENTS.add(external_id)
    send_text(chat_id, "Verificando tu pago. Dame un momento, por favor...")
    try:
        result = api("POST", f"/orders/{external_id}/settle-xaut?confirm=EXECUTE_HTX_XAUT_BUY")
    except Exception as exc:
        send_text(chat_id, f"Todavia no pude confirmar esa orden. Intenta de nuevo en un momento.\n\nDetalle: {friendly_api_error(exc)}")
        return
    finally:
        PENDING_SETTLEMENTS.discard(external_id)
    if not result.get("executed") and result.get("status") == "payment_not_confirmed":
        send_text(chat_id, "Todavia no veo el pago confirmado en Coinsenda. Espera un poco y toca 'Ya pague' otra vez.")
        return
    summary = result.get("user_summary") or {}
    message = summary.get("message") or "Compra procesada. Usa /saldo para ver tu cuenta."
    if "(" in message and "XAUT" in message:
        message = message.split("(", 1)[0].strip()
    message = message.replace("gramos de oro digital", "gramos de OD (oro digital) 🥇")
    send_text(chat_id, message)


def send_balance(chat_id: int, user: dict[str, Any]) -> None:
    if not account_exists(user.get("id", chat_id)):
        send_text(chat_id, "Todavia no tengo tu cuenta por aqui. Vamos a crearla en un momento.")
        ask_name(chat_id)
        return
    try:
        portfolio = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}/portfolio")
    except Exception:
        send_text(chat_id, "Aun no tienes saldo registrado. Usa /ahorros para empezar.")
        return
    send_text(
        chat_id,
        "Tu saldo:\n\n"
        f"{portfolio['gold_grams_net']:.12f} gramos de OD (oro digital) 🥇\n"
        f"COP invertido: {portfolio['cop_invested']:,.0f}\n"
        f"Movimientos: {portfolio['entries_count']}",
        buttons=[[{"text": "🥇 Ahorrar mas", "callback_data": "menu:ahorros"}, {"text": "📜 Movimientos", "callback_data": "movimientos"}]],
    )


def send_movements(chat_id: int, user: dict[str, Any]) -> None:
    if not account_exists(user.get("id", chat_id)):
        send_text(chat_id, "Todavia no tengo tu cuenta por aqui. Vamos a crearla en un momento.")
        ask_name(chat_id)
        return
    try:
        portfolio = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}/portfolio")
    except Exception:
        send_text(chat_id, "Aun no tienes movimientos.")
        return
    entries = list(reversed(portfolio.get("entries", [])))[:5]
    if not entries:
        send_text(chat_id, "Aun no tienes movimientos.")
        return
    lines = ["Ultimos movimientos:"]
    for entry in entries:
        lines.append(f"- {entry['external_id']}: {entry['gold_grams']:.12f} g OD 🥇 / {entry['cop_gross']:,.0f} COP")
    send_text(chat_id, "\n".join(lines))


def send_order_status(chat_id: int, external_id: str) -> None:
    order = api("GET", f"/orders/{external_id}")
    send_text(chat_id, f"Orden {external_id}\nPago: {order['payment_status']}\nXAUT: {order['conversion_status']}\nCOP: {order['amount_cop_gross']:,.0f}")


def identity(chat_id: int, user: dict[str, Any], display_name: str | None = None) -> dict[str, Any]:
    first = user.get("first_name") or ""
    last = user.get("last_name") or ""
    name = display_name or (first + " " + last).strip() or user.get("username") or str(chat_id)
    return {
        "provider": "telegram",
        "provider_user_id": str(user.get("id", chat_id)),
        "chat_id": str(chat_id),
        "username": user.get("username"),
        "display_name": name,
        "first_name": first or None,
        "last_name": last or None,
    }


def friendly_api_error(exc: Exception) -> str:
    text = str(exc)
    if "conversion_status=executing" in text:
        return "Tu compra ya esta en proceso. Espera un momento, por favor."
    if "conversion_status=settled" in text:
        return "Esta orden ya fue procesada. Usa /saldo para ver tu cuenta."
    if "balance is not enough" in text or "balance-insufficient" in text:
        return "El pago fue confirmado, pero estamos completando la compra de oro. Intenta de nuevo en un momento."
    return text


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
