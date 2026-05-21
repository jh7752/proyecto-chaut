from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from .store import OrderStore


SETTLED_STATES = {"settled"}
LEGACY_STATES = {"voided", "failed"}
EXPIRED_STATES = {"expired"}
ATTENTION_PAYMENT_STATES = {"ambiguous", "payment_reconciliation_ambiguous"}
ATTENTION_CONVERSION_STATES = {"executing", "submitted"}


def require_admin(request: Request, token: str | None) -> None:
    if token and request.query_params.get("token") != token and request.headers.get("x-admin-token") != token:
        raise HTTPException(status_code=401, detail="Admin token required")


def render_admin(title: str, body: str, token: str | None = None) -> HTMLResponse:
    token_qs = f"?token={escape(token)}" if token else ""
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Chaut Admin</title>
  <style>
    :root {{
      --ink:#182116; --deep:#24341f; --leaf:#4c6a3d; --leaf-2:#819b62;
      --gold:#c99633; --gold-2:#f3d782; --paper:#fff9e8; --paper-soft:rgba(255,249,232,.78);
      --mist:#edf0dc; --line:rgba(40,58,31,.14); --line-strong:rgba(40,58,31,.24);
      --ok:#247a53; --warn:#a66c13; --bad:#b54535; --blue:#2e617d;
      --shadow:0 26px 80px rgba(27,44,23,.16); --soft-shadow:0 14px 40px rgba(27,44,23,.09);
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0; color:var(--ink); font-family: ui-serif, Georgia, Cambria, 'Times New Roman', serif;
      background:#eef0de; font-size:15px;
    }}
    body:before {{
      content:""; position:fixed; inset:0; z-index:-3;
      background:
        radial-gradient(circle at 8% 12%, rgba(243,215,130,.95) 0 9%, transparent 28%),
        radial-gradient(circle at 88% -4%, rgba(145,173,105,.8) 0 13%, transparent 34%),
        radial-gradient(circle at 70% 92%, rgba(198,224,177,.72) 0 11%, transparent 32%),
        linear-gradient(135deg,#fff7dc 0%,#edf1df 42%,#dce6cc 100%);
    }}
    body:after {{
      content:""; position:fixed; inset:0; z-index:-2; pointer-events:none; opacity:.2;
      background-image:
        linear-gradient(90deg, rgba(36,52,31,.23) 1px, transparent 1px),
        linear-gradient(rgba(36,52,31,.18) 1px, transparent 1px);
      background-size:42px 42px; mask-image:linear-gradient(to bottom, black, transparent 76%);
    }}
    .grain {{ position:fixed; inset:0; z-index:-1; pointer-events:none; opacity:.18; background:repeating-radial-gradient(circle at 20% 30%, rgba(24,33,22,.11) 0 1px, transparent 1px 4px); mix-blend-mode:multiply; }}
    .shell {{ width:min(1220px,calc(100% - 32px)); margin:0 auto; }}
    header {{ padding:28px 0 16px; display:grid; grid-template-columns:1fr auto; align-items:end; gap:20px; }}
    .brand {{ display:flex; align-items:center; gap:16px; }}
    .mark {{ width:58px; height:58px; border-radius:20px; display:grid; place-items:center; color:#2b3117; font-weight:900; letter-spacing:-.08em; background:conic-gradient(from 210deg,#f4d776,#bb8430,#fff2b2,#7f9a5b,#f4d776); box-shadow:inset 0 0 0 1px rgba(255,255,255,.5), 0 18px 38px rgba(121,86,28,.22); }}
    .eyebrow {{ margin:0 0 7px; color:var(--gold); text-transform:uppercase; letter-spacing:.18em; font-size:11px; font-weight:800; }}
    h1 {{ margin:0; font-size:clamp(34px,5.6vw,74px); line-height:.86; letter-spacing:-.07em; text-wrap:balance; }}
    .subtitle {{ margin:10px 0 0; color:var(--leaf); font-size:16px; }}
    .statusbar {{ display:flex; gap:9px; flex-wrap:wrap; justify-content:flex-end; }}
    .badge {{ border:1px solid var(--line); border-radius:999px; padding:10px 13px; background:rgba(255,255,255,.56); color:var(--leaf); white-space:nowrap; box-shadow:var(--soft-shadow); }}
    nav {{ position:sticky; top:0; z-index:10; display:flex; gap:10px; padding:10px 0 22px; flex-wrap:wrap; backdrop-filter:blur(16px); }}
    nav a,.button {{
      color:var(--ink); text-decoration:none; border:1px solid var(--line); padding:10px 14px; border-radius:999px;
      background:rgba(255,255,255,.66); box-shadow:0 8px 26px rgba(39,65,43,.06); transition:.18s ease;
    }}
    nav a:hover,.button:hover {{ border-color:rgba(201,150,51,.62); transform:translateY(-1px); background:rgba(255,249,232,.88); }}
    main {{ padding:0 0 54px; }}
    .hero {{ position:relative; overflow:hidden; border:1px solid var(--line); background:linear-gradient(135deg,rgba(255,255,255,.78),rgba(255,248,222,.62)); border-radius:34px; padding:22px; box-shadow:var(--shadow); margin-bottom:18px; }}
    .hero:before {{ content:""; position:absolute; right:-70px; top:-90px; width:220px; height:220px; border-radius:50%; background:radial-gradient(circle, rgba(201,150,51,.18), transparent 68%); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }}
    .card {{
      position:relative; background:var(--paper-soft); border:1px solid var(--line); border-radius:26px; padding:18px;
      box-shadow:var(--soft-shadow); backdrop-filter:blur(12px); overflow:hidden;
    }}
    .card:after {{ content:""; position:absolute; inset:auto 14px 0; height:3px; background:linear-gradient(90deg,transparent,var(--gold-2),transparent); opacity:.55; }}
    .metric {{ font-size:clamp(24px,3vw,40px); font-weight:900; letter-spacing:-.055em; overflow-wrap:anywhere; line-height:.96; }}
    .muted {{ color:#75836b; }}
    h2 {{ margin:30px 0 12px; font-size:28px; letter-spacing:-.045em; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:12px; margin:30px 0 12px; }}
    .section-head h2 {{ margin:0; }}
    .table-wrap {{ overflow:auto; border-radius:24px; box-shadow:var(--shadow); border:1px solid var(--line); background:rgba(255,249,232,.58); }}
    table {{ width:100%; border-collapse:collapse; background:rgba(255,252,240,.86); min-width:780px; }}
    th,td {{ padding:14px 15px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; }}
    th {{ position:sticky; top:0; z-index:1; font-size:10px; text-transform:uppercase; color:#7d8b70; letter-spacing:.14em; background:rgba(255,255,255,.8); backdrop-filter:blur(10px); }}
    tr:hover td {{ background:rgba(255,241,189,.38); }}
    tr:last-child td {{ border-bottom:0; }}
    a {{ color:#294f35; font-weight:700; }}
    code {{ background:#eef2e8; padding:4px 7px; border-radius:9px; color:#274a33; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:.92em; }}
    .order-id {{ display:inline-flex; align-items:center; gap:7px; }}
    .order-id:before {{ content:""; width:8px; height:8px; border-radius:50%; background:var(--gold); box-shadow:0 0 0 4px rgba(201,150,51,.14); }}
    .pill {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:6px 10px; font-size:12px; font-weight:800; background:#edf1e7; color:var(--leaf); white-space:nowrap; }}
    .pill:before {{ content:""; width:7px; height:7px; border-radius:50%; background:currentColor; }}
    .ok {{ color:var(--ok); }} .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }} .info {{ color:var(--blue); }}
    .pill.ok {{ background:#dff2e8; color:var(--ok); }} .pill.bad {{ background:#f8e3dd; color:var(--bad); }} .pill.warn {{ background:#fff0c4; color:#94661b; }} .pill.info {{ background:#dfeef4; color:var(--blue); }}
    .legacy {{ opacity:.58; }}
    .money {{ font-weight:850; letter-spacing:-.02em; white-space:nowrap; }}
    .date {{ min-width:190px; }}
    pre {{ white-space:pre-wrap; max-height:360px; overflow:auto; background:#132018; color:#f7f0d4; padding:14px; border-radius:16px; font-size:12px; line-height:1.45; }}
    form.inline {{ display:inline-flex; margin:4px 6px 4px 0; }}
    button.action {{ cursor:pointer; border:1px solid var(--line); border-radius:999px; padding:10px 14px; background:rgba(255,255,255,.74); color:var(--ink); font-weight:800; box-shadow:0 8px 26px rgba(39,65,43,.06); }}
    button.action:hover {{ border-color:rgba(201,150,51,.62); transform:translateY(-1px); background:rgba(255,249,232,.9); }}
    button.danger {{ color:var(--bad); border-color:rgba(181,69,53,.26); }}
    .actions {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:14px; }}
    .split {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,.45fr); gap:16px; align-items:start; }}
    ul.clean {{ margin:0; padding-left:18px; }}
    .empty {{ text-align:center; padding:28px; color:#75836b; }}
    @media (max-width:760px) {{
      .shell {{ width:min(100% - 22px,1180px); }} header {{ align-items:start; grid-template-columns:1fr; }} .brand {{ align-items:flex-start; }} .mark {{ width:48px; height:48px; border-radius:16px; }} .statusbar {{ justify-content:flex-start; }} .split {{ grid-template-columns:1fr; }} table {{ min-width:720px; }} th,td {{ padding:12px; }}
    }}
  </style>
</head>
<body>
  <div class="grain"></div>
  <div class="shell">
    <header>
      <div class="brand"><div class="mark">Au</div><div><p class="eyebrow">Chaut Admin</p><h1>{escape(title)}</h1><p class="subtitle">Control operativo de ahorros en oro digital</p></div></div>
      <div class="statusbar"><div class="badge">HTX activo</div><div class="badge">Bre-B / Coinsenda</div></div>
    </header>
    <nav><a href="/admin{token_qs}">Dashboard</a><a href="/admin/orders{token_qs}">Ordenes</a><a href="/admin/accounts{token_qs}">Usuarios</a></nav>
    <main>{body}</main>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


def admin_dashboard(store: OrderStore, token: str | None = None) -> HTMLResponse:
    orders = store.list_orders(200)
    accounts = store.list_accounts(200)
    total_cop = total_xaut = total_grams = 0.0
    total_entries = 0
    for account in accounts:
        portfolio = store.get_portfolio(account.customer_id)
        total_cop += portfolio.cop_invested
        total_xaut += portfolio.xaut_net
        total_grams += portfolio.gold_grams_net
        total_entries += portfolio.entries_count
    active_orders = [order for order in orders if order.conversion_status not in LEGACY_STATES]
    attention_orders = [order for order in active_orders if needs_attention(order)]
    pending = sum(1 for order in active_orders if order.payment_status not in {"confirmed", "expired"})
    expired = sum(1 for order in active_orders if order.payment_status in EXPIRED_STATES)
    settled = sum(1 for order in active_orders if order.conversion_status in SETTLED_STATES)
    body = f"""
    <section class="hero">
      <div class="grid">
        {metric_card("Usuarios", len(accounts))}
        {metric_card("Ordenes activas", len(active_orders))}
        {metric_card("Pendientes pago", pending)}
        {metric_card("Expiradas", expired)}
        {metric_card("Atencion", len(attention_orders))}
        {metric_card("Settled", settled)}
        {metric_card("COP invertido", f"{total_cop:,.0f}")}
      </div>
    </section>
    <section class="grid">
      <div class="card"><div class="muted">XAUT neto custodiado</div><div class="metric">{total_xaut:.18f}</div><p class="muted">Basado en ledger, no en ordenes de prueba.</p></div>
      <div class="card"><div class="muted">Oro digital acreditado</div><div class="metric">{total_grams:.12f} g</div><p class="muted">Suma de compras settled con ledger entry.</p></div>
      <div class="card"><div class="muted">Movimientos reales</div><div class="metric">{total_entries}</div><p class="muted">Solo compras con ledger entry suman al saldo.</p></div>
    </section>
    <div class="section-head"><h2>Atencion operativa</h2><span class="badge">Revisar primero</span></div>
    {orders_table(attention_orders[:12], token, events_by_order=events_map(store, attention_orders[:12]))}
    <div class="section-head"><h2>Ordenes relevantes</h2><span class="badge">Ultimas 12</span></div>
    {orders_table(active_orders[:12], token, events_by_order=events_map(store, active_orders[:12]))}
    <div class="section-head"><h2>Legado / pruebas</h2><span class="muted">Auditoria</span></div>
    <p class="muted">Ordenes voided o fallidas se conservan para auditoria, pero no afectan saldos.</p>
    {orders_table([order for order in orders if order.conversion_status in LEGACY_STATES][:8], token, legacy=True, events_by_order=events_map(store, [order for order in orders if order.conversion_status in LEGACY_STATES][:8]))}
    """
    return render_admin("Dashboard", body, token)


def admin_orders(store: OrderStore, token: str | None = None) -> HTMLResponse:
    orders = store.list_orders(200)
    active = [order for order in orders if order.conversion_status not in LEGACY_STATES]
    attention = [order for order in active if needs_attention(order)]
    paid = [order for order in active if order.payment_status == "confirmed"]
    expired = [order for order in active if order.payment_status in EXPIRED_STATES]
    unpaid = [order for order in active if order.payment_status not in {"confirmed", "expired"}]
    legacy = [order for order in orders if order.conversion_status in LEGACY_STATES]
    body = f"""
    <section class="hero"><div class="grid">{metric_card("Atencion", len(attention))}{metric_card("Pagadas", len(paid))}{metric_card("Pendientes vivas", len(unpaid))}{metric_card("Expiradas", len(expired))}{metric_card("Legado", len(legacy))}{metric_card("Total", len(orders))}</div></section>
    <div class="section-head"><h2>Atencion operativa</h2><span class="badge">Revisar primero</span></div><p class="muted">Pagos ambiguos, compras en ejecucion o pagos confirmados sin XAUT settled.</p>{orders_table(attention, token, events_by_order=events_map(store, attention))}
    <div class="section-head"><h2>Pagadas / operables</h2><span class="badge">Pago confirmado</span></div><p class="muted">Ordenes con pago confirmado. Si XAUT dice not_started, falta ejecutar settlement o es una orden anterior a la trazabilidad fina.</p>{orders_table(paid, token, events_by_order=events_map(store, paid))}
    <div class="section-head"><h2>Pendientes vivas</h2><span class="badge">Dentro de ventana</span></div><p class="muted">PaymentRequests que aun no han confirmado pago y no han expirado.</p>{orders_table(unpaid, token, compact=True, events_by_order=events_map(store, unpaid))}
    <div class="section-head"><h2>Expiradas</h2><span class="muted">No afectan saldo</span></div>{orders_table(expired, token, compact=True, legacy=True, events_by_order=events_map(store, expired))}
    <div class="section-head"><h2>Legado / pruebas</h2><span class="muted">Historico</span></div>{orders_table(legacy, token, legacy=True, events_by_order=events_map(store, legacy))}
    """
    return render_admin("Ordenes", body, token)


def admin_order_detail(store: OrderStore, external_id: str, token: str | None = None) -> HTMLResponse:
    order = store.get_order(external_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    events = store.list_events(external_id)
    portfolio_link = ""
    if order.customer_id:
        portfolio_link = f'<a class="button" href="/admin/accounts/{escape(order.customer_id)}{_token_qs(token)}">Ver usuario</a>'
    body = f"""
    <div class="split">
      <div class="card">
        <p class="muted">Orden</p><div class="metric"><code>{escape(order.external_id)}</code></div>
        <p><b>Usuario:</b> <code>{escape(order.customer_id or '-')}</code></p>
        <p><b>Pago:</b> {status_pill(order.payment_status)}</p>
        <p><b>Conversion:</b> {conversion_pill(order.conversion_status)}</p>
        {portfolio_link}
        {admin_action_panel(order, token)}
      </div>
      <div class="card">
        <p class="muted">Monto</p>
        <div class="metric">{order.amount_cop_gross:,.0f} COP</div>
        <p><b>USDT:</b> {order.payment_amount or 0}</p>
        <p><b>Creada:</b> {format_bogota_time(order.created_at)}</p>
      </div>
    </div>
    <div class="section-head"><h2>Timeline de eventos</h2><span class="badge">{len(events)} eventos</span></div>
    <div class="table-wrap"><table><tr><th>Fecha</th><th>Tipo</th><th>Payload</th></tr>
    {''.join(f'<tr><td class="date">{format_bogota_time(event.created_at)}</td><td><code>{escape(event.event_type)}</code></td><td><pre>{escape(str(event.payload))}</pre></td></tr>' for event in events)}
    </table></div>
    """
    return render_admin("Detalle Orden", body, token)


def admin_accounts(store: OrderStore, token: str | None = None) -> HTMLResponse:
    rows = []
    for account in store.list_accounts(200):
        portfolio = store.get_portfolio(account.customer_id)
        rows.append(
            f"<tr><td><a class='order-id' href='/admin/accounts/{escape(account.customer_id)}{_token_qs(token)}'><code>{escape(account.customer_id)}</code></a></td>"
            f"<td>{escape(account.display_name or '-')}</td><td>{portfolio.entries_count}</td><td class='money'>{portfolio.cop_invested:,.0f}</td>"
            f"<td>{portfolio.xaut_net:.18f}</td><td>{portfolio.gold_grams_net:.12f}</td></tr>"
        )
    body = "<div class='table-wrap'><table><tr><th>Usuario</th><th>Nombre</th><th>Movs</th><th>COP</th><th>XAUT</th><th>Gramos</th></tr>" + "".join(rows) + "</table></div>"
    return render_admin("Usuarios", body, token)


def admin_account_detail(store: OrderStore, customer_id: str, token: str | None = None) -> HTMLResponse:
    account = store.get_account(customer_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    portfolio = store.get_portfolio(customer_id)
    entries = "".join(
        f"<tr><td class='date'>{format_bogota_time(entry.created_at)}</td><td><a class='order-id' href='/admin/orders/{escape(entry.external_id)}{_token_qs(token)}'><code>{escape(entry.external_id)}</code></a></td><td class='money'>{entry.cop_gross:,.0f}</td><td>{entry.usdt_spent:.12f}</td><td>{entry.amount:.18f}</td><td>{entry.gold_grams:.12f}</td></tr>"
        for entry in portfolio.entries
    )
    identities = "".join(f"<li>{escape(identity.provider)}: <code>{escape(identity.provider_user_id)}</code></li>" for identity in account.identities)
    body = f"""
    <section class="hero"><div class="grid">
      {metric_card("COP invertido", f"{portfolio.cop_invested:,.0f}")}
      {metric_card("XAUT neto", f"{portfolio.xaut_net:.18f}")}
      {metric_card("Gramos oro", f"{portfolio.gold_grams_net:.12f}")}
    </div></section>
    <div class="card"><p><b>Usuario:</b> <code>{escape(account.customer_id)}</code></p><p><b>Nombre:</b> {escape(account.display_name or '-')}</p><ul class="clean">{identities}</ul></div>
    <div class="section-head"><h2>Ledger</h2><span class="badge">{portfolio.entries_count} movimientos</span></div><div class="table-wrap"><table><tr><th>Fecha</th><th>Orden</th><th>COP</th><th>USDT</th><th>XAUT</th><th>Gramos</th></tr>{entries}</table></div>
    """
    return render_admin("Usuario", body, token)


def admin_action_panel(order, token: str | None = None) -> str:
    token_part = f"&token={escape(token)}" if token else ""
    external_id = escape(order.external_id)
    actions = [
        f'<form class="inline" method="post" action="/admin/orders/{external_id}/reconcile?redirect=detail{token_part}"><button class="action" type="submit">Revisar pago</button></form>',
        f'<form class="inline" method="post" action="/admin/orders/{external_id}/prepare-xaut?redirect=detail{token_part}"><button class="action" type="submit">Preparar XAUT</button></form>',
        f'<form class="inline" method="post" action="/admin/orders/{external_id}/mark-attention?redirect=detail{token_part}"><button class="action" type="submit">Marcar atencion</button></form>',
    ]
    if order.payment_status == "confirmed" and order.conversion_status not in SETTLED_STATES | LEGACY_STATES:
        actions.append(
            f'<form class="inline" method="post" action="/admin/orders/{external_id}/settle-xaut?redirect=detail&confirm=EXECUTE_HTX_XAUT_BUY{token_part}"><button class="action danger" type="submit">Ejecutar settlement</button></form>'
        )
    return '<div class="actions">' + ''.join(actions) + '</div>'


def events_map(store: OrderStore, orders) -> dict[str, list]:
    return {order.external_id: store.list_events(order.external_id) for order in orders}


def orders_table(orders, token: str | None = None, legacy: bool = False, compact: bool = False, events_by_order: dict[str, list] | None = None) -> str:
    rows = []
    for order in orders:
        row_class = " class='legacy'" if legacy else ""
        customer = "-" if compact else escape(order.customer_id or "-")
        row_events = (events_by_order or {}).get(order.external_id, [])
        date_label, main_date, secondary_label, secondary_date = order_date_context(order, row_events)
        rows.append(
            f"<tr{row_class}><td><a class='order-id' href='/admin/orders/{escape(order.external_id)}{_token_qs(token)}'><code>{escape(order.external_id)}</code></a></td>"
            f"<td><code>{customer}</code></td><td class='money'>{order.amount_cop_gross:,.0f}</td><td>{order.payment_amount or ''}</td>"
            f"<td>{status_pill(order.payment_status)}</td><td>{conversion_pill(order.conversion_status)}</td>"
            f"<td>{attention_pill(order)}</td>"
            f"<td>{admin_action_panel(order, token)}</td>"
            f"<td class='date'>{escape(date_label)}: {format_bogota_time(main_date)}<br><span class='muted'>{escape(secondary_label)}: {format_bogota_time(secondary_date)}</span></td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='9' class='empty'>Sin registros.</td></tr>")
    return "<div class='table-wrap'><table><tr><th>Orden</th><th>Usuario</th><th>COP</th><th>USDT</th><th>Pago</th><th>XAUT</th><th>Operacion</th><th>Acciones</th><th>Fecha operativa</th></tr>" + "".join(rows) + "</table></div>"


def order_date_context(order, events: list) -> tuple[str, str, str, str]:
    filled_time = _order_filled_time(order)
    if filled_time:
        return "Compra", filled_time, "Creada", order.created_at
    expired_at = _order_expired_time(events)
    if order.payment_status in EXPIRED_STATES and expired_at:
        return "Expira", expired_at, "Marcada", order.updated_at or order.created_at
    if order.updated_at:
        return "Actualizada", order.updated_at, "Creada", order.created_at
    return "Creada", order.created_at, "Creada", order.created_at


def _order_filled_time(order) -> str | None:
    return getattr(order, "ledger_entry_created_at", None)


def _order_expired_time(events: list) -> str | None:
    for event in reversed(events):
        if event.event_type == "payment.expired":
            return event.payload.get("expired_at") or event.created_at
    return None


def needs_attention(order) -> bool:
    if order.payment_status in ATTENTION_PAYMENT_STATES:
        return True
    if order.conversion_status in ATTENTION_CONVERSION_STATES:
        return True
    return order.payment_status == "confirmed" and order.conversion_status not in SETTLED_STATES | LEGACY_STATES


def attention_pill(order) -> str:
    if needs_attention(order):
        return '<span class="pill bad">revisar</span>'
    if order.conversion_status in SETTLED_STATES:
        return '<span class="pill ok">ok</span>'
    if order.payment_status in EXPIRED_STATES:
        return '<span class="pill info">expirada</span>'
    return '<span class="pill warn">normal</span>'


def metric_card(label: str, value) -> str:
    return f'<div class="card"><div class="muted">{escape(str(label))}</div><div class="metric">{escape(str(value))}</div></div>'


def status_pill(text: str) -> str:
    cls = "ok" if text == "confirmed" else "info" if text == "expired" else "warn"
    return f'<span class="pill {cls}">{escape(text)}</span>'


def conversion_pill(text: str) -> str:
    cls = "ok" if text == "settled" else "bad" if text in LEGACY_STATES else "warn"
    return f'<span class="pill {cls}">{escape(text)}</span>'


def _token_qs(token: str | None) -> str:
    return f"?token={escape(token)}" if token else ""


def format_bogota_time(value: str) -> str:
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(timezone(timedelta(hours=-5)))
        return escape(local.strftime("%Y-%m-%d %I:%M %p GMT-5"))
    except Exception:
        return escape(value)
