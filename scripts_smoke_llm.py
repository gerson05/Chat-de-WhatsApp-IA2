"""Smoke test de la migración a Gemini. Uso: python scripts_smoke_llm.py"""
import asyncio
from orchestrator import llm
from orchestrator.tools import TOOL_SCHEMAS


def test_conversion():
    # tool schemas -> gemini function_declarations
    gtools = llm._convert_tools(TOOL_SCHEMAS)
    assert gtools and "function_declarations" in gtools[0]
    assert len(gtools[0]["function_declarations"]) == 5

    # roundtrip de un turno con tool_use + tool_result
    msgs = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": [
            llm._ToolUseBlock(id="call_x_0", name="registrar_intencion", input={"etapa": "contacto"}),
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_x_0", "content": '{"ok": true}'},
        ]},
    ]
    contents = llm._convert_messages(msgs)
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["function_call"]["name"] == "registrar_intencion"
    fr = contents[2]["parts"][0]["function_response"]
    assert fr["name"] == "registrar_intencion" and fr["response"] == {"ok": True}
    print("OK conversion: tools y roundtrip tool_use/tool_result")


async def test_live():
    client = llm.get_llm_client()
    resp = await client.messages.create(
        model="gemini-2.0-flash",
        max_tokens=128,
        system="Responde en una sola frase corta en español.",
        messages=[{"role": "user", "content": "Di 'hola mundo' y nada mas."}],
    )
    texts = [b.text for b in resp.content if b.type == "text"]
    print(f"OK live: stop_reason={resp.stop_reason} reply={' '.join(texts)!r}")


if __name__ == "__main__":
    test_conversion()
    try:
        asyncio.run(test_live())
    except Exception as exc:
        print(f"FALLO live (revisa la API key / modelo): {type(exc).__name__}: {exc}")
