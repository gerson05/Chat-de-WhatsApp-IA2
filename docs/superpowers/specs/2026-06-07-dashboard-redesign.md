# Dashboard Redesign — Icesi IA Console

**Date:** 2026-06-07  
**Status:** Approved

## Summary

Rediseño completo del dashboard de testing del agente comercial Icesi IA (`orchestrator/static/console.html`). El objetivo es pasar de un HTML monolítico funcional-pero-básico a una interfaz profesional con iconos SVG reales, jerarquía visual clara y panel de historial de sesiones.

## Decisions

| Decisión | Elección |
|---|---|
| Estilo visual | Clean Light — navy #003087 + red #e63946, fondo blanco, shadows suaves |
| Layout | 2 columnas (chat + sidebar derecha) + panel izquierdo de sesiones |
| Iconos | Lucide Icons via CDN — sin emojis en ningún componente |
| Estructura de archivos | Separados: HTML + CSS + JS |
| Historial de sesiones | Data real desde backend (`GET /sessions` → Redis) |

## Architecture

### Archivos

```
orchestrator/static/
├── console.html        # shell HTML — solo estructura e imports
├── css/
│   └── console.css     # todos los estilos
└── js/
    └── console.js      # toda la lógica JS
```

FastAPI ya sirve `orchestrator/static/` — no requiere cambios de config.

### Endpoint nuevo

```
GET /sessions
Authorization: Bearer {CHAT_API_KEY}  (opcional, si está configurada)

Response 200:
[
  {
    "phone": "+573001234567",
    "etapa_ciipoc": "identificacion",
    "segmento": "Posgrado",
    "escalado": true,
    "turn_count": 3,
    "last_active_ts": 1780867000
  },
  ...
]
```

Implementación: leer keys de Redis con prefijo de sesión, parsear metadata. Retorna máximo 50 sesiones ordenadas por `last_active_ts` descendente.

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Header: logo · pill · [spacer] · [settings icon] · [reiniciar btn]  │
├──────────────┬──────────────────────────┬────────────────────┤
│  Sessions    │         Chat             │     Sidebar        │
│  220px       │         flex: 1          │     260px          │
│              │                          │                    │
│  - título    │  - log de burbujas       │  - estado sesión   │
│  - input tel │  - typing indicator      │  - latencia        │
│  - lista     │  - chips de sugerencias  │  - stepper CIIPOC  │
│    sesiones  │  - composer + send btn   │  - tools           │
└──────────────┴──────────────────────────┴────────────────────┘
```

## Components

### Header
- Logo texto "Icesi IA" + pill "Consola"
- Botón settings: icono Lucide `settings`, abre panel de ajustes (URL servidor + API key)
- Botón reiniciar: icono Lucide `rotate-ccw` + texto "Reiniciar sesión", fondo `#e63946`

### Panel izquierdo — Sesiones (220px)
- Título "SESIONES" en uppercase small + botón refresh (icono `refresh-cw`)
- Input de teléfono + botón flecha para cargar sesión manualmente
- Lista de sesiones: fetch a `GET /sessions` al cargar y cada 30s
- Cada item: número de teléfono, tiempo relativo + turnos, badges de etapa/segmento/escalado
- Sesión activa: highlight azul + borde izquierdo `#003087`
- Click en sesión: carga ese teléfono como usuario activo, limpia log

### Chat (centro, flex: 1)
- Burbujas: usuario (navy, alineada derecha), bot (blanca con sombra, izquierda), sistema (amarillo suave), error (rojo suave)
- Meta bajo burbuja bot: `{etapa} · {segmento} · {ms} ms · {n} tools`
- Typing indicator: 3 puntos animados (blink CSS)
- Chips de sugerencias rápidas: fondo `#eff6ff`, borde azul claro
- Composer: textarea auto-resize, fondo `#f8faff`, focus con borde navy; botón send cuadrado redondeado (42×42px, `border-radius: 10px`) con icono Lucide `send`

### Sidebar derecha (260px)
- **Estado de sesión:** segmento, badge escalado (si/no), session ID truncado en monospace
- **Latencia:** valor grande en navy, unidad en gris, incluye conteo de tools
- **CIIPOC Stepper:** línea vertical conectora, dots con check icon (Lucide `check`) para pasos completados, dot navy pulsante para paso actual
- **Tools:** cada tool como `<details>` card — header con icono `wrench`/`search`/`database` según nombre, latencia del tool, body en monospace dark (`#0f172a`)

### Iconos Lucide usados
`settings`, `rotate-ccw`, `refresh-cw`, `arrow-right`, `send`, `user`, `alert-circle`, `zap`, `git-commit`, `check`, `circle`, `wrench`, `search`, `database`

## Non-Goals

- No dark mode toggle (puede añadirse después)
- No filtros/búsqueda en el panel de sesiones
- No exportar conversación
- No websockets (polling cada 30s es suficiente para consola de testing)

## Implementation Notes

- El endpoint `GET /sessions` debe tolerar Redis vacío (retorna `[]`)
- El panel de sesiones muestra "Sin sesiones activas" cuando la lista está vacía
- El JS de auto-refresh usa `setInterval(fetchSessions, 30000)` — se cancela con `clearInterval` al destruir
- `console.html` carga Lucide via CDN `<script>`: `https://unpkg.com/lucide@latest/dist/umd/lucide.min.js`, llamado `lucide.createIcons()` al final de `console.js`
- Sin frameworks JS — vanilla ES2020+
- Compatible con Chrome/Firefox/Edge modernos (no IE)
