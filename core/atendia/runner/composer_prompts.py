"""
Prompts del Composer (gpt-4o).

Editas:
  1. SYSTEM_PROMPT_TEMPLATE — instrucciones generales + tono.
  2. ACTION_GUIDANCE        — bloque condicional por acción.
  3. HISTORY_FORMAT         — formato de turnos previos.
  4. OUTPUT_INSTRUCTIONS    — reglas sobre el JSON de salida.

Helpers (render_template, _render_history) viven en _template_helpers.
"""
import re

from atendia.runner._template_helpers import (
    _render_history,
    render_template,
)
from atendia.runner.composer_protocol import ComposerInput


# ============================================================
# 1. SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT_TEMPLATE = """\
Eres {{bot_name}}, un asistente de ventas por WhatsApp. Tu tarea es REDACTAR
la respuesta al cliente — NO decides qué hacer (eso ya lo decidió el sistema).

Tono y estilo:
- Registro: {{register}}.
- Emojis: {{use_emojis}}.
- Máximo {{max_words}} palabras por mensaje.
- NUNCA uses estas frases: {{forbidden_phrases}}.
- Frases típicas que puedes usar cuando encajen naturalmente: {{signature_phrases}}.

Estado de la conversación:
- Stage actual: {{stage}}
- Última intent del cliente: {{last_intent}}
- Datos extraídos hasta ahora: {{extracted_data}}

{{action_guidance}}

{{output_instructions}}
"""


# ============================================================
# 2. ACTION GUIDANCE — bloque condicional por acción
# ============================================================
ACTION_GUIDANCE: dict[str, str] = {
    "greet": (
        "Acción: SALUDAR. Saluda brevemente y ofrece ayuda. "
        "NO preguntes datos todavía."
    ),
    "ask_field": (
        "Acción: PEDIR DATO. Necesitas que el cliente te diga el campo "
        "'{{missing_field}}' ({{missing_field_description}}). Pregúntalo "
        "naturalmente, en una sola frase."
    ),
    "ask_clarification": (
        "Acción: PEDIR ACLARACIÓN. El sistema NO entendió bien el último "
        "mensaje. Pídele al cliente que reformule o aclare. NO inventes contexto."
    ),
    "explain_payment_options": (
        "Acción: EXPLICAR OPCIONES DE PAGO. Las opciones genéricas son "
        "efectivo, transferencia y crédito (financiamiento). Menciónalas "
        "brevemente y pregunta cuál prefiere."
    ),
    "lookup_faq": (
        "Acción: BUSCAR EN FAQ. NO TIENES BASE DE FAQS CONECTADA todavía. "
        "Redirige diciendo que lo consultas y le respondes en breve. "
        "NO inventes ninguna respuesta. Mensaje sugerido tipo: "
        "'Déjame revisar y te confirmo en un momento.'"
    ),
    "quote": (
        "Acción: COTIZAR. NO TIENES CATÁLOGO DE PRECIOS CONECTADO todavía. "
        "Redirige diciendo que vas a consultar el precio exacto y se lo pasas. "
        "NO INVENTES PRECIOS. NUNCA des una cifra. Mensaje sugerido tipo: "
        "'Déjame consultar el precio exacto y te lo paso en un momentito.'"
    ),
    "close": (
        "Acción: CERRAR. El cliente acordó comprar. Pasa al siguiente paso "
        "concreto. Si tienes payment_link en action_payload, inclúyelo. "
        "Si no, di que en breve le mandas el link."
    ),
}


# ============================================================
# 3. HISTORY FORMAT
# ============================================================
HISTORY_FORMAT = "[{{role}}] {{text}}"


# ============================================================
# 4. OUTPUT INSTRUCTIONS
# ============================================================
OUTPUT_INSTRUCTIONS = """\
Reglas de salida:
- Devuelve un objeto JSON {"messages": [...]}.
- "messages" es una lista de 1 a {{max_messages}} mensajes cortos.
- Cada mensaje es una cadena, máximo {{max_words}} palabras.
- Si 1 mensaje basta, devuelve 1. Solo divide en 2-3 si es natural en chat
  (saludo + pregunta, por ejemplo).
- NO uses Markdown. NO uses comillas innecesarias. Solo texto plano de chat.
"""


# ============================================================
# build_composer_prompt
# ============================================================

def _render_extracted(extracted: dict) -> str:
    if not extracted:
        return "(ninguno todavía)"
    return ", ".join(f"{k}={v}" for k, v in extracted.items())


def build_composer_prompt(input: ComposerInput) -> list[dict[str, str]]:
    """Assemble the chat-completions message list for gpt-4o."""
    guidance_template = ACTION_GUIDANCE.get(
        input.action, "Acción: " + input.action.upper(),
    )
    # Substitute payload fields if the guidance template has placeholders.
    guidance_vars = {
        "missing_field": str(input.action_payload.get("field_name", "")),
        "missing_field_description": str(
            input.action_payload.get("field_description", ""),
        ),
    }
    needed = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", guidance_template))
    if not needed:
        guidance = guidance_template
    else:
        # Fill any missing keys with "" so render_template doesn't raise.
        for k in needed:
            guidance_vars.setdefault(k, "")
        guidance = render_template(guidance_template, **guidance_vars)

    output_instructions = render_template(
        OUTPUT_INSTRUCTIONS,
        max_messages=str(input.max_messages),
        max_words=str(input.tone.max_words_per_message),
    )

    system_content = render_template(
        SYSTEM_PROMPT_TEMPLATE,
        bot_name=input.tone.bot_name,
        register=input.tone.register,
        use_emojis=input.tone.use_emojis,
        max_words=str(input.tone.max_words_per_message),
        forbidden_phrases=", ".join(input.tone.forbidden_phrases) or "(ninguna)",
        signature_phrases=", ".join(input.tone.signature_phrases) or "(ninguna)",
        stage=input.current_stage,
        last_intent=input.last_intent or "(ninguna)",
        extracted_data=_render_extracted(input.extracted_data),
        action_guidance=guidance,
        output_instructions=output_instructions,
    )

    return [
        {"role": "system", "content": system_content},
        *_render_history(input.history, history_format=HISTORY_FORMAT),
    ]
