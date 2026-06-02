"""
Core conversation loop: builds context, calls Claude with tool-use,
executes tool calls, returns final response text.
"""
import json
import logging
import re
from typing import Optional

from . import llm

from .config import get_settings
from .models import SessionState
from .system_prompt import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, dispatch_tool

settings = get_settings()
log = logging.getLogger(__name__)

# Patterns that may signal hallucinated factual claims — used by the gate
_HALLUCINATION_PATTERNS = [
    r"\$[\d.,]+",                        # price figures
    r"\d+\s*%\s*(de\s+beca|descuento)",  # beca percentages
    r"cuesta?\s+[\d.,]+",
    r"valor\s+(es|de)\s+[\d.,]+",
    r"semestre[s]?\s+\$",
]

_FRUSTRATION_KEYWORDS = [
    "no me entiendes", "no sirves", "esto no sirve", "qué mal servicio",
    "horrible", "inútil", "no ayudas", "para qué sirves",
]

_B2B_KEYWORDS = [
    "empresa", "compañía", "grupo de empleados", "convenio empresarial",
    "capacitar a", "matricular varios", "organización",
]

_CRISIS_KEYWORDS = [
    "suicidio", "no quiero vivir", "me quiero matar", "no puedo más",
    "desesperado", "crisis", "ayuda psicológica",
]


def _detect_pre_escalation(message: str) -> Optional[str]:
    """Detect conditions that should trigger escalation even before Claude responds."""
    msg_lower = message.lower()
    for kw in _CRISIS_KEYWORDS:
        if kw in msg_lower:
            return "crisis_emocional"
    for kw in _B2B_KEYWORDS:
        if kw in msg_lower:
            return "b2b"
    return None


def _has_hallucination_risk(text: str) -> bool:
    for pat in _HALLUCINATION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def _check_frustration(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _FRUSTRATION_KEYWORDS)


def _build_messages(session: SessionState, user_message: str) -> list[dict]:
    """Assemble the messages array for the Claude API call."""
    messages = []

    # Include compressed early history if exists
    if session.resumen_temprano:
        messages.append({
            "role": "user",
            "content": f"[CONTEXTO PREVIO DE LA CONVERSACIÓN]\n{session.resumen_temprano}",
        })
        messages.append({
            "role": "assistant",
            "content": "Entendido, tengo el contexto de la conversación anterior.",
        })

    # Session state context injected as a system-level user message
    state_summary = (
        f"[ESTADO ACTUAL DE SESIÓN]\n"
        f"Segmento: {session.segmento.value}\n"
        f"Etapa CIIPOC: {session.etapa_ciipoc.value}\n"
        f"Programa de interés: {session.programa_interes or 'No identificado'}\n"
        f"Nombre: {session.nombre or 'No capturado'}\n"
        f"Barrera: {session.barrera or 'No identificada'}\n"
        f"Necesidad: {session.necesidad_identificada or 'No identificada'}\n"
        f"Mensajes sin avance de etapa: {session.contador_mensajes_sin_avance}\n"
        f"Estado funnel CRM: {session.estado_funnel_crm.value}"
    )
    messages.append({"role": "user", "content": state_summary})
    messages.append({"role": "assistant", "content": "Contexto de sesión cargado. Listo para atender."})

    # Recent history
    for turn in session.get_recent_history():
        messages.append({"role": turn.role, "content": turn.text})

    # Current user message
    messages.append({"role": "user", "content": user_message})
    return messages


async def run_conversation_turn(
    user_message: str,
    session: SessionState,
    client: llm.GeminiClient,
) -> tuple[str, list[dict]]:
    """
    Runs one full conversation turn including tool-use loop.
    Returns (final_text, tool_calls_executed).
    """
    tool_calls_executed: list[dict] = []

    # Pre-flight checks
    pre_escalate = _detect_pre_escalation(user_message)
    if pre_escalate:
        user_message = (
            user_message
            + f"\n[SISTEMA: Detectada señal de '{pre_escalate}'. "
            "Llama escalar_a_asesor inmediatamente con el motivo correcto.]"
        )

    if _check_frustration(user_message):
        user_message = (
            user_message
            + "\n[SISTEMA: El aspirante muestra frustración. "
            "Discúlpate brevemente y llama escalar_a_asesor con motivo='frustracion'.]"
        )

    if session.contador_mensajes_sin_avance >= settings.max_turns_without_advance:
        user_message = (
            user_message
            + "\n[SISTEMA: Se superaron 10 mensajes sin avanzar de etapa CIIPOC. "
            "Llama escalar_a_asesor con motivo='sin_avance'.]"
        )

    messages = _build_messages(session, user_message)
    final_text = ""
    iterations = 0
    max_iterations = 8  # prevent infinite tool-use loops

    current_messages = messages[:]

    while iterations < max_iterations:
        iterations += 1

        try:
            response = await client.messages.create(
                model=settings.llm_model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=current_messages,
                timeout=settings.model_timeout_seconds,
            )
        except llm.APITimeoutError:
            log.warning("[Conversation] Claude timeout — returning fallback")
            return (
                "Estoy procesando tu solicitud, dame un momento por favor.",
                tool_calls_executed,
            )
        except Exception as exc:
            log.error(f"[Conversation] Claude API error: {exc}")
            return (
                "Estoy teniendo dificultades técnicas. Un asesor te contactará pronto.",
                tool_calls_executed,
            )

        # Collect text blocks
        text_parts = [
            block.text for block in response.content if block.type == "text"
        ]
        if text_parts:
            final_text = " ".join(text_parts)

        # If no tool calls, we're done
        if response.stop_reason != "tool_use":
            break

        # Execute tool calls
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        tool_results = []

        for block in tool_use_blocks:
            result = dispatch_tool(block.name, block.input, session)
            tool_calls_executed.append({"name": block.name, "input": block.input, "result": result})

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        # Continue the conversation with tool results
        current_messages = current_messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": tool_results},
        ]

    if not final_text.strip() and tool_calls_executed:
        try:
            closing = await client.messages.create(
                model=settings.llm_model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=current_messages,
                timeout=settings.model_timeout_seconds,
            )
            closing_parts = [b.text for b in closing.content if b.type == "text"]
            if closing_parts:
                final_text = " ".join(closing_parts)
        except Exception as exc:
            log.warning(f"[Conversation] Closing-text retry failed: {exc}")

    # Hallucination gate: if response contains risky patterns and no KB was called,
    # force a KB lookup signal
    kb_was_called = any(tc["name"] == "consultar_base_conocimiento" for tc in tool_calls_executed)
    if final_text and _has_hallucination_risk(final_text) and not kb_was_called:
        log.warning("[Conversation] Hallucination risk detected — suppressing response")
        final_text = (
            "Déjame confirmar ese dato con la información más actualizada de Icesi. "
            "Un momento, por favor."
        )

    # Loop detection: if response == last bot message, escalate
    last_bot = next(
        (t.text for t in reversed(session.historial) if t.role == "assistant"), ""
    )
    if final_text and final_text.strip() == last_bot.strip():
        log.warning("[Conversation] Loop detected — escalating")
        final_text = (
            "Quiero asegurarme de darte la mejor atención. "
            "Voy a conectarte con un asesor del equipo Icesi."
        )

    return final_text or "Gracias por escribirnos. ¿En qué puedo ayudarte?", tool_calls_executed
