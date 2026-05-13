from html import escape

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from .store import OrderStore


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
    :root {{ --ink:#172018; --muted:#647064; --line:#d8dfd4; --gold:#b8872f; --green:#1f6f4a; --bad:#a63c32; }}
    body {{ margin:0; color:var(--ink); font-family: Georgia, 'Times New Roman', serif; background:radial-gradient(circle at 10% 0,#fff1be,transparent 28%),linear-gradient(135deg,#f8f3df,#e8efe5); }}
    header {{ padding:28px 32px 10px; }} h1 {{ margin:0; font-size:34px; letter-spacing:-.03em; }}
    nav {{ display:flex; gap:10px; padding:0 32px 20px; flex-wrap:wrap; }} nav a {{ color:var(--ink); text-decoration:none; border:1px solid var(--line); padding:8px 12px; border-radius:999px; background:rgba(255,255,255,.62); }}
    main {{ padding:0 32px 36px; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }}
    .card {{ background:rgba(255,255,255,.76); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow:0 18px 40px rgba(31,55,36,.08); }}
    .metric {{ font-size:28px; font-weight:700; }} .muted {{ color:var(--muted); }}
    table {{ width:100%; border-collapse:collapse; background:rgba(255,255,255,.76); border-radius:16px; overflow:hidden; }} th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ font-size:12px; text-transform:uppercase; color:var(--muted); }}
    code {{ background:#eef1e9; padding:2px 5px; border-radius:6px; }} .ok {{ color:var(--green); font-weight:700; }} .bad {{ color:var(--bad); font-weight:700; }}
    pre {{ white-space:pre-wrap; overflow:auto; background:#172018; color:#f6f1dc; padding:14px; border-radius:12px; }}
    @media (max-width:640px) {{ header, main, nav {{ padding-left:16px; padding-right:16px; }} td,th {{ font-size:13px; }} }}
  </style>
</head>
<body>
  <header><h1>{escape(title)}</h1><p class="muted">Chaut admin operativo</p></header>
  <nav><a href="/admin{token_qs}">Dashboard</a><a href="/admin/orders{token_qs}">Ordenes</a><a href="/admin/accounts{token_qs}">Usuarios</a></nav>
  <main>{body}</main>
</body>
</html>"""
    return HTMLResponse(html)


def admin_dashboard(store: OrderStore, token: str | None = None) -> HTMLResponse:
    orders = store.list_orders(200)
    accounts = store.list_accounts(200)
    total_cop = 0.0
    total_xaut = 0.0
    total_grams = 0.0
    total_entries = 0
    for account in accounts:
        portfolio = store.get_portfolio(account.customer_id)
        total_cop += portfolio.cop_invested
        total_xaut += portfolio.xaut_net
        total_grams += portfolio.gold_grams_net
        total_entries += portfolio.entries_count
    pending = sum(1 for order in orders if order.payment_status != "confirmed")
    body = f"""
    <section class="grid">
      <div class="card"><div class="muted">Usuarios</div><div class="metric">{len(accounts)}</div></div>
      <div class="card"><div class="muted">Ordenes</div><div class="metric">{len(orders)}</div></div>
      <div class="card"><div class="muted">Pendientes pago</div><div class="metric">{pending}</div></div>
      <div class="card"><div class="muted">COP invertido</div><div class="metric">{total_cop:,.0f}</div></div>
      <div class="card"><div class="muted">XAUT neto</div><div class="metric">{total_xaut:.18f}</div></div>
      <div class="card"><div class="muted">Gramos oro</div><div class="metric">{total_grams:.12f}</div></div>
    </section>
    <h2>Actividad reciente</h2>
    {orders_table(orders[:12], token)}
    <p class="muted">Movimientos ledger: {total_entries}</p>
    """
    return render_admin("Dashboard", body, token)


def admin_orders(store: OrderStore, token: str | None = None) -> HTMLResponse:
    return render_admin("Ordenes", orders_table(store.list_orders(200), token), token)


def admin_order_detail(store: OrderStore, external_id: str, token: str | None = None) -> HTMLResponse:
    order = store.get_order(external_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    events = store.list_events(external_id)
    portfolio_link = ""
    if order.customer_id:
        portfolio_link = f'<p><a href="/admin/accounts/{escape(order.customer_id)}{_token_qs(token)}">Ver usuario</a></p>'
    body = f"""
    <div class="card">
      <p><b>Orden:</b> <code>{escape(order.external_id)}</code></p>
      <p><b>Usuario:</b> <code>{escape(order.customer_id or '-')}</code></p>
      <p><b>Pago:</b> {escape(order.payment_status)} / <b>Conversion:</b> {escape(order.conversion_status)}</p>
      <p><b>COP:</b> {order.amount_cop_gross:,.0f} / <b>USDT:</b> {order.payment_amount or 0}</p>
      {portfolio_link}
    </div>
    <h2>Eventos</h2>
    <table><tr><th>Fecha</th><th>Tipo</th><th>Payload</th></tr>
    {''.join(f'<tr><td>{escape(event.created_at)}</td><td><code>{escape(event.event_type)}</code></td><td><pre>{escape(str(event.payload))}</pre></td></tr>' for event in events)}
    </table>
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
    body = "<table><tr><th>Usuario</th><th>Nombre</th><th>Movs</th><th>COP</th><th>XAUT</th><th>Gramos</th></tr>" + "".join(rows) + "</table>"
    return render_admin("Usuarios", body, token)


def admin_account_detail(store: OrderStore, customer_id: str, token: str | None = None) -> HTMLResponse:
    account = store.get_account(customer_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    portfolio = store.get_portfolio(customer_id)
    entries = "".join(
        f"<tr><td>{escape(entry.created_at)}</td><td><a href='/admin/orders/{escape(entry.external_id)}{_token_qs(token)}'><code>{escape(entry.external_id)}</code></a></td><td>{entry.cop_gross:,.0f}</td><td>{entry.usdt_spent:.12f}</td><td>{entry.amount:.18f}</td><td>{entry.gold_grams:.12f}</td></tr>"
        for entry in portfolio.entries
    )
    identities = "".join(f"<li>{escape(identity.provider)}: <code>{escape(identity.provider_user_id)}</code></li>" for identity in account.identities)
    body = f"""
    <section class="grid">
      <div class="card"><div class="muted">COP invertido</div><div class="metric">{portfolio.cop_invested:,.0f}</div></div>
      <div class="card"><div class="muted">XAUT neto</div><div class="metric">{portfolio.xaut_net:.18f}</div></div>
      <div class="card"><div class="muted">Gramos oro</div><div class="metric">{portfolio.gold_grams_net:.12f}</div></div>
    </section>
    <div class="card"><p><b>Usuario:</b> <code>{escape(account.customer_id)}</code></p><p><b>Nombre:</b> {escape(account.display_name or '-')}</p><ul>{identities}</ul></div>
    <h2>Ledger</h2><table><tr><th>Fecha</th><th>Orden</th><th>COP</th><th>USDT</th><th>XAUT</th><th>Gramos</th></tr>{entries}</table>
    """
    return render_admin("Usuario", body, token)


def orders_table(orders, token: str | None = None) -> str:
    rows = []
    for order in orders:
        pay_class = "ok" if order.payment_status == "confirmed" else "bad"
        conv_class = "ok" if order.conversion_status == "settled" else ("bad" if order.conversion_status in {"failed", "voided"} else "")
        rows.append(
            f"<tr><td><a href='/admin/orders/{escape(order.external_id)}{_token_qs(token)}'><code>{escape(order.external_id)}</code></a></td>"
            f"<td><code>{escape(order.customer_id or '-')}</code></td><td>{order.amount_cop_gross:,.0f}</td><td>{order.payment_amount or ''}</td>"
            f"<td class='{pay_class}'>{escape(order.payment_status)}</td><td class='{conv_class}'>{escape(order.conversion_status)}</td><td>{escape(order.created_at)}</td></tr>"
        )
    return "<table><tr><th>Orden</th><th>Usuario</th><th>COP</th><th>USDT</th><th>Pago</th><th>XAUT</th><th>Fecha</th></tr>" + "".join(rows) + "</table>"


def _token_qs(token: str | None) -> str:
    return f"?token={escape(token)}" if token else ""
