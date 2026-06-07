# Sistema de Agente Conversacional IA para el Proceso Comercial de la Universidad Icesi

**Versión:** 1.0  
**Fecha:** Junio 2026  
**Equipo:** Área Comercial — Universidad Icesi  

---

## 1. Resumen Ejecutivo

El Sistema de Agente Conversacional IA es una solución de automatización del proceso de atención a aspirantes de la Universidad Icesi, desarrollada para operar en los canales de WhatsApp y Telegram. El agente acompaña al aspirante a lo largo del embudo comercial de la institución (metodología CIIPOC), resuelve preguntas frecuentes con información actualizada de la base de conocimiento, y escala a asesores humanos cuando la situación lo requiere.

El sistema fue construido enteramente sobre modelos de lenguaje gratuitos (Google Gemini AI Studio) y se puede desplegar en infraestructura de bajo costo, lo que lo hace viable para una implementación piloto sin inversión en licencias de LLM.

---

## 2. Contexto y Motivación

### 2.1 Problemática

El equipo comercial de la Universidad Icesi recibe un volumen considerable de consultas de aspirantes a través de canales digitales. Las consultas incluyen preguntas sobre programas académicos, requisitos de admisión, costos, becas y procesos de matrícula. Atender este volumen de forma manual implica:

- **Alto costo operativo**: Los asesores dedican tiempo significativo a preguntas repetitivas que podrían automatizarse.
- **Pérdida de oportunidades**: Consultas fuera del horario de atención quedan sin respuesta, reduciendo la conversión.
- **Inconsistencia en la información**: Cada asesor puede dar respuestas diferentes a la misma pregunta.
- **Falta de trazabilidad**: Sin un sistema centralizado, no existe visibilidad del recorrido del aspirante ni de las barreras que enfrenta.

### 2.2 Solución

Un agente conversacional que opera 24/7, responde con información verificada de la base de conocimiento institucional, guía al aspirante por las etapas del embudo CIIPOC, y hace handoff inteligente al asesor humano cuando detecta señales de alta intención, frustración o preguntas fuera de su alcance.

---

## 3. Arquitectura del Sistema

### 3.1 Diagrama de componentes

```
                        ┌─────────────────────────────────────────┐
                        │           CANALES DE ENTRADA              │
                        │   WhatsApp (Meta API)  │  Telegram Bot   │
                        └──────────────┬──────────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────────┐
                        │         ORQUESTADOR (FastAPI)             │
                        │  orchestrator/main.py                     │
                        │  - Rate limiting                          │
                        │  - Deduplicación de mensajes              │
                        │  - Pipeline de procesamiento              │
                        └──────────────┬──────────────────────────┘
                                       │
            ┌──────────────────────────┼───────────────────────────┐
            │                          │                            │
┌───────────▼──────────┐  ┌───────────▼──────────┐  ┌────────────▼──────────┐
│  GESTIÓN DE SESIÓN   │  │  CONVERSACIÓN (LLM)  │  │    BASE DE DATOS       │
│  Redis (TTL 7 días)  │  │  Gemini via Gemini   │  │    PostgreSQL          │
│  session_store.py    │  │  API (gratuita)       │  │    db.py               │
│  - Historial         │  │  conversation.py      │  │    - conversation_logs │
│  - Estado CIIPOC     │  │  - System prompt      │  │    - tickets_escal.    │
│  - Datos del lead    │  │  - Tool dispatching   │  │    - intenciones_log   │
└──────────────────────┘  └───────────┬──────────┘  └────────────────────────┘
                                       │
            ┌──────────────────────────┼───────────────────────────┐
            │                          │                            │
┌───────────▼──────────┐  ┌───────────▼──────────┐  ┌────────────▼──────────┐
│  BASE DE CONOCIMIENTO│  │    TOOLS / ACCIONES  │  │     NIVEL 2 (BIZ)      │
│  RAG local (FAISS)   │  │    tools.py           │  │     nivel2.py          │
│  rag.py              │  │  - consultar_kb       │  │  - Sync CRM            │
│  - Embeddings locales│  │  - validar_programa   │  │  - Persistir tickets   │
│  - Búsqueda coseno   │  │  - registrar_intencion│  │  - Follow-up queue     │
│  - icesi-kb/ (YAML)  │  │  - escalar_a_asesor   │  │  - Notif. WA interno   │
└──────────────────────┘  │  - sugerir_paso       │  └────────────────────────┘
                          └──────────────────────┘
```

### 3.2 Flujo de una conversación

1. El aspirante envía un mensaje por WhatsApp o Telegram.
2. El webhook recibe el mensaje, verifica la firma HMAC y deduplica.
3. Se aplica rate limiting (máximo de mensajes por día por usuario).
4. Se carga la sesión del usuario desde Redis (o se crea una nueva consultando el CRM).
5. Si el historial supera la ventana máxima, se comprime con el LLM.
6. El orquestador construye el contexto completo (system prompt + historial + tools).
7. Gemini genera una respuesta, opcionalmente llamando tools.
8. Cada tool call se despacha, el resultado se pasa de vuelta al modelo.
9. La respuesta final se envía al usuario por el canal de origen.
10. El módulo Nivel 2 procesa en background: actualiza CRM, persiste tickets, programa follow-ups.
11. La conversación se guarda en PostgreSQL para auditoría.

---

## 4. Metodología CIIPOC

El agente estructura su comportamiento de acuerdo con la metodología CIIPOC (Contacto, Indagación, Identificación, Propuesta, Objeciones, Cierre), que es el marco de ventas consultivas de la Universidad Icesi.

| Etapa | Objetivo del agente |
|-------|---------------------|
| **Contacto** | Presentarse, capturar nombre, abrir conversación con pregunta abierta |
| **Indagación** | Descubrir momento de decisión (explorando / comparando / decidido) y barrera principal |
| **Identificación** | Hacer resumen empático, conectar necesidad con diferencial Icesi |
| **Propuesta** | Presentar 2-3 diferenciales del programa con datos de la KB |
| **Objeciones** | Escuchar objeción, validar, responder con datos; escalar si es compleja |
| **Cierre** | Proponer una acción concreta: llamada, evento, formulario de interés |

El agente no presiona por matrícula directa. Su función es acompañar y pasar el lead a un asesor en el momento adecuado.

---

## 5. Base de Conocimiento (RAG)

### 5.1 Estructura

La base de conocimiento está organizada en cuatro categorías dentro de `icesi-kb/`:

```
icesi-kb/
├── 00_diferenciales_icesi/     Propuesta de valor, acompañamiento, financiación
├── 01_metodologia_ciipoc/      Guías de la metodología
├── 02_portafolio/
│   ├── pregrado/               Fichas de programas de pregrado
│   ├── posgrado/               Maestrías, especializaciones
│   └── educontinua/            Diplomados, cursos
├── 03_faqs/                    Admisión, becas, proceso de matrícula
├── 04_reglas_escalamiento/     Cuándo y cómo escalar
└── manifest.yaml               Índice con metadatos de todos los documentos
```

Cada documento es un archivo Markdown con frontmatter YAML que incluye: `id`, `nombre`, `segmento`, `tags`, `vigencia`.

### 5.2 Funcionamiento del RAG

El sistema usa recuperación de información local sin dependencia de servidores externos:

1. Al iniciar, los documentos se indexan con embeddings de texto (compatibles con Gemini o locales via `sentence-transformers`).
2. Ante una consulta, se calcula similitud coseno entre el embedding de la consulta y los chunks indexados.
3. Se retornan los N chunks más relevantes, filtrados opcionalmente por segmento.
4. El agente siempre consulta la KB antes de afirmar datos factuales (precios, fechas, requisitos).

### 5.3 Herramienta `consultar_base_conocimiento`

```json
{
  "name": "consultar_base_conocimiento",
  "params": {
    "consulta": "¿Cuál es la duración de la Maestría en Mercadeo?",
    "segmento_filtro": "posgrado"
  }
}
```

---

## 6. Sistema de Escalamiento

### 6.1 Cuándo escala el agente

El agente escala automáticamente cuando detecta:

| Motivo | Descripción |
|--------|-------------|
| `solicitud_explicita` | El aspirante pide hablar con una persona |
| `dato_no_documentado` | Pregunta sin respuesta en la KB |
| `objecion_compleja` | Objeción que requiere negociación personalizada |
| `frustracion` | Señales de frustración detectadas en el mensaje |
| `sin_avance` | Sin progreso en el embudo después de 10+ mensajes |
| `alta_intencion_cierre` | Alta intención de matrícula detectada |
| `b2b` | Caso corporativo (múltiples empleados) |
| `crisis_emocional` | Señal de crisis detectada — escalamiento inmediato |
| `programa_fuera_piloto` | Programa no disponible en la KB del piloto |

### 6.2 Flujo del escalamiento

```
Agente detecta condición de escalamiento
         │
         ▼
tool_escalar_a_asesor() → determina asesor según segmento
         │
         ▼
proceso_after_turn() → _handle_escalation()
    ├── Crea tarea en CRM (HubSpot / MockCRM)
    ├── Persiste EscalamientoTicket en PostgreSQL
    └── Notifica grupo interno de WhatsApp
         │
         ▼
Asesor ve ticket en Dashboard → toma el caso
```

### 6.3 Asignación de asesores

| Segmento | Asesor |
|----------|--------|
| Pregrado | Julian Andrés Gil |
| Posgrado | Lauri Ariza |
| Educación Continua | Yerli Valencia |
| Casos B2B | Alejandra Tinoco |
| Indefinido / Jefatura | Carlos Londoño (Jefe Comercial) |

### 6.4 Ticket de escalamiento

Cada ticket incluye:
- Prioridad (🔴 alta / 🟡 media / 🟢 baja)
- Datos del aspirante: nombre, programa de interés, segmento, etapa CIIPOC
- Necesidad identificada y barrera principal
- Tono del aspirante (e.g., "frustrado con costos", "muy motivado")
- Últimos 5 intercambios de la conversación
- Acción recomendada

---

## 7. Gestión de Tickets

### 7.1 Modelo de datos

```sql
tickets_escalamiento (
    id               UUID PRIMARY KEY,
    session_id       VARCHAR(64),
    lead_id          VARCHAR(100),
    motivo           VARCHAR(50),
    prioridad        VARCHAR(10),
    asesor_asignado  VARCHAR(100),
    ticket_text      TEXT,
    asesor_tomo_caso BOOLEAN DEFAULT false,
    asesor_nombre    VARCHAR(100),
    took_at          TIMESTAMP,
    created_at       TIMESTAMP
)
```

### 7.2 API de tickets

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/tickets` | Lista tickets. `?pendiente=true` para no tomados |
| `POST` | `/tickets/{id}/tomar` | Asesor toma el caso (first-claim wins) |

Ejemplo de uso:
```bash
# Ver tickets pendientes
curl http://localhost:8000/tickets?pendiente=true

# Tomar un ticket
curl -X POST http://localhost:8000/tickets/UUID-AQUI/tomar \
  -H "Content-Type: application/json" \
  -d '{"asesor_nombre": "Lauri Ariza"}'
```

### 7.3 Panel en dashboard

El dashboard Streamlit incluye una sección "Gestión de Tickets" donde los asesores pueden:
- Ver tickets pendientes, tomados o todos
- Expandir el ticket completo para leer el briefing
- Introducir su nombre y hacer clic en "Tomar caso"

---

## 8. Canales de Comunicación

### 8.1 WhatsApp

Integración con la API oficial de Meta (WhatsApp Business Platform):
- Verificación de webhook con token configurable
- Validación de firma HMAC-SHA256 en cada mensaje entrante
- Soporte para mensajes largos: automáticamente divididos en partes ≤ 1024 caracteres
- Notificación de escalamientos a grupos internos de WhatsApp por segmento

### 8.2 Telegram

Bot de Telegram para la demo y pruebas:
- Disponible via `python-telegram-bot`
- Mismo pipeline de procesamiento que WhatsApp
- Sin límite de longitud de mensaje

### 8.3 Consola web interactiva

Disponible en `http://localhost:8000/` durante desarrollo:
- Interfaz chat en el navegador
- Permite probar el agente sin WhatsApp ni Telegram
- Útil para QA y evaluación de respuestas

---

## 9. Modelo de Datos

### 9.1 Sesión (Redis)

La sesión se almacena en Redis con TTL de 7 días e incluye:

| Campo | Descripción |
|-------|-------------|
| `id_usuario` | Hash HMAC del número de teléfono |
| `etapa_ciipoc` | Etapa actual en el embudo |
| `segmento` | pregrado / posgrado / educontinua / indefinido |
| `programa_interes` | Programa identificado |
| `necesidad_identificada` | Necesidad del aspirante |
| `barrera` | Barrera principal detectada |
| `historial` | Turnos de conversación (ventana de 20 mensajes) |
| `escalado` | Flag de si ya fue escalado |
| `estado_funnel_crm` | lead / inscrito / admitido / matriculado / etc. |

### 9.2 Tablas PostgreSQL

| Tabla | Propósito |
|-------|-----------|
| `conversation_logs` | Historial completo de conversaciones para auditoría |
| `tickets_escalamiento` | Tickets de escalamiento a asesores |
| `intenciones_log` | Log de avances de etapa CIIPOC |
| `kb_chunks` | Fragmentos de la base de conocimiento con embeddings vectoriales |

---

## 10. Integración CRM

El sistema incluye un adaptador CRM con tres implementaciones:

| Implementación | Uso |
|----------------|-----|
| `MockCRM` | Pruebas y desarrollo local — en memoria |
| `HubSpotCRM` | Producción — integración con HubSpot via API REST |

Operaciones disponibles:
- `get_lead(id)` — Recuperar datos del lead
- `update_lead(id, fields)` — Actualizar etapa, segmento, programa, barrera
- `create_task(task)` — Crear tarea de seguimiento para el asesor

La variable de entorno `CRM_PROVIDER=hubspot` activa la integración real. Sin ella, usa el mock.

---

## 11. Dashboard de Métricas

El dashboard Streamlit (`dashboard/app.py`) provee:

### Métricas KPI
- Total de conversaciones iniciadas
- Tiempo promedio de respuesta del agente
- Número de escalamientos
- Conversaciones con avance de etapa CIIPOC

### Visualizaciones
- Conversaciones por día (gráfico de barras)
- Distribución de etapas CIIPOC (funnel)
- Distribución de tiempos de respuesta (histograma)
- Escalamientos por motivo (gráfico de torta)
- Actividad por segmento

### Gestión operacional
- **Panel de tickets**: ver, filtrar y tomar tickets de escalamiento
- **Evaluación de calidad**: registro manual semanal de precisión de respuestas (meta ≥ 95% correctas)

---

## 12. Configuración y Despliegue

### 12.1 Variables de entorno (`.env`)

| Variable | Descripción | Requerida |
|----------|-------------|-----------|
| `GEMINI_API_KEY` | API key de Google Gemini AI Studio | Sí |
| `DATABASE_URL` | URL de PostgreSQL | En producción |
| `REDIS_URL` | URL de Redis | En producción |
| `WHATSAPP_PHONE_ID` | ID del número de WhatsApp Business | Para WA |
| `WHATSAPP_ACCESS_TOKEN` | Token de acceso Meta | Para WA |
| `WHATSAPP_VERIFY_TOKEN` | Token de verificación del webhook | Para WA |
| `WHATSAPP_APP_SECRET` | Secreto para firma HMAC | Para WA |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram | Para Telegram |
| `CRM_PROVIDER` | `mock` (default) o `hubspot` | No |
| `HUBSPOT_API_KEY` | API key de HubSpot | Si CRM=hubspot |
| `CHAT_API_KEY` | Bearer token para endpoint `/chat` | Recomendado |
| `APP_ENV` | `development` o `production` | No (default: development) |

### 12.2 Inicio rápido (desarrollo)

```bash
# 1. Clonar e instalar dependencias
pip install -r requirements.txt

# 2. Copiar variables de entorno
cp .env.example .env
# Editar .env con GEMINI_API_KEY mínimamente

# 3. Levantar infraestructura (Docker)
make infra

# 4. Indexar base de conocimiento
make ingest

# 5. Iniciar orquestador
make dev

# 6. Acceder a la consola en http://localhost:8000/
# 7. Correr dashboard en http://localhost:8501/
make dashboard
```

### 12.3 Despliegue con Docker Compose

```bash
docker compose up --build
```

Servicios incluidos:
- `orchestrator`: FastAPI en puerto 8000
- `dashboard`: Streamlit en puerto 8501
- `postgres`: PostgreSQL 16 con pgvector
- `redis`: Redis 7

---

## 13. Pruebas

### 13.1 Suite de pruebas

21 pruebas unitarias e integración en `tests/test_conversation.py`:

| Módulo | Pruebas | Cobertura |
|--------|---------|-----------|
| `validar_programa` | T01-T02 | Búsqueda exacta y parcial, programa no encontrado |
| `registrar_intencion` | T03-T05 | Avance de etapa, contador sin avance, captura de datos |
| `escalar_a_asesor` | T06-T09 | Marcado de sesión, enrutamiento por segmento, B2B, contenido del ticket |
| `sugerir_siguiente_paso` | T10-T11 | Etapa válida, etapa inválida |
| `dispatch_tool` | T12 | Tool desconocida |
| `SessionState` | T13-T14 | Historial, ventana de contexto |
| Conversation guards | T15-T19 | Detección de alucinación, frustración, crisis, B2B |
| WhatsApp splitting | T20-T21 | Mensaje corto, mensaje largo |
| Escalamiento tools | T-ESC-01 a T-ESC-03 | motivo en retorno, tono en ticket, persistencia en DB |

### 13.2 Correr pruebas

```bash
make test
# o con cobertura:
make test-cov
```

---

## 14. Seguridad

- **Firma HMAC-SHA256**: cada mensaje de WhatsApp se verifica contra la firma enviada por Meta.
- **Hash de teléfonos**: los números de teléfono se almacenan como hashes HMAC — nunca en texto plano.
- **Rate limiting**: máximo de mensajes por usuario por día, configurable via `MAX_MESSAGES_PER_DAY`.
- **Bearer token**: el endpoint `/chat` requiere autenticación con token cuando `CHAT_API_KEY` está configurado.
- **CORS**: en producción, solo dominios `*.icesi.edu.co` están permitidos.
- **Deduplicación**: buffer circular de 10,000 message IDs para evitar procesamiento doble.

---

## 15. Limitaciones y Trabajo Futuro

### Limitaciones del MVP

| Ítem | Estado |
|------|--------|
| Cola de follow-ups (Redis sorted set) | Pierde jobs al reiniciar |
| Integración CRM HubSpot | No probada en producción |
| Hash de teléfonos reversible | HMAC con secreto compartido |
| Sin política de retención de datos | Pendiente evaluación Ley 1581 |

### Próximas iteraciones sugeridas

1. **Cola de follow-ups persistente** — migrar de Redis sorted set a Celery + PostgreSQL backend.
2. **Tool de captura de datos** — `capturar_datos_aspirante` para nombre, email y teléfono estructurado.
3. **A/B testing de prompts** — versionado del system prompt con override por sesión.
4. **Framework de evaluación automática** — integración con LLM-as-judge para calidad de respuestas.
5. **Webhook seguro en producción** — forzar validación de `WHATSAPP_APP_SECRET` en todos los entornos.

---

## 16. Glosario

| Término | Definición |
|---------|-----------|
| **CIIPOC** | Contacto, Indagación, Identificación, Propuesta, Objeciones, Cierre — metodología de ventas consultivas de Icesi |
| **Escalamiento** | Transferencia de la conversación de la IA a un asesor humano |
| **RAG** | Retrieval-Augmented Generation — técnica de IA que enriquece las respuestas del LLM con documentos recuperados |
| **Segmento** | Área académica del programa de interés: pregrado, posgrado, educación continua |
| **Tool call** | Llamada a una función externa realizada por el LLM durante la generación de respuesta |
| **Nivel 2** | Módulo de lógica de negocio que se ejecuta después de cada turno de conversación |
| **TTL** | Time To Live — tiempo máximo de vida de un dato en caché (Redis) |

---

*Documento generado para presentación al Centro de Innovación y Proyectos de la Universidad Icesi.*
