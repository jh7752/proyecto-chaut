import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

CACHE_PATH = Path("/tmp/chaut-seticap-trm-cache.json")
CONTAINER_SETICAP_DIR = Path("/app/vendor/seticap-trm")
REPO_SETICAP_DIR = Path(__file__).resolve().parents[2] / "vendor" / "seticap-trm"
SETICAP_DIR = CONTAINER_SETICAP_DIR if CONTAINER_SETICAP_DIR.exists() else REPO_SETICAP_DIR
CACHE_TTL_SECONDS = 3600
SUPERFINANCIERA_TRM_URL = (
    "https://www.datos.gov.co/resource/32sa-8pi3.json"
    "?$limit=1&$order=vigenciadesde%20DESC"
)


def get_seticap_trm(ttl_seconds: int = CACHE_TTL_SECONDS) -> dict:
    cached = _read_cache()
    now = time.time()
    if cached and now - float(cached.get("fetched_at_epoch", 0)) < ttl_seconds:
        return {**cached, "source": "seticap-cache"}

    for fetcher in (_fetch_superfinanciera_trm, _fetch_seticap_trm):
        try:
            payload = fetcher()
            payload["fetched_at_epoch"] = now
            CACHE_PATH.write_text(json.dumps(payload))
            return payload
        except Exception:
            continue
    if cached:
        return {**cached, "source": "trm-cache-stale"}
    raise RuntimeError("Could not fetch TRM")


def _fetch_superfinanciera_trm() -> dict:
    with urllib.request.urlopen(SUPERFINANCIERA_TRM_URL, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    row = payload[0] if payload else {}
    value = float(row["valor"])
    return {
        "reference_rate": value,
        "reference_rate_source": "superfinanciera-datos-gov",
        "reference_rate_date": row.get("vigenciadesde"),
        "reference_rate_valid_until": row.get("vigenciahasta"),
        "source": "superfinanciera",
    }


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
