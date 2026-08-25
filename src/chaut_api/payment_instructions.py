import re
from typing import Any


ADDRESS_PATTERNS = [
    ("bre-b", re.compile(r"@[A-Za-z0-9._-]{6,64}")),
    ("tron", re.compile(r"\bT[A-Za-z1-9]{33}\b")),
    ("evm", re.compile(r"\b0x[a-fA-F0-9]{40}\b")),
    ("btc", re.compile(r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}\b")),
]


def extract_payment_instructions(inspection: dict[str, Any]) -> dict[str, Any]:
    structured = inspection.get("instructions") or {}
    text_parts = [
        str(structured.get("breb_alias") or ""),
        str(structured.get("amount_cop_text") or ""),
        str(inspection.get("before") or ""),
        str(inspection.get("snapshot", {}).get("bodyText") or ""),
        str(inspection.get("after", {}).get("text") or ""),
        str(inspection.get("finalSnapshot", {}).get("bodyText") or ""),
    ]
    events = inspection.get("events") or []
    for event in events:
        body = event.get("body")
        post_data = event.get("postData")
        if body:
            text_parts.append(str(body))
        if post_data:
            text_parts.append(str(post_data))
    full_text = "\n".join(text_parts)

    addresses = []
    for network, pattern in ADDRESS_PATTERNS:
        for match in pattern.findall(full_text):
            item = {"network": network, "address": match}
            if item not in addresses:
                addresses.append(item)

    methods = []
    for method in ["DCOP", "PSE", "Wompi", "Nequi", "Bancolombia", "Transferencia"]:
        if re.search(rf"\b{re.escape(method)}\b", full_text, re.IGNORECASE):
            methods.append(method)

    amount_match = re.search(r"(?:Envía|Envia|Enviar)\s+([0-9.,]+)\s+COP", full_text, re.IGNORECASE)
    amount_cop_text = structured.get("amount_cop_text") or (amount_match.group(1) if amount_match else None)
    deposit_provider_id = structured.get("deposit_provider_id")

    return {
        "status": "extracted" if addresses or methods or deposit_provider_id else "not_found",
        "methods": methods or (["Bre-B"] if structured.get("breb_alias") else []),
        "addresses": addresses,
        "amount_cop_text": amount_cop_text,
        "deposit_provider_id": deposit_provider_id,
        "summary": {
            "events_count": len(events),
            "has_front_text": bool(full_text.strip()),
            "source": inspection.get("mode"),
        },
    }


def parse_cop_amount(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = value.strip().replace(" ", "")
    if not normalized:
        return None
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(",", "")
    elif "," in normalized:
        parts = normalized.split(",")
        if len(parts[-1]) == 2:
            normalized = "".join(parts[:-1]) + "." + parts[-1]
        else:
            normalized = "".join(parts)
    try:
        return float(normalized)
    except ValueError:
        return None
