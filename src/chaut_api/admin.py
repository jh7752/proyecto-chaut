import base64
from datetime import datetime, timedelta, timezone
from html import escape
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .store import OrderStore


SETTLED_STATES = {"settled"}
LEGACY_STATES = {"voided", "failed"}
EXPIRED_STATES = {"expired"}
ATTENTION_PAYMENT_STATES = {"ambiguous", "payment_reconciliation_ambiguous"}
ATTENTION_CONVERSION_STATES = {"executing", "submitted"}
ADMIN_SESSION_MAX_AGE_SECONDS = 60 * 60 * 12


def _encode_session_token(payload: str, session_secret: str) -> str:
    signature = hmac.new(session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    encoded_payload = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{encoded_payload}.{signature}"


def _decode_session_token(token: str, session_secret: str) -> tuple[int, str] | None:
    try:
        encoded_payload, signature = token.split(".", 1)
        padding = "=" * (-len(encoded_payload) % 4)
        payload = base64.urlsafe_b64decode(encoded_payload + padding).decode()
        expected = hmac.new(session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        issued_at_text, csrf_token = payload.split(":", 1)
        issued_at = int(issued_at_text)
    except (ValueError, TypeError):
        return None
    if issued_at > int(time.time()) + 60 or int(time.time()) - issued_at > ADMIN_SESSION_MAX_AGE_SECONDS:
        return None
    return issued_at, csrf_token


def require_admin(request: Request, token: str | None) -> None:
    if (
        token
        and request.query_params.get("token") != token
        and request.headers.get("x-admin-token") != token
    ):
        raise HTTPException(status_code=401, detail="Admin token required")


def is_admin_session(request: Request, session_secret: str | None) -> bool:
    if not session_secret:
        return False
    cookie = request.cookies.get("chaut_admin_session")
    return bool(cookie) and _decode_session_token(cookie, session_secret) is not None


def require_admin_login(request: Request, session_secret: str | None) -> None:
    if not is_admin_session(request, session_secret):
        raise HTTPException(status_code=401, detail="Admin login required")


def require_admin_csrf(request: Request, session_secret: str | None, csrf_token: str) -> None:
    if not session_secret:
        return
    cookie = request.cookies.get("chaut_admin_session")
    session = _decode_session_token(cookie or "", session_secret)
    if session is None or not csrf_token or not hmac.compare_digest(session[1], csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def admin_csrf_token(request: Request, session_secret: str | None) -> str:
    cookie = request.cookies.get("chaut_admin_session")
    session = _decode_session_token(cookie or "", session_secret or "")
    return session[1] if session else ""


def admin_login_page(error: str | None = None) -> HTMLResponse:
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login - Chaut Admin</title>
  <style>
    :root {{ --ink:#1a1a2e; --leaf:#3a7d5e; --leaf-2:#5ea882; --gold:#d4a853; --gold-2:#f7e4a0; --cream:#f8f6f0; --line:rgba(42,45,62,.13); --shadow:0 20px 60px rgba(26,26,46,.12); }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ min-height:100vh; margin:0; display:grid; place-items:center; color:var(--ink); font-family:'Segoe UI',system-ui,-apple-system,sans-serif; background:linear-gradient(135deg,#e8e4f0 0%,#f0f4e8 50%,#f5f0e0 100%); }}
    body:before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.16; background:linear-gradient(90deg,rgba(49,84,62,.2) 1px,transparent 1px),linear-gradient(rgba(49,84,62,.18) 1px,transparent 1px); background-size:44px 44px; mask-image:linear-gradient(to bottom,black,transparent 74%); }}
    .login-shell {{ width:min(440px,calc(100% - 28px)); display:grid; gap:12px; }}
    .card {{ position:relative; overflow:hidden; border:1px solid var(--line); border-radius:32px; padding:34px; background:rgba(255,255,255,.92); box-shadow:var(--shadow); backdrop-filter:blur(16px); }}
    .card:after {{ content:""; position:absolute; right:-56px; top:-72px; width:178px; height:178px; border-radius:50%; background:radial-gradient(circle,rgba(244,214,122,.4),transparent 68%); }}
    .coin {{ width:70px; height:70px; margin-bottom:18px; filter:drop-shadow(0 18px 24px rgba(121,86,28,.2)); }}
    .eyebrow {{ color:var(--gold); text-transform:uppercase; letter-spacing:.18em; font-size:12px; font-weight:800; margin:0 0 10px; }}
    h1 {{ margin:0 0 10px; font-size:46px; letter-spacing:-.04em; line-height:.95; text-wrap:balance; font-weight:800; }}
    p {{ color:var(--leaf); line-height:1.5; }}
    label {{ display:block; margin:16px 0 7px; color:var(--leaf); font-weight:800; }}
    input {{ width:100%; border:1px solid var(--line); border-radius:16px; padding:14px 15px; color:var(--ink); font:inherit; background:rgba(255,255,255,.96); outline:none; transition:border-color .18s ease, box-shadow .18s ease, transform .18s ease; }}
    input:focus-visible {{ border-color:rgba(189,138,50,.76); box-shadow:0 0 0 4px rgba(189,138,50,.16); transform:translateY(-1px); }}
    button {{ width:100%; margin-top:20px; border:0; border-radius:16px; padding:14px 16px; color:#fff; background:linear-gradient(135deg,#3a7d5e,#2a5c44); font:inherit; font-weight:700; cursor:pointer; box-shadow:0 12px 28px rgba(58,125,94,.25); transition:transform .18s ease, box-shadow .18s ease, filter .18s ease; }}
    button:hover {{ transform:scale(1.025); box-shadow:0 20px 40px rgba(49,84,62,.27); filter:saturate(1.06); }}
    button:focus-visible {{ outline:3px solid rgba(189,138,50,.42); outline-offset:3px; }}
    .error {{ color:#b24a36; font-weight:800; border-left:3px solid #b24a36; padding:8px 10px; border-radius:12px; background:rgba(248,227,221,.72); }}
    .login-footer {{ text-align:center; color:rgba(49,84,62,.72); font-size:13px; letter-spacing:.04em; }}
  </style>
</head>
<body>
  <main class="login-shell">
    <form class="card" method="post" action="/login">
      <svg class="coin" viewBox="0 0 96 96" role="img" aria-label="Moneda Chaut" xmlns="http://www.w3.org/2000/svg">
        <defs><linearGradient id="coin-gold" x1="18" x2="78" y1="14" y2="82" gradientUnits="userSpaceOnUse"><stop stop-color="#fff2ad"/><stop offset=".45" stop-color="#c99633"/><stop offset="1" stop-color="#7f9a5b"/></linearGradient></defs>
        <circle cx="48" cy="48" r="40" fill="url(#coin-gold)"/><circle cx="48" cy="48" r="29" fill="none" stroke="rgba(255,255,255,.68)" stroke-width="4"/><path d="M35 56c5 7 20 8 26-1m-4-20c-6-5-19-4-24 5" fill="none" stroke="#24341f" stroke-linecap="round" stroke-width="5"/><text x="48" y="55" text-anchor="middle" font-size="21" font-weight="900" fill="#24341f" font-family="Georgia,serif">Au</text>
      </svg>
      <p class="eyebrow">Chaut Admin</p>
      <h1>Acceso operativo</h1>
      <p>Panel privado para controlar ahorros en oro digital.</p>
      {error_html}
      <label for="username">Usuario</label>
      <input id="username" name="username" autocomplete="username" required autofocus>
      <label for="password">Clave</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Entrar</button>
    </form>
    <footer class="login-footer">Powered by Chaut</footer>
  </main>
</body>
</html>""")


def create_admin_session_response(session_secret: str, redirect_to: str = "/admin") -> Response:
    response = RedirectResponse(redirect_to, status_code=303)
    payload = f"{int(time.time())}:{secrets.token_urlsafe(32)}"
    response.set_cookie(
        "chaut_admin_session",
        _encode_session_token(payload, session_secret),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=ADMIN_SESSION_MAX_AGE_SECONDS,
        path="/",
    )
    return response


def clear_admin_session_response() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("chaut_admin_session", path="/", secure=True, samesite="strict")
    return response


def valid_admin_credentials(
    username: str, password: str, expected_username: str | None, expected_password: str | None
) -> bool:
    if not expected_username or not expected_password:
        return False
    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(
        password, expected_password
    )


def render_admin(
    title: str,
    body: str,
    token: str | None = None,
    csrf_token: str = "",
) -> HTMLResponse:
    token_qs = f"?token={escape(token)}" if token else ""
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Chaut Admin</title>
  <style>
    :root {{
      --ink:#1a1a2e; --deep:#24244a; --leaf:#3a7d5e; --leaf-2:#5ea882;
      --gold:#d4a853; --gold-2:#f7e4a0; --paper:#faf9f4; --paper-soft:rgba(255,255,255,.88);
      --mist:#eeeef5; --line:rgba(42,45,62,.1); --line-strong:rgba(42,45,62,.2);
      --ok:#2d9d6a; --warn:#d4963a; --bad:#d45050; --blue:#3a82b4;
      --shadow:0 26px 80px rgba(27,44,23,.16); --soft-shadow:0 14px 40px rgba(27,44,23,.09);
      --sidebar:270px; --content-max:1220px;
    }}
    [data-theme="dark"] {{
      --ink:#e8e4f0; --deep:#0f0f1a; --leaf:#5ea882; --leaf-2:#3a7d5e;
      --gold:#f0c96a; --gold-2:#f7e4a0; --paper:#16162a; --paper-soft:rgba(22,22,42,.88);
      --mist:#0f0f1a; --line:rgba(232,228,240,.12); --line-strong:rgba(232,228,240,.22);
      --ok:#5eeaa0; --warn:#f0c96a; --bad:#ff8a8a; --blue:#6ec0f0;
      --shadow:0 26px 80px rgba(0,0,0,.34); --soft-shadow:0 14px 40px rgba(0,0,0,.2);
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0; color:var(--ink); font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background:#eeeef5; font-size:15px; transition:background .3s ease,color .3s ease;
    }}
    body:before {{
      content:""; position:fixed; inset:0; z-index:-3;
      background:
        radial-gradient(circle at 8% 12%, rgba(212,168,83,.28) 0 14%, transparent 32%),
        radial-gradient(circle at 88% -4%, rgba(94,168,130,.24) 0 16%, transparent 36%),
        radial-gradient(circle at 70% 92%, rgba(180,160,220,.2) 0 14%, transparent 34%),
        linear-gradient(135deg,#f8f6f0 0%,#eeeef5 42%,#e8e4f0 100%);
    }}
    [data-theme="dark"] body:before {{ background:radial-gradient(circle at 7% 10%,rgba(240,201,106,.18),transparent 28%),radial-gradient(circle at 90% -4%,rgba(94,168,130,.16),transparent 34%),linear-gradient(135deg,#0f0f1a 0%,#16162a 48%,#0a0a18 100%); }}
    body:after {{
      content:""; position:fixed; inset:0; z-index:-2; pointer-events:none; opacity:.2;
      background-image:linear-gradient(90deg, rgba(36,52,31,.23) 1px, transparent 1px),linear-gradient(rgba(36,52,31,.18) 1px, transparent 1px);
      background-size:42px 42px; mask-image:linear-gradient(to bottom, black, transparent 76%);
    }}
    [data-theme="dark"] body:after {{ opacity:.12; filter:invert(1); }}
    a,button,input {{ transition:border-color .18s ease, background .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease, opacity .18s ease; }}
    a:focus-visible,button:focus-visible,input:focus-visible {{ outline:3px solid rgba(201,150,51,.45); outline-offset:3px; }}
    .grain {{ position:fixed; inset:0; z-index:-1; pointer-events:none; opacity:.18; background:repeating-radial-gradient(circle at 20% 30%, rgba(24,33,22,.11) 0 1px, transparent 1px 4px); mix-blend-mode:multiply; }}
    .mobile-topbar {{ display:none; }}
    .menu-toggle {{ display:none; }}
    .sidebar {{ position:fixed; inset:18px auto 18px 18px; width:var(--sidebar); z-index:20; display:flex; flex-direction:column; gap:18px; padding:18px; border:1px solid var(--line); border-radius:24px; background:rgba(255,255,255,.78); box-shadow:var(--shadow); backdrop-filter:blur(20px); }}
    [data-theme="dark"] .sidebar {{ background:rgba(22,22,42,.82); }}
    .side-brand {{ display:flex; align-items:center; gap:13px; text-decoration:none; color:var(--ink); }}
    .mark {{ flex:0 0 auto; width:52px; height:52px; border-radius:16px; display:grid; place-items:center; color:#1a1a2e; font-weight:900; letter-spacing:-.06em; background:linear-gradient(135deg,#d4a853,#f7e4a0,#5ea882); box-shadow:inset 0 0 0 1px rgba(255,255,255,.4), 0 12px 28px rgba(212,168,83,.2); }}
    .brand-title {{ display:block; font-size:23px; font-weight:900; letter-spacing:-.05em; line-height:1; }}
    .eyebrow {{ margin:0 0 7px; color:var(--gold); text-transform:uppercase; letter-spacing:.18em; font-size:11px; font-weight:800; }}
    .side-nav {{ display:grid; gap:8px; }}
    .side-nav a,.logout,.theme-toggle,.button {{ color:var(--ink); text-decoration:none; border:1px solid var(--line); padding:11px 13px; border-radius:14px; background:rgba(255,255,255,.5); box-shadow:0 4px 12px rgba(42,45,62,.05); font:inherit; font-weight:700; cursor:pointer; }}
    [data-theme="dark"] .side-nav a,[data-theme="dark"] .logout,[data-theme="dark"] .theme-toggle,[data-theme="dark"] .button {{ background:rgba(255,255,255,.06); }}
    .side-nav a:hover,.logout:hover,.theme-toggle:hover,.button:hover {{ border-color:rgba(212,168,83,.5); transform:translateY(-1px); background:rgba(248,244,238,.9); }}
    [data-theme="dark"] .side-nav a:hover,[data-theme="dark"] .logout:hover,[data-theme="dark"] .theme-toggle:hover,[data-theme="dark"] .button:hover {{ background:rgba(212,168,83,.12); }}
    .side-icon {{ display:inline-grid; place-items:center; width:28px; height:28px; margin-right:7px; border-radius:8px; background:rgba(212,168,83,.12); }}
    .side-spacer {{ flex:1; }}
    .logout {{ display:block; text-align:center; color:#fff; background:linear-gradient(135deg,#3a7d5e,#2a5c44); }}
    .layout {{ min-height:100vh; padding-left:calc(var(--sidebar) + 38px); }}
    .shell {{ width:min(var(--content-max),calc(100% - 32px)); margin:0 auto; }}
    header {{ padding:30px 0 18px; display:grid; grid-template-columns:1fr auto; align-items:end; gap:20px; }}
    h1 {{ margin:0; font-size:clamp(34px,5.6vw,68px); line-height:.9; letter-spacing:-.04em; text-wrap:balance; font-weight:800; }}
    .subtitle {{ margin:10px 0 0; color:var(--leaf); font-size:16px; }}
    .statusbar {{ display:flex; gap:9px; flex-wrap:wrap; justify-content:flex-end; }}
    .badge {{ border:1px solid var(--line); border-radius:999px; padding:10px 13px; background:rgba(255,255,255,.56); color:var(--leaf); white-space:nowrap; box-shadow:var(--soft-shadow); }}
    [data-theme="dark"] .badge {{ background:rgba(255,255,255,.06); }}
    main {{ padding:0 0 30px; }}
    .site-footer {{ padding:6px 0 30px; color:#75836b; font-size:13px; }}
    .hero {{ position:relative; overflow:hidden; border:1px solid var(--line); background:linear-gradient(135deg,rgba(255,255,255,.85),rgba(248,244,238,.7)); border-radius:24px; padding:22px; box-shadow:var(--shadow); margin-bottom:18px; }}
    [data-theme="dark"] .hero {{ background:linear-gradient(135deg,rgba(255,255,255,.06),rgba(212,168,83,.08)); }}
    .hero:before {{ content:""; position:absolute; right:-70px; top:-90px; width:220px; height:220px; border-radius:50%; background:radial-gradient(circle, rgba(212,168,83,.15), transparent 68%); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }}
    .card {{ position:relative; background:var(--paper-soft); border:1px solid var(--line); border-radius:20px; padding:18px; box-shadow:var(--soft-shadow); backdrop-filter:blur(12px); overflow:hidden; }}
    .card:after {{ content:""; position:absolute; inset:auto 14px 0; height:2px; background:linear-gradient(90deg,transparent,var(--gold-2),transparent); opacity:.45; }}
    .premium-hero {{ display:grid; grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr); gap:18px; align-items:stretch; }}
    .command-card {{ min-height:260px; padding:26px; display:flex; flex-direction:column; justify-content:space-between; background:linear-gradient(135deg,rgba(26,26,46,.96),rgba(42,42,74,.92)); color:#fff; border:0; }}
    .command-card:after {{ display:none; }}
    .command-card .eyebrow,.command-card .muted {{ color:rgba(247,228,160,.82); }}
    .command-card h2 {{ margin:12px 0 10px; font-size:clamp(34px,5vw,58px); line-height:.92; letter-spacing:-.055em; }}
    .command-actions {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }}
    .command-actions a {{ color:#1a1a2e; background:#f7e4a0; border-radius:14px; padding:11px 14px; text-decoration:none; box-shadow:0 10px 28px rgba(0,0,0,.18); }}
    .mini-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    .signal-card {{ min-height:123px; background:rgba(255,255,255,.72); }}
    [data-theme="dark"] .signal-card {{ background:rgba(255,255,255,.07); }}
    .signal-value {{ display:block; margin-top:8px; font-size:30px; font-weight:850; letter-spacing:-.05em; }}
    .health-strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; margin-top:14px; }}
    .health-item {{ border:1px solid var(--line); border-radius:16px; padding:12px; background:rgba(255,255,255,.58); }}
    [data-theme="dark"] .health-item {{ background:rgba(255,255,255,.06); }}
    .revenue-card {{ background:linear-gradient(135deg,rgba(247,228,160,.82),rgba(255,255,255,.86)); border-color:rgba(212,168,83,.34); }}
    [data-theme="dark"] .revenue-card {{ background:linear-gradient(135deg,rgba(212,168,83,.18),rgba(255,255,255,.06)); }}
    .revenue-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-top:12px; }}
    .revenue-kpi {{ border:1px solid rgba(212,168,83,.28); border-radius:16px; padding:12px; background:rgba(255,255,255,.48); }}
    [data-theme="dark"] .revenue-kpi {{ background:rgba(255,255,255,.06); }}
    .revenue-kpi b {{ display:block; margin-top:5px; font-size:24px; letter-spacing:-.045em; overflow-wrap:anywhere; }}
    .metric-card {{ min-height:132px; display:grid; align-content:space-between; gap:14px; }}
    .metric-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }}
    .metric-icon {{ display:grid; place-items:center; width:42px; height:42px; border-radius:12px; color:var(--gold); background:rgba(212,168,83,.1); box-shadow:inset 0 0 0 1px rgba(212,168,83,.15); }}
    .metric-icon svg {{ width:22px; height:22px; }}
    .metric {{ font-size:clamp(24px,3vw,40px); font-weight:900; letter-spacing:-.055em; overflow-wrap:anywhere; line-height:.96; }}
    .muted {{ color:#8888a0; }}
    [data-theme="dark"] .muted,.site-footer {{ color:#9898b8; }}
    h2 {{ margin:30px 0 12px; font-size:28px; letter-spacing:-.045em; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:12px; margin:30px 0 12px; }}
    .section-head h2 {{ margin:0; }}
    .table-wrap {{ overflow:auto; border-radius:20px; box-shadow:var(--shadow); border:1px solid var(--line); background:rgba(255,255,255,.6); scrollbar-width:thin; scrollbar-color:rgba(212,168,83,.5) transparent; }}
    table {{ width:100%; border-collapse:separate; border-spacing:0; background:rgba(255,255,255,.92); min-width:780px; }}
    [data-theme="dark"] table {{ background:rgba(22,22,42,.88); }}
    th,td {{ padding:14px 15px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; }}
    th {{ position:sticky; top:0; z-index:1; font-size:10px; text-transform:uppercase; color:#8888a0; letter-spacing:.14em; background:rgba(255,255,255,.92); backdrop-filter:blur(10px); }}
    [data-theme="dark"] th {{ background:rgba(22,22,42,.95); color:#9898b8; }}
    tbody tr:nth-child(even) td {{ background:rgba(94,168,130,.04); }}
    tr:hover td {{ background:rgba(212,168,83,.1); }}
    [data-theme="dark"] tr:hover td {{ background:rgba(212,168,83,.14); }}
    tr.needs-attention td {{ border-left:0; }}
    tr.needs-attention td:first-child {{ border-left:4px solid var(--bad); }}
    tr:last-child td {{ border-bottom:0; }}
    a {{ color:#2a5c44; font-weight:700; }}
    [data-theme="dark"] a {{ color:#f0c96a; }}
    code {{ background:#f0eef5; padding:4px 7px; border-radius:8px; color:#2a2a4a; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:.92em; }}
    [data-theme="dark"] code {{ background:rgba(255,255,255,.08); color:#e8e4f0; }}
    .order-id {{ display:inline-flex; align-items:center; gap:7px; }}
    .order-id:before {{ content:""; width:8px; height:8px; border-radius:50%; background:var(--gold); box-shadow:0 0 0 4px rgba(212,168,83,.12); }}
    .pill {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:6px 10px; font-size:12px; font-weight:700; background:#f0eef5; color:var(--leaf); white-space:nowrap; }}
    .pill:before {{ content:""; width:7px; height:7px; border-radius:50%; background:currentColor; }}
    .ok {{ color:var(--ok); }} .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }} .info {{ color:var(--blue); }}
    .pill.ok {{ background:#e6f7ee; color:var(--ok); }} .pill.bad {{ background:#fce8e8; color:var(--bad); }} .pill.warn {{ background:#fef3dc; color:#94661b; }} .pill.info {{ background:#e4f0f8; color:var(--blue); }}
    [data-theme="dark"] .pill {{ background:rgba(255,255,255,.08); }}
    .legacy {{ opacity:.58; }}
    .money {{ font-weight:850; letter-spacing:-.02em; white-space:nowrap; }}
    .date {{ min-width:190px; }}
    pre {{ white-space:pre-wrap; max-height:360px; overflow:auto; background:#132018; color:#f7f0d4; padding:14px; border-radius:16px; font-size:12px; line-height:1.45; }}
    .day-group {{ margin:0 0 24px; position:relative; }}
    .day-title {{ margin:18px 0 10px; display:inline-flex; align-items:center; gap:9px; border:1px solid var(--line); border-radius:999px; padding:8px 12px; background:rgba(255,255,255,.6); color:var(--leaf); font-weight:800; }}
    [data-theme="dark"] .day-title {{ background:rgba(255,255,255,.06); }}
    .day-title:before {{ content:""; width:8px; height:8px; border-radius:50%; background:var(--gold); }}
    .timeline {{ display:grid; gap:11px; position:relative; min-width:0; }}
    .timeline:before {{ content:""; position:absolute; left:16px; top:8px; bottom:8px; width:2px; background:linear-gradient(var(--gold),rgba(129,155,98,.28)); }}
    .order-card {{ position:relative; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:14px; align-items:start; padding:14px 16px 14px 44px; border:1px solid var(--line); border-radius:20px; background:rgba(255,255,255,.9); box-shadow:var(--soft-shadow); min-width:0; transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease; }}
    [data-theme="dark"] .order-card {{ background:rgba(22,22,42,.88); }}
    .order-card:before {{ content:""; position:absolute; left:10px; top:18px; width:14px; height:14px; border-radius:50%; background:var(--paper); border:3px solid var(--gold); box-shadow:0 0 0 5px rgba(212,168,83,.1); }}
    .order-card.needs-attention {{ border-left:4px solid var(--bad); }}
    .order-card:hover {{ transform:translateY(-2px); border-color:rgba(212,168,83,.3); box-shadow:0 16px 40px rgba(42,45,62,.12); }}
    .order-main {{ display:grid; gap:7px; min-width:0; }}
    .order-main .order-id {{ max-width:100%; overflow:hidden; }}
    .order-main code {{ overflow-wrap:anywhere; }}
    .order-meta {{ display:flex; flex-wrap:wrap; gap:7px; align-items:center; }}
    .order-money {{ text-align:right; min-width:112px; }}
    .order-money strong {{ display:block; font-size:22px; letter-spacing:-.04em; line-height:1; }}
    .order-time {{ color:#8888a0; font-size:13px; line-height:1.35; overflow-wrap:anywhere; }}
    .order-rate {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; color:var(--leaf); font-size:12px; line-height:1.35; }}
    .order-rate strong {{ color:var(--ink); font-weight:850; }}
    [data-theme="dark"] .order-time {{ color:#9898b8; }}
    .orders-split {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; align-items:start; }}
    .orders-panel {{ min-width:0; }}
    .account-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; }}
    .account-card {{ display:grid; gap:14px; min-height:220px; text-decoration:none; color:var(--ink); }}
    .account-card:hover {{ transform:translateY(-2px); border-color:rgba(212,168,83,.34); box-shadow:0 18px 46px rgba(42,45,62,.12); }}
    .account-head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    .avatar {{ width:46px; height:46px; border-radius:15px; display:grid; place-items:center; color:#fff; font-weight:850; background:linear-gradient(135deg,var(--leaf),var(--gold)); box-shadow:0 12px 28px rgba(58,125,94,.18); }}
    .account-name {{ margin:0; font-size:20px; letter-spacing:-.035em; }}
    .account-stats {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
    .account-stat {{ border:1px solid var(--line); border-radius:14px; padding:10px; background:rgba(255,255,255,.52); }}
    [data-theme="dark"] .account-stat {{ background:rgba(255,255,255,.06); }}
    .account-stat b {{ display:block; margin-top:4px; font-size:18px; }}
    .rating-badge {{ display:inline-flex; align-items:center; justify-content:center; min-width:44px; height:44px; border-radius:14px; padding:0 12px; font-weight:900; color:#1a1a2e; background:linear-gradient(135deg,#f7e4a0,#d4a853); }}
    .rating-new {{ background:#f0eef5; color:#8888a0; }}
    .score-bar {{ height:9px; border-radius:999px; overflow:hidden; background:rgba(42,45,62,.08); }}
    .score-bar span {{ display:block; height:100%; width:calc(var(--score) * 1%); border-radius:inherit; background:linear-gradient(90deg,var(--leaf),var(--gold)); }}
    .orders-panel .section-head {{ margin:0 0 10px; }}
    .split {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,.45fr); gap:16px; align-items:start; }}
    .split.rates-layout {{ grid-template-columns:minmax(260px,.7fr) minmax(280px,.55fr) minmax(360px,1fr); }}
    .rate-card {{ border-color:rgba(212,168,83,.34); background:linear-gradient(135deg,rgba(247,228,160,.78),rgba(255,255,255,.88)); }}
    [data-theme="dark"] .rate-card {{ background:linear-gradient(135deg,rgba(212,168,83,.18),rgba(255,255,255,.07)); }}
    .rate-card .kv b {{ font-size:16px; }}
    .profile-tabs {{ margin-top:14px; display:grid; gap:14px; }}
    .tab-nav {{ display:flex; flex-wrap:wrap; gap:9px; padding:8px; border:1px solid var(--line); border-radius:16px; background:rgba(255,255,255,.5); width:max-content; max-width:100%; }}
    [data-theme="dark"] .tab-nav {{ background:rgba(255,255,255,.06); }}
    .tab-nav a {{ text-decoration:none; color:var(--leaf); font-weight:700; border-radius:12px; padding:9px 13px; background:rgba(255,255,255,.6); border:1px solid transparent; }}
    [data-theme="dark"] .tab-nav a {{ background:rgba(255,255,255,.06); }}
    .tab-nav a:hover {{ border-color:rgba(212,168,83,.4); color:var(--ink); }}
    .profile-panel {{ scroll-margin-top:96px; }}
    .credit-card {{ display:grid; grid-template-columns:minmax(140px,.45fr) minmax(0,1fr); gap:16px; align-items:center; }}
    .score-ring {{ width:132px; height:132px; border-radius:50%; display:grid; place-items:center; margin:auto; background:conic-gradient(var(--gold) calc(var(--score) * 1%), rgba(94,168,130,.12) 0); box-shadow:inset 0 0 0 12px rgba(255,255,255,.92), var(--soft-shadow); }}
    [data-theme="dark"] .score-ring {{ box-shadow:inset 0 0 0 12px rgba(22,22,42,.94), var(--soft-shadow); }}
    .score-ring span {{ font-size:13px; color:#8888a0; }}
    .score-content {{ display:grid; place-items:center; line-height:1; }}
    .score-ring strong {{ font-size:34px; letter-spacing:-.06em; }}
    .kv-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }}
    .kv {{ border:1px solid var(--line); border-radius:14px; padding:11px 12px; background:rgba(255,255,255,.6); }}
    [data-theme="dark"] .kv {{ background:rgba(255,255,255,.06); }}
    .kv b {{ display:block; margin-top:4px; font-size:18px; }}
    .reason-list {{ display:grid; gap:8px; margin:12px 0 0; padding:0; list-style:none; }}
    .reason-list li {{ border-left:3px solid var(--gold); padding:8px 10px; border-radius:10px; background:rgba(255,255,255,.6); }}
    [data-theme="dark"] .reason-list li {{ background:rgba(255,255,255,.06); }}
    ul.clean {{ margin:0; padding-left:18px; }}
    .empty {{ text-align:center; padding:28px; color:#8888a0; }}
    @media (max-width:900px) {{
      .mobile-topbar {{ position:sticky; top:0; z-index:30; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 14px; border-bottom:1px solid var(--line); background:rgba(255,255,255,.88); backdrop-filter:blur(16px); }}
      [data-theme="dark"] .mobile-topbar {{ background:rgba(22,22,42,.9); }}
      .menu-toggle {{ display:grid; place-items:center; width:44px; height:44px; border:1px solid var(--line); border-radius:15px; background:rgba(255,255,255,.58); color:var(--ink); font-size:21px; cursor:pointer; }}
      .sidebar {{ transform:translateX(calc(-100% - 28px)); transition:transform .22s ease; }}
      body.nav-open .sidebar {{ transform:translateX(0); }}
      .layout {{ padding-left:0; }}
      .shell {{ width:min(100% - 22px,1180px); }}
      header {{ align-items:start; grid-template-columns:1fr; padding-top:22px; }}
      .statusbar {{ justify-content:flex-start; }}
      .split,.orders-split,.credit-card,.premium-hero {{ grid-template-columns:1fr; }}
      table {{ min-width:720px; }} th,td {{ padding:12px; }}
      .order-card {{ grid-template-columns:1fr; padding:14px 14px 14px 40px; }}
      .order-money {{ text-align:left; }}
      .tab-nav {{ border-radius:22px; width:100%; }}
      .mini-grid {{ grid-template-columns:1fr; }}
    }}
    @media print {{
      .sidebar,.mobile-topbar,.statusbar,.site-footer {{ display:none !important; }}
      .layout {{ padding-left:0; }} .shell {{ width:100%; }} body {{ background:#fff; color:#000; }} body:before,body:after,.grain {{ display:none; }}
      .card,.hero,.table-wrap,.order-card {{ box-shadow:none; break-inside:avoid; }} a {{ color:#000; text-decoration:none; }}
    }}
  </style>
  <script>
    (function() {{
      var theme = localStorage.getItem('chaut-theme') || 'light';
      document.documentElement.dataset.theme = theme;
      window.toggleChautTheme = function() {{
        var next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        localStorage.setItem('chaut-theme', next);
      }};
      window.toggleChautNav = function() {{ document.body.classList.toggle('nav-open'); }};
    }})();
  </script>
</head>
<body>
  <div class="grain"></div>
  <div class="mobile-topbar"><a class="side-brand" href="/admin{token_qs}"><span class="mark">Au</span><span class="brand-title">Chaut</span></a><button class="menu-toggle" type="button" onclick="toggleChautNav()" aria-label="Abrir navegacion">☰</button></div>
  <aside class="sidebar" aria-label="Navegacion principal">
    <a class="side-brand" href="/admin{token_qs}"><span class="mark">Au</span><span><span class="brand-title">Chaut</span><span class="eyebrow">Admin</span></span></a>
    <nav class="side-nav"><a href="/admin{token_qs}"><span class="side-icon">□</span>Dashboard</a><a href="/admin/orders{token_qs}"><span class="side-icon">◇</span>Ordenes</a><a href="/admin/withdrawals{token_qs}"><span class="side-icon">△</span>Retiros</a><a href="/admin/accounts{token_qs}"><span class="side-icon">○</span>Cuentas</a></nav>
    <button class="theme-toggle" type="button" onclick="toggleChautTheme()">Modo claro/oscuro</button>
    <div class="side-spacer"></div>
    <a class="logout" href="/logout">Salir</a>
  </aside>
  <div class="layout">
    <div class="shell">
      <header>
        <div><p class="eyebrow">Chaut Admin</p><h1>{escape(title)}</h1><p class="subtitle">Control operativo de ahorros en oro digital</p></div>
        <div class="statusbar"><div class="badge">HTX activo</div><div class="badge">Bre-B / Coinsenda</div></div>
      </header>
      <main>{body}</main>
      <footer class="site-footer">Powered by Chaut · panel operativo privado</footer>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


def admin_dashboard(
    store: OrderStore, token: str | None = None, csrf_token: str = ""
) -> HTMLResponse:
    orders = store.list_orders(200)
    accounts = store.list_accounts(200)
    total_cop_net = total_xaut = total_grams = 0.0
    total_entries = 0
    for account in accounts:
        portfolio = store.get_portfolio(account.customer_id)
        total_cop_net += max(portfolio.cop_net_contributed, 0.0)
        total_xaut += portfolio.xaut_net
        total_grams += portfolio.gold_grams_net
        total_entries += portfolio.entries_count
    active_orders = [order for order in orders if order.conversion_status not in LEGACY_STATES]
    attention_orders = [order for order in active_orders if needs_attention(order)]
    revenue = commission_summary(store)
    pending = sum(
        1 for order in active_orders if order.payment_status not in {"confirmed", "expired"}
    )
    expired = sum(1 for order in active_orders if order.payment_status in EXPIRED_STATES)
    settled = sum(1 for order in active_orders if order.conversion_status in SETTLED_STATES)
    body = f"""
    <section class="premium-hero">
      <div class="card command-card">
        <div>
          <p class="eyebrow">Centro operativo</p>
          <h2>{total_cop_net:,.0f} COP netos</h2>
          <p class="muted">Vista ejecutiva de Chaut: usuarios, ordenes, credito y oro digital en una sola consola. Neto = depositos menos retiros completados.</p>
        </div>
        <div class="command-actions">
          <a href="/admin/orders{_token_qs(token)}">Revisar ordenes</a>
          <a href="/admin/accounts{_token_qs(token)}">Ver usuarios</a>
        </div>
      </div>
      <div class="mini-grid">
        <div class="card signal-card"><span class="muted">Atencion operativa</span><span class="signal-value bad">{len(attention_orders)}</span><p class="muted">Ordenes que necesitan revision.</p></div>
        <div class="card signal-card"><span class="muted">Settled</span><span class="signal-value ok">{settled}</span><p class="muted">Compras listas en ledger.</p></div>
        <div class="card signal-card"><span class="muted">Usuarios</span><span class="signal-value">{len(accounts)}</span><p class="muted">Cuentas identificadas.</p></div>
        <div class="card signal-card"><span class="muted">Pendientes</span><span class="signal-value warn">{pending}</span><p class="muted">Pagos por confirmar.</p></div>
      </div>
    </section>
    <section class="health-strip">
      <div class="health-item"><span class="muted">XAUT neto</span><b>{total_xaut:.8f}</b></div>
      <div class="health-item"><span class="muted">Oro digital</span><b>{total_grams:.8f} g</b></div>
      <div class="health-item"><span class="muted">Movimientos reales</span><b>{total_entries}</b></div>
      <div class="health-item"><span class="muted">Expiradas</span><b>{expired}</b></div>
    </section>
    <section class="card revenue-card">
      <div class="section-head"><h2>Ingresos Chaut en XAUT</h2><span class="badge">{revenue["paid_count"]} compras con comision</span></div>
      <p class="muted">Comision/spread acumulado despues del cambio: el usuario paga COP completo y Chaut toma su ingreso al final en oro digital.</p>
      <div class="revenue-grid">
        <div class="revenue-kpi"><span class="muted">XAUT Chaut</span><b>{revenue["chaut_spread_xaut"]:.18f}</b></div>
        <div class="revenue-kpi"><span class="muted">Oro equivalente</span><b>{revenue["chaut_spread_gold_grams"]:.12f} g</b></div>
        <div class="revenue-kpi"><span class="muted">Fees HTX pagados</span><b>{revenue["exchange_fee_xaut"]:.18f}</b></div>
        <div class="revenue-kpi"><span class="muted">Ordenes liquidadas</span><b>{revenue["settled_count"]}</b></div>
      </div>
    </section>
    <div class="section-head"><h2>Comisiones por orden</h2><span class="badge">Detalle ledger</span></div>
    {commission_table(revenue["rows"])}
    <div class="section-head"><h2>Ultimas ordenes</h2><span class="badge">Resumen rapido</span></div>
    {split_orders_timeline(store, active_orders, token)}
    <div class="section-head"><h2>Legado / pruebas</h2><span class="muted">Auditoria</span></div>
    <p class="muted">Ordenes voided o fallidas se conservan para auditoria, pero no afectan saldos.</p>
    {orders_table([order for order in orders if order.conversion_status in LEGACY_STATES][:8], token, legacy=True, events_by_order=events_map(store, [order for order in orders if order.conversion_status in LEGACY_STATES][:8]))}
    """
    return render_admin("Dashboard", body, token, csrf_token)


def admin_orders(
    store: OrderStore, token: str | None = None, csrf_token: str = ""
) -> HTMLResponse:
    orders = store.list_orders(200)
    active = [order for order in orders if order.conversion_status not in LEGACY_STATES]
    paid = [order for order in active if order.payment_status == "confirmed"]
    unpaid = [order for order in active if order.payment_status != "confirmed"]
    legacy = [order for order in orders if order.conversion_status in LEGACY_STATES]
    body = f"""
    <section class="hero"><div class="grid">{metric_card("Pagadas", len(paid))}{metric_card("No pagadas", len(unpaid))}{metric_card("Legado", len(legacy))}{metric_card("Total", len(orders))}</div></section>
    <div class="section-head"><h2>Pagadas</h2><span class="badge">Confirmadas</span></div><p class="muted">Ordenes confirmadas, ordenadas por fecha de compra y separadas por dia.</p>{grouped_orders_by_day(store, paid, token, view="cards")}
    <div class="section-head"><h2>No pagadas</h2><span class="badge">Pendientes y expiradas</span></div><p class="muted">PaymentRequests pendientes, ambiguas o expiradas. Las expiradas usan la fecha real de vencimiento.</p>{grouped_orders_by_day(store, unpaid, token, compact=True, view="cards")}
    <div class="section-head"><h2>Legado / pruebas</h2><span class="muted">Historico</span></div>{grouped_orders_by_day(store, legacy, token, legacy=True)}
    """
    return render_admin("Ordenes", body, token, csrf_token)


def htx_execution_price(store: OrderStore, external_id: str) -> float | None:
    event = next(
        (
            event
            for event in reversed(store.list_events(external_id))
            if event.event_type == "xaut.order_filled"
        ),
        None,
    )
    if event is None:
        return None
    fill = event.payload.get("order", {})
    try:
        usdt_spent = float(fill.get("field_cash_amount") or 0)
        xaut_bought = float(fill.get("field_amount") or 0)
    except (TypeError, ValueError):
        return None
    return usdt_spent / xaut_bought if usdt_spent > 0 and xaut_bought > 0 else None


def admin_order_detail(
    store: OrderStore,
    external_id: str,
    token: str | None = None,
    csrf_token: str = "",
) -> HTMLResponse:
    order = store.get_order(external_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    events = store.list_events(external_id)
    portfolio_link = ""
    if order.customer_id:
        portfolio_link = f'<a class="button" href="/admin/accounts/{escape(order.customer_id)}{_token_qs(token)}">Ver usuario</a>'
    htx_price = htx_execution_price(store, external_id)
    body = f"""
    <div class="split rates-layout">
      <div class="card">
        <p class="muted">Orden</p><div class="metric"><code>{escape(order.external_id)}</code></div>
        <p><b>Usuario:</b> <code>{escape(order.customer_id or "-")}</code></p>
        <p><b>Pago:</b> {status_pill(order.payment_status)}</p>
        <p><b>Conversion:</b> {conversion_pill(order.conversion_status)}</p>
        {portfolio_link}
      </div>
      <div class="card">
        <p class="muted">Monto</p>
        <div class="metric">{order.amount_cop_gross:,.0f} COP</div>
        <p><b>USDT:</b> {format_decimal(order.payment_amount, 6)}</p>
        <p><b>Creada:</b> {format_bogota_time(order.created_at)}</p>
      </div>
      <div class="card rate-card">
        <p class="muted">Tasas aplicadas</p>
        <div class="kv-grid">
          <div class="kv"><span class="muted">Coinsenda venta</span><b>{format_rate(order.sell_price_cop_per_usdt)}</b></div>
          <div class="kv"><span class="muted">Referencia</span><b>{format_rate(order.reference_rate_cop_per_usdt)}</b></div>
          <div class="kv"><span class="muted">Fuente</span><b>{escape(order.reference_rate_source or "-")}</b></div>
          <div class="kv"><span class="muted">Fecha ref.</span><b>{escape(order.reference_rate_date or "-")}</b></div>
          <div class="kv"><span class="muted">USDT cobrado</span><b>{format_decimal(order.payment_amount, 6)}</b></div>
          <div class="kv"><span class="muted">Spread estimado</span><b>{format_cop(order.spread_profit_cop_estimated)}</b></div>
          <div class="kv"><span class="muted">Compra XAUT HTX</span><b>{format_decimal(htx_price, 4)} USDT/XAUT</b></div>
        </div>
      </div>
    </div>
    <div class="section-head"><h2>Timeline de eventos</h2><span class="badge">{len(events)} eventos</span></div>
    <div class="table-wrap"><table><tr><th>Fecha</th><th>Tipo</th><th>Payload</th></tr>
    {"".join(f'<tr><td class="date">{format_bogota_time(event.created_at)}</td><td><code>{escape(event.event_type)}</code></td><td><pre>{escape(str(event.payload))}</pre></td></tr>' for event in events)}
    </table></div>
    """
    return render_admin("Detalle Orden", body, token, csrf_token)



def admin_withdrawals(
    store: OrderStore, token: str | None = None, csrf_token: str = ""
) -> HTMLResponse:
    withdrawals = store.list_withdrawals(limit=100)
    pending = [wd for wd in withdrawals if wd.status in {"requested", "selling_xaut", "sell_review", "xaut_sold", "transferring_usdt", "swapping_cop", "paying_cop", "swap_failed", "payout_failed"}]
    cards = []
    for wd in pending or withdrawals[:20]:
        confirm_form = ""
        if wd.status in {"xaut_sold", "paying_cop", "payout_failed"}:
            confirm_form = (
                f'<form class="action-form" method="post" action="/admin/withdrawals/{escape(wd.withdrawal_id)}/confirm-payment{_token_qs(token)}">'
                f'<input name="csrf_token" type="hidden" value="{escape(csrf_token)}">'
                '<input name="cop_paid" type="number" step="0.01" placeholder="COP pagado" required>'
                '<input name="cop_tx_ref" placeholder="Referencia Bre-B" required>'
                '<input name="admin_note" placeholder="Nota opcional">'
                '<button class="button" type="submit">Confirmar pago COP</button></form>'
            )
        fail_form = ""
        if wd.status in {"requested", "selling_xaut", "sell_review"}:
            fail_form = (
                f'<form class="action-form" method="post" action="/admin/withdrawals/{escape(wd.withdrawal_id)}/mark-failed{_token_qs(token)}">'
                f'<input name="csrf_token" type="hidden" value="{escape(csrf_token)}">'
                '<input name="reason" placeholder="Motivo del fallo verificado" required>'
                '<input name="admin_note" placeholder="Nota: confirma que no hubo venta/movimiento externo">'
                '<button class="button" type="submit">Liberar reserva verificada</button></form>'
            )
        usdt = "" if wd.usdt_received is None else f"{wd.usdt_received:.8f}"
        price = "" if wd.xaut_sell_price is None else f"{wd.xaut_sell_price:.2f}"
        estimated = "" if wd.estimated_value_cop is None else f"{wd.estimated_value_cop:,.0f}"
        cop_received = "" if wd.cop_received is None else f"{wd.cop_received:,.2f}"
        coinsenda_price = "" if wd.coinsenda_sell_price is None else f"{wd.coinsenda_sell_price:,.2f}"
        cards.append(
            f'<article class="card"><p class="eyebrow">{escape(wd.status)}</p>'
            f'<h2><code>{escape(wd.withdrawal_id)}</code></h2><div class="grid">'
            f'<div><span class="muted">Cliente</span><br><code>{escape(wd.customer_id)}</code></div>'
            f'<div><span class="muted">Gramos</span><br>{wd.gold_grams:.12f}</div>'
            f'<div><span class="muted">XAUT</span><br>{wd.xaut_amount:.18f}</div>'
            f'<div><span class="muted">USDT recibido</span><br>{usdt}</div>'
            f'<div><span class="muted">Precio venta</span><br>{price}</div>'
            f'<div><span class="muted">Valor COP estimado</span><br>{estimated}</div>'
            f'<div><span class="muted">COP swap</span><br>{cop_received}</div>'
            f'<div><span class="muted">Tasa Coinsenda</span><br>{coinsenda_price}</div>'
            f'<div><span class="muted">Bre-B Coinsenda</span><br><code>{escape(str(wd.coinsenda_withdraw_id or ""))}</code></div>'
            f'<div><span class="muted">Llave Bre-B</span><br><code>{escape(wd.breb_key)}</code></div>'
            f'</div>{confirm_form}{fail_form}</article>'
        )
    body = "<div class='section-head'><h2>Retiros pendientes</h2></div>" + ("".join(cards) if cards else "<p class='muted'>No hay retiros.</p>")
    return render_admin("Retiros", body, token, csrf_token)

def admin_accounts(
    store: OrderStore, token: str | None = None, csrf_token: str = ""
) -> HTMLResponse:
    cards = []
    rows = []
    for account in store.list_accounts(200):
        portfolio = store.get_portfolio(account.customer_id)
        credit = store.get_credit_profile(account.customer_id)
        initials = (account.display_name or account.customer_id or "U")[:2].upper()
        rating_class = "rating-new" if credit.rating == "nuevo" else ""
        href = f"/admin/accounts/{escape(account.customer_id)}{_token_qs(token)}"
        cards.append(
            f'<a class="card account-card" href="{href}">'
            f'<div class="account-head"><div><div class="avatar">{escape(initials)}</div><p class="account-name">{escape(account.display_name or account.customer_id)}</p><span class="muted"><code>{escape(account.customer_id)}</code></span></div><span class="rating-badge {rating_class}">{escape(credit.rating)}</span></div>'
            f'<div class="score-bar" style="--score:{credit.score}"><span></span></div>'
            f'<div class="account-stats"><div class="account-stat"><span class="muted">Score</span><b>{credit.score}/100</b></div><div class="account-stat"><span class="muted">Cupo</span><b>{credit.suggested_credit_limit_cop:,.0f}</b></div><div class="account-stat"><span class="muted">COP neto</span><b>{portfolio.cop_net_contributed:,.0f}</b></div><div class="account-stat"><span class="muted">LTV max</span><b>{credit.max_ltv_percent:.0f}%</b></div></div>'
            "</a>"
        )
        rows.append(
            f"<tr><td><a class='order-id' href='{href}'><code>{escape(account.customer_id)}</code></a></td>"
            f"<td>{escape(account.display_name or '-')}</td><td>{portfolio.entries_count}</td><td class='money'>{portfolio.cop_net_contributed:,.0f}</td>"
            f"<td>{credit.score}</td><td>{escape(credit.rating)}</td><td class='money'>{credit.suggested_credit_limit_cop:,.0f}</td><td>{credit.max_ltv_percent:.0f}%</td></tr>"
        )
    body = (
        "<section class='account-grid'>" + "".join(cards) + "</section>"
        "<div class='section-head'><h2>Tabla completa</h2><span class='badge'>Credito y saldos</span></div>"
        "<div class='table-wrap'><table><thead><tr><th>Usuario</th><th>Nombre</th><th>Movs</th><th>COP neto</th><th>Score</th><th>Rating</th><th>Cupo</th><th>LTV</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )
    return render_admin("Usuarios", body, token, csrf_token)


def admin_account_detail(
    store: OrderStore,
    customer_id: str,
    token: str | None = None,
    csrf_token: str = "",
) -> HTMLResponse:
    account = store.get_account(customer_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    portfolio = store.get_portfolio(customer_id)
    credit = store.get_credit_profile(customer_id)
    entries = "".join(
        f"<tr><td class='date'>{format_bogota_time(entry.created_at)}</td><td><a class='order-id' href='/admin/orders/{escape(entry.external_id)}{_token_qs(token)}'><code>{escape(entry.external_id)}</code></a></td><td class='money'>{entry.cop_gross:,.0f}</td><td>{entry.usdt_spent:.12f}</td><td>{entry.amount:.18f}</td><td>{entry.gold_grams:.12f}</td></tr>"
        for entry in portfolio.entries
    )
    identities = "".join(
        f"<li>{escape(identity.provider)}: <code>{escape(identity.provider_user_id)}</code></li>"
        for identity in account.identities
    )
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in credit.reasons)
    body = f"""
    <section class="hero"><div class="grid">
      {metric_card("COP neto", f"{portfolio.cop_net_contributed:,.0f}")}
      {metric_card("COP invertido", f"{portfolio.cop_invested:,.0f}")}
      {metric_card("COP retirado", f"{portfolio.cop_withdrawn:,.0f}")}
      {metric_card("Oro digital", f"{portfolio.gold_grams_net:.12f} g")}
    </div></section>
    <section class="profile-tabs">
      <div class="tab-nav"><a href="#perfil">Perfil</a><a href="#credito">Credito</a><a href="#ledger">Ledger</a></div>
      <div id="perfil" class="profile-panel card">
        <div class="section-head"><h2>Perfil del usuario</h2><span class="badge">{escape(account.status)}</span></div>
        <div class="kv-grid"><div class="kv"><span class="muted">Usuario</span><b><code>{escape(account.customer_id)}</code></b></div><div class="kv"><span class="muted">Nombre</span><b>{escape(account.display_name or "-")}</b></div><div class="kv"><span class="muted">Identidades</span><b>{len(account.identities)}</b></div></div>
        <p class="muted">Canales vinculados</p><ul class="clean">{identities}</ul>
      </div>
      <div id="credito" class="profile-panel card credit-card">
        <div class="score-ring" style="--score:{credit.score}"><div class="score-content"><strong>{credit.score}</strong><span>/100</span></div></div>
        <div>
          <div class="section-head"><h2>Perfil crediticio interno</h2><span class="rating-badge {"rating-new" if credit.rating == "nuevo" else ""}">{escape(credit.rating)}</span></div>
          <p class="muted">Calificacion operativa para prestamos con colateral en oro digital. Combina actividad, pagos confirmados, colateral y alertas historicas.</p>
          <div class="kv-grid"><div class="kv"><span class="muted">Cupo sugerido</span><b>{credit.suggested_credit_limit_cop:,.0f} COP</b></div><div class="kv"><span class="muted">LTV max</span><b>{credit.max_ltv_percent:.0f}%</b></div><div class="kv"><span class="muted">Garantia referencia</span><b>{credit.collateral_value_cop:,.0f} COP</b></div><div class="kv"><span class="muted">Ordenes</span><b>{credit.paid_orders} pagadas · {credit.unpaid_orders} no pagadas · {credit.expired_orders} expiradas</b></div></div>
          <ul class="reason-list">{reasons}</ul>
        </div>
      </div>
      <div id="ledger" class="profile-panel">
        <div class="section-head"><h2>Ledger</h2><span class="badge">{portfolio.entries_count} movimientos</span></div><div class="table-wrap"><table><tr><th>Fecha</th><th>Orden</th><th>COP</th><th>USDT</th><th>XAUT</th><th>Gramos</th></tr>{entries}</table></div>
      </div>
    </section>
    """
    return render_admin("Usuario", body, token, csrf_token)


def split_orders_timeline(store: OrderStore, orders, token: str | None = None) -> str:
    active = [order for order in orders if order.conversion_status not in LEGACY_STATES]
    paid = [order for order in active if order.payment_status == "confirmed"][:12]
    unpaid = [order for order in active if order.payment_status != "confirmed"][:12]
    return (
        '<div class="orders-split">'
        f'<section class="orders-panel"><div class="section-head"><h2>Pagadas</h2><span class="badge">{len(paid)}</span></div>{grouped_orders_by_day(store, paid, token, view="cards")}</section>'
        f'<section class="orders-panel"><div class="section-head"><h2>No pagadas</h2><span class="badge">{len(unpaid)}</span></div>{grouped_orders_by_day(store, unpaid, token, compact=True, view="cards")}</section>'
        "</div>"
    )


def grouped_orders_by_day(
    store: OrderStore,
    orders,
    token: str | None = None,
    legacy: bool = False,
    compact: bool = False,
    view: str = "table",
) -> str:
    events_by_order = events_map(store, orders)
    dated_orders = []
    for order in orders:
        _, main_date, _, _ = order_date_context(order, events_by_order.get(order.external_id, []))
        dated_orders.append((order_sort_key(main_date), format_bogota_day(main_date), order))
    dated_orders.sort(key=lambda item: item[0], reverse=True)
    groups: dict[str, list] = {}
    for _, day, order in dated_orders:
        groups.setdefault(day, []).append(order)
    if not groups:
        return (
            order_cards([], token, legacy=legacy, compact=compact, events_by_order=events_by_order)
            if view == "cards"
            else orders_table([], token, legacy=legacy, compact=compact)
        )
    sections = []
    for day, day_orders in groups.items():
        content = (
            order_cards(
                day_orders, token, legacy=legacy, compact=compact, events_by_order=events_by_order
            )
            if view == "cards"
            else orders_table(
                day_orders, token, legacy=legacy, compact=compact, events_by_order=events_by_order
            )
        )
        sections.append(
            f'<section class="day-group"><div class="day-title">{escape(day)}</div>{content}</section>'
        )
    return "".join(sections)


def events_map(store: OrderStore, orders) -> dict[str, list]:
    return {order.external_id: store.list_events(order.external_id) for order in orders}


def order_cards(
    orders,
    token: str | None = None,
    legacy: bool = False,
    compact: bool = False,
    events_by_order: dict[str, list] | None = None,
) -> str:
    if not orders:
        return '<div class="card empty">Sin registros.</div>'
    cards = []
    for order in orders:
        row_events = (events_by_order or {}).get(order.external_id, [])
        date_label, main_date, secondary_label, secondary_date = order_date_context(
            order, row_events
        )
        customer = "-" if compact else escape(order.customer_id or "-")
        legacy_class = " legacy" if legacy else ""
        attention_class = " needs-attention" if needs_attention(order) else ""
        cards.append(
            f'<article class="order-card{legacy_class}{attention_class}">'
            f'<div class="order-main"><a class="order-id" href="/admin/orders/{escape(order.external_id)}{_token_qs(token)}"><code>{escape(order.external_id)}</code></a>'
            f'<div class="order-meta"><code>{customer}</code>{status_pill(order.payment_status)}{conversion_pill(order.conversion_status)}{attention_pill(order)}</div>'
            f'<div class="order-time">{escape(date_label)}: {format_bogota_time(main_date)} · {escape(secondary_label)}: {format_bogota_time(secondary_date)}</div>'
            f'<div class="order-rate"><span class="muted">Coinsenda</span> <strong>{format_rate(order.sell_price_cop_per_usdt)}</strong> <span class="muted">Ref.</span> <strong>{format_rate(order.reference_rate_cop_per_usdt)}</strong></div></div>'
            f'<div class="order-money"><strong>{order.amount_cop_gross:,.0f}</strong><span class="muted">COP</span></div>'
            "</article>"
        )
    return '<div class="timeline">' + "".join(cards) + "</div>"


def orders_table(
    orders,
    token: str | None = None,
    legacy: bool = False,
    compact: bool = False,
    events_by_order: dict[str, list] | None = None,
) -> str:
    rows = []
    for order in orders:
        classes = ["legacy"] if legacy else []
        if needs_attention(order):
            classes.append("needs-attention")
        row_class = f' class="{" ".join(classes)}"' if classes else ""
        customer = "-" if compact else escape(order.customer_id or "-")
        row_events = (events_by_order or {}).get(order.external_id, [])
        date_label, main_date, secondary_label, secondary_date = order_date_context(
            order, row_events
        )
        rows.append(
            f"<tr{row_class}><td><a class='order-id' href='/admin/orders/{escape(order.external_id)}{_token_qs(token)}'><code>{escape(order.external_id)}</code></a></td>"
            f"<td><code>{customer}</code></td><td class='money'>{order.amount_cop_gross:,.0f}</td><td>{format_decimal(order.payment_amount, 6)}</td>"
            f"<td>{format_rate(order.sell_price_cop_per_usdt)}</td><td>{format_rate(order.reference_rate_cop_per_usdt)}</td>"
            f"<td>{status_pill(order.payment_status)}</td><td>{conversion_pill(order.conversion_status)}</td>"
            f"<td>{attention_pill(order)}</td>"
            f"<td class='date'>{escape(date_label)}: {format_bogota_time(main_date)}<br><span class='muted'>{escape(secondary_label)}: {format_bogota_time(secondary_date)}</span></td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='10' class='empty'>Sin registros.</td></tr>")
    return (
        "<div class='table-wrap'><table><thead><tr><th>Orden</th><th>Usuario</th><th>COP</th><th>USDT</th><th>Coinsenda</th><th>Referencia</th><th>Pago</th><th>XAUT</th><th>Operacion</th><th>Fecha operativa</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


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
    return (
        order.payment_status == "confirmed"
        and order.conversion_status not in SETTLED_STATES | LEGACY_STATES
    )


def attention_pill(order) -> str:
    if needs_attention(order):
        return '<span class="pill bad">revisar</span>'
    if order.conversion_status in SETTLED_STATES:
        return '<span class="pill ok">ok</span>'
    if order.payment_status in EXPIRED_STATES:
        return '<span class="pill info">expirada</span>'
    return '<span class="pill warn">normal</span>'


def commission_summary(store: OrderStore) -> dict:
    rows = []
    total_spread = 0.0
    total_spread_grams = 0.0
    total_exchange_fee = 0.0
    settled_count = 0
    for account in store.list_accounts(500):
        for entry in store.get_portfolio(account.customer_id).entries:
            if entry.entry_type != "xaut_purchase":
                continue
            settled_count += 1
            payload = entry.payload or {}
            allocation = payload.get("allocation") if isinstance(payload, dict) else {}
            fill = payload.get("order") if isinstance(payload, dict) else {}
            chaut_spread = float((allocation or {}).get("chaut_spread_xaut") or 0)
            chaut_spread_grams = float((allocation or {}).get("chaut_spread_gold_grams") or 0)
            exchange_fee = float((fill or {}).get("field_fees") or 0)
            total_spread += chaut_spread
            total_spread_grams += chaut_spread_grams
            total_exchange_fee += exchange_fee
            rows.append(
                {
                    "created_at": entry.created_at,
                    "external_id": entry.external_id,
                    "customer_id": entry.customer_id,
                    "cop_gross": entry.cop_gross,
                    "client_xaut": entry.amount,
                    "client_grams": entry.gold_grams,
                    "chaut_spread_xaut": chaut_spread,
                    "chaut_spread_gold_grams": chaut_spread_grams,
                    "exchange_fee_xaut": exchange_fee,
                }
            )
    rows.sort(key=lambda row: order_sort_key(row["created_at"]), reverse=True)
    return {
        "settled_count": settled_count,
        "paid_count": sum(1 for row in rows if row["chaut_spread_xaut"] > 0),
        "chaut_spread_xaut": total_spread,
        "chaut_spread_gold_grams": total_spread_grams,
        "exchange_fee_xaut": total_exchange_fee,
        "rows": rows,
    }


def commission_table(rows: list[dict]) -> str:
    visible_rows = [row for row in rows if row["chaut_spread_xaut"] > 0]
    html_rows = []
    for row in visible_rows[:8]:
        html_rows.append(
            f"<tr><td class='date'>{format_bogota_time(row['created_at'])}</td>"
            f"<td><a class='order-id' href='/admin/orders/{escape(row['external_id'])}'><code>{escape(row['external_id'])}</code></a></td>"
            f"<td><code>{escape(row['customer_id'])}</code></td>"
            f"<td class='money'>{row['cop_gross']:,.0f}</td>"
            f"<td>{row['client_xaut']:.18f}</td>"
            f"<td>{row['chaut_spread_xaut']:.18f}</td>"
            f"<td>{row['chaut_spread_gold_grams']:.12f} g</td>"
            f"<td>{row['exchange_fee_xaut']:.18f}</td></tr>"
        )
    if not html_rows:
        html_rows.append(
            "<tr><td colspan='8' class='empty'>Sin comisiones XAUT registradas aun.</td></tr>"
        )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Fecha</th><th>Orden</th><th>Usuario</th><th>COP</th><th>XAUT cliente</th><th>XAUT Chaut</th><th>Oro Chaut</th><th>Fee HTX</th></tr></thead><tbody>"
        + "".join(html_rows)
        + "</tbody></table></div>"
    )



def format_decimal(value, places: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.{places}f}"


def format_rate(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.2f} COP/USDT"


def format_cop(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.2f} COP"

def metric_card(label: str, value) -> str:
    icons = {
        "usuarios": "users",
        "ordenes": "chart",
        "ordenes activas": "chart",
        "pagadas": "chart",
        "no pagadas": "clock",
        "pendientes pago": "clock",
        "expiradas": "clock",
        "atencion": "trend",
        "settled": "trend",
        "cop invertido": "money",
        "oro digital": "money",
        "cupo sugerido": "money",
    }
    icon = metric_icon(icons.get(str(label).lower(), "chart"))
    return (
        '<div class="card metric-card">'
        f'<div class="metric-top"><div class="muted">{escape(str(label))}</div>{icon}</div>'
        f'<div class="metric">{escape(str(value))}</div>'
        "</div>"
    )


def metric_icon(name: str) -> str:
    svgs = {
        "chart": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19V9m7 10V5m7 14v-7" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2.4"/></svg>',
        "trend": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16l5-5 4 4 7-8m0 0v6m0-6h-6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2"/></svg>',
        "money": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 100 18 9 9 0 000-18zm0 5v8m-3-2c.8 1.2 4.9 1.5 5.6-.2.8-2-5.5-1.6-4.6-4 .7-1.8 4.1-1.5 5-.4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2"/></svg>',
        "clock": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 7v6l4 2m5-3a9 9 0 11-18 0 9 9 0 0118 0z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2"/></svg>',
        "users": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 11a4 4 0 100-8 4 4 0 000 8zm6.5-1.5a3 3 0 100-6M3 21c.7-4 3-6 6-6s5.3 2 6 6m3.5-5.5c1.6.7 2.7 2.4 3.2 5.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2"/></svg>',
    }
    return f'<span class="metric-icon">{svgs[name]}</span>'


def status_pill(text: str) -> str:
    cls = "ok" if text == "confirmed" else "info" if text == "expired" else "warn"
    return f'<span class="pill {cls}">{escape(text)}</span>'


def conversion_pill(text: str) -> str:
    cls = "ok" if text == "settled" else "bad" if text in LEGACY_STATES else "warn"
    return f'<span class="pill {cls}">{escape(text)}</span>'


def _token_qs(token: str | None) -> str:
    return f"?token={escape(token)}" if token else ""


def order_sort_key(value: str) -> datetime:
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def format_bogota_day(value: str) -> str:
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(timezone(timedelta(hours=-5)))
        return escape(local.strftime("%Y-%m-%d"))
    except Exception:
        return escape(value[:10] if value else "Sin fecha")


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
