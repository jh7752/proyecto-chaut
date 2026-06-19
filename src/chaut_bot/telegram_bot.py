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
PAYMENT_EXPIRATION_MINUTES = 45
PENDING_NAMES: dict[int, bool] = {}
PENDING_CUSTOM_AMOUNTS: set[int] = set()
PENDING_SETTLEMENTS: set[str] = set()
PENDING_WITHDRAWAL_KEYS: dict[int, dict[str, Any]] = {}
PENDING_PARTIAL_WITHDRAWALS: set[int] = set()
NOTIFIED_WITHDRAWALS: set[str] = set()


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
    elif chat_id in PENDING_PARTIAL_WITHDRAWALS and text and not text.startswith("/"):
        handle_partial_withdrawal_amount(chat_id, user, text)
    elif chat_id in PENDING_WITHDRAWAL_KEYS and text and not text.startswith("/"):
        handle_withdrawal_key(chat_id, user, text)
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
        send_text(chat_id, "Hola. Soy Chaut, tu asistente para ahorrar en oro digital 🥇\n\nUsa /ahorros para empezar o /saldo para ver tu cuenta.")


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
        send_savings_menu(chat_id, "¿Cuánto quieres ahorrar hoy en oro digital 🥇?")
    elif data.startswith("ahorros:") and not account_exists(user.get("id", chat_id)):
        send_text(chat_id, "Con mucho gusto. Primero dime tu nombre para dejar tu cuenta bien organizada.")
        ask_name(chat_id)
    elif data == "ahorros:5000":
        create_checkout(chat_id, user, 5000)
    elif data == "ahorros:10000":
        create_checkout(chat_id, user, 10000)
    elif data == "ahorros:custom":
        PENDING_CUSTOM_AMOUNTS.add(chat_id)
        send_text(chat_id, "¿Cuánto quieres ahorrar?\n\nEscribe el monto en COP. Mínimo 5.000. Ejemplo: 25.000")
    elif data.startswith("paid:"):
        settle_order(chat_id, data.split(":", 1)[1])
    elif data == "saldo":
        send_balance(chat_id, user)
    elif data == "movimientos":
        send_movements(chat_id, user)
    elif data.startswith("withdraw:status:"):
        check_withdrawal_status(chat_id, data.rsplit(":", 1)[1])
    elif data == "withdraw:start":
        start_withdrawal(chat_id, user)
    elif data == "withdraw:all":
        ask_withdrawal_key(chat_id, user)
    elif data == "withdraw:custom":
        ask_partial_withdrawal_amount(chat_id, user)
    elif data == "withdraw:change_key":
        ask_withdrawal_key(chat_id, user)
    elif data == "withdraw:confirm":
        confirm_withdrawal(chat_id, user)
    elif data == "withdraw:cancel":
        PENDING_WITHDRAWAL_KEYS.pop(chat_id, None)
        PENDING_PARTIAL_WITHDRAWALS.discard(chat_id)
        send_text(chat_id, "Retiro cancelado.")


def handle_custom_amount(chat_id: int, user: dict[str, Any], text: str) -> None:
    amount = parse_cop_input(text)
    if amount is None:
        send_text(chat_id, "No pude leer ese monto. Escríbelo así, porfa: 25.000")
        return
    if amount < MIN_COP:
        send_text(chat_id, "El mínimo para ahorrar en oro digital 🥇 es 5.000 COP. Escribe otro monto, porfa.")
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
            send_savings_menu(chat_id, f"Qué gusto tenerte de vuelta, {name}\n\n¿Cuánto quieres ahorrar hoy en oro digital 🥇?")
        else:
            send_savings_menu(chat_id, f"Qué gusto tenerte de vuelta, {name}\n\n¿Cuánto quieres ahorrar hoy en oro digital 🥇?")
        return
    start_onboarding(chat_id)


def welcome_existing_user(chat_id: int, user: dict[str, Any]) -> None:
    account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
    name = account.get("display_name") or "de vuelta"
    send_savings_menu(chat_id, f"Qué gusto tenerte de vuelta, {name}\n\n¿Cuánto quieres ahorrar hoy en oro digital 🥇?")


def start_onboarding(chat_id: int) -> None:
    PENDING_NAMES[chat_id] = True
    send_text(
        chat_id,
        "Hola, qué gusto tenerte por aquí 🥇\n\nSoy Chaut, tu asistente para ahorrar en oro digital 🥇.\n\nPara crear tu cuenta, dime tu nombre y apellido.",
    )


def ensure_account_then_menu(chat_id: int, user: dict[str, Any]) -> None:
    if account_exists(user.get("id", chat_id)):
        account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
        name = account.get("display_name") or "de vuelta"
        send_savings_menu(chat_id, f"Qué gusto tenerte de vuelta, {name}. ¿Cuánto quieres ahorrar hoy en oro digital 🥇?")
    else:
        send_text(
            chat_id,
            "Hola, qué gusto tenerte por aquí. Para atenderte mejor, dime tu nombre y apellido.",
            buttons=[[{"text": "Registrar mi nombre", "callback_data": "register"}]],
        )
        PENDING_NAMES[chat_id] = True


def ask_name(chat_id: int) -> None:
    PENDING_NAMES[chat_id] = True
    send_text(chat_id, "Escríbeme tu nombre y apellido, porfa.\n\nEjemplo: Pepito Pérez")


def register_name(chat_id: int, user: dict[str, Any], display_name: str) -> None:
    if account_exists(user.get("id", chat_id)):
        PENDING_NAMES.pop(chat_id, None)
        welcome_existing_user(chat_id, user)
        return
    clean_name = " ".join(display_name.split())
    if len(clean_name) < 3:
        send_text(chat_id, "¿Me regalas tu nombre un poquito más completo, porfa? Nombre y apellido estaría perfecto.")
        return
    api("POST", "/accounts/identify", identity(chat_id, user, clean_name))
    PENDING_NAMES.pop(chat_id, None)
    send_text(
        chat_id,
        f"Listo, {clean_name}.\n\n¿Cuánto quieres ahorrar hoy?",
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


def send_savings_menu(chat_id: int, message: str = "¿Qué quieres hacer hoy?") -> None:
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
        send_text(chat_id, "El mínimo para ahorrar en oro digital 🥇 es 5.000 COP.")
        return
    send_text(chat_id, "Dame un momento, estoy generando tu referencia Bre-B.")
    account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
    payload = {
        "client_id": f"telegram:{user.get('id', chat_id)}",
        "identity": identity(chat_id, user, account.get("display_name")),
        "amount_cop": amount_cop,
        "method": "Bre-B",
        "expiration_minutes": PAYMENT_EXPIRATION_MINUTES,
    }
    checkout = api("POST", "/checkout", payload)
    external_id = checkout["external_id"]
    if checkout.get("checkout_status") != "ready" or not checkout.get("pay_to") or not checkout.get("pay_amount_cop"):
        send_text(
            chat_id,
            "No pude generar una llave Bre-B confiable en este momento. Intenta de nuevo en unos segundos, por favor.",
            buttons=[[{"text": "Intentar otra vez", "callback_data": f"ahorros:{amount_cop}"}], [{"text": "📊 Ver saldo", "callback_data": "saldo"}]],
        )
        return
    text = (
        "Listo. Haz la transferencia exacta por Bre-B:\n\n"
        "Monto: "
        f"{checkout.get('pay_amount_cop')} COP\n"
        f"Llave: {checkout.get('pay_to')}\n\n"
        f"Orden: {external_id}\n\n"
        f"Esta referencia vence en {checkout.get('expires_in_minutes') or PAYMENT_EXPIRATION_MINUTES} minutos.\n\n"
        "Cuando termines el pago, toca el botón para validar la transferencia y acreditar tu oro digital 🥇."
    )
    send_text(chat_id, text, buttons=[[{"text": "✅ Ya hice el pago", "callback_data": f"paid:{external_id}"}], [{"text": "📊 Ver saldo", "callback_data": "saldo"}]])


def settle_order(chat_id: int, external_id: str) -> None:
    if external_id in PENDING_SETTLEMENTS:
        send_text(chat_id, "Ya estoy validando ese pago. Dame un momento, por favor.")
        return
    PENDING_SETTLEMENTS.add(external_id)
    send_text(chat_id, "Validando tu pago. Dame un momento, por favor...")
    try:
        result = api("POST", f"/orders/{external_id}/settle-xaut?confirm=EXECUTE_HTX_XAUT_BUY")
    except Exception as exc:
        send_text(chat_id, f"Todavía no pude confirmar esa orden. Intenta de nuevo en un momento.\n\nDetalle: {friendly_api_error(exc)}")
        return
    finally:
        PENDING_SETTLEMENTS.discard(external_id)
    if not result.get("executed") and result.get("status") == "payment_not_confirmed":
        send_text(chat_id, "Todavía no veo el pago confirmado. Espera un poco y toca 'Ya hice el pago' otra vez.")
        return
    summary = result.get("user_summary") or {}
    message = summary.get("message") or "Compra procesada. Usa /saldo para ver tu oro digital 🥇."
    if "(" in message and "XAUT" in message:
        message = message.split("(", 1)[0].strip()
    message = message.replace("gramos de oro digital", "gramos de oro digital 🥇")
    send_text(chat_id, message)


def format_cop(value: float | int | None) -> str:
    if value is None:
        return "0"
    return f"{float(value):,.0f}"


def portfolio_for_user(chat_id: int, user: dict[str, Any], *, include_markup: bool = True) -> dict[str, Any] | None:
    if not account_exists(user.get("id", chat_id)):
        return None
    suffix = "" if include_markup else "?include_markup=false"
    return api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}/portfolio{suffix}")


def send_balance(chat_id: int, user: dict[str, Any]) -> None:
    if not account_exists(user.get("id", chat_id)):
        send_text(chat_id, "Todavía no tengo tu cuenta por aquí. Vamos a crearla en un momento.")
        ask_name(chat_id)
        return
    try:
        portfolio = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}/portfolio")
    except Exception:
        send_text(chat_id, "Aún no tienes oro digital 🥇 acreditado. Usa /ahorros para empezar.")
        return
    lines = ["Tu oro digital 🥇"]
    lines.append(f"{portfolio['gold_grams_net']:.12f} g")
    if portfolio.get("estimated_value_cop") is not None:
        lines.append(f"Valor hoy: {portfolio['estimated_value_cop']:,.0f} COP")
    lines.extend(
        [
            f"Invertido: {portfolio['cop_invested']:,.0f} COP",
            f"Movimientos: {portfolio['entries_count']}",
        ]
    )
    buttons = [[{"text": "🥇 Ahorrar más", "callback_data": "menu:ahorros"}, {"text": "📜 Movimientos", "callback_data": "movimientos"}]]
    if portfolio.get("gold_grams_net", 0) > 0:
        buttons.append([{"text": "Retirar oro 🥇", "callback_data": "withdraw:start"}])
    send_text(chat_id, "\n".join(lines), buttons=buttons)


def start_withdrawal(chat_id: int, user: dict[str, Any]) -> None:
    try:
        portfolio = portfolio_for_user(chat_id, user, include_markup=False)
    except Exception:
        portfolio = None
    if not portfolio or portfolio.get("gold_grams_net", 0) <= 0:
        send_text(chat_id, "Aún no tienes oro digital disponible para retirar.")
        return
    estimated_cop = portfolio.get("estimated_value_cop")
    lines = [
        "Retirar oro 🥇",
        "",
        f"Disponible: {portfolio['gold_grams_net']:.12f} g",
    ]
    if estimated_cop is not None:
        lines.append(f"Recibes aprox: {format_cop(estimated_cop)} COP")
    lines.append("\n¿Cuánto quieres retirar?")
    send_text(
        chat_id,
        "\n".join(lines),
        buttons=[
            [{"text": "Retirar todo", "callback_data": "withdraw:all"}, {"text": "Otro monto", "callback_data": "withdraw:custom"}],
            [{"text": "Cancelar", "callback_data": "withdraw:cancel"}],
        ],
    )


def ask_partial_withdrawal_amount(chat_id: int, user: dict[str, Any]) -> None:
    try:
        portfolio = portfolio_for_user(chat_id, user, include_markup=False)
    except Exception:
        portfolio = None
    if not portfolio or portfolio.get("gold_grams_net", 0) <= 0:
        send_text(chat_id, "Aún no tienes oro digital disponible para retirar.")
        return
    estimated_cop = portfolio.get("estimated_value_cop") or 0
    PENDING_PARTIAL_WITHDRAWALS.add(chat_id)
    send_text(
        chat_id,
        f"¿Cuánto quieres retirar?\n\nDisponible: {portfolio['gold_grams_net']:.12f} g"
        + (f" (~{format_cop(estimated_cop)} COP)" if estimated_cop else "")
        + "\n\nEscribe el monto en COP. Ejemplo: 50.000",
        buttons=[[{"text": "Cancelar", "callback_data": "withdraw:cancel"}]],
    )


def handle_partial_withdrawal_amount(chat_id: int, user: dict[str, Any], text: str) -> None:
    amount_cop = parse_cop_input(text)
    if amount_cop is None or amount_cop <= 0:
        send_text(chat_id, "No pude leer ese monto. Escríbelo así, porfa: 50.000")
        return
    PENDING_PARTIAL_WITHDRAWALS.discard(chat_id)
    try:
        portfolio = portfolio_for_user(chat_id, user, include_markup=False)
    except Exception:
        portfolio = None
    if not portfolio or portfolio.get("gold_grams_net", 0) <= 0:
        send_text(chat_id, "Aún no tienes oro digital disponible para retirar.")
        return
    estimated_cop = portfolio.get("estimated_value_cop") or 0
    if estimated_cop > 0 and amount_cop >= estimated_cop:
        # Requesting all or more → treat as full withdrawal
        ask_withdrawal_key(chat_id, user)
        return
    # Calculate proportional XAUT
    if estimated_cop <= 0:
        send_text(chat_id, "No pude calcular el valor de tu oro. Intenta más tarde.")
        return
    ratio = amount_cop / estimated_cop
    partial_xaut = portfolio["xaut_net"] * ratio
    partial_grams = portfolio["gold_grams_net"] * ratio
    PENDING_WITHDRAWAL_KEYS[chat_id] = {
        "portfolio": portfolio,
        "partial_xaut": partial_xaut,
        "partial_grams": partial_grams,
        "partial_cop": amount_cop,
        "amount_mode": "partial",
    }
    send_text(
        chat_id,
        f"Retiro parcial\n\nMonto: {format_cop(amount_cop)} COP\n"
        f"Equivalente: {partial_grams:.12f} g de oro\n\n"
        "¿A qué llave Bre-B enviamos el dinero?\n\nEscribe tu llave Bre-B.",
        buttons=[[{"text": "Cancelar", "callback_data": "withdraw:cancel"}]],
    )


def ask_withdrawal_key(chat_id: int, user: dict[str, Any]) -> None:
    try:
        portfolio = portfolio_for_user(chat_id, user, include_markup=False)
    except Exception:
        portfolio = None
    if not portfolio or portfolio.get("gold_grams_net", 0) <= 0:
        send_text(chat_id, "Aún no tienes oro digital disponible para retirar.")
        return
    PENDING_WITHDRAWAL_KEYS[chat_id] = {"portfolio": portfolio}
    send_text(
        chat_id,
        "¿A qué llave Bre-B enviamos el dinero?\n\nEscribe tu llave Bre-B.",
        buttons=[[{"text": "Cancelar", "callback_data": "withdraw:cancel"}]],
    )


def handle_withdrawal_key(chat_id: int, user: dict[str, Any], text: str) -> None:
    request = PENDING_WITHDRAWAL_KEYS.get(chat_id) or {}
    breb_key = " ".join(text.split())
    if len(breb_key) < 3:
        send_text(chat_id, "Esa llave se ve muy corta. Escríbela de nuevo, porfa.")
        return
    try:
        portfolio = portfolio_for_user(chat_id, user, include_markup=False) or request.get("portfolio")
    except Exception:
        portfolio = request.get("portfolio")
    if not portfolio or portfolio.get("gold_grams_net", 0) <= 0:
        PENDING_WITHDRAWAL_KEYS.pop(chat_id, None)
        send_text(chat_id, "Aún no tienes oro digital disponible para retirar.")
        return
    # Preserve partial withdrawal info if coming from custom amount flow
    partial_xaut = request.get("partial_xaut")
    partial_grams = request.get("partial_grams")
    partial_cop = request.get("partial_cop")
    amount_mode = request.get("amount_mode", "all")
    request = {"portfolio": portfolio, "breb_key": breb_key, "amount_mode": amount_mode}
    if partial_xaut is not None:
        request["partial_xaut"] = partial_xaut
        request["partial_grams"] = partial_grams
        request["partial_cop"] = partial_cop
    PENDING_WITHDRAWAL_KEYS[chat_id] = request
    lines = ["Confirmar retiro", ""]
    if amount_mode == "partial" and partial_cop is not None:
        lines.append(f"Monto: {format_cop(partial_cop)} COP")
        lines.append(f"Equivalente: {partial_grams:.12f} g de oro")
    else:
        estimated_cop = portfolio.get("estimated_value_cop")
        if estimated_cop is not None:
            lines.append(f"Recibes aprox: {format_cop(estimated_cop)} COP")
    lines.extend([f"Llave Bre-B: {breb_key}", "", "¿Confirmas?"])
    send_text(
        chat_id,
        "\n".join(lines),
        buttons=[
            [{"text": "Confirmar", "callback_data": "withdraw:confirm"}],
            [{"text": "Cambiar llave", "callback_data": "withdraw:change_key"}, {"text": "Cancelar", "callback_data": "withdraw:cancel"}],
        ],
    )


def confirm_withdrawal(chat_id: int, user: dict[str, Any]) -> None:
    request = PENDING_WITHDRAWAL_KEYS.pop(chat_id, None)
    if not request or not request.get("breb_key"):
        ask_withdrawal_key(chat_id, user)
        return
    try:
        account = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}")
        amount_mode = request.get("amount_mode", "all")
        payload = {
            "customer_id": account["customer_id"],
            "provider": "telegram",
            "provider_user_id": str(user.get("id", chat_id)),
            "chat_id": str(chat_id),
            "breb_key": request["breb_key"],
            "amount_mode": amount_mode,
            "portfolio_snapshot": request.get("portfolio", {}),
        }
        if amount_mode == "partial" and request.get("partial_xaut") is not None:
            payload["portfolio_snapshot"] = {
                **request.get("portfolio", {}),
                "xaut_net": request["partial_xaut"],
                "gold_grams_net": request["partial_grams"],
            }
        withdrawal = api("POST", "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL", payload)
    except Exception as exc:
        send_text(chat_id, f"No pude registrar el retiro. Intenta de nuevo en un momento.\n\nDetalle: {friendly_api_error(exc)}")
        return
    estimated_cop = withdrawal.get("estimated_value_cop")
    lines = ["Retiro recibido ✅"]
    if estimated_cop is not None:
        lines.append(f"Recibes aprox: {format_cop(estimated_cop)} COP")
    if withdrawal.get("status") == "xaut_sold":
        lines.append("Ya vendimos tu oro digital. Ahora haremos el pago a tu llave Bre-B.")
    elif withdrawal.get("status") == "failed":
        lines.append("No pudimos procesar la venta en este momento. Te avisaremos cuando lo revisemos.")
    else:
        lines.append("Estamos procesando la venta de tu oro digital. Te avisaremos cuando enviemos el pago.")
    send_text(chat_id, "\n".join(lines), buttons=[[{"text": "Ver estado", "callback_data": f"withdraw:status:{withdrawal['withdrawal_id']}"}], [{"text": "📊 Ver saldo", "callback_data": "saldo"}]])



def check_withdrawal_status(chat_id: int, withdrawal_id: str) -> None:
    withdrawal = api("GET", f"/withdrawals/{withdrawal_id}")
    if withdrawal.get("status") == "completed":
        notify_withdrawal_completed(chat_id, withdrawal)
    elif withdrawal.get("status") == "failed":
        send_text(chat_id, f"El retiro {withdrawal_id} quedó fallido. Lo revisaremos manualmente.")
    elif withdrawal.get("status") == "xaut_sold":
        send_text(chat_id, "Ya vendimos tu oro digital. Estamos preparando el pago manual por Bre-B.")
    else:
        send_text(chat_id, "Estamos procesando la venta de tu oro digital.")


def notify_withdrawal_completed(chat_id: int, withdrawal: dict[str, Any]) -> None:
    withdrawal_id = withdrawal.get("withdrawal_id")
    if withdrawal_id in NOTIFIED_WITHDRAWALS:
        return
    NOTIFIED_WITHDRAWALS.add(withdrawal_id)
    send_text(
        chat_id,
        f"Te enviamos {format_cop(withdrawal.get('cop_paid'))} COP a tu llave Bre-B {withdrawal.get('breb_key')}. Ref: {withdrawal.get('cop_tx_ref')}",
        buttons=[[{"text": "📊 Ver saldo", "callback_data": "saldo"}]],
    )

def send_movements(chat_id: int, user: dict[str, Any]) -> None:
    if not account_exists(user.get("id", chat_id)):
        send_text(chat_id, "Todavía no tengo tu cuenta por aquí. Vamos a crearla en un momento.")
        ask_name(chat_id)
        return
    try:
        portfolio = api("GET", f"/accounts/by-identity/telegram/{user.get('id', chat_id)}/portfolio")
    except Exception:
        send_text(chat_id, "Aún no tienes movimientos.")
        return
    entries = list(reversed(portfolio.get("entries", [])))[:5]
    if not entries:
        send_text(chat_id, "Aún no tienes movimientos.")
        return
    lines = ["Últimos movimientos:"]
    for entry in entries:
        movement_date = format_movement_date(entry.get("created_at"))
        lines.append(f"- {movement_date} · {entry['gold_grams']:.12f} g oro digital 🥇 / {entry['cop_gross']:,.0f} COP")
    send_text(chat_id, "\n".join(lines))


def send_order_status(chat_id: int, external_id: str) -> None:
    order = api("GET", f"/orders/{external_id}")
    send_text(chat_id, f"Orden {external_id}\nPago: {order['payment_status']}\nXAUT: {order['conversion_status']}\nCOP: {order['amount_cop_gross']:,.0f}")


def format_movement_date(value: str | None) -> str:
    if not value:
        return "Movimiento"
    months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    try:
        month_index = int(value[5:7]) - 1
        return f"{int(value[8:10])} {months[month_index]}"
    except (ValueError, IndexError):
        return "Movimiento"


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
        return "Tu compra ya está en proceso. Espera un momento, por favor."
    if "conversion_status=settled" in text:
        return "Esta orden ya fue procesada. Usa /saldo para ver tu oro digital 🥇."
    if "balance is not enough" in text or "balance-insufficient" in text:
        return "El pago fue confirmado. Estamos acreditando tu oro digital 🥇."
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
