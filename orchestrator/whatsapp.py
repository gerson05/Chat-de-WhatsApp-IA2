"""WhatsApp Cloud API: webhook verification, message receiving, message sending."""
import hashlib
import hmac
import logging
from typing import Optional

import httpx

from .config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)

WA_API_BASE = "https://graph.facebook.com/v20.0"


# ── Signature verification ─────────────────────────────────────────────────────

def verify_signature(payload: bytes, x_hub_signature: str) -> bool:
    """Validate Meta webhook HMAC-SHA256 signature using the App Secret."""
    if not settings.whatsapp_app_secret:
        if settings.app_env == "production":
            log.error(
                "[WA] WHATSAPP_APP_SECRET not set in production — "
                "rejecting webhook. Set the env var to restore service."
            )
            return False
        log.warning(
            "[WA] WHATSAPP_APP_SECRET not set — skipping signature check "
            "(dev mode only, never deploy without this secret)."
        )
        return True

    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, x_hub_signature or "")


# ── Parse incoming webhook ─────────────────────────────────────────────────────

def parse_incoming_message(body: dict) -> Optional[dict]:
    """
    Extract (from_number, message_text, message_id) from a webhook payload.
    Returns None if the payload is not a text message.
    """
    try:
        entry = body["entry"][0]
        change = entry["changes"][0]
        value = change["value"]
        message = value["messages"][0]

        if message.get("type") != "text":
            return None

        return {
            "from": message["from"],
            "text": message["text"]["body"],
            "message_id": message["id"],
            "timestamp": message.get("timestamp"),
        }
    except (KeyError, IndexError):
        return None


# ── Send message ───────────────────────────────────────────────────────────────

async def send_text_message(to: str, text: str) -> bool:
    """Send a WhatsApp text message. Splits into ≤3 bubbles if >1024 chars."""
    if not settings.whatsapp_phone_id or not settings.whatsapp_access_token:
        log.info(f"[WA] DEMO MODE — to={to}: {text[:120]}...")
        return True

    chunks = _split_message(text)
    url = f"{WA_API_BASE}/{settings.whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": chunk, "preview_url": False},
            }
            resp = await client.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code != 200:
                log.error(f"[WA] Send failed: {resp.status_code} {resp.text}")
                return False
    return True


async def send_template_message(to: str, template_name: str, params: list[str]) -> bool:
    """Send a pre-approved WhatsApp template message."""
    if not settings.whatsapp_phone_id or not settings.whatsapp_access_token:
        log.info(f"[WA] DEMO — template {template_name} to {to} params={params}")
        return True

    components = []
    if params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        })

    url = f"{WA_API_BASE}/{settings.whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "es"},
            "components": components,
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers, timeout=10)
        return resp.status_code == 200


def _split_message(text: str, max_len: int = 1024) -> list[str]:
    """Split long messages into up to 3 WhatsApp-sized bubbles."""
    if len(text) <= max_len:
        return [text]

    parts = []
    while text and len(parts) < 3:
        if len(text) <= max_len:
            parts.append(text)
            break
        # Try to split at a sentence boundary
        cut = text.rfind(". ", 0, max_len)
        if cut == -1:
            cut = max_len
        else:
            cut += 1
        parts.append(text[:cut].strip())
        text = text[cut:].strip()

    return parts
