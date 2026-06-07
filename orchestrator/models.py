from enum import Enum
from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class Segmento(str, Enum):
    pregrado = "pregrado"
    posgrado = "posgrado"
    educontinua = "educontinua"
    indefinido = "indefinido"


class EtapaCIIPOC(str, Enum):
    contacto = "contacto"
    indagacion = "indagacion"
    identificacion = "identificacion"
    propuesta = "propuesta"
    objeciones = "objeciones"
    cierre = "cierre"


class MomentoDecision(str, Enum):
    explorando = "explorando"
    comparando = "comparando"
    decidido = "decidido"
    indefinido = "indefinido"


class EstadoFunnel(str, Enum):
    lead = "lead"
    inscrito = "inscrito"
    admitido = "admitido"
    matricula_proceso = "matricula_proceso"
    matriculado = "matriculado"
    inactivo = "inactivo"
    perdido = "perdido"


class TurnMessage(BaseModel):
    role: str  # "user" | "assistant"
    text: str
    ts: datetime = None

    def __init__(self, **data):
        if data.get("ts") is None:
            data["ts"] = datetime.utcnow()
        super().__init__(**data)


class SessionState(BaseModel):
    id_usuario: str
    tel_encrypted: str = ""
    id_lead_crm: Optional[str] = None
    nombre: Optional[str] = None
    segmento: Segmento = Segmento.indefinido
    etapa_ciipoc: EtapaCIIPOC = EtapaCIIPOC.contacto
    programa_interes: Optional[str] = None
    momento_decision: MomentoDecision = MomentoDecision.indefinido
    necesidad_identificada: Optional[str] = None
    barrera: Optional[str] = None
    ultima_pregunta: str = ""
    intencion_siguiente_accion: Optional[str] = None
    historial: list[TurnMessage] = []
    resumen_temprano: str = ""
    estado_funnel_crm: EstadoFunnel = EstadoFunnel.lead
    escalado: bool = False
    id_asesor_asignado: Optional[str] = None
    contador_mensajes_sin_avance: int = 0
    total_bot_messages: int = 0
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        now = datetime.utcnow()
        if data.get("created_at") is None:
            data["created_at"] = now
        if data.get("updated_at") is None:
            data["updated_at"] = now
        super().__init__(**data)

    def get_recent_history(self, n: int = 8) -> list[TurnMessage]:
        return self.historial[-n:]

    def add_turn(self, role: str, text: str):
        self.historial.append(TurnMessage(role=role, text=text))
        self.updated_at = datetime.utcnow()
        if role == "user":
            self.ultima_pregunta = text


class EscalamientoMotivo(str, Enum):
    solicitud_explicita = "solicitud_explicita"
    dato_no_documentado = "dato_no_documentado"
    objecion_compleja = "objecion_compleja"
    frustracion = "frustracion"
    sin_avance = "sin_avance"
    alta_intencion_cierre = "alta_intencion_cierre"
    b2b = "b2b"
    crisis_emocional = "crisis_emocional"
    programa_fuera_piloto = "programa_fuera_piloto"


class Prioridad(str, Enum):
    alta = "alta"
    media = "media"
    baja = "baja"


class ResumenEscalamiento(BaseModel):
    nombre_aspirante: Optional[str] = None
    programa_interes: Optional[str] = None
    segmento: Optional[str] = None
    etapa_ciipoc_actual: Optional[str] = None
    necesidad_identificada: Optional[str] = None
    barrera_principal: Optional[str] = None
    tono_aspirante: Optional[str] = None
    ultimos_5_intercambios: Optional[str] = None
    siguiente_accion_sugerida: Optional[str] = None
