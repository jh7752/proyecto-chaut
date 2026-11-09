import json
import time
import urllib.request
from datetime import date
from pathlib import Path

CACHE_PATH = Path("/tmp/chaut-trm-cache.json")
CACHE_TTL_SECONDS = 1800
DATOS_GOV_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json?$limit=5&$order=vigenciadesde%20DESC"


def get_seticap_trm(ttl_seconds: int = CACHE_TTL_SECONDS) -> dict:
    cached = _read_cache()
    now = time.time()
    if cached and now - float(cached.get("fetched_at_epoch", 0)) < ttl_seconds:
        return {**cached, "source": "datos-gov-cache"}

    try:
        return refresh_seticap_trm_cache()
    except Exception:
        pass
    if cached:
        return {**cached, "source": "datos-gov-cache-stale"}
    raise RuntimeError("Could not fetch official TRM from datos.gov.co")


def get_cached_seticap_trm(ttl_seconds: int = CACHE_TTL_SECONDS) -> dict | None:
    cached = _read_cache()
    if not cached:
        return None
    now = time.time()
    source = "datos-gov-cache" if now - float(cached.get("fetched_at_epoch", 0)) < ttl_seconds else "datos-gov-cache-stale"
    return {**cached, "source": source}


def refresh_seticap_trm_cache() -> dict:
    payload = _fetch_seticap_trm()
    payload["fetched_at_epoch"] = time.time()
    CACHE_PATH.write_text(json.dumps(payload))
    return payload


def _fetch_seticap_trm() -> dict:
    today = date.today().isoformat()
    req = urllib.request.Request(
        DATOS_GOV_URL,
        headers={"Accept": "application/json", "User-Agent": "Chaut TRM/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        rows = json.loads(response.read().decode())
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("datos.gov.co returned no TRM rows")
    selected = None
    for row in rows:
        vigencia = str(row.get("vigenciadesde") or "")[:10]
        if vigencia and vigencia <= today:
            selected = row
            break
    if selected is None:
        selected = rows[0]
    try:
        value = float(selected["valor"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"datos.gov.co TRM row invalid: {selected}") from exc
    vigencia_desde = str(selected.get("vigenciadesde") or "")[:10]
    vigencia_hasta = str(selected.get("vigenciahasta") or "")[:10]
    return {
        "reference_rate": value,
        "reference_rate_source": "datos-gov-trm",
        "reference_rate_date": vigencia_desde or None,
        "reference_rate_valid_until": vigencia_hasta or None,
        "source": "datos-gov",
    }


def _read_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return None
