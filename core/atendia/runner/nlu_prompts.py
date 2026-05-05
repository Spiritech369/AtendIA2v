"""
Prompts del NLU (gpt-4o-mini).

Aquí editas:
  1. SYSTEM_PROMPT_TEMPLATE — instrucciones al modelo.
  2. HISTORY_FORMAT         — cómo se renderiza cada turno previo.
  3. OUTPUT_INSTRUCTIONS    — recordatorio del formato de salida.

Los placeholders entre {{ }} se sustituyen al construir la request.
"""
import re

from atendia.contracts.pipeline_definition import FieldSpec

# ============================================================
# 1. SYSTEM PROMPT — instrucciones generales
# ============================================================
SYSTEM_PROMPT_TEMPLATE = """\
Eres un clasificador de intenciones para un asistente de ventas por WhatsApp.
Tu única tarea es analizar el último mensaje del cliente y devolver un JSON
estricto que cumpla el schema. NO redactas respuestas. NO sugieres acciones.

Stage actual de la conversación: {{stage}}

Campos requeridos para avanzar (extrae si el cliente los menciona, explícita
o implícitamente, en el último mensaje):
{{required_fields_block}}

Campos opcionales (extrae si aparecen; no los inventes si no aparecen):
{{optional_fields_block}}

{{output_instructions}}
"""


# ============================================================
# 2. HISTORY FORMAT
# ============================================================
HISTORY_FORMAT = "[{{role}}] {{text}}"

ROLE_LABELS = {
    "inbound": "cliente",
    "outbound": "asistente",
}


# ============================================================
# 3. OUTPUT INSTRUCTIONS
# ============================================================
OUTPUT_INSTRUCTIONS = """\
Reglas de salida:
- Si tu confianza global sobre la intent es < 0.7, marca un string descriptivo
  en "ambiguities" (ej: "intent_borderline_buy_vs_ask_price").
- NO inventes valores. Si el cliente no dijo un dato, NO lo incluyas en entities.
- Para entities numéricas, devuelve número (no string).
- intent: greeting | ask_info | ask_price | buy | schedule | complain |
          off_topic | unclear.
- sentiment: positive, neutral, negative.
- confidence: número 0.0–1.0 sobre tu certeza de la intent.
"""


_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, **vars: str) -> str:
    """Substitute {{name}} placeholders. Raise if any remain unfilled.

    Extra vars are ignored. Missing vars raise RuntimeError so a typo never
    silently leaves a placeholder in the prompt sent to the LLM.
    """
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in vars:
            raise RuntimeError(
                f"unsubstituted placeholder {{{{ {key} }}}} in template"
            )
        return str(vars[key])
    return _PLACEHOLDER_RE.sub(_sub, template)


def _render_fields(fields: list[FieldSpec]) -> str:
    if not fields:
        return "(ninguno)"
    return "\n".join(
        f"- {f.name}: {f.description or '(sin descripción)'}"
        for f in fields
    )


def _render_history(history: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Convert [(direction, text), ...] into chat messages.

    inbound → role 'user', outbound → role 'assistant'. The bracketed label
    inside the content uses ROLE_LABELS for transparency.
    """
    out: list[dict[str, str]] = []
    for direction, text in history:
        role = "user" if direction == "inbound" else "assistant"
        label = ROLE_LABELS.get(direction, direction)
        rendered = render_template(HISTORY_FORMAT, role=label, text=text)
        out.append({"role": role, "content": rendered})
    return out


def build_prompt(
    *,
    text: str,
    current_stage: str,
    required_fields: list[FieldSpec],
    optional_fields: list[FieldSpec],
    history: list[tuple[str, str]],
) -> list[dict[str, str]]:
    """Assemble the full chat-completions message list for the NLU call."""
    system_content = render_template(
        SYSTEM_PROMPT_TEMPLATE,
        stage=current_stage,
        required_fields_block=_render_fields(required_fields),
        optional_fields_block=_render_fields(optional_fields),
        output_instructions=OUTPUT_INSTRUCTIONS,
    )
    return [
        {"role": "system", "content": system_content},
        *_render_history(history),
        {"role": "user", "content": text},
    ]
