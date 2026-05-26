from datetime import datetime, timedelta, timezone
from html import escape
import hmac
import secrets

from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .store import OrderStore


SETTLED_STATES = {"settled"}
LEGACY_STATES = {"voided", "failed"}
EXPIRED_STATES = {"expired"}
ATTENTION_PAYMENT_STATES = {"ambiguous", "payment_reconciliation_ambiguous"}
ATTENTION_CONVERSION_STATES = {"executing", "submitted"}


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
    return bool(cookie) and hmac.compare_digest(cookie, session_secret)


def require_admin_login(request: Request, session_secret: str | None) -> None:
    if not is_admin_session(request, session_secret):
        raise HTTPException(status_code=401, detail="Admin login required")


def admin_login_page(error: str | None = None) -> HTMLResponse:
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login - Chaut Admin</title>
  <style>
    :root {{ --ink:#182117; --leaf:#31543e; --leaf-2:#6f8d58; --gold:#bd8a32; --gold-2:#f4d67a; --cream:#fbf5df; --line:rgba(49,84,62,.18); --shadow:0 26px 80px rgba(26,47,31,.18); }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ min-height:100vh; margin:0; display:grid; place-items:center; color:var(--ink); font-family:Georgia,Cambria,'Times New Roman',serif; background:radial-gradient(circle at 18% 10%,rgba(255,230,161,.95),transparent 31%),radial-gradient(circle at 88% 4%,rgba(199,224,180,.9),transparent 29%),linear-gradient(135deg,#fbf4dc,#dfe8d4); }}
    body:before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.16; background:linear-gradient(90deg,rgba(49,84,62,.2) 1px,transparent 1px),linear-gradient(rgba(49,84,62,.18) 1px,transparent 1px); background-size:44px 44px; mask-image:linear-gradient(to bottom,black,transparent 74%); }}
    .login-shell {{ width:min(440px,calc(100% - 28px)); display:grid; gap:12px; }}
    .card {{ position:relative; overflow:hidden; border:1px solid var(--line); border-radius:32px; padding:34px; background:rgba(255,252,240,.86); box-shadow:var(--shadow); backdrop-filter:blur(12px); }}
    .card:after {{ content:""; position:absolute; right:-56px; top:-72px; width:178px; height:178px; border-radius:50%; background:radial-gradient(circle,rgba(244,214,122,.4),transparent 68%); }}
    .coin {{ width:70px; height:70px; margin-bottom:18px; filter:drop-shadow(0 18px 24px rgba(121,86,28,.2)); }}
    .eyebrow {{ color:var(--gold); text-transform:uppercase; letter-spacing:.18em; font-size:12px; font-weight:800; margin:0 0 10px; }}
    h1 {{ margin:0 0 10px; font-size:46px; letter-spacing:-.065em; line-height:.9; text-wrap:balance; }}
    p {{ color:var(--leaf); line-height:1.5; }}
    label {{ display:block; margin:16px 0 7px; color:var(--leaf); font-weight:800; }}
    input {{ width:100%; border:1px solid var(--line); border-radius:16px; padding:14px 15px; color:var(--ink); font:inherit; background:rgba(255,255,255,.92); outline:none; transition:border-color .18s ease, box-shadow .18s ease, transform .18s ease; }}
    input:focus-visible {{ border-color:rgba(189,138,50,.76); box-shadow:0 0 0 4px rgba(189,138,50,.16); transform:translateY(-1px); }}
    button {{ width:100%; margin-top:20px; border:0; border-radius:999px; padding:14px 16px; color:#fff; background:linear-gradient(135deg,var(--leaf),#1f3b2b); font:inherit; font-weight:800; cursor:pointer; box-shadow:0 16px 32px rgba(49,84,62,.22); transition:transform .18s ease, box-shadow .18s ease, filter .18s ease; }}
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
    response.set_cookie(
        "chaut_admin_session",
        session_secret,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return response


def clear_admin_session_response() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("chaut_admin_session")
    return response


def valid_admin_credentials(
    username: str, password: str, expected_username: str | None, expected_password: str | None
) -> bool:
    if not expected_username or not expected_password:
        return False
    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(
        password, expected_password
    )


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
      --sidebar:270px; --content-max:1220px;
    }}
    [data-theme="dark"] {{
      --ink:#f6efd3; --deep:#10170f; --leaf:#abc78b; --leaf-2:#7f9a5b;
      --gold:#e1ae4b; --gold-2:#f6d982; --paper:#162015; --paper-soft:rgba(24,34,22,.84);
      --mist:#10170f; --line:rgba(246,239,211,.14); --line-strong:rgba(246,239,211,.24);
      --ok:#7bd6a8; --warn:#e7bb68; --bad:#ed8f7e; --blue:#86c5dd;
      --shadow:0 26px 80px rgba(0,0,0,.34); --soft-shadow:0 14px 40px rgba(0,0,0,.2);
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0; color:var(--ink); font-family: ui-serif, Georgia, Cambria, 'Times New Roman', serif;
      background:#eef0de; font-size:15px; transition:background .25s ease,color .25s ease;
    }}
    body:before {{
      content:""; position:fixed; inset:0; z-index:-3;
      background:
        radial-gradient(circle at 8% 12%, rgba(243,215,130,.95) 0 9%, transparent 28%),
        radial-gradient(circle at 88% -4%, rgba(145,173,105,.8) 0 13%, transparent 34%),
        radial-gradient(circle at 70% 92%, rgba(198,224,177,.72) 0 11%, transparent 32%),
        linear-gradient(135deg,#fff7dc 0%,#edf1df 42%,#dce6cc 100%);
    }}
    [data-theme="dark"] body:before {{ background:radial-gradient(circle at 7% 10%,rgba(201,150,51,.26),transparent 27%),radial-gradient(circle at 90% -4%,rgba(129,155,98,.22),transparent 32%),linear-gradient(135deg,#10170f 0%,#182215 48%,#0d140d 100%); }}
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
    .sidebar {{ position:fixed; inset:18px auto 18px 18px; width:var(--sidebar); z-index:20; display:flex; flex-direction:column; gap:18px; padding:18px; border:1px solid var(--line); border-radius:30px; background:rgba(255,252,240,.74); box-shadow:var(--shadow); backdrop-filter:blur(18px); }}
    [data-theme="dark"] .sidebar {{ background:rgba(16,23,15,.76); }}
    .side-brand {{ display:flex; align-items:center; gap:13px; text-decoration:none; color:var(--ink); }}
    .mark {{ flex:0 0 auto; width:52px; height:52px; border-radius:18px; display:grid; place-items:center; color:#2b3117; font-weight:900; letter-spacing:-.08em; background:conic-gradient(from 210deg,#f4d776,#bb8430,#fff2b2,#7f9a5b,#f4d776); box-shadow:inset 0 0 0 1px rgba(255,255,255,.5), 0 18px 38px rgba(121,86,28,.22); }}
    .brand-title {{ display:block; font-size:23px; font-weight:900; letter-spacing:-.05em; line-height:1; }}
    .eyebrow {{ margin:0 0 7px; color:var(--gold); text-transform:uppercase; letter-spacing:.18em; font-size:11px; font-weight:800; }}
    .side-nav {{ display:grid; gap:8px; }}
    .side-nav a,.logout,.theme-toggle,.button {{ color:var(--ink); text-decoration:none; border:1px solid var(--line); padding:11px 13px; border-radius:18px; background:rgba(255,255,255,.56); box-shadow:0 8px 26px rgba(39,65,43,.06); font:inherit; font-weight:800; cursor:pointer; }}
    [data-theme="dark"] .side-nav a,[data-theme="dark"] .logout,[data-theme="dark"] .theme-toggle,[data-theme="dark"] .button {{ background:rgba(255,255,255,.06); }}
    .side-nav a:hover,.logout:hover,.theme-toggle:hover,.button:hover {{ border-color:rgba(201,150,51,.62); transform:translateY(-1px); background:rgba(255,249,232,.88); }}
    [data-theme="dark"] .side-nav a:hover,[data-theme="dark"] .logout:hover,[data-theme="dark"] .theme-toggle:hover,[data-theme="dark"] .button:hover {{ background:rgba(201,150,51,.14); }}
    .side-icon {{ display:inline-grid; place-items:center; width:28px; height:28px; margin-right:7px; border-radius:10px; background:rgba(201,150,51,.14); }}
    .side-spacer {{ flex:1; }}
    .logout {{ display:block; text-align:center; color:#fff; background:linear-gradient(135deg,var(--leaf),#1f3b2b); }}
    .layout {{ min-height:100vh; padding-left:calc(var(--sidebar) + 38px); }}
    .shell {{ width:min(var(--content-max),calc(100% - 32px)); margin:0 auto; }}
    header {{ padding:30px 0 18px; display:grid; grid-template-columns:1fr auto; align-items:end; gap:20px; }}
    h1 {{ margin:0; font-size:clamp(34px,5.6vw,72px); line-height:.86; letter-spacing:-.07em; text-wrap:balance; }}
    .subtitle {{ margin:10px 0 0; color:var(--leaf); font-size:16px; }}
    .statusbar {{ display:flex; gap:9px; flex-wrap:wrap; justify-content:flex-end; }}
    .badge {{ border:1px solid var(--line); border-radius:999px; padding:10px 13px; background:rgba(255,255,255,.56); color:var(--leaf); white-space:nowrap; box-shadow:var(--soft-shadow); }}
    [data-theme="dark"] .badge {{ background:rgba(255,255,255,.06); }}
    main {{ padding:0 0 30px; }}
    .site-footer {{ padding:6px 0 30px; color:#75836b; font-size:13px; }}
    .hero {{ position:relative; overflow:hidden; border:1px solid var(--line); background:linear-gradient(135deg,rgba(255,255,255,.78),rgba(255,248,222,.62)); border-radius:34px; padding:22px; box-shadow:var(--shadow); margin-bottom:18px; }}
    [data-theme="dark"] .hero {{ background:linear-gradient(135deg,rgba(255,255,255,.08),rgba(201,150,51,.08)); }}
    .hero:before {{ content:""; position:absolute; right:-70px; top:-90px; width:220px; height:220px; border-radius:50%; background:radial-gradient(circle, rgba(201,150,51,.18), transparent 68%); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }}
    .card {{ position:relative; background:var(--paper-soft); border:1px solid var(--line); border-radius:26px; padding:18px; box-shadow:var(--soft-shadow); backdrop-filter:blur(12px); overflow:hidden; }}
    .card:after {{ content:""; position:absolute; inset:auto 14px 0; height:3px; background:linear-gradient(90deg,transparent,var(--gold-2),transparent); opacity:.55; }}
    .metric-card {{ min-height:132px; display:grid; align-content:space-between; gap:14px; }}
    .metric-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }}
    .metric-icon {{ display:grid; place-items:center; width:42px; height:42px; border-radius:16px; color:var(--gold); background:rgba(201,150,51,.14); box-shadow:inset 0 0 0 1px rgba(201,150,51,.18); }}
    .metric-icon svg {{ width:22px; height:22px; }}
    .metric {{ font-size:clamp(24px,3vw,40px); font-weight:900; letter-spacing:-.055em; overflow-wrap:anywhere; line-height:.96; }}
    .muted {{ color:#75836b; }}
    [data-theme="dark"] .muted,.site-footer {{ color:#a7b895; }}
    h2 {{ margin:30px 0 12px; font-size:28px; letter-spacing:-.045em; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:12px; margin:30px 0 12px; }}
    .section-head h2 {{ margin:0; }}
    .table-wrap {{ overflow:auto; border-radius:24px; box-shadow:var(--shadow); border:1px solid var(--line); background:rgba(255,249,232,.58); scrollbar-width:thin; scrollbar-color:rgba(201,150,51,.7) transparent; }}
    table {{ width:100%; border-collapse:separate; border-spacing:0; background:rgba(255,252,240,.86); min-width:780px; }}
    [data-theme="dark"] table {{ background:rgba(22,32,21,.88); }}
    th,td {{ padding:14px 15px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; }}
    th {{ position:sticky; top:0; z-index:1; font-size:10px; text-transform:uppercase; color:#7d8b70; letter-spacing:.14em; background:rgba(255,255,255,.86); backdrop-filter:blur(10px); }}
    [data-theme="dark"] th {{ background:rgba(16,23,15,.95); color:#a7b895; }}
    tbody tr:nth-child(even) td {{ background:rgba(129,155,98,.055); }}
    tr:hover td {{ background:rgba(255,241,189,.48); }}
    [data-theme="dark"] tr:hover td {{ background:rgba(201,150,51,.16); }}
    tr.needs-attention td {{ border-left:0; }}
    tr.needs-attention td:first-child {{ border-left:4px solid var(--bad); }}
    tr:last-child td {{ border-bottom:0; }}
    a {{ color:#294f35; font-weight:700; }}
    [data-theme="dark"] a {{ color:#d4c17a; }}
    code {{ background:#eef2e8; padding:4px 7px; border-radius:9px; color:#274a33; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:.92em; }}
    [data-theme="dark"] code {{ background:rgba(255,255,255,.08); color:#f6efd3; }}
    .order-id {{ display:inline-flex; align-items:center; gap:7px; }}
    .order-id:before {{ content:""; width:8px; height:8px; border-radius:50%; background:var(--gold); box-shadow:0 0 0 4px rgba(201,150,51,.14); }}
    .pill {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:6px 10px; font-size:12px; font-weight:800; background:#edf1e7; color:var(--leaf); white-space:nowrap; }}
    .pill:before {{ content:""; width:7px; height:7px; border-radius:50%; background:currentColor; }}
    .ok {{ color:var(--ok); }} .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }} .info {{ color:var(--blue); }}
    .pill.ok {{ background:#dff2e8; color:var(--ok); }} .pill.bad {{ background:#f8e3dd; color:var(--bad); }} .pill.warn {{ background:#fff0c4; color:#94661b; }} .pill.info {{ background:#dfeef4; color:var(--blue); }}
    [data-theme="dark"] .pill {{ background:rgba(255,255,255,.08); }}
    .legacy {{ opacity:.58; }}
    .money {{ font-weight:850; letter-spacing:-.02em; white-space:nowrap; }}
    .date {{ min-width:190px; }}
    pre {{ white-space:pre-wrap; max-height:360px; overflow:auto; background:#132018; color:#f7f0d4; padding:14px; border-radius:16px; font-size:12px; line-height:1.45; }}
    .day-group {{ margin:0 0 24px; position:relative; }}
    .day-title {{ margin:18px 0 10px; display:inline-flex; align-items:center; gap:9px; border:1px solid var(--line); border-radius:999px; padding:8px 12px; background:rgba(255,255,255,.62); color:var(--leaf); font-weight:900; }}
    [data-theme="dark"] .day-title {{ background:rgba(255,255,255,.06); }}
    .day-title:before {{ content:""; width:8px; height:8px; border-radius:50%; background:var(--gold); }}
    .timeline {{ display:grid; gap:11px; position:relative; min-width:0; }}
    .timeline:before {{ content:""; position:absolute; left:16px; top:8px; bottom:8px; width:2px; background:linear-gradient(var(--gold),rgba(129,155,98,.28)); }}
    .order-card {{ position:relative; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:14px; align-items:start; padding:14px 16px 14px 44px; border:1px solid var(--line); border-radius:24px; background:rgba(255,252,240,.86); box-shadow:var(--soft-shadow); min-width:0; transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease; }}
    [data-theme="dark"] .order-card {{ background:rgba(22,32,21,.88); }}
    .order-card:before {{ content:""; position:absolute; left:10px; top:18px; width:14px; height:14px; border-radius:50%; background:var(--paper); border:3px solid var(--gold); box-shadow:0 0 0 5px rgba(201,150,51,.12); }}
    .order-card.needs-attention {{ border-left:4px solid var(--bad); }}
    .order-card:hover {{ transform:translateY(-1px); border-color:rgba(201,150,51,.34); box-shadow:0 20px 48px rgba(27,44,23,.14); }}
    .order-main {{ display:grid; gap:7px; min-width:0; }}
    .order-main .order-id {{ max-width:100%; overflow:hidden; }}
    .order-main code {{ overflow-wrap:anywhere; }}
    .order-meta {{ display:flex; flex-wrap:wrap; gap:7px; align-items:center; }}
    .order-money {{ text-align:right; min-width:112px; }}
    .order-money strong {{ display:block; font-size:22px; letter-spacing:-.04em; line-height:1; }}
    .order-time {{ color:#75836b; font-size:13px; line-height:1.35; overflow-wrap:anywhere; }}
    [data-theme="dark"] .order-time {{ color:#a7b895; }}
    .orders-split {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; align-items:start; }}
    .orders-panel {{ min-width:0; }}
    .orders-panel .section-head {{ margin:0 0 10px; }}
    .split {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,.45fr); gap:16px; align-items:start; }}
    .profile-tabs {{ margin-top:14px; display:grid; gap:14px; }}
    .tab-nav {{ display:flex; flex-wrap:wrap; gap:9px; padding:8px; border:1px solid var(--line); border-radius:999px; background:rgba(255,255,255,.42); width:max-content; max-width:100%; }}
    [data-theme="dark"] .tab-nav {{ background:rgba(255,255,255,.06); }}
    .tab-nav a {{ text-decoration:none; color:var(--leaf); font-weight:900; border-radius:999px; padding:9px 13px; background:rgba(255,255,255,.62); border:1px solid transparent; }}
    [data-theme="dark"] .tab-nav a {{ background:rgba(255,255,255,.06); }}
    .tab-nav a:hover {{ border-color:rgba(201,150,51,.44); color:var(--ink); }}
    .profile-panel {{ scroll-margin-top:96px; }}
    .credit-card {{ display:grid; grid-template-columns:minmax(140px,.45fr) minmax(0,1fr); gap:16px; align-items:center; }}
    .score-ring {{ width:132px; height:132px; border-radius:50%; display:grid; place-items:center; margin:auto; background:conic-gradient(var(--gold) calc(var(--score) * 1%), rgba(129,155,98,.18) 0); box-shadow:inset 0 0 0 12px rgba(255,249,232,.92), var(--soft-shadow); }}
    [data-theme="dark"] .score-ring {{ box-shadow:inset 0 0 0 12px rgba(16,23,15,.94), var(--soft-shadow); }}
    .score-ring strong {{ font-size:34px; letter-spacing:-.06em; }}
    .kv-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }}
    .kv {{ border:1px solid var(--line); border-radius:18px; padding:11px 12px; background:rgba(255,255,255,.48); }}
    [data-theme="dark"] .kv {{ background:rgba(255,255,255,.06); }}
    .kv b {{ display:block; margin-top:4px; font-size:18px; }}
    .reason-list {{ display:grid; gap:8px; margin:12px 0 0; padding:0; list-style:none; }}
    .reason-list li {{ border-left:3px solid var(--gold); padding:8px 10px; border-radius:12px; background:rgba(255,255,255,.48); }}
    [data-theme="dark"] .reason-list li {{ background:rgba(255,255,255,.06); }}
    ul.clean {{ margin:0; padding-left:18px; }}
    .empty {{ text-align:center; padding:28px; color:#75836b; }}
    @media (max-width:900px) {{
      .mobile-topbar {{ position:sticky; top:0; z-index:30; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:11px 14px; border-bottom:1px solid var(--line); background:rgba(255,252,240,.82); backdrop-filter:blur(16px); }}
      [data-theme="dark"] .mobile-topbar {{ background:rgba(16,23,15,.86); }}
      .menu-toggle {{ display:grid; place-items:center; width:44px; height:44px; border:1px solid var(--line); border-radius:15px; background:rgba(255,255,255,.58); color:var(--ink); font-size:21px; cursor:pointer; }}
      .sidebar {{ transform:translateX(calc(-100% - 28px)); transition:transform .22s ease; }}
      body.nav-open .sidebar {{ transform:translateX(0); }}
      .layout {{ padding-left:0; }}
      .shell {{ width:min(100% - 22px,1180px); }}
      header {{ align-items:start; grid-template-columns:1fr; padding-top:22px; }}
      .statusbar {{ justify-content:flex-start; }}
      .split,.orders-split,.credit-card {{ grid-template-columns:1fr; }}
      table {{ min-width:720px; }} th,td {{ padding:12px; }}
      .order-card {{ grid-template-columns:1fr; padding:14px 14px 14px 40px; }}
      .order-money {{ text-align:left; }}
      .tab-nav {{ border-radius:22px; width:100%; }}
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
    <nav class="side-nav"><a href="/admin{token_qs}"><span class="side-icon">□</span>Dashboard</a><a href="/admin/orders{token_qs}"><span class="side-icon">◇</span>Ordenes</a><a href="/admin/accounts{token_qs}"><span class="side-icon">○</span>Cuentas</a></nav>
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
    pending = sum(
        1 for order in active_orders if order.payment_status not in {"confirmed", "expired"}
    )
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
    <div class="section-head"><h2>Ultimas ordenes</h2><span class="badge">Resumen rapido</span></div>
    {split_orders_timeline(store, active_orders, token)}
    <div class="section-head"><h2>Legado / pruebas</h2><span class="muted">Auditoria</span></div>
    <p class="muted">Ordenes voided o fallidas se conservan para auditoria, pero no afectan saldos.</p>
    {orders_table([order for order in orders if order.conversion_status in LEGACY_STATES][:8], token, legacy=True, events_by_order=events_map(store, [order for order in orders if order.conversion_status in LEGACY_STATES][:8]))}
    """
    return render_admin("Dashboard", body, token)


def admin_orders(store: OrderStore, token: str | None = None) -> HTMLResponse:
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
    return render_admin("Ordenes", body, token)


def admin_order_detail(
    store: OrderStore, external_id: str, token: str | None = None
) -> HTMLResponse:
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
        <p><b>Usuario:</b> <code>{escape(order.customer_id or "-")}</code></p>
        <p><b>Pago:</b> {status_pill(order.payment_status)}</p>
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
    <div class="section-head"><h2>Timeline de eventos</h2><span class="badge">{len(events)} eventos</span></div>
    <div class="table-wrap"><table><tr><th>Fecha</th><th>Tipo</th><th>Payload</th></tr>
    {"".join(f'<tr><td class="date">{format_bogota_time(event.created_at)}</td><td><code>{escape(event.event_type)}</code></td><td><pre>{escape(str(event.payload))}</pre></td></tr>' for event in events)}
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
    body = (
        "<div class='table-wrap'><table><tr><th>Usuario</th><th>Nombre</th><th>Movs</th><th>COP</th><th>XAUT</th><th>Gramos</th></tr>"
        + "".join(rows)
        + "</table></div>"
    )
    return render_admin("Usuarios", body, token)


def admin_account_detail(
    store: OrderStore, customer_id: str, token: str | None = None
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
      {metric_card("COP invertido", f"{portfolio.cop_invested:,.0f}")}
      {metric_card("Oro digital", f"{portfolio.gold_grams_net:.12f} g")}
      {metric_card("Rating", credit.rating)}
      {metric_card("Cupo sugerido", f"{credit.suggested_credit_limit_cop:,.0f} COP")}
    </div></section>
    <section class="profile-tabs">
      <div class="tab-nav"><a href="#perfil">Perfil</a><a href="#credito">Credito</a><a href="#ledger">Ledger</a></div>
      <div id="perfil" class="profile-panel card">
        <div class="section-head"><h2>Perfil del usuario</h2><span class="badge">{escape(account.status)}</span></div>
        <div class="kv-grid"><div class="kv"><span class="muted">Usuario</span><b><code>{escape(account.customer_id)}</code></b></div><div class="kv"><span class="muted">Nombre</span><b>{escape(account.display_name or "-")}</b></div><div class="kv"><span class="muted">Identidades</span><b>{len(account.identities)}</b></div></div>
        <p class="muted">Canales vinculados</p><ul class="clean">{identities}</ul>
      </div>
      <div id="credito" class="profile-panel card credit-card">
        <div class="score-ring" style="--score:{credit.score}"><strong>{credit.score}</strong><span>/100</span></div>
        <div>
          <div class="section-head"><h2>Perfil crediticio interno</h2><span class="badge">Rating {escape(credit.rating)}</span></div>
          <div class="kv-grid"><div class="kv"><span class="muted">Cupo sugerido</span><b>{credit.suggested_credit_limit_cop:,.0f} COP</b></div><div class="kv"><span class="muted">LTV max</span><b>{credit.max_ltv_percent:.0f}%</b></div><div class="kv"><span class="muted">Garantia referencia</span><b>{credit.collateral_value_cop:,.0f} COP</b></div><div class="kv"><span class="muted">Ordenes</span><b>{credit.paid_orders} / {credit.unpaid_orders} / {credit.expired_orders}</b></div></div>
          <ul class="reason-list">{reasons}</ul>
        </div>
      </div>
      <div id="ledger" class="profile-panel">
        <div class="section-head"><h2>Ledger</h2><span class="badge">{portfolio.entries_count} movimientos</span></div><div class="table-wrap"><table><tr><th>Fecha</th><th>Orden</th><th>COP</th><th>USDT</th><th>XAUT</th><th>Gramos</th></tr>{entries}</table></div>
      </div>
    </section>
    """
    return render_admin("Usuario", body, token)


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
            f'<div class="order-time">{escape(date_label)}: {format_bogota_time(main_date)} · {escape(secondary_label)}: {format_bogota_time(secondary_date)}</div></div>'
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
            f"<td><code>{customer}</code></td><td class='money'>{order.amount_cop_gross:,.0f}</td><td>{order.payment_amount or ''}</td>"
            f"<td>{status_pill(order.payment_status)}</td><td>{conversion_pill(order.conversion_status)}</td>"
            f"<td>{attention_pill(order)}</td>"
            f"<td class='date'>{escape(date_label)}: {format_bogota_time(main_date)}<br><span class='muted'>{escape(secondary_label)}: {format_bogota_time(secondary_date)}</span></td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='8' class='empty'>Sin registros.</td></tr>")
    return (
        "<div class='table-wrap'><table><thead><tr><th>Orden</th><th>Usuario</th><th>COP</th><th>USDT</th><th>Pago</th><th>XAUT</th><th>Operacion</th><th>Fecha operativa</th></tr></thead><tbody>"
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
