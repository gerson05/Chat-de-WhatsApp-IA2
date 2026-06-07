"""
5 tool functions that the Claude orchestrator calls.
Each returns a dict that is serialized back to the model as a tool_result.
"""
import json
import re
import yaml
import os
from datetime import datetime
from typing import Optional

from .config import get_settings
from .rag import query_kb, format_kb_results
from .models import (
    SessionState, EtapaCIIPOC, EscalamientoMotivo, Prioridad, ResumenEscalamiento
)

settings = get_settings()

# ── Tool schemas for Claude API ────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "consultar_base_conocimiento",
        "description": (
            "Recupera fragmentos relevantes de la base de conocimiento Icesi "
            "(diferenciales, fichas de programa, FAQs, financiación). "
            "Úsala antes de afirmar cualquier dato factual sobre programas, "
            "becas, precios, fechas o procesos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Pregunta o tema a buscar, en lenguaje natural y en español.",
                },
                "segmento_filtro": {
                    "type": "string",
                    "enum": ["pregrado", "posgrado", "educontinua", "transversal"],
                },
            },
            "required": ["consulta"],
        },
    },
    {
        "name": "validar_programa",
        "description": (
            "Valida que un programa exista en el piloto y devuelve su ficha resumida "
            "(id, nombre, unidad, duración, modalidad, diferencial_breve). "
            "Si no existe, devuelve null y el modelo debe escalar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string"},
            },
            "required": ["nombre"],
        },
    },
    {
        "name": "registrar_intencion",
        "description": (
            "Registra avances de la conversación: etapa CIIPOC alcanzada, "
            "programa de interés confirmado, necesidad, barrera, siguiente acción. "
            "No retorna nada útil para el aspirante; es memoria interna del sistema."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "etapa": {
                    "type": "string",
                    "enum": [
                        "contacto", "indagacion", "identificacion",
                        "propuesta", "objeciones", "cierre",
                    ],
                },
                "programa": {"type": "string"},
                "siguiente_accion": {"type": "string"},
                "barrera": {"type": "string"},
                "necesidad": {"type": "string"},
            },
            "required": ["etapa"],
        },
    },
    {
        "name": "escalar_a_asesor",
        "description": (
            "Activa el handoff al asesor humano. El orquestador creará un ticket "
            "en CRM y notificará al equipo por WhatsApp interno. "
            "Después de llamarla, envía un mensaje al usuario informándole."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "enum": [
                        "solicitud_explicita", "dato_no_documentado",
                        "objecion_compleja", "frustracion", "sin_avance",
                        "alta_intencion_cierre", "b2b", "crisis_emocional",
                        "programa_fuera_piloto",
                    ],
                },
                "prioridad": {
                    "type": "string",
                    "enum": ["alta", "media", "baja"],
                },
                "resumen": {
                    "type": "object",
                    "properties": {
                        "nombre_aspirante": {"type": "string"},
                        "programa_interes": {"type": "string"},
                        "segmento": {"type": "string"},
                        "etapa_ciipoc_actual": {"type": "string"},
                        "necesidad_identificada": {"type": "string"},
                        "barrera_principal": {"type": "string"},
                        "tono_aspirante": {
                            "type": "string",
                            "description": (
                                "Tono emocional del aspirante en los últimos mensajes. "
                                "Ej: 'ansioso por fechas', 'frustrado con costos', 'muy motivado'."
                            ),
                        },
                        "ultimos_5_intercambios": {"type": "string"},
                        "siguiente_accion_sugerida": {"type": "string"},
                    },
                },
            },
            "required": ["motivo", "prioridad", "resumen"],
        },
    },
    {
        "name": "capturar_datos_aspirante",
        "description": (
            "Registra y valida datos de contacto del aspirante: nombre completo, "
            "email y/o teléfono. Llama esta función cuando el aspirante proporcione "
            "cualquiera de estos datos durante la conversación. Los datos se persisten "
            "en la sesión y se sincronizan con el CRM en el momento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre completo del aspirante.",
                },
                "email": {
                    "type": "string",
                    "description": "Dirección de correo electrónico del aspirante.",
                },
                "telefono": {
                    "type": "string",
                    "description": "Número de teléfono de contacto (solo dígitos, sin espacios ni guiones).",
                },
            },
        },
    },
    {
        "name": "sugerir_siguiente_paso",
        "description": (
            "Devuelve la siguiente mejor acción CIIPOC dada la etapa actual y el contexto. "
            "Útil cuando el modelo duda cómo avanzar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "etapa_actual": {"type": "string"},
            },
            "required": ["etapa_actual"],
        },
    },
]

# ── Manifest loader ────────────────────────────────────────────────────────────

_manifest_cache: Optional[dict] = None


def _load_manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        manifest_path = os.path.join(settings.kb_path, "manifest.yaml")
        if os.path.exists(manifest_path):
            with open(manifest_path, encoding="utf-8") as f:
                _manifest_cache = yaml.safe_load(f) or {}
        else:
            _manifest_cache = {"documentos": []}
    return _manifest_cache


# ── Next-step table ────────────────────────────────────────────────────────────

_NEXT_STEP = {
    "contacto": (
        "Estás en Contacto. Siguiente paso: pedir nombre del aspirante y usar "
        "una pregunta abierta para descubrir qué programa le interesa. "
        "Ejemplo: '¿Qué te llevó a interesarte por Icesi?'"
    ),
    "indagacion": (
        "Estás en Indagación. Siguiente paso: descubrir el momento de decisión "
        "(¿explorando, comparando, decidido?) y la barrera principal "
        "(costo, horario, distancia, dudas académicas)."
    ),
    "identificacion": (
        "Estás en Identificación. Siguiente paso: hacer un resumen empático de "
        "lo que escuchaste ('Entiendo, estás buscando...') y conectarlo con el "
        "programa o diferencial Icesi más relevante."
    ),
    "propuesta": (
        "Estás en Propuesta. Siguiente paso: presentar 2-3 diferenciales clave "
        "del programa usando datos de la KB. Cerrar con una pregunta de "
        "confirmación: '¿Esto responde lo que estabas buscando?'"
    ),
    "objeciones": (
        "Estás en Objeciones. Siguiente paso: escuchar la objeción completa, "
        "validar con empatía, responder con datos de la KB. Si es financiera "
        "compleja, escalar al asesor."
    ),
    "cierre": (
        "Estás en Cierre. Siguiente paso: proponer UNA acción concreta: "
        "agendar llamada con asesor, inscribirse a evento, completar formulario "
        "de interés. NO presiones por matrícula directa."
    ),
}

# ── Tool implementations ────────────────────────────────────────────────────────


def tool_consultar_base_conocimiento(
    consulta: str,
    segmento_filtro: Optional[str] = None,
    session: Optional[SessionState] = None,
) -> dict:
    # Enrich the query with session context for better retrieval
    if session:
        contexto = ""
        if session.etapa_ciipoc:
            contexto += f" etapa:{session.etapa_ciipoc.value}"
        if session.programa_interes:
            contexto += f" programa:{session.programa_interes}"
        consulta_enriquecida = consulta + contexto
    else:
        consulta_enriquecida = consulta

    seg = segmento_filtro
    if not seg and session and session.segmento.value != "indefinido":
        seg = session.segmento.value

    chunks = query_kb(consulta_enriquecida, segmento_filtro=seg)
    return {"resultado": format_kb_results(chunks), "chunks_encontrados": len(chunks)}


def tool_validar_programa(nombre: str) -> dict:
    manifest = _load_manifest()
    docs = manifest.get("documentos", [])
    nombre_lower = nombre.lower()

    for doc in docs:
        doc_nombre = doc.get("nombre", "").lower()
        doc_id = doc.get("id", "").lower()
        if nombre_lower in doc_nombre or nombre_lower in doc_id:
            return {
                "encontrado": True,
                "id": doc.get("id"),
                "nombre": doc.get("nombre"),
                "unidad": doc.get("unidad"),
                "nivel": doc.get("nivel"),
                "duracion": doc.get("duracion"),
                "modalidad": doc.get("modalidad"),
                "diferencial_breve": doc.get("diferencial_breve", ""),
            }

    # Try partial match
    for doc in docs:
        palabras = nombre_lower.split()
        doc_nombre = doc.get("nombre", "").lower()
        if any(p in doc_nombre for p in palabras if len(p) > 4):
            return {
                "encontrado": True,
                "id": doc.get("id"),
                "nombre": doc.get("nombre"),
                "unidad": doc.get("unidad"),
                "diferencial_breve": doc.get("diferencial_breve", ""),
            }

    return {
        "encontrado": False,
        "mensaje": (
            f"El programa '{nombre}' no está en el piloto actual. "
            "Debes escalar al asesor de la unidad correspondiente."
        ),
    }


def tool_registrar_intencion(
    etapa: str,
    session: SessionState,
    programa: Optional[str] = None,
    siguiente_accion: Optional[str] = None,
    barrera: Optional[str] = None,
    necesidad: Optional[str] = None,
) -> dict:
    try:
        nueva_etapa = EtapaCIIPOC(etapa)
    except ValueError:
        return {"ok": False, "error": f"Etapa inválida: {etapa}"}

    etapas_orden = list(EtapaCIIPOC)
    idx_actual = etapas_orden.index(session.etapa_ciipoc)
    idx_nueva = etapas_orden.index(nueva_etapa)

    avanzó = idx_nueva > idx_actual
    session.etapa_ciipoc = nueva_etapa

    if avanzó:
        session.contador_mensajes_sin_avance = 0
    else:
        session.contador_mensajes_sin_avance += 1

    if programa:
        session.programa_interes = programa
    if siguiente_accion:
        session.intencion_siguiente_accion = siguiente_accion
    if barrera:
        session.barrera = barrera
    if necesidad:
        session.necesidad_identificada = necesidad

    return {"ok": True, "etapa_registrada": etapa, "avanzó_etapa": avanzó}


def tool_escalar_a_asesor(
    motivo: str,
    prioridad: str,
    resumen: dict,
    session: SessionState,
) -> dict:
    session.escalado = True

    # Determine target advisor based on segment
    segmento_map = {
        "pregrado": "Julian Andrés Gil",
        "posgrado": "Lauri Ariza",
        "educontinua": "Yerli Valencia",
    }
    if motivo == "b2b":
        asesor = "Alejandra Tinoco"
    elif session.segmento.value in segmento_map:
        asesor = segmento_map[session.segmento.value]
    else:
        asesor = "Carlos Londoño (Jefe Comercial)"

    session.id_asesor_asignado = asesor

    ticket = _build_ticket(motivo, prioridad, resumen, asesor, session)

    # Persist ticket to DB (async via nivel2 — here we just return the ticket)
    return {
        "ok": True,
        "motivo": motivo,
        "asesor_asignado": asesor,
        "prioridad": prioridad,
        "ticket": ticket,
        "mensaje_para_aspirante": (
            f"Perfecto, voy a conectarte con {asesor} del equipo Icesi, "
            "quien te atenderá personalmente. Te contactará muy pronto. "
            "¡Gracias por tu paciencia!"
        ),
    }


_FRUSTRATION_KW = [
    "no me entiendes", "no sirves", "esto no sirve", "qué mal",
    "horrible", "inútil", "no ayudas", "para qué sirves",
    "mentira", "no es cierto", "nunca", "siempre mal", "pésimo",
]

_URGENCIA_LABEL = {
    "crisis_emocional":     "🚨 URGENTE — posible crisis emocional",
    "alta_intencion_cierre": "🎯 OPORTUNIDAD — alta intención de matrícula",
    "b2b":                  "🏢 B2B — requiere propuesta empresarial",
    "frustracion":          "⚠️  ATENCIÓN — aspirante frustrado",
    "solicitud_explicita":  "👋 Solicitó asesor directamente",
    "objecion_compleja":    "💡 Objeción compleja — requiere criterio humano",
    "dato_no_documentado":  "🔍 Dato no documentado en KB",
    "sin_avance":           "⏳ Sin avance — conversación estancada",
    "programa_fuera_piloto": "📋 Programa fuera del piloto actual",
}

_MOTIVO_TEXTO = {
    "solicitud_explicita":  "Solicitó hablar con asesor",
    "dato_no_documentado":  "Preguntó dato no documentado",
    "objecion_compleja":    "Objeción compleja",
    "frustracion":          "Señales de frustración",
    "sin_avance":           "Sin avance después de 10+ mensajes",
    "alta_intencion_cierre": "Alta intención de matrícula",
    "b2b":                  "Caso corporativo / B2B",
    "crisis_emocional":     "Señal de crisis emocional",
    "programa_fuera_piloto": "Programa fuera del piloto",
}


def _compute_frustration_level(session: SessionState) -> str:
    recent = " ".join(t.text.lower() for t in session.historial[-6:] if t.role == "user")
    hits = sum(1 for kw in _FRUSTRATION_KW if kw in recent)
    if hits >= 2:
        return "alto 🔴"
    if hits == 1:
        return "medio 🟡"
    return "bajo 🟢"


def _build_ticket(motivo, prioridad, resumen, asesor, session: SessionState) -> str:
    prioridad_emoji = {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(prioridad, "⚪")
    nombre = resumen.get("nombre_aspirante") or session.nombre or "Aspirante"
    programa = resumen.get("programa_interes") or session.programa_interes or "Por definir"
    seg = resumen.get("segmento") or session.segmento.value
    etapa = resumen.get("etapa_ciipoc_actual") or session.etapa_ciipoc.value
    necesidad = resumen.get("necesidad_identificada") or session.necesidad_identificada or "—"
    barrera = resumen.get("barrera_principal") or session.barrera or "—"
    tono = resumen.get("tono_aspirante") or "—"
    intercambios = resumen.get("ultimos_5_intercambios") or _last_turns(session, 5)
    siguiente = resumen.get("siguiente_accion_sugerida") or session.intencion_siguiente_accion or "—"
    motivo_texto = _MOTIVO_TEXTO.get(motivo, motivo)
    urgencia = _URGENCIA_LABEL.get(motivo, f"Motivo: {motivo_texto}")
    frustracion = _compute_frustration_level(session)
    turno_en_etapa = session.contador_mensajes_sin_avance

    return (
        f"{prioridad_emoji} ESCALAMIENTO IA — Prioridad: {prioridad.upper()}\n"
        f"{'═' * 45}\n"
        f"📋 BRIEFING EJECUTIVO\n"
        f"  {urgencia}\n"
        f"  {nombre} → {programa} (etapa: {etapa}, segmento: {seg})\n"
        f"  Frustración: {frustracion} | Turnos sin avance: {turno_en_etapa}\n"
        f"  Barrera: {barrera}\n"
        f"{'─' * 45}\n"
        f"Aspirante: {nombre} ({session.id_lead_crm or 'nuevo lead'})\n"
        f"Programa: {programa}\n"
        f"Segmento: {seg}\n"
        f"Etapa CIIPOC: {etapa}\n"
        f"Asesor asignado: {asesor}\n"
        f"Motivo: {motivo_texto}\n\n"
        f"📌 Necesidad identificada:\n{necesidad}\n\n"
        f"🚧 Barrera principal:\n{barrera}\n\n"
        f"🎭 Tono del aspirante:\n{tono}\n\n"
        f"💬 Últimos intercambios:\n{intercambios}\n\n"
        f"✅ Acción recomendada:\n{siguiente}\n\n"
        f"⏱ Hora del escalamiento: {datetime.utcnow().strftime('%H:%M UTC')}"
    )


def _last_turns(session: SessionState, n: int) -> str:
    turns = session.historial[-n:]
    return "\n".join(
        f"[{'Aspirante' if t.role == 'user' else 'Agente'}] {t.text}"
        for t in turns
    )


_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_PHONE_RE = re.compile(r'^\d{7,15}$')


def tool_capturar_datos_aspirante(
    session: SessionState,
    nombre: Optional[str] = None,
    email: Optional[str] = None,
    telefono: Optional[str] = None,
) -> dict:
    updated = []
    errors = []

    if nombre:
        session.nombre = nombre.strip()
        updated.append("nombre")

    if email:
        email = email.strip().lower()
        if _EMAIL_RE.match(email):
            session.email = email
            updated.append("email")
        else:
            errors.append(f"email inválido: '{email}'")

    if telefono:
        telefono_clean = re.sub(r'\D', '', telefono)
        if _PHONE_RE.match(telefono_clean):
            session.telefono_contacto = telefono_clean
            updated.append("telefono")
        else:
            errors.append(f"teléfono inválido: '{telefono}'")

    return {
        "ok": len(updated) > 0,
        "campos_guardados": updated,
        "errores": errors,
        "resumen": (
            f"Datos guardados: {', '.join(updated)}."
            if updated else "No se guardó ningún dato."
        ),
    }


def tool_sugerir_siguiente_paso(etapa_actual: str) -> dict:
    sugerencia = _NEXT_STEP.get(etapa_actual.lower())
    if not sugerencia:
        sugerencia = (
            "No reconozco esa etapa. Las etapas válidas son: "
            "contacto, indagacion, identificacion, propuesta, objeciones, cierre."
        )
    return {"sugerencia": sugerencia}


# ── Dispatcher ────────────────────────────────────────────────────────────────

def dispatch_tool(
    name: str,
    input_data: dict,
    session: SessionState,
) -> dict:
    """Routes a tool_call from Claude to the correct function."""
    if name == "consultar_base_conocimiento":
        return tool_consultar_base_conocimiento(
            consulta=input_data["consulta"],
            segmento_filtro=input_data.get("segmento_filtro"),
            session=session,
        )
    elif name == "validar_programa":
        return tool_validar_programa(nombre=input_data["nombre"])
    elif name == "registrar_intencion":
        return tool_registrar_intencion(
            etapa=input_data["etapa"],
            session=session,
            programa=input_data.get("programa"),
            siguiente_accion=input_data.get("siguiente_accion"),
            barrera=input_data.get("barrera"),
            necesidad=input_data.get("necesidad"),
        )
    elif name == "escalar_a_asesor":
        return tool_escalar_a_asesor(
            motivo=input_data["motivo"],
            prioridad=input_data["prioridad"],
            resumen=input_data.get("resumen", {}),
            session=session,
        )
    elif name == "capturar_datos_aspirante":
        return tool_capturar_datos_aspirante(
            session=session,
            nombre=input_data.get("nombre"),
            email=input_data.get("email"),
            telefono=input_data.get("telefono"),
        )
    elif name == "sugerir_siguiente_paso":
        return tool_sugerir_siguiente_paso(etapa_actual=input_data["etapa_actual"])
    else:
        return {"error": f"Tool desconocida: {name}"}
