import json
import re
import subprocess
import time
from pathlib import Path

CACHE_PATH = Path("/tmp/chaut-seticap-trm-cache.json")
CONTAINER_SETICAP_DIR = Path("/app/vendor/seticap-trm")
REPO_SETICAP_DIR = Path(__file__).resolve().parents[2] / "vendor" / "seticap-trm"
SETICAP_DIR = CONTAINER_SETICAP_DIR if CONTAINER_SETICAP_DIR.exists() else REPO_SETICAP_DIR
CACHE_TTL_SECONDS = 1800


def get_seticap_trm(ttl_seconds: int = CACHE_TTL_SECONDS) -> dict:
    cached = _read_cache()
    now = time.time()
    if cached and now - float(cached.get("fetched_at_epoch", 0)) < ttl_seconds:
        return {**cached, "source": "seticap-cache"}

    try:
        return refresh_seticap_trm_cache()
    except Exception:
        pass
    if cached:
        return {**cached, "source": "seticap-cache-stale"}
    raise RuntimeError("Could not fetch Seticap close rate")


def get_cached_seticap_trm(ttl_seconds: int = CACHE_TTL_SECONDS) -> dict | None:
    cached = _read_cache()
    if not cached:
        return None
    now = time.time()
    source = "seticap-cache" if now - float(cached.get("fetched_at_epoch", 0)) < ttl_seconds else "seticap-cache-stale"
    return {**cached, "source": source}


def refresh_seticap_trm_cache() -> dict:
    payload = _fetch_seticap_trm()
    payload["fetched_at_epoch"] = time.time()
    CACHE_PATH.write_text(json.dumps(payload))
    return payload


def _fetch_seticap_trm() -> dict:
    result = subprocess.run(
        ["node", "trm.js"],
        cwd=SETICAP_DIR,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = _parse_seticap_output(result.stdout)
    payload["source"] = "seticap"
    return payload


def _read_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return None


def _parse_seticap_output(output: str) -> dict:
    close_match = re.search(r"Cierre:\s*\$\s*([0-9,.]+)", output)
    date_match = re.search(r"Fecha:\s*([^\n]+)", output)
    if not close_match:
        raise ValueError("Could not parse Seticap close rate")
    value = float(close_match.group(1).replace(",", ""))
    return {
        "reference_rate": value,
        "reference_rate_source": "seticap-close",
        "reference_rate_date": date_match.group(1).strip() if date_match else None,
    }
