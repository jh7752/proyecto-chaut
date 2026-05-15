import json
import re
import subprocess
import time
from pathlib import Path

CACHE_PATH = Path("/tmp/chaut-seticap-trm-cache.json")
SETICAP_DIR = Path(__file__).resolve().parents[3] / "vendor" / "seticap-trm"
CACHE_TTL_SECONDS = 3600


def get_seticap_trm(ttl_seconds: int = CACHE_TTL_SECONDS) -> dict:
    cached = _read_cache()
    now = time.time()
    if cached and now - float(cached.get("fetched_at_epoch", 0)) < ttl_seconds:
        return {**cached, "source": "seticap-cache"}

    try:
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
        payload["fetched_at_epoch"] = now
        CACHE_PATH.write_text(json.dumps(payload))
        return payload
    except Exception:
        if cached:
            return {**cached, "source": "seticap-cache-stale"}
        raise


def _read_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return None


def _parse_seticap_output(output: str) -> dict:
    trm_match = re.search(r"TRM:\s*\$\s*([0-9,.]+)", output)
    date_match = re.search(r"Fecha:\s*([^\n]+)", output)
    if not trm_match:
        raise ValueError("Could not parse Seticap TRM")
    value = float(trm_match.group(1).replace(",", ""))
    return {
        "reference_rate": value,
        "reference_rate_source": "seticap",
        "reference_rate_date": date_match.group(1).strip() if date_match else None,
    }
