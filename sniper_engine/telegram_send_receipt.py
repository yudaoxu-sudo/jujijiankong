from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _optional_int(value: Any) -> int | None:
    return value if type(value) is int else None


def read_telegram_send_receipt(response: Any) -> dict[str, Any]:
    try:
        payload = json.loads(response.read())
    except (AttributeError, json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Telegram sendMessage returned an invalid response") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("Telegram sendMessage did not confirm the message")

    result = payload.get("result")
    if not isinstance(result, dict):
        result = {}
    http_status = getattr(response, "status", None)
    if http_status is None:
        getcode = getattr(response, "getcode", None)
        http_status = getcode() if callable(getcode) else None
    return {
        "api_ok": True,
        "http_status": _optional_int(http_status),
        "message_id": _optional_int(result.get("message_id")),
        "message_date": _optional_int(result.get("date")),
    }


def record_telegram_send_receipt(
    path: Path,
    *,
    sent_at: str,
    signature: str,
    text: str,
    receipt: dict[str, Any],
) -> None:
    if receipt.get("api_ok") is not True:
        raise RuntimeError("Telegram sendMessage receipt is not confirmed")
    payload = {
        "sent_at": sent_at,
        "signature": signature,
        "text": text,
        "text_chars": len(text),
        "text_lines": len(text.splitlines()) if text else 0,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "api_ok": True,
        "http_status": _optional_int(receipt.get("http_status")),
        "message_id": _optional_int(receipt.get("message_id")),
        "message_date": _optional_int(receipt.get("message_date")),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
