# Mejoras Pendientes — Icesi IA

Listado de mejoras identificadas tras el análisis del sistema. Ordenadas por prioridad.

---

## Críticas (antes de producción)

### 1. Seguridad del webhook en desarrollo
- **Problema:** `verify_signature()` retorna `True` si `WHATSAPP_APP_SECRET` está vacío — cualquier actor externo puede enviar mensajes falsos al webhook.
- **Archivo:** `orchestrator/whatsapp.py`
- **Fix:** Forzar validación del secreto en todos los ambientes no-test; agregar check en CI/CD que falle si la variable está ausente en producción.

### 2. Vulnerabilidades de prompt injection
- **Problema:** El mensaje del usuario se inyecta directamente en el array de mensajes de Claude sin sanitización adicional. Solo se filtran palabras clave de pre-escalamiento.
- **Archivo:** `orchestrator/conversation.py`
- **Fix:** Validar longitud máxima del mensaje, escapar patrones peligrosos, agregar guardrails para prompt injection antes de pasar al modelo.

### 3. Fallo silencioso en ingest de KB
- **Problema:** Si Cohere no está disponible, el ingest continúa indexando con zero-vectors sin advertir al usuario. El RAG queda silenciosamente roto.
- **Archivo:** `ingest/`
- **Fix:** Fail fast en errores de embeddings; agregar paso de validación post-ingest que pruebe una consulta real al RAG antes de reportar éxito.

---

## Funcionalidad

### 4. Tool explícito para captura de datos del aspirante
- **Problema:** No existe un tool dedicado para capturar email, nombre completo y teléfono. Esta información puede perderse en el contexto conversacional.
- **Fix:** Agregar `tool_capturar_datos_aspirante` que valide y persista datos de contacto en la sesión y los sincronice con el CRM en ese mismo momento.

### 5. Cola de follow-ups persistente
- **Problema:** Los follow-ups se programan en un Redis sorted set (`followup_queue`) que pierde todos los jobs programados si el servicio se reinicia.
- **Archivo:** `orchestrator/nivel2.py` → `_schedule_followup()`
- **Fix:** Migrar a Celery + RabbitMQ (o BullMQ si se adopta Node) para persistencia y reintentos automáticos de jobs.

### 6. Archivo de conversaciones para compliance
- **Problema:** El historial de sesiones se pierde al expirar en Redis (TTL 7 días). No hay audit trail para revisiones de calidad o cumplimiento normativo.
- **Archivo:** `orchestrator/session_store.py`
- **Fix:** Archivar sesiones completas a PostgreSQL al expirar el TTL; implementar log inmutable de conversaciones con timestamps.

### 7. Alertas de documentos KB expirados
- **Problema:** Los documentos de la base de conocimiento tienen campo `vigencia` en su frontmatter, pero no existe ningún job que alerte cuando un documento esté próximo a vencer. El bot puede responder con información desactualizada.
- **Archivo:** `icesi-kb/manifest.yaml`
- **Fix:** Job diario que revise fechas de vigencia y marque documentos próximos a vencer en el dashboard; notificación interna al responsable de contenido.

---

## Calidad y Operaciones

### 8. Contexto enriquecido al escalar a asesor
- **Problema:** El tool `escalar_a_asesor` envía los últimos 5 intercambios + metadatos crudos. El asesor no recibe un resumen del sentimiento, nivel de frustración ni el contexto clave de la conversación.
- **Archivo:** `orchestrator/tools.py`
- **Fix:** Agregar capa de pre-escalamiento (Tier 1.5) que genere un briefing estructurado: motivo, etapa CIIPOC, barrera principal, tono del aspirante y acción recomendada.

### 9. Panel de administración en el dashboard
- **Problema:** El dashboard Streamlit es de solo lectura. Los asesores deben usar el CRM por separado para gestionar tickets de escalamiento.
- **Archivo:** `dashboard/`
- **Fix:** Agregar panel de admin con: gestión de tickets de escalamiento, reasignación a asesores, edición básica de KB, y disparo manual de follow-ups.

### 10. Framework de A/B testing de prompts
- **Problema:** El system prompt es monolítico. No hay forma de probar variaciones de tono o estrategia conversacional sin afectar todas las sesiones.
- **Archivo:** `orchestrator/system_prompt.py`
- **Fix:** Agregar versionado de system prompt y mecanismo de override por sesión (ej. variable de entorno o flag en sesión) para experimentos controlados.

### 11. Integración CRM testeada en producción
- **Problema:** Solo el adaptador mock está probado. El adaptador HubSpot no tiene lógica de reintentos ni recuperación ante errores. El mapeo de campos está hardcodeado.
- **Archivo:** `orchestrator/crm_adapter.py`
- **Fix:** Agregar contract tests para HubSpot; implementar circuit breaker + backoff exponencial; hacer el mapeo de campos configurable via env o YAML.

### 12. Fallback local para embeddings
- **Problema:** Si Cohere no está disponible, no hay alternativa para generar embeddings. El sistema depende 100% de una API externa para búsqueda semántica.
- **Archivo:** `ingest/` + `orchestrator/rag.py`
- **Fix:** Agregar soporte para embeddings locales con `sentence-transformers` como fallback cuando Cohere no responde.

---

## Compliance y Privacidad

### 13. Revisión de manejo de datos personales
- **Problema:** El hash del teléfono usa HMAC con el app secret (reversible si se compromete el secreto). No hay política de retención de datos implementada en código. Sin revisión para cumplimiento de normativa colombiana de protección de datos (Ley 1581).
- **Fix:** Evaluar uso de hash one-way para identificadores; implementar política de retención configurable; revisar flujo de datos con criterio de Ley 1581 / Habeas Data.

---

## Estado General

| # | Área | Estado |
|---|------|--------|
| #1 | Webhook signature | ✅ Resuelto |
| #2 | Prompt injection | ✅ Resuelto |
| #3 | Ingest fail-fast | ✅ Resuelto |
| #4 | Tool captura datos aspirante | ✅ Resuelto |
| #5 | Cola follow-ups persistente | ✅ Resuelto |
| #6 | Archivo conversaciones Postgres | ✅ Resuelto |
| #7 | Alertas vigencia KB | ✅ Resuelto |
| #8 | Briefing estructurado escalamiento | ✅ Resuelto |
| #9 | Panel admin dashboard | Pendiente (pospuesto) |
| #10 | A/B testing prompts | ✅ Resuelto |
| #11 | CRM HubSpot con reintentos | ✅ Resuelto |
| #12 | Fallback local embeddings | ✅ Resuelto |
| #13 | Compliance Ley 1581 | ✅ Resuelto (parcial) |

| Área | Estado |
|------|--------|
| Arquitectura core | Sólida |
| Seguridad producción | ✅ Resuelta (#1, #2, #3) |
| Funcionalidad MVP | ✅ Completa + mejoras (#4, #5, #6) |
| Operaciones / Monitoring | ✅ Mejorado (#7, #8, #10, #12) |
| Resiliencia / CRM | ✅ Mejorado (#11 circuit breaker) |
| Compliance | ⚠️ Parcial (#13 hash+retención — falta revisión legal) |
| Panel admin dashboard | Pendiente (#9) |
