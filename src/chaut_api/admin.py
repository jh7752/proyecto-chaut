from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from .store import OrderStore


SETTLED_STATES = {"settled"}
LEGACY_STATES = {"voided", "failed"}


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
      --obsidian:#152018; --moss:#31543e; --sage:#87977d; --cream:#fbf5df;
      --paper:rgba(255,252,240,.82); --line:rgba(49,84,62,.16); --gold:#bd8a32;
      --mint:#2d8c63; --ember:#b24a36; --shadow:0 24px 80px rgba(26,47,31,.14);
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--obsidian); font-family: Georgia, 'Times New Roman', serif; background:#eef1df; }}
    body:before {{ content:""; position:fixed; inset:0; z-index:-2; background:radial-gradient(circle at 12% 8%,#ffe9a9 0 12%,transparent 32%),radial-gradient(circle at 85% 0,#c7e0b4 0 10%,transparent 30%),linear-gradient(135deg,#fbf4dc 0%,#e7eee0 46%,#d9e1ce 100%); }}
    body:after {{ content:""; position:fixed; inset:0; z-index:-1; opacity:.16; background-image:linear-gradient(90deg,var(--moss) 1px,transparent 1px),linear-gradient(var(--moss) 1px,transparent 1px); background-size:44px 44px; mask-image:linear-gradient(to bottom,black,transparent 78%); }}
    .shell {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; }}
    header {{ padding:34px 0 18px; display:flex; justify-content:space-between; align-items:flex-end; gap:18px; }}
    h1 {{ margin:0; font-size:clamp(34px,5vw,64px); line-height:.9; letter-spacing:-.06em; }}
    .eyebrow {{ margin:0 0 8px; color:var(--gold); text-transform:uppercase; letter-spacing:.16em; font-size:12px; font-weight:700; }}
    .subtitle {{ margin:10px 0 0; color:var(--moss); font-size:17px; }}
    .badge {{ border:1px solid var(--line); border-radius:999px; padding:10px 14px; background:rgba(255,255,255,.52); color:var(--moss); white-space:nowrap; }}
    nav {{ display:flex; gap:10px; padding:0 0 26px; flex-wrap:wrap; }}
    nav a,.button {{ color:var(--obsidian); text-decoration:none; border:1px solid var(--line); padding:10px 14px; border-radius:999px; background:rgba(255,255,255,.68); box-shadow:0 8px 26px rgba(39,65,43,.06); }}
    nav a:hover,.button:hover {{ border-color:rgba(189,138,50,.55); transform:translateY(-1px); }}
    main {{ padding:0 0 48px; }}
    .hero {{ border:1px solid var(--line); background:linear-gradient(135deg,rgba(255,255,255,.78),rgba(255,248,222,.62)); border-radius:30px; padding:24px; box-shadow:var(--shadow); margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; }}
    .card {{ background:var(--paper); border:1px solid var(--line); border-radius:24px; padding:18px; box-shadow:0 18px 45px rgba(31,55,36,.08); backdrop-filter:blur(10px); }}
    .metric {{ font-size:clamp(24px,3vw,38px); font-weight:700; letter-spacing:-.04em; overflow-wrap:anywhere; }}
    .muted {{ color:var(--sage); }}
    h2 {{ margin:30px 0 12px; font-size:26px; letter-spacing:-.03em; }}
    .table-wrap {{ overflow:auto; border-radius:22px; box-shadow:var(--shadow); border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; background:rgba(255,252,240,.84); min-width:760px; }}
    th,td {{ padding:13px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ font-size:11px; text-transform:uppercase; color:var(--sage); letter-spacing:.12em; background:rgba(255,255,255,.48); }}
    tr:hover td {{ background:rgba(255,246,206,.36); }}
    code {{ background:#edf1e7; padding:3px 6px; border-radius:8px; color:#274a33; }}
    .pill {{ display:inline-block; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:700; background:#edf1e7; color:var(--moss); }}
    .ok {{ color:var(--mint); }} .bad {{ color:var(--ember); }} .warn {{ color:var(--gold); }}
    .pill.ok {{ background:#e0f3e9; color:var(--mint); }} .pill.bad {{ background:#f8e5df; color:var(--ember); }} .pill.warn {{ background:#fff0c4; color:#94661b; }}
    .legacy {{ opacity:.55; }}
    pre {{ white-space:pre-wrap; max-height:360px; overflow:auto; background:#132018; color:#f7f0d4; padding:14px; border-radius:14px; font-size:12px; }}
    .split {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,.45fr); gap:16px; align-items:start; }}
    ul.clean {{ margin:0; padding-left:18px; }}
    @media (max-width:760px) {{ .shell {{ width:min(100% - 22px,1180px); }} header {{ align-items:flex-start; flex-direction:column; }} .split {{ grid-template-columns:1fr; }} table {{ min-width:680px; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <header><div><p class="eyebrow">Chaut Admin</p><h1>{escape(title)}</h1><p class="subtitle">Control operativo de ahorros en oro digital</p></div><div class="badge">Genesis HTX activa</div></header>
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
    pending = sum(1 for order in active_orders if order.payment_status != "confirmed")
    settled = sum(1 for order in active_orders if order.conversion_status in SETTLED_STATES)
    body = f"""
    <section class="hero">
      <div class="grid">
        {metric_card("Usuarios", len(accounts))}
        {metric_card("Ordenes activas", len(active_orders))}
        {metric_card("Pendientes pago", pending)}
        {metric_card("Settled", settled)}
        {metric_card("COP invertido", f"{total_cop:,.0f}")}
        {metric_card("Gramos oro", f"{total_grams:.12f}")}
      </div>
    </section>
    <section class="grid">
      <div class="card"><div class="muted">XAUT neto custodiado</div><div class="metric">{total_xaut:.18f}</div><p class="muted">Basado en ledger, no en ordenes de prueba.</p></div>
      <div class="card"><div class="muted">Movimientos reales</div><div class="metric">{total_entries}</div><p class="muted">Solo compras con ledger entry suman al saldo.</p></div>
    </section>
    <h2>Ordenes relevantes</h2>
    {orders_table(active_orders[:12], token)}
    <h2>Legado / pruebas</h2>
    <p class="muted">Ordenes voided o fallidas se conservan para auditoria, pero no afectan saldos.</p>
    {orders_table([order for order in orders if order.conversion_status in LEGACY_STATES][:8], token, legacy=True)}
    """
    return render_admin("Dashboard", body, token)


def admin_orders(store: OrderStore, token: str | None = None) -> HTMLResponse:
    orders = store.list_orders(200)
    active = [order for order in orders if order.conversion_status not in LEGACY_STATES]
    paid = [order for order in active if order.payment_status == "confirmed"]
    unpaid = [order for order in active if order.payment_status != "confirmed"]
    legacy = [order for order in orders if order.conversion_status in LEGACY_STATES]
    body = f"""
    <section class="hero"><div class="grid">{metric_card("Pagadas", len(paid))}{metric_card("No pagas", len(unpaid))}{metric_card("Legado", len(legacy))}{metric_card("Total", len(orders))}</div></section>
    <h2>Pagadas / operables</h2><p class="muted">Ordenes con pago confirmado. Si XAUT dice not_started, falta ejecutar settlement o es una orden anterior a la trazabilidad fina.</p>{orders_table(paid, token)}
    <h2>No pagas</h2><p class="muted">PaymentRequests creados o pruebas que aun no han confirmado pago; no mueven XAUT ni afectan saldos.</p>{orders_table(unpaid, token, compact=True)}
    <h2>Legado / pruebas</h2>{orders_table(legacy, token, legacy=True)}
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
        <p><b>Pago:</b> {status_pill(order.payment_status, order.payment_status == "confirmed")}</p>
        <p><b>Conversion:</b> {conversion_pill(order.conversion_status)}</p>
        {portfolio_link}
      </div>
      <div class="card">
        <p class="muted">Monto</p>
        <div class="metric">{order.amount_cop_gross:,.0f} COP</div>
        <p><b>USDT:</b> {order.payment_amount or 0}</p>
        <p><b>Creada:</b> {format_bogota_time(order.created_at)}</p>
      </div>
    </div>
    <h2>Timeline de eventos</h2>
    <div class="table-wrap"><table><tr><th>Fecha</th><th>Tipo</th><th>Payload</th></tr>
    {''.join(f'<tr><td>{format_bogota_time(event.created_at)}</td><td><code>{escape(event.event_type)}</code></td><td><pre>{escape(str(event.payload))}</pre></td></tr>' for event in events)}
    </table></div>
    """
    return render_admin("Detalle Orden", body, token)


def admin_accounts(store: OrderStore, token: str | None = None) -> HTMLResponse:
    rows = []
    for account in store.list_accounts(200):
        portfolio = store.get_portfolio(account.customer_id)
        rows.append(
            f"<tr><td><a href='/admin/accounts/{escape(account.customer_id)}{_token_qs(token)}'><code>{escape(account.customer_id)}</code></a></td>"
            f"<td>{escape(account.display_name or '-')}</td><td>{portfolio.entries_count}</td><td>{portfolio.cop_invested:,.0f}</td>"
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
        f"<tr><td>{format_bogota_time(entry.created_at)}</td><td><a href='/admin/orders/{escape(entry.external_id)}{_token_qs(token)}'><code>{escape(entry.external_id)}</code></a></td><td>{entry.cop_gross:,.0f}</td><td>{entry.usdt_spent:.12f}</td><td>{entry.amount:.18f}</td><td>{entry.gold_grams:.12f}</td></tr>"
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
    <h2>Ledger</h2><div class="table-wrap"><table><tr><th>Fecha</th><th>Orden</th><th>COP</th><th>USDT</th><th>XAUT</th><th>Gramos</th></tr>{entries}</table></div>
    """
    return render_admin("Usuario", body, token)


def orders_table(orders, token: str | None = None, legacy: bool = False, compact: bool = False) -> str:
    rows = []
    for order in orders:
        row_class = " class='legacy'" if legacy else ""
        customer = "-" if compact else escape(order.customer_id or "-")
        rows.append(
            f"<tr{row_class}><td><a href='/admin/orders/{escape(order.external_id)}{_token_qs(token)}'><code>{escape(order.external_id)}</code></a></td>"
            f"<td><code>{customer}</code></td><td>{order.amount_cop_gross:,.0f}</td><td>{order.payment_amount or ''}</td>"
            f"<td>{status_pill(order.payment_status, order.payment_status == 'confirmed')}</td><td>{conversion_pill(order.conversion_status)}</td><td>{format_bogota_time(order.created_at)}</td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='7' class='muted'>Sin registros.</td></tr>")
    return "<div class='table-wrap'><table><tr><th>Orden</th><th>Usuario</th><th>COP</th><th>USDT</th><th>Pago</th><th>XAUT</th><th>Fecha</th></tr>" + "".join(rows) + "</table></div>"


def metric_card(label: str, value) -> str:
    return f'<div class="card"><div class="muted">{escape(str(label))}</div><div class="metric">{escape(str(value))}</div></div>'


def status_pill(text: str, ok: bool) -> str:
    return f'<span class="pill {"ok" if ok else "warn"}">{escape(text)}</span>'


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
