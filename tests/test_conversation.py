"""
Test suite for the Icesi IA conversation system.
20 scenarios covering CIIPOC flow, escalations, tool dispatch, and guards.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.models import SessionState, Segmento, EtapaCIIPOC
from orchestrator.tools import dispatch_tool, tool_validar_programa, tool_sugerir_siguiente_paso
from orchestrator.session_store import hash_phone


# ── Fixtures ────────────────────────────────────────────────────────────────────

def make_session(**kwargs) -> SessionState:
    defaults = {
        "id_usuario": hash_phone("+573001234567"),
        "segmento": Segmento.indefinido,
        "etapa_ciipoc": EtapaCIIPOC.contacto,
    }
    defaults.update(kwargs)
    return SessionState(**defaults)


# ── Tool unit tests ─────────────────────────────────────────────────────────────

class TestValidarPrograma:
    def test_programa_existente_ingenieria(self, tmp_path, monkeypatch):
        """T01: validar_programa finds Ingeniería de Sistemas in manifest."""
        manifest = {
            "documentos": [{
                "id": "PRG-PIL-01",
                "nombre": "Ingeniería de Sistemas",
                "unidad": "pregrado",
                "diferencial_breve": "Formación práctica.",
            }]
        }
        manifest_path = tmp_path / "manifest.yaml"
        import yaml
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")
        monkeypatch.setenv("KB_PATH", str(tmp_path))

        import orchestrator.tools as tools_mod
        tools_mod._manifest_cache = None
        monkeypatch.setattr(tools_mod.settings, "kb_path", str(tmp_path))
        tools_mod._manifest_cache = None

        result = tool_validar_programa("Ingeniería de Sistemas")
        assert result["encontrado"] is True
        assert result["id"] == "PRG-PIL-01"

    def test_programa_no_existente(self, tmp_path, monkeypatch):
        """T02: validar_programa returns not found for unknown program."""
        import yaml, orchestrator.tools as tools_mod
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.dump({"documentos": []}), encoding="utf-8")
        tools_mod._manifest_cache = None
        monkeypatch.setattr(tools_mod.settings, "kb_path", str(tmp_path))
        tools_mod._manifest_cache = None

        result = tool_validar_programa("Doctorado en Astrofísica")
        assert result["encontrado"] is False
        assert "escalar" in result["mensaje"].lower()


class TestRegistrarIntencion:
    def test_avance_de_etapa(self):
        """T03: registrar_intencion advances CIIPOC stage."""
        session = make_session(etapa_ciipoc=EtapaCIIPOC.contacto)
        result = dispatch_tool(
            "registrar_intencion",
            {"etapa": "indagacion", "programa": "Ingeniería de Sistemas"},
            session,
        )
        assert result["ok"] is True
        assert result["avanzó_etapa"] is True
        assert session.etapa_ciipoc == EtapaCIIPOC.indagacion
        assert session.programa_interes == "Ingeniería de Sistemas"
        assert session.contador_mensajes_sin_avance == 0

    def test_no_avance_no_incrementa_contador(self):
        """T04: staying in same stage does not reset the no-advance counter."""
        session = make_session(
            etapa_ciipoc=EtapaCIIPOC.propuesta,
            contador_mensajes_sin_avance=3,
        )
        result = dispatch_tool(
            "registrar_intencion",
            {"etapa": "propuesta"},
            session,
        )
        assert result["avanzó_etapa"] is False
        assert session.contador_mensajes_sin_avance == 4

    def test_captura_barrera_y_necesidad(self):
        """T05: registrar_intencion captures barrier and need."""
        session = make_session()
        dispatch_tool(
            "registrar_intencion",
            {
                "etapa": "identificacion",
                "barrera": "Costo del programa",
                "necesidad": "Crecimiento profesional",
            },
            session,
        )
        assert session.barrera == "Costo del programa"
        assert session.necesidad_identificada == "Crecimiento profesional"


class TestEscalarAsesor:
    def test_escalamiento_marca_sesion(self):
        """T06: escalar_a_asesor marks session as escalated."""
        session = make_session(segmento=Segmento.posgrado, nombre="Juan")
        result = dispatch_tool(
            "escalar_a_asesor",
            {
                "motivo": "solicitud_explicita",
                "prioridad": "media",
                "resumen": {
                    "nombre_aspirante": "Juan",
                    "programa_interes": "MBA",
                    "segmento": "posgrado",
                    "etapa_ciipoc_actual": "propuesta",
                },
            },
            session,
        )
        assert result["ok"] is True
        assert session.escalado is True

    def test_enrutamiento_correcto_posgrado(self):
        """T07: escalation routes to Lauri Ariza for posgrado."""
        session = make_session(segmento=Segmento.posgrado)
        result = dispatch_tool(
            "escalar_a_asesor",
            {"motivo": "dato_no_documentado", "prioridad": "media", "resumen": {}},
            session,
        )
        assert "Lauri" in result["asesor_asignado"]

    def test_enrutamiento_b2b(self):
        """T08: B2B escalation routes to Alejandra Tinoco."""
        session = make_session(segmento=Segmento.educontinua)
        result = dispatch_tool(
            "escalar_a_asesor",
            {"motivo": "b2b", "prioridad": "alta", "resumen": {}},
            session,
        )
        assert "Alejandra" in result["asesor_asignado"]

    def test_ticket_contiene_resumen(self):
        """T09: escalation ticket contains key information."""
        session = make_session(
            segmento=Segmento.pregrado,
            nombre="Santiago",
            programa_interes="PRG-PIL-01",
            etapa_ciipoc=EtapaCIIPOC.cierre,
        )
        result = dispatch_tool(
            "escalar_a_asesor",
            {
                "motivo": "alta_intencion_cierre",
                "prioridad": "alta",
                "resumen": {
                    "nombre_aspirante": "Santiago",
                    "siguiente_accion_sugerida": "Llamar hoy",
                },
            },
            session,
        )
        ticket = result["ticket"]
        assert "Santiago" in ticket
        assert "ALTA" in ticket
        assert "Llamar hoy" in ticket


class TestSugerirSiguientePaso:
    def test_etapa_contacto(self):
        """T10: sugerir_siguiente_paso returns guidance for Contacto."""
        result = tool_sugerir_siguiente_paso("contacto")
        assert "nombre" in result["sugerencia"].lower()

    def test_etapa_invalida(self):
        """T11: sugerir_siguiente_paso handles unknown stage gracefully."""
        result = tool_sugerir_siguiente_paso("etapa_inexistente")
        assert "válidas" in result["sugerencia"].lower()


class TestDispatcher:
    def test_unknown_tool(self):
        """T12: dispatch_tool returns error for unknown tool name."""
        session = make_session()
        result = dispatch_tool("herramienta_inexistente", {}, session)
        assert "error" in result


# ── Session state tests ────────────────────────────────────────────────────────

class TestSessionState:
    def test_add_turn_updates_last_question(self):
        """T13: add_turn stores user text as ultima_pregunta."""
        session = make_session()
        session.add_turn("user", "¿Cuánto cuesta el MBA?")
        assert session.ultima_pregunta == "¿Cuánto cuesta el MBA?"

    def test_get_recent_history_limit(self):
        """T14: get_recent_history respects the window limit."""
        session = make_session()
        for i in range(12):
            session.add_turn("user" if i % 2 == 0 else "assistant", f"mensaje {i}")
        recent = session.get_recent_history(8)
        assert len(recent) == 8


# ── Conversation guard tests ───────────────────────────────────────────────────

class TestConversationGuards:
    def test_hallucination_pattern_detected(self):
        """T15: _has_hallucination_risk detects price patterns."""
        from orchestrator.conversation import _has_hallucination_risk
        assert _has_hallucination_risk("El semestre cuesta $15.000.000") is True
        assert _has_hallucination_risk("Contáctanos para más información") is False

    def test_frustration_detection(self):
        """T16: _check_frustration detects frustration keywords."""
        from orchestrator.conversation import _check_frustration
        assert _check_frustration("no me entiendes para nada") is True
        assert _check_frustration("gracias, eso es lo que necesitaba") is False

    def test_pre_escalation_crisis(self):
        """T17: _detect_pre_escalation catches crisis signals."""
        from orchestrator.conversation import _detect_pre_escalation
        assert _detect_pre_escalation("no quiero vivir más") == "crisis_emocional"

    def test_pre_escalation_b2b(self):
        """T18: _detect_pre_escalation catches B2B signals."""
        from orchestrator.conversation import _detect_pre_escalation
        assert _detect_pre_escalation("quiero matricular a un grupo de empleados") == "b2b"

    def test_no_pre_escalation_normal(self):
        """T19: _detect_pre_escalation returns None for normal messages."""
        from orchestrator.conversation import _detect_pre_escalation
        assert _detect_pre_escalation("hola me interesa la maestría en mercadeo") is None


# ── WA message splitting ───────────────────────────────────────────────────────

class TestWhatsAppSplitting:
    def test_short_message_not_split(self):
        """T20: Short messages are not split."""
        from orchestrator.whatsapp import _split_message
        msg = "Hola, soy el asistente de Icesi."
        parts = _split_message(msg)
        assert len(parts) == 1
        assert parts[0] == msg

    def test_long_message_split(self):
        """T21: Long messages are split into ≤3 parts."""
        from orchestrator.whatsapp import _split_message
        msg = "A" * 3000
        parts = _split_message(msg)
        assert 1 < len(parts) <= 3
        for p in parts:
            assert len(p) <= 1024


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
