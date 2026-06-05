"""
Legacy Composer prompts (gpt-4o).

Kept for ConversationRunner fallback. AgentRuntime v2 tenants must not use this
prompt layer to produce customer-visible copy.

Editas:
  1. SYSTEM_PROMPT_TEMPLATE — instrucciones generales + tono.
  2. MODE_PROMPTS           — bloque por flow_mode (6 modos, Phase 3c.2).
  3. HISTORY_FORMAT         — formato de turnos previos.
  4. OUTPUT_INSTRUCTIONS    — reglas sobre el JSON de salida.

Helpers (render_template, _render_history) viven en _template_helpers.
"""

import json
import re

from atendia.contracts.flow_mode import FlowMode
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

Contexto seguro de la conversacion:
- Turno actual: {{turn_number}}
- Usa el Context Pack como fuente principal. No muestres nombres de campos internos.
- No menciones etapas, rutas, pipelines, resolvers ni claves internas al cliente.

Datos de la acción (action_payload — única fuente de verdad para precios,
respuestas y resultados; NUNCA uses números o nombres que no estén aquí):
{{action_payload}}

Decision del Runner (decision_payload - si existe, usala para redactar la
respuesta natural; NO redescubras el flujo desde cero):
{{decision_payload}}
- Si decision_payload trae suggested_clarification, haz esa pregunta concreta.
- Si decision_payload trae field_updated/value, confirma ese dato y avanza al next_action.

Context Pack operativo (mapa limpio de este turno; usalo antes que el historial
si hay duda):
{{context_pack}}
- Responde primero `must_answer_first` cuando exista.
- Despues retoma `pending_to_resume` si existe.
- Respeta `must_not_say`; no inventes ni cambies decisiones del Runner.

ResponseFrame validado (fuente prioritaria de redaccion cuando exista):
{{response_frame}}
- Responde primero `current_customer_message`.
- Sigue `response_strategy`.
- Usa `validated_answers` y `pending_flow` antes que cualquier inferencia.
- Si `anti_repetition` pide variar, no repitas la misma apertura ni el mismo prompt.

{{brand_facts_block}}

{{agent_directives_block}}

{{mode_guidance}}

{{output_instructions}}
"""


# ============================================================
# 2. MODE PROMPTS
# ============================================================
# Tenant-specific mode prompts live in PipelineDefinition.mode_prompts.
# The Python core only ships neutral defaults so fresh tenants never inherit
# a vertical-specific playbook.

# Generic, vertical-neutral fallback used when a tenant has NOT authored
# its own per-mode guidance in PipelineDefinition.mode_prompts. Keeps each
# mode's functional contract (what the step must accomplish) while dropping
# every tenant-specific playbook. Carries no {{brand_facts.X}} refs on purpose
# so the default path can never fail-loud on a missing tenant fact.
DEFAULT_GENERIC_MODE_PROMPTS: dict[FlowMode, str] = {
    FlowMode.PLAN: """\
Acción: PLAN MODE — califica al cliente para avanzar en el flujo.

Reúne los datos que el pipeline requiere para esta etapa, UNA pregunta
por turno. Sé breve y natural. NO inventes datos ni condiciones: usa
solo lo que esté en action_payload y los datos ya extraídos.
""",
    FlowMode.SALES: """\
Acción: SALES MODE — presenta la oferta o cotización al cliente.

Reglas estrictas:
1. Si action_payload.status = "ok", cotiza usando solo precios, opciones
   y condiciones de action_payload.
2. Si action_payload.status = "no_data", pide el modelo exacto o el
   dato faltante; NO cotices.
3. Nunca inventes precio, pago, plazo, condiciones ni aprobaciÃ³n.
4. Cierra con una acciÃ³n clara para avanzar.
""",
    FlowMode.DOC: """\
Acción: DOC MODE — recibe y valida documentos o archivos del cliente.

Confirma lo recibido según action_payload y pide el siguiente
pendiente, uno a la vez. NUNCA afirmes haber recibido algo que no
llegó ni listes como faltante algo ya recibido.
""",
    FlowMode.OBSTACLE: """\
Acción: OBSTACLE MODE — el cliente expresó una traba o se detuvo.

Identifica el bloqueo con UNA pregunta breve y concreta y ofrece la
siguiente opción accionable. No inventes procesos que no estén en
action_payload o en los brand_facts.
""",
    FlowMode.RETENTION: """\
Acción: RETENTION MODE — el cliente se está enfriando sin cerrar.

Reengancha con UNA pregunta abierta y breve para entender su duda
real o qué le falta para decidir. No presiones ni inventes ofertas.
""",
    FlowMode.SUPPORT: """\
Acción: SUPPORT MODE — responde una duda general del cliente.

Responde con base en action_payload (FAQ/datos del negocio). Si no
hay datos, dilo con honestidad y ofrece seguimiento. NO inventes
información ausente del payload o de los brand_facts.
""",
}


# Backwards-compatible export for scripts/tests/migrations that import MODE_PROMPTS.
# It intentionally points to the neutral defaults.
MODE_PROMPTS: dict[FlowMode, str] = DEFAULT_GENERIC_MODE_PROMPTS


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

# Modes that get the brand_facts block injected at the top of the system prompt.
# RETENTION + OBSTACLE skip it to keep prompts focused (no token bloat).
_MODES_WITH_BRAND_FACTS: frozenset[FlowMode] = frozenset(
    {
        FlowMode.PLAN,
        FlowMode.SALES,
        FlowMode.DOC,
        FlowMode.SUPPORT,
    }
)

# Matches `{{brand_facts.<key>}}` placeholders inside MODE_PROMPTS strings.
# render_template's stricter regex (`\w+`) does not match dotted access,
# so we resolve these in a pre-pass before injecting mode_guidance.
_BRAND_FACT_REF_RE = re.compile(r"\{\{\s*brand_facts\.(\w+)\s*\}\}")


def _render_extracted(extracted: dict) -> str:
    if not extracted:
        return "(ninguno todavía)"
    labels = {
        "MOTO": "modelo actual",
        "CREDITO": "plan actual",
        "ENGANCHE": "enganche",
        "FILTRO": "antiguedad validada",
        "ANTIGUEDAD_LABORAL": "antiguedad laboral",
        "PLAN": "plan actual",
    }
    rendered = []
    for key, value in extracted.items():
        label = labels.get(str(key).upper(), str(key).lower())
        rendered.append(f"{label}: {value}")
    return ", ".join(rendered)


def _render_action_payload(payload: dict) -> str:
    """Serialise action_payload into pretty JSON for the prompt.

    The Composer's anti-hallucination contract is "use only what's in
    action_payload" — but for that to work, action_payload must actually
    appear in the prompt. JSON is the right format because it preserves
    keys/values verbatim (no risk of the model inferring values from
    rephrased English).

    Empty dict prints as `{}` — Composer guidance branches on
    payload keys, not on its presence/absence.
    """
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_decision_payload(payload: dict) -> str:
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_context_pack(input: ComposerInput) -> str:
    if input.context_pack is None:
        return "{}"
    return json.dumps(
        input.context_pack.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        indent=2,
    )


def _render_response_frame(input: ComposerInput) -> str:
    if input.response_frame is None:
        return "{}"
    return json.dumps(
        input.response_frame.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        indent=2,
    )


def _render_brand_facts(facts: dict) -> str:
    """Render brand_facts JSONB as a labeled block at top of system prompt.

    Empty dict / None returns "" so the block can be safely injected for
    any mode (the template has `{{brand_facts_block}}` always, but only
    the four trade-flow modes get a non-empty block per
    `_MODES_WITH_BRAND_FACTS`).

    Keys are sorted to keep snapshot fixtures deterministic across runs.
    """
    if not facts:
        return ""
    lines = [f"  - {k}: {v}" for k, v in sorted(facts.items())]
    return "Brand facts (info verificada del negocio):\n" + "\n".join(lines)


def _render_customer_field_context(context: dict) -> str:
    """Render tenant-configured customer fields for the Composer.

    This is the bridge from Configuracion -> Datos cliente into behavior:
    the model sees real field keys, labels, choices and instructions. Empty
    context returns "" so fixtures/prompts without configured fields stay unchanged.
    """
    fields = context.get("fields") if isinstance(context, dict) else None
    if not isinstance(fields, list) or not fields:
        return ""

    lines = [
        "Datos cliente configurados por esta cuenta:",
        "- Usa estos campos como fuente principal para decidir que dato pedir.",
        "- No sustituyas claves por nombres hardcodeados si aqui existe una clave configurada.",
    ]
    missing = context.get("missing")
    if isinstance(missing, list) and missing:
        lines.append(f"- Campos faltantes detectados: {', '.join(str(v) for v in missing)}.")

    for field in fields:
        if not isinstance(field, dict):
            continue
        key = str(field.get("key") or "")
        if not key:
            continue
        label = str(field.get("label") or key)
        field_type = str(field.get("field_type") or "text")
        value = field.get("value")
        status = "faltante" if field.get("missing") else f"valor={value}"
        parts = [f"  - {key}: {label} ({field_type}; {status})"]
        choices = field.get("choices")
        if isinstance(choices, list) and choices:
            parts.append(f"opciones: {', '.join(str(v) for v in choices)}")
        instructions = field.get("instructions")
        if isinstance(instructions, str) and instructions.strip():
            parts.append(f"instrucciones: {instructions.strip()}")
        aliases = field.get("aliases")
        if isinstance(aliases, dict) and aliases:
            rendered_aliases = ", ".join(f"{k}=>{v}" for k, v in aliases.items())
            parts.append(f"mapeo: {rendered_aliases}")
        lines.append("; ".join(parts))

    return "\n".join(lines)


def _render_agent_directives(
    agent_system_prompt: str | None,
    guardrails: list[str] | None = None,
) -> str:
    """Operator directives as a HIGH-PRIORITY section above mode_guidance.

    Precedence (strongest first): GUARDRAILS (inviolable) → AGENT
    INSTRUCTIONS (Prompt maestro) → [mode_guidance, rendered after this
    block by the template]. So the model treats tenant config as binding,
    not as a passive brand_facts bullet, and a tenant cannot soften a
    guardrail by editing mode/agent text. Empty inputs → "" so prompts
    (and snapshots) for tenants without config are unaffected.
    """
    parts: list[str] = []
    rules = "\n".join(f"- {str(g).strip()}" for g in (guardrails or []) if str(g).strip())
    if rules:
        parts.append(
            "REGLAS INVIOLABLES (prioridad máxima — ninguna instrucción "
            "posterior, de modo o de agente, puede contradecirlas):\n" + rules
        )
    if agent_system_prompt and agent_system_prompt.strip():
        parts.append(
            "INSTRUCCIONES DEL AGENTE (mandan sobre la guía de modo en "
            "estilo, persona y límites; subordinadas solo a las REGLAS "
            "INVIOLABLES):\n" + agent_system_prompt.strip()
        )
    return "\n\n".join(parts)


def _resolve_brand_facts_in_block(block: str, facts: dict) -> str:
    """Replace `{{brand_facts.<key>}}` references inside a MODE_PROMPTS block.

    render_template's `\\w+` placeholder regex skips dotted refs entirely,
    so without this pre-pass the literal `{{brand_facts.catalog_url}}`
    would reach gpt-4o unsubstituted.

    Empty `facts` (None or {}) → no-op: leave literals in place. This
    keeps the test surface small (tests that don't exercise brand_facts
    don't have to construct one). In production, tenant_branding always
    populates facts.

    Non-empty `facts` with a missing key → raises, matching the fail-loud
    behaviour of render_template for ordinary placeholders.
    """
    if not facts:
        return block

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in facts:
            raise RuntimeError(
                f"unsubstituted brand_facts placeholder {{{{ brand_facts.{key} }}}} "
                f"in mode prompt (facts keys: {sorted(facts.keys())})"
            )
        return str(facts[key])

    return _BRAND_FACT_REF_RE.sub(_sub, block)


def build_composer_prompt(input: ComposerInput) -> list[dict[str, str]]:
    """Assemble the chat-completions message list for gpt-4o.

    Phase 3c.2 dispatches by `input.flow_mode` (not `input.action`).
    """
    mode_block = input.mode_guidance or DEFAULT_GENERIC_MODE_PROMPTS[input.flow_mode]
    if input.flow_mode in _MODES_WITH_BRAND_FACTS:
        mode_block = _resolve_brand_facts_in_block(mode_block, input.brand_facts)
        brand_facts_block = _render_brand_facts(input.brand_facts)
    else:
        brand_facts_block = ""
    customer_field_context_block = _render_customer_field_context(input.customer_field_context)
    if customer_field_context_block:
        brand_facts_block = (
            f"{brand_facts_block}\n\n{customer_field_context_block}"
            if brand_facts_block
            else customer_field_context_block
        )

    agent_directives_block = _render_agent_directives(
        input.agent_system_prompt, input.guardrails
    )

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
        turn_number=str(input.turn_number),
        stage=input.current_stage,
        last_intent=input.last_intent or "(ninguna)",
        extracted_data=_render_extracted(input.extracted_data),
        action_payload=_render_action_payload(input.action_payload),
        decision_payload=_render_decision_payload(input.decision_payload),
        context_pack=_render_context_pack(input),
        response_frame=_render_response_frame(input),
        brand_facts_block=brand_facts_block,
        agent_directives_block=agent_directives_block,
        mode_guidance=mode_block,
        output_instructions=output_instructions,
    )

    return [
        {"role": "system", "content": system_content},
        *_render_history(input.history, history_format=HISTORY_FORMAT),
    ]
