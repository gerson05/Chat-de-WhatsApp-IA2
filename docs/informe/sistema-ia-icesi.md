# Sistema de Agente Conversacional IA para el Proceso Comercial de la Universidad Icesi

**Versión:** 1.1  
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
│  Redis (TTL 7 días)  │  │  Gemini (gratuita)   │  │    PostgreSQL          │
│  + InMemoryFallback  │  │  conversation.py      │  │    db.py               │
│  session_store.py    │  │  - A/B system prompt  │  │    - conversation_logs │
│  - Historial         │  │  - Sanitiz. mensajes  │  │    - tickets_escal.    │
│  - Estado CIIPOC     │  │  - Tool dispatching   │  │    - archived_sessions │
│  - Archiva en Postgres│  │  - Injection guard    │  │    - followup_jobs     │
└──────────────────────┘  └───────────┬──────────┘  └────────────────────────┘
                                       │
            ┌──────────────────────────┼───────────────────────────┐
            │                          │                            │
┌───────────▼──────────┐  ┌───────────▼──────────┐  ┌────────────▼──────────┐
│  BASE DE CONOCIMIENTO│  │    TOOLS / ACCIONES  │  │     NIVEL 2 (BIZ)      │
│  RAG local (pickle)  │  │    tools.py           │  │     nivel2.py          │
│  rag.py              │  │  - consultar_kb       │  │  - Sync CRM            │
│  - Gemini embeddings │  │  - validar_programa   │  │  - Persistir tickets   │
│  - Fallback local    │  │  - registrar_intencion│  │  - Celery follow-ups   │
│  - Vigencia checker  │  │  - escalar_a_asesor   │  │  - Notif. WA interno   │
│  - icesi-kb/ (YAML)  │  │  - sugerir_paso       │  └────────────────────────┘
└──────────────────────┘  │  - capturar_datos     │
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

1. Al iniciar, los documentos se indexan con embeddings de texto (Gemini AI Studio free tier por defecto).
2. Si Gemini no responde, el sistema hace fallback automático a `sentence-transformers` local.
3. Ante una consulta, se calcula similitud coseno entre el embedding de la consulta y los chunks indexados.
4. Se retornan los N chunks más relevantes, filtrados opcionalmente por segmento y vigencia.
5. El agente siempre consulta la KB antes de afirmar datos factuales (precios, fechas, requisitos).

### 5.3 Validación y vigencia

- `python -m ingest.check_vigencia` — CLI que lee `manifest.yaml` y reporta documentos expirados (🔴) o próximos a vencer (🟡), con el nombre del aprobador responsable.
- El script también se ejecuta automáticamente al arrancar la aplicación y emite advertencias en log.
- El proceso de ingest termina con **exit code 1** si los embeddings fallan o el índice resultante no retorna resultados útiles (antes continuaba silenciosamente con vectores en cero).

### 5.4 Herramienta `consultar_base_conocimiento`

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

Cada ticket incluye un **Briefing Ejecutivo** al inicio para lectura rápida del asesor:

```
🔴 ESCALAMIENTO IA — Prioridad: ALTA
═════════════════════════════════════════════
📋 BRIEFING EJECUTIVO
  ⚠️  ATENCIÓN — aspirante frustrado
  María → MBA (etapa: objeciones, segmento: posgrado)
  Frustración: alto 🔴 | Turnos sin avance: 4
  Barrera: Costo del programa
─────────────────────────────────────────────
```

El nivel de frustración (`alto/medio/bajo`) se calcula automáticamente analizando los últimos 6 mensajes del aspirante con 12 palabras clave. Debajo del briefing se incluye el detalle completo: necesidad, barrera, tono reportado por el agente, últimos intercambios y acción recomendada.

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

### 9.1 Sesión (Redis + archivo Postgres)

La sesión se almacena en Redis con TTL de 7 días. En cada guardado, se archiva también en PostgreSQL para audit trail (sobrevive a la expiración del TTL).

| Campo | Descripción |
|-------|-------------|
| `id_usuario` | Hash HMAC del número de teléfono (secreto dedicado `PHONE_HASH_SECRET`) |
| `etapa_ciipoc` | Etapa actual en el embudo |
| `segmento` | pregrado / posgrado / educontinua / indefinido |
| `programa_interes` | Programa identificado |
| `nombre` | Nombre del aspirante (capturado por tool) |
| `email` | Email de contacto (capturado y validado por tool) |
| `telefono_contacto` | Teléfono adicional (capturado y validado por tool) |
| `necesidad_identificada` | Necesidad del aspirante |
| `barrera` | Barrera principal detectada |
| `historial` | Turnos de conversación (ventana de 20 mensajes) |
| `escalado` | Flag de si ya fue escalado |
| `prompt_variant` | Variante A/B del system prompt (`v1` / `v2`) |
| `estado_funnel_crm` | lead / inscrito / admitido / matriculado / etc. |

### 9.2 Tablas PostgreSQL

| Tabla | Propósito |
|-------|-----------|
| `conversation_logs` | Historial turn-by-turn de conversaciones para auditoría |
| `tickets_escalamiento` | Tickets de escalamiento con seguimiento de asesores |
| `intenciones_log` | Log de avances de etapa CIIPOC |
| `kb_chunks` | Fragmentos de la KB con embeddings vectoriales |
| `archived_sessions` | JSON completo de sesiones archivadas; `purge_after` configurable (Ley 1581) |
| `followup_jobs` | Cola de follow-ups persistente; jobs sobreviven reinicios del servicio |

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

La variable de entorno `CRM_BACKEND=hubspot` activa la integración real. Sin ella, usa el mock.

**Resiliencia (HubSpot):** todas las llamadas pasan por un circuit breaker que abre tras 5 fallos consecutivos (se resetea en 60 s) y un mecanismo de retry con backoff exponencial (1 s / 2 s, máximo 3 intentos). Los errores se registran sin bloquear el pipeline conversacional.

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
| `WHATSAPP_APP_SECRET` | Secreto para firma HMAC — **obligatorio en producción** | Para WA |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram | Para Telegram |
| `CRM_BACKEND` | `mock` (default) o `hubspot` | No |
| `HUBSPOT_API_KEY` | API key de HubSpot | Si CRM=hubspot |
| `CHAT_API_KEY` | Bearer token para endpoint `/chat` | Recomendado |
| `APP_ENV` | `development` o `production` | No (default: development) |
| `PHONE_HASH_SECRET` | Secreto dedicado para HMAC de teléfonos (Ley 1581) | Recomendado |
| `DATA_RETENTION_DAYS` | Días de retención de sesiones archivadas (default: 90) | No |
| `PROMPT_VARIANT_DEFAULT` | Variante A/B del system prompt: `v1` o `v2` (default: v1) | No |

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

24 pruebas unitarias e integración en `tests/test_conversation.py` — **24/24 passing**:

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

## 14. Seguridad y Compliance

### Seguridad

- **Firma HMAC-SHA256**: cada mensaje de WhatsApp se verifica contra la firma enviada por Meta. En entorno `production`, si `WHATSAPP_APP_SECRET` no está configurado el webhook rechaza todas las solicitudes con 401 (antes las aceptaba silenciosamente).
- **Sanitización de mensajes**: los mensajes del usuario son truncados a 2000 caracteres y se neutralizan intentos de prompt injection mediante el patrón `[SISTEMA:]` antes de llegar al LLM.
- **Hash de teléfonos**: los números se almacenan como hashes HMAC-SHA256 con `PHONE_HASH_SECRET` — un secreto dedicado separado del secreto de la aplicación.
- **Rate limiting**: máximo de mensajes por usuario por día, configurable via `MAX_MESSAGES_PER_DAY`.
- **Bearer token**: el endpoint `/chat` requiere autenticación con token cuando `CHAT_API_KEY` está configurado.
- **CORS**: en producción, solo dominios `*.icesi.edu.co` están permitidos.
- **Deduplicación**: buffer circular de 10,000 message IDs para evitar procesamiento doble.

### Compliance (Ley 1581 / Habeas Data)

- **Retención configurable**: sesiones archivadas en PostgreSQL con campo `purge_after` basado en `DATA_RETENTION_DAYS` (default 90 días). Función `purge_expired_sessions()` disponible para ejecución periódica via cron.
- **Sin datos en texto plano**: teléfonos siempre hasheados; el sistema no almacena cédulas, direcciones ni datos bancarios (principio no negociable en el system prompt).
- **Pendiente de revisión legal**: el flujo completo de datos debe ser revisado por el área jurídica de Icesi antes del despliegue en producción con datos reales.

---

## 15. A/B Testing de Prompts

El sistema soporta experimentos controlados de system prompt sin afectar todas las sesiones:

- **`v1`** (default): tono consultivo estándar CIIPOC, mensajes de 2-6 líneas.
- **`v2`**: tono más directo y conciso, mensajes de 1-4 líneas, orientado a acción rápida.

La variante se asigna al crear la sesión desde `PROMPT_VARIANT_DEFAULT`. Para un experimento, se puede cambiar la variable a `v2` en un subconjunto de usuarios o por segmento. Las métricas de conversación en el dashboard permiten comparar el avance de etapa CIIPOC entre variantes.

---

## 16. Cola de Follow-ups

Los recordatorios se programan según la etapa CIIPOC del aspirante:

| Etapa | Delay |
|-------|-------|
| Indagación | 72 h |
| Propuesta | 48 h |
| Objeciones | 24 h |
| Cierre | 24 h |

Los jobs se escriben en **dos destinos simultáneos**:
1. **Celery** (broker: Redis) — ejecución rápida con autoretry y backoff exponencial.
2. **PostgreSQL** (`followup_jobs`) — persistencia duradera; si Redis reinicia, los jobs no se pierden.

Arrancar el worker:
```bash
celery -A orchestrator.celery_worker worker --loglevel=info
```

---

## 17. Limitaciones y Trabajo Futuro

### Pendiente de implementación

| Ítem | Prioridad |
|------|-----------|
| Panel de administración en dashboard (gestión de tickets, edición KB) | Media |
| Revisión legal completa Ley 1581 por área jurídica | Alta |
| Pruebas de integración CRM HubSpot en producción con datos reales | Alta |
| Framework de evaluación automática (LLM-as-judge) | Baja |

### Próximas iteraciones sugeridas

1. **Panel admin en dashboard** — gestión de tickets, reasignación, edición de KB y disparo manual de follow-ups.
2. **Evaluación automática de calidad** — integración con LLM-as-judge para medir precisión de respuestas semanalmente.
3. **Revisión jurídica Ley 1581** — validar flujo completo de datos personales con el área legal de Icesi antes del go-live.

---

## 18. Glosario

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
