"""
Capa de abstracción del LLM.

Envuelve Google Gemini (AI Studio) detrás de una interfaz compatible con la
API Messages de Anthropic, de modo que el resto del código
(`conversation.py`, `session_store.py`) puede seguir llamando
`client.messages.create(system=..., tools=..., messages=...)` sin cambios.

Motivo: el MVP migró de Claude (de pago) a Gemini (capa gratuita de AI Studio).
Toda la lógica específica de proveedor queda aislada en este módulo.
"""
import asyncio
import json
import logging
from typing import Any, Optional

import google.generativeai as genai

from .config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)


# ── Excepciones (replican la superficie de anthropic usada en el código) ─────────

class APITimeoutError(Exception):
    """Equivalente a anthropic.APITimeoutError para el manejo en conversation.py."""


# ── Bloques de respuesta (replican response.content de Anthropic) ────────────────

class _TextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id: str, name: str, input: dict):
        self.id = id
        self.name = name
        self.input = input


class _Response:
    """Replica el objeto de respuesta de Anthropic: .content (lista de bloques) y .stop_reason."""

    def __init__(self, content: list, stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


# ── Conversión de tipos proto de Gemini a estructuras Python planas ──────────────

def _to_plain(obj: Any) -> Any:
    """Convierte recursivamente los tipos proto-plus (MapComposite / RepeatedComposite)
    devueltos por Gemini en dicts / lists nativos de Python."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "items"):  # MapComposite / dict
        return {k: _to_plain(v) for k, v in obj.items()}
    if hasattr(obj, "__iter__"):  # RepeatedComposite / list / tuple
        try:
            return [_to_plain(v) for v in obj]
        except TypeError:
            return obj
    return obj


# ── Conversión de tools (schema Anthropic → function_declarations de Gemini) ─────

def _convert_tools(tools: Optional[list]) -> Optional[list]:
    if not tools:
        return None
    declarations = []
    for tool in tools:
        declarations.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        })
    return [{"function_declarations": declarations}]


# ── Conversión de mensajes (formato Anthropic → contents de Gemini) ──────────────

def _build_id_to_name(messages: list) -> dict:
    """Mapea tool_use_id → nombre de la tool, escaneando los bloques tool_use previos.
    Gemini referencia las function_response por nombre, no por id."""
    id_to_name: dict = {}
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "tool_use" and block.get("id"):
                    id_to_name[block["id"]] = block.get("name")
            else:
                if getattr(block, "type", None) == "tool_use" and getattr(block, "id", None):
                    id_to_name[block.id] = block.name
    return id_to_name


def _convert_messages(messages: list) -> list:
    """Convierte el array de mensajes estilo Anthropic en `contents` de Gemini."""
    id_to_name = _build_id_to_name(messages)
    contents = []

    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        content = m["content"]
        parts: list = []

        if isinstance(content, str):
            if content:
                parts.append({"text": content})
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        parts.append({"text": block.get("text", "")})
                    elif btype == "tool_use":
                        parts.append({"function_call": {
                            "name": block.get("name"),
                            "args": block.get("input", {}) or {},
                        }})
                    elif btype == "tool_result":
                        name = id_to_name.get(block.get("tool_use_id"), "tool")
                        raw = block.get("content")
                        try:
                            resp_obj = json.loads(raw) if isinstance(raw, str) else raw
                        except (json.JSONDecodeError, TypeError):
                            resp_obj = {"result": raw}
                        if not isinstance(resp_obj, dict):
                            resp_obj = {"result": resp_obj}
                        parts.append({"function_response": {"name": name, "response": resp_obj}})
                else:
                    # Bloques de respuesta propios (_TextBlock / _ToolUseBlock)
                    btype = getattr(block, "type", None)
                    if btype == "text":
                        parts.append({"text": block.text})
                    elif btype == "tool_use":
                        parts.append({"function_call": {"name": block.name, "args": block.input or {}}})

        if parts:
            contents.append({"role": role, "parts": parts})

    return contents


# ── Parseo de la respuesta de Gemini → bloques estilo Anthropic ──────────────────

def _parse_response(resp: Any) -> _Response:
    content: list = []
    has_tool = False

    try:
        parts = resp.candidates[0].content.parts
    except (AttributeError, IndexError):
        parts = []

    for idx, part in enumerate(parts):
        fn = getattr(part, "function_call", None)
        if fn and getattr(fn, "name", None):
            args = {}
            try:
                args = _to_plain(fn.args) or {}
            except Exception as exc:  # pragma: no cover
                log.warning(f"[LLM] No se pudieron parsear args de tool: {exc}")
            content.append(_ToolUseBlock(id=f"call_{fn.name}_{idx}", name=fn.name, input=args))
            has_tool = True
        else:
            text = getattr(part, "text", None)
            if text:
                content.append(_TextBlock(text=text))

    return _Response(content=content, stop_reason="tool_use" if has_tool else "end_turn")


# ── Cliente compatible con anthropic.AsyncAnthropic ──────────────────────────────

class _Messages:
    async def create(
        self,
        *,
        model: str,
        messages: list,
        max_tokens: int = 1024,
        system: Optional[str] = None,
        tools: Optional[list] = None,
        timeout: Optional[float] = None,
        **_kwargs,
    ) -> _Response:
        contents = _convert_messages(messages)
        gtools = _convert_tools(tools)

        gmodel = genai.GenerativeModel(
            model_name=model,
            system_instruction=system,
            tools=gtools,
            generation_config={"max_output_tokens": max_tokens},
        )

        try:
            coro = gmodel.generate_content_async(contents)
            resp = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)
        except asyncio.TimeoutError as exc:
            raise APITimeoutError("Gemini request timed out") from exc

        return _parse_response(resp)


class GeminiClient:
    """Cliente Gemini con la misma forma que anthropic.AsyncAnthropic: `client.messages.create(...)`."""

    def __init__(self, api_key: str):
        if not api_key:
            log.warning("[LLM] GEMINI_API_KEY vacío — las llamadas al modelo fallarán.")
        genai.configure(api_key=api_key)
        self.messages = _Messages()


_client: Optional[GeminiClient] = None


def get_llm_client() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient(api_key=settings.gemini_api_key)
    return _client
