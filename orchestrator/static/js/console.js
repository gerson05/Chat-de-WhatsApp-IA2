"use strict";

const CIIPOC = ["contacto", "indagacion", "identificacion", "propuesta", "objeciones", "cierre"];
const CIIPOC_LABELS = {
  contacto: "Contacto",
  indagacion: "Indagación",
  identificacion: "Identificación",
  propuesta: "Propuesta",
  objeciones: "Objeciones",
  cierre: "Cierre",
};

const $ = id => document.getElementById(id);

// ── Settings (localStorage) ──────────────────────────────────────

function loadSettings() {
  $("phone").value = localStorage.getItem("icesi_phone") || "+573001234567";
  $("base-url").value = localStorage.getItem("icesi_base") || window.location.origin;
  $("api-key").value = localStorage.getItem("icesi_apikey") || "";
}

function saveSettings() {
  localStorage.setItem("icesi_phone", $("phone").value);
  localStorage.setItem("icesi_base", $("base-url").value);
  localStorage.setItem("icesi_apikey", $("api-key").value);
}

// ── Sessions panel ───────────────────────────────────────────────

let _refreshTimer = null;

async function fetchSessions() {
  const btn = $("refresh-btn");
  if (btn) btn.classList.add("spinning");
  try {
    const base = ($("base-url").value || window.location.origin).replace(/\/$/, "");
    const headers = {};
    if ($("api-key").value) headers["Authorization"] = "Bearer " + $("api-key").value;
    const resp = await fetch(base + "/sessions", { headers });
    if (!resp.ok) return;
    const sessions = await resp.json();
    renderSessions(sessions);
  } catch (_) {
    // silently ignore — sessions panel is non-critical
  } finally {
    if (btn) btn.classList.remove("spinning");
  }
}

function renderSessions(sessions) {
  const list = $("sessions-list");
  const activePhone = $("phone").value;

  if (!sessions || sessions.length === 0) {
    list.innerHTML = '<div class="sessions-empty">Sin sesiones activas.</div>';
    return;
  }

  list.innerHTML = sessions.map(s => {
    const isActive = s.phone === activePhone;
    const timeAgo = _timeAgo(s.last_active_ts);
    const turns = s.turn_count > 0 ? `· ${s.turn_count} turnos` : "";
    const badges = [
      `<span class="si-badge etapa">${_esc(CIIPOC_LABELS[s.etapa_ciipoc] || s.etapa_ciipoc)}</span>`,
      s.escalado ? `<span class="si-badge escalado">Escalado</span>` : "",
      s.segmento && s.segmento !== "indefinido" ? `<span class="si-badge segmento">${_esc(s.segmento)}</span>` : "",
    ].filter(Boolean).join("");

    return `<div class="session-item${isActive ? " active" : ""}" data-phone="${_esc(s.phone)}" onclick="loadSessionPhone('${_esc(s.phone)}')">
      <div class="si-phone">${_esc(s.phone)}</div>
      <div class="si-meta">${timeAgo} ${turns}</div>
      <div class="si-badges">${badges}</div>
    </div>`;
  }).join("");
}

function loadSessionPhone(phone) {
  $("phone").value = phone;
  saveSettings();
  document.querySelectorAll(".session-item").forEach(el => {
    el.classList.toggle("active", el.dataset.phone === phone);
  });
}

function _timeAgo(ts) {
  if (!ts) return "—";
  const date = new Date(ts);
  const diff = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diff < 60) return "Hace un momento";
  if (diff < 3600) return `Hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `Hace ${Math.floor(diff / 3600)}h`;
  return `Hace ${Math.floor(diff / 86400)} días`;
}

function _esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Chat ─────────────────────────────────────────────────────────

const chatLog = $("chat-log");

function addBubble(text, cls, meta) {
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("div");
    m.className = "bubble-meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function renderStepper(stage) {
  const stepper = $("stepper");
  const idx = CIIPOC.indexOf(stage);
  stepper.innerHTML = CIIPOC.map((s, i) => {
    const cls = idx === -1 ? "" : (i < idx ? "done" : i === idx ? "current" : "");
    const dotInner = cls === "done"
      ? `<svg data-lucide="check" stroke="white" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></svg>`
      : cls === "current"
      ? `<svg data-lucide="dot" stroke="white" fill="white"></svg>`
      : "";
    return `<div class="step ${cls}">
      <div class="step-dot">${dotInner}</div>
      <span class="step-label">${CIIPOC_LABELS[s]}</span>
    </div>`;
  }).join("");
  lucide.createIcons();
}

function renderTools(toolCalls) {
  const box = $("tools-panel");
  if (!toolCalls || toolCalls.length === 0) {
    box.innerHTML = '<div class="tools-empty">Sin tools en este turno.</div>';
    return;
  }
  box.innerHTML = toolCalls.map(tc => `
    <details class="tool-item">
      <summary class="tool-header">
        <svg data-lucide="wrench" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
        ${_esc(tc.name)}
        <span class="tool-ms">${tc.latency_ms != null ? tc.latency_ms + " ms" : ""}</span>
      </summary>
      <div class="tool-body">input: ${JSON.stringify(tc.input, null, 2)}\n\nresult: ${JSON.stringify(tc.result, null, 2)}</div>
    </details>`).join("");
  lucide.createIcons();
}

function setState(data) {
  $("segmento").textContent = data.segmento || "—";
  $("session-id").textContent = (data.session_id || "—").slice(0, 16) + "…";

  const escaladoBadge = $("escalado");
  if (data.escalado) {
    escaladoBadge.className = "badge si";
    escaladoBadge.innerHTML = `<svg data-lucide="alert-circle" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg> Sí`;
  } else {
    escaladoBadge.className = "badge no";
    escaladoBadge.textContent = "No";
  }

  if (data._latency_ms != null) {
    $("latency-val").textContent = data._latency_ms.toLocaleString();
    $("latency-unit").textContent = `ms · último turno${data.tool_calls?.length ? " · " + data.tool_calls.length + " tool(s)" : ""}`;
  }

  renderStepper(data.etapa_ciipoc);
  renderTools(data.tool_calls);
  lucide.createIcons();
}

// ── Send ─────────────────────────────────────────────────────────

let busy = false;

async function send(text, reset = false) {
  if (busy) return;
  const message = text ?? $("chat-input").value.trim();
  if (!message && !reset) return;
  busy = true;
  $("send-btn").disabled = true;

  if (message) addBubble(message, "user");
  $("chat-input").value = "";
  autoResize($("chat-input"));

  const typing = document.createElement("div");
  typing.className = "typing-indicator";
  typing.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  chatLog.appendChild(typing);
  chatLog.scrollTop = chatLog.scrollHeight;

  const base = ($("base-url").value || window.location.origin).replace(/\/$/, "");
  const headers = { "Content-Type": "application/json" };
  if ($("api-key").value) headers["Authorization"] = "Bearer " + $("api-key").value;

  try {
    const t0 = performance.now();
    const resp = await fetch(base + "/chat", {
      method: "POST",
      headers,
      body: JSON.stringify({ phone: $("phone").value, message: message || "Hola", reset_session: reset }),
    });
    const ms = Math.round(performance.now() - t0);
    typing.remove();

    if (!resp.ok) {
      const detail = await resp.text();
      addBubble(`Error ${resp.status}: ${detail}`, "err");
      return;
    }

    const data = await resp.json();
    data._latency_ms = ms;
    const metaLabel = CIIPOC_LABELS[data.etapa_ciipoc] || data.etapa_ciipoc;
    addBubble(data.reply, "bot", `${metaLabel} · ${data.segmento} · ${ms} ms${data.tool_calls?.length ? " · " + data.tool_calls.length + " tool(s)" : ""}`);
    setState(data);
    fetchSessions();
  } catch (e) {
    typing.remove();
    addBubble("No se pudo contactar el servidor: " + e.message, "err");
  } finally {
    busy = false;
    $("send-btn").disabled = false;
    $("chat-input").focus();
  }
}

// ── Auto-resize textarea ─────────────────────────────────────────

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

// ── Reset session ─────────────────────────────────────────────────

async function resetSession() {
  chatLog.innerHTML = "";
  addBubble("Sesión reiniciada para " + $("phone").value, "sys");
  renderStepper("contacto");
  renderTools([]);
  $("segmento").textContent = "—";
  $("session-id").textContent = "—";
  $("latency-val").textContent = "—";
  $("latency-unit").textContent = "";
  const escaladoBadge = $("escalado");
  escaladoBadge.className = "badge no";
  escaladoBadge.textContent = "No";
  lucide.createIcons();
  await send("Hola", true);
}

// ── Init ──────────────────────────────────────────────────────────

function init() {
  loadSettings();
  renderStepper("contacto");
  renderTools([]);
  addBubble("Bienvenido a la consola de pruebas del agente comercial Icesi. Escribe un mensaje o usa una sugerencia para iniciar la conversación.", "sys");
  lucide.createIcons();

  fetchSessions();
  _refreshTimer = setInterval(fetchSessions, 30000);

  $("phone").addEventListener("change", saveSettings);
  $("base-url").addEventListener("change", saveSettings);
  $("api-key").addEventListener("change", saveSettings);

  $("settings-btn").addEventListener("click", () => $("settings-bar").classList.toggle("show"));
  $("reset-btn").addEventListener("click", resetSession);
  $("refresh-btn").addEventListener("click", fetchSessions);
  $("load-phone-btn").addEventListener("click", () => loadSessionPhone($("phone").value));

  $("send-btn").addEventListener("click", () => send());
  $("chat-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("chat-input").addEventListener("input", () => autoResize($("chat-input")));

  $("chips-row").addEventListener("click", e => {
    if (e.target.classList.contains("chip")) {
      $("chat-input").value = e.target.textContent;
      $("chat-input").focus();
      autoResize($("chat-input"));
    }
  });

  $("chat-input").focus();
}

init();
