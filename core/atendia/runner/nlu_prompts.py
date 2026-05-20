"""
Prompts del NLU (gpt-4o-mini).

Aquí editas:
  1. SYSTEM_PROMPT_TEMPLATE — instrucciones al modelo.
  2. HISTORY_FORMAT         — cómo se renderiza cada turno previo.
  3. OUTPUT_INSTRUCTIONS    — recordatorio del formato de salida.

Los placeholders entre {{ }} se sustituyen al construir la request.
"""

from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner._template_helpers import (
    ROLE_LABELS,  # noqa: F401  (re-exported for tests / external callers)
    _render_history,
    render_template,
)

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

Topics comerciales configurados para este tenant:
{{topics_block}}

{{output_instructions}}
"""


# ============================================================
# 2. HISTORY FORMAT
# ============================================================
HISTORY_FORMAT = "[{{role}}] {{text}}"


# ============================================================
# 3. OUTPUT INSTRUCTIONS
# ============================================================
OUTPUT_INSTRUCTIONS = """\
Reglas de salida:
- Si tu confianza global sobre la intent es < 0.7, marca un string descriptivo
  en "ambiguities" (ej: "intent_borderline_buy_vs_ask_price").
- NO inventes valores. Si el cliente no dijo un dato, NO lo incluyas en entities.
- Para entities numéricas, devuelve número (no string).
- Si el ultimo mensaje corrige, cambia o menciona de nuevo un campo opcional,
  incluyelo en entities aunque ya existiera un valor anterior.
- Si el cliente menciona varios valores posibles para el mismo campo singular,
  extrae solo el valor principal si es inequivoco; si esta pidiendo comparar
  varios, no reemplaces el campo singular y deja la comparacion al composer.
- intent: greeting | ask_info | ask_price | buy | schedule | complain |
          off_topic | unclear.
- topic: usa SOLO una key de la lista configurada para este tenant. Si ningun
  topic encaja claramente, devuelve null.
- sub_intent: intencion fina dentro del topic. Usa una key configurada si
  existe; si el topic encaja pero no hay sub_intent clara, devuelve null.
- sales_signal: none | low | medium | high. Es una senal comercial secundaria,
  NO una orden de avance.
- sentiment: positive, neutral, negative.
- confidence: número 0.0–1.0 sobre tu certeza de la intent.
"""


def _render_fields(fields: list[FieldSpec]) -> str:
    if not fields:
        return "(ninguno)"
    return "\n".join(f"- {f.name}: {f.description or '(sin descripción)'}" for f in fields)


def _render_topics(topics: list[dict] | None) -> str:
    if not topics:
        return "(ninguno configurado; devuelve topic=null y sub_intent=null)"
    lines: list[str] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        key = str(topic.get("key") or "").strip()
        if not key:
            continue
        label = str(topic.get("label") or key).strip()
        description = str(topic.get("description") or "").strip()
        parts = [f"- {key}: {label}"]
        if description:
            parts.append(description)
        examples = topic.get("examples")
        if isinstance(examples, list) and examples:
            rendered = ", ".join(str(v) for v in examples[:5] if str(v).strip())
            if rendered:
                parts.append(f"ejemplos: {rendered}")
        sub_intents = topic.get("sub_intents")
        if isinstance(sub_intents, list) and sub_intents:
            rendered_subs: list[str] = []
            for item in sub_intents[:12]:
                if isinstance(item, dict):
                    sub_key = str(item.get("key") or "").strip()
                    sub_label = str(item.get("label") or sub_key).strip()
                    if sub_key:
                        rendered_subs.append(f"{sub_key} ({sub_label})")
                else:
                    sub_key = str(item).strip()
                    if sub_key:
                        rendered_subs.append(sub_key)
            if rendered_subs:
                parts.append(f"sub_intents: {', '.join(rendered_subs)}")
        lines.append("; ".join(parts))
    return "\n".join(lines) if lines else "(ninguno configurado; devuelve topic=null y sub_intent=null)"


def build_prompt(
    *,
    text: str,
    current_stage: str,
    required_fields: list[FieldSpec],
    optional_fields: list[FieldSpec],
    history: list[tuple[str, str]],
    topics: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Assemble the full chat-completions message list for the NLU call."""
    system_content = render_template(
        SYSTEM_PROMPT_TEMPLATE,
        stage=current_stage,
        required_fields_block=_render_fields(required_fields),
        optional_fields_block=_render_fields(optional_fields),
        topics_block=_render_topics(topics),
        output_instructions=OUTPUT_INSTRUCTIONS,
    )
    return [
        {"role": "system", "content": system_content},
        *_render_history(history, history_format=HISTORY_FORMAT),
        {"role": "user", "content": text},
    ]
