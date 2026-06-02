"""
Bot de Telegram (modo polling) — canal de la demo.

Reusa el mismo pipeline del orquestador (Nivel 1 + Nivel 2 + RAG) a través del
adaptador de canal. No necesita endpoint HTTPS público ni verificación de
empresa: solo un token de @BotFather. Es gratis e ilimitado.

Ejecutar:
    python -m orchestrator.telegram_bot
"""
import logging
import sys

# Consolas Windows en cp1252: forzar UTF-8 (tickets/logs con emojis).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
)

from .config import get_settings
from .channels import TelegramChannel
from .main import _process_message
from .session_store import get_redis, hash_phone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("telegram_bot")
settings = get_settings()

WELCOME = (
    "👋 ¡Hola! Soy el asistente comercial de la Universidad Icesi.\n"
    "Cuéntame qué programa te interesa (pregrado, posgrado o educación continua) "
    "y con gusto te acompaño.\n\n"
    "Usa /reset si quieres empezar de cero."
)


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def on_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    try:
        r = await get_redis()
        await r.delete(f"session:{hash_phone(chat_id)}")
    except Exception as exc:
        log.warning(f"No se pudo reiniciar la sesión: {exc}")
    await update.message.reply_text("Listo, reinicié nuestra conversación. ¿En qué te puedo ayudar?")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = str(update.effective_chat.id)
    text = update.message.text

    # Indicador "escribiendo…" mientras el modelo responde.
    try:
        await context.bot.send_chat_action(chat_id=int(chat_id), action="typing")
    except Exception:
        pass

    channel = TelegramChannel(context.bot)
    try:
        # _process_message envía la respuesta por el canal (Telegram) internamente.
        await _process_message(chat_id, text, channel)
    except Exception as exc:
        log.exception("Error procesando mensaje")
        await update.message.reply_text(
            "Tuve un inconveniente técnico. Un asesor del equipo Icesi te puede ayudar; "
            "intenta de nuevo en un momento."
        )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Excepción en el handler", exc_info=context.error)


def main():
    token = settings.telegram_bot_token
    if not token:
        raise SystemExit(
            "Falta TELEGRAM_BOT_TOKEN en el .env. "
            "Crea un bot con @BotFather en Telegram y pega el token."
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("reset", on_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)

    log.info("Bot de Telegram iniciado (polling). Ctrl+C para detener.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
