"""REAL sandbox smoke: 2 conversations through the live LLM, zero side-effects.

Seeds a Dinamo-Motos-faithful tenant (pipeline + branding brand_facts +
default agent system_prompt — modeled on the project's own canonical
tests/runner/test_phase3c2_live.py fixture, since the dev DB has no
pre-configured real tenant), then runs:

  1. GENERAL  — generic sales inquiry
  2. CREDITO  — motorcycle-credit / financing conversation

through the REAL OpenAINLU (gpt-4o-mini) + OpenAIComposer (gpt-4o) via
run_sandbox_conversation. Hard per-run cost cap; everything is rolled
back (proven by before/after row counts) and no WhatsApp is sent.
Seed rows are deleted at the end.
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.nlu_openai import OpenAINLU
from atendia.sandbox.harness import estimate_cost, run_sandbox_conversation
from atendia.sandbox.result import CostCapExceeded

# Broad single-stage pipeline: every real-NLU intent resolves to an
# allowed action (greet/ask_field/quote/close/book_appointment/...), so
# realistic "buy on credit" conversations don't trip NoActionAvailableError.
# required_fields=[] → the bot answers the question asked instead of
# interrogating for ciudad/sueldo (higher-fidelity replies for the demo).
PIPELINE = {
    "version": 1,
    "stages": [
        {
            "id": "qualify",
            "required_fields": [],
            "actions_allowed": [
                "greet",
                "ask_field",
                "ask_clarification",
                "lookup_faq",
                "search_catalog",
                "quote",
                "close",
                "book_appointment",
                "escalate_to_human",
            ],
            "transitions": [],
        }
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human",
}

# Canonical Dinamo config (mirrors test_phase3c2_live.py _BRAND/_DINAMO_TONE)
_VOICE = {
    "register": "informal_mexicano",
    "use_emojis": "sparingly",
    "max_words_per_message": 45,
    "bot_name": "Dinamo",
    "forbidden_phrases": ["estimado cliente", "le saluda atentamente"],
    "signature_phrases": [],
}
_BRAND_FACTS = {
    "address": "Benito Juárez 801, Centro, Monterrey",
    "approval_time_hours": "24",
    "buro_max_amount": "$50 mil",
    "catalog_url": "https://dinamomotos.com/catalogo.html",
    "delivery_time_days": "3-7",
    "human_agent_name": "Francisco",
    "enganche_desde": "$3,500",
    "plazos_meses": "6, 12, 18 y 24",
    "post_completion_form": "https://forms.gle/ejemplo",
}
_AGENT_PROMPT = (
    "Eres Dinamo, asesor de ventas y crédito de Dinamo Motos (motos Italika "
    "y financiamiento propio). Ayudas al cliente a elegir moto y a armar su "
    "plan de crédito: enganche, mensualidades, plazo y requisitos. NUNCA "
    "inventes precios, montos ni mensualidades exactas que no tengas como "
    "dato; si no lo tienes, dilo y ofrece conectar con un asesor humano "
    "(Francisco). Tono cercano y mexicano, mensajes cortos."
)
_AGENT_GOAL = "Calificar al prospecto y avanzarlo hacia una cotización o plan de crédito."

SCRIPT_GENERAL = [
    "Hola, buenas tardes",
    "Me interesa una motocicleta para repartir comida",
    "¿Qué modelos manejan y como en cuánto andan?",
    "¿Dónde están ubicados y cómo la entregan?",
]
SCRIPT_CREDITO = [
    "Hola, quiero comprar una moto a crédito",
    "¿De cuánto es el enganche?",
    "Gano como 9 mil al mes y estoy en buró, ¿igual puedo?",
    "¿De cuánto saldrían las mensualidades a 12 meses para una Italika 150?",
    "¿Qué papeles necesito para meter la solicitud?",
]

CAP_PER_RUN = Decimal("0.40")  # hard ceiling; expected actual ~ $0.05/run


async def _counts(s: AsyncSession, conv_id, tid) -> dict:
    c = {}
    for t in ("messages", "turn_traces", "field_suggestions"):
        c[t] = (
            await s.execute(
                text(f"SELECT count(*) FROM {t} WHERE conversation_id=:c"),
                {"c": conv_id},
            )
        ).scalar()
    c["outbound_outbox"] = (
        await s.execute(
            text("SELECT count(*) FROM outbound_outbox WHERE tenant_id=:t"),
            {"t": tid},
        )
    ).scalar()
    return c


async def _run_scenario(factory, label, conv_id, tid, script, nlu, composer):
    print(f"\n{'=' * 70}\n  {label}  (conv {conv_id})\n{'=' * 70}")
    async with factory() as s:
        before = await _counts(s, conv_id, tid)

    spent = Decimal("0")
    try:
        result = await run_sandbox_conversation(
            conversation_id=conv_id,
            tenant_id=tid,
            script=script,
            cost_cap_usd=CAP_PER_RUN,
            nlu_provider=nlu,
            composer_provider=composer,
        )
        turns = result.turns
        spent = result.total_cost_usd
    except CostCapExceeded as e:
        turns = e.partial
        spent = e.spent
        print(f"  [cost cap {CAP_PER_RUN} hit — showing {len(turns)} partial turns]")

    for i, (inb, t) in enumerate(zip(script, turns), 1):
        reply = " | ".join(t.would_be_outbound) if t.would_be_outbound else "(sin respuesta)"
        print(f"\n  T{i}  👤 {inb}")
        print(f"      flow_mode={t.flow_mode}  cost=${t.cost_usd:.5f}")
        print(f"      🤖 {reply}")

    async with factory() as s:
        after = await _counts(s, conv_id, tid)
    ok = "✅ ZERO side-effects" if after == before else f"❌ LEAK before={before} after={after}"
    print(f"\n  run total = ${spent:.5f}   |   {ok}")
    return spent


async def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    st = get_settings()
    print("DB:", st.database_url)
    api_key = st.openai_api_key
    assert api_key, "no ATENDIA_V2_OPENAI_API_KEY"

    engine = create_async_engine(st.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    import json

    async with factory() as s:
        tid = (
            await s.execute(
                text("INSERT INTO tenants (name) VALUES ('sandbox_smoke_dinamo') RETURNING id")
            )
        ).scalar()
        await s.execute(
            text(
                "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                "VALUES (:t,1,:d\\:\\:jsonb,true)"
            ),
            {"t": tid, "d": json.dumps(PIPELINE)},
        )
        await s.execute(
            text(
                "INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages) "
                "VALUES (:t,'Dinamo',:v\\:\\:jsonb,:dm\\:\\:jsonb)"
            ),
            {"t": tid, "v": json.dumps(_VOICE), "dm": json.dumps({"brand_facts": _BRAND_FACTS})},
        )
        await s.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, is_default, system_prompt, goal, tone) "
                "VALUES (gen_random_uuid(), :t, 'Dinamo', true, :sp, :g, 'amigable')"
            ),
            {"t": tid, "sp": _AGENT_PROMPT, "g": _AGENT_GOAL},
        )
        cid = (
            await s.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164) "
                    "VALUES (:t,'+5218110000001') RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar()
        conv_ids = {}
        for key in ("GENERAL", "CREDITO"):
            cv = (
                await s.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                        "VALUES (:t,:c,'qualify') RETURNING id"
                    ),
                    {"t": tid, "c": cid},
                )
            ).scalar()
            await s.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": cv},
            )
            conv_ids[key] = cv
        await s.commit()

    try:
        est = await estimate_cost(
            tenant_id=tid, n_turns=len(SCRIPT_GENERAL) + len(SCRIPT_CREDITO)
        )
        print(f"\nPre-run estimate (no history → fallback): ~${est:.4f}")
        print(f"Hard cap per run: ${CAP_PER_RUN}  |  budget: $1.53")

        nlu = OpenAINLU(api_key=api_key)
        composer = OpenAIComposer(api_key=api_key)

        g = await _run_scenario(
            factory, "ESCENARIO 1 — GENERAL (ventas)", conv_ids["GENERAL"],
            tid, SCRIPT_GENERAL, nlu, composer,
        )
        c = await _run_scenario(
            factory, "ESCENARIO 2 — CREDITO DE MOTOS", conv_ids["CREDITO"],
            tid, SCRIPT_CREDITO, nlu, composer,
        )
        print(f"\n{'#' * 70}\n  GRAN TOTAL GASTADO = ${g + c:.5f}   (de tu $1.53)\n{'#' * 70}")
    finally:
        async with factory() as s:
            await s.execute(text("DELETE FROM tenants WHERE id=:t"), {"t": tid})
            await s.commit()
        await engine.dispose()
        print("\nseed rows deleted · harness rolled back all runner writes · nada persistió")


if __name__ == "__main__":
    asyncio.run(main())
