"""
Adaptador de canal de mensajería (espejo del adaptador anti-corrupción del CRM).

El pipeline del orquestador (`_process_message`) es agnóstico del canal: recibe
un `recipient` (identificador estable del usuario) y un `Channel` por el que
responder. Así Telegram, WhatsApp y el endpoint HTTP comparten el mismo núcleo
(Nivel 1 + Nivel 2 + RAG) sin duplicar lógica.
"""
import logging
from typing import Optional

from .whatsapp import send_text_message

log = logging.getLogger(__name__)


def _split(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts, rest = [], text
    while rest:
        parts.append(rest[:max_len])
        rest = rest[max_len:]
    return parts


class Channel:
    """Interfaz uniforme de salida."""
    name = "base"

    async def send(self, recipient: str, text: str) -> None:
        raise NotImplementedError


class WhatsAppChannel(Channel):
    name = "whatsapp"

    async def send(self, recipient: str, text: str) -> None:
        await send_text_message(recipient, text)


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, bot):
        self._bot = bot  # telegram.Bot (inyectado por telegram_bot.py)

    async def send(self, recipient: str, text: str) -> None:
        if not text:
            return
        for chunk in _split(text, 4096):  # límite de Telegram
            await self._bot.send_message(chat_id=int(recipient), text=chunk)


class NoopChannel(Channel):
    """No envía nada: la respuesta se devuelve por HTTP (endpoint /chat, consola web)."""
    name = "api"

    async def send(self, recipient: str, text: str) -> None:
        return None


# Instancias compartidas reutilizables
WHATSAPP = WhatsAppChannel()
NOOP = NoopChannel()
