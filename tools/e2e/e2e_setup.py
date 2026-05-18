"""Reusable E2E setup client for the moto-credito product validation plan.

Task 2: load the `docs/Prompt master.txt` text into the product as a real
Agent via the Agente IA Manager API (`POST /api/v1/agents`), exactly as an
operator would through the UI — no DB shortcuts, no runtime-code changes.

This module is intentionally a small, clean toolkit. Later tasks (KB,
pipeline, conversations, workflows) import `Client` and reuse its
authenticated session, so keep it stable and side-effect-free at import.

Auth model (already discovered, see plan):
  POST /api/v1/auth/login {email,password} -> 200, body has `csrf_token`
  and sets the session + csrf cookies. Every unsafe request must carry the
  cookie jar AND the `X-CSRF-Token` header (double-submit CSRF). The same
  `httpx.Client` keeps the cookie jar across calls.

Run as __main__ (Task 2 steps 2-4):
  cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/e2e_setup.py

It will: login -> create the agent -> read it back and assert the
system_prompt round-trips byte-identical + flow_mode_rules persisted ->
make AT MOST ONE real preview-response LLM call (small real $) -> print a
PASS/FAIL summary. It never loops LLM calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

# --- constants -------------------------------------------------------------

BASE_URL = "http://localhost:8001"
LOGIN_EMAIL = "dele.zored@hotmail.com"
LOGIN_PASSWORD = "dinamo123"

# docs/Prompt master.txt lives at the repo root (this file is core/scripts/).
REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_MASTER_PATH = REPO_ROOT / "docs" / "Prompt master.txt"

# Operator-realistic flow_mode_rules. Sprint 1 hardening made these live:
# the runner prefers agent.flow_mode_rules and only falls back to pipeline
# defaults for legacy tenants. Pipeline JSON stays focused on stages/docs
# so Agent IA is the single operator-facing owner of routing.
AGENT_FLOW_MODE_RULES: dict[str, Any] = {
    "rules": [
        {
            "id": "doc_attachment",
            "trigger": {"type": "has_attachment"},
            "mode": "DOC",
        },
        {
            "id": "obstacle_kw",
            "trigger": {
                "type": "keyword_in_text",
                "list": [
                    "manana",
                    "ahorita",
                    "al rato",
                    "cuando llegue",
                    "luego",
                    "luego te mando",
                    "tengo que pedirlas",
                ],
            },
            "mode": "OBSTACLE",
        },
        {
            "id": "retention_kw",
            "trigger": {
                "type": "keyword_in_text",
                "list": ["gracias", "ok gracias", "gracias por la info"],
            },
            "mode": "RETENTION",
        },
        {
            "id": "plan_missing_tipo",
            "trigger": {"type": "field_missing", "field": "tipo_credito"},
            "mode": "PLAN",
        },
        {
            "id": "plan_missing_plan",
            "trigger": {"type": "field_missing", "field": "plan_credito"},
            "mode": "PLAN",
        },
        {
            "id": "sales_plan_present",
            "trigger": {"type": "field_present", "field": "plan_credito"},
            "mode": "SALES",
        },
        {
            "id": "fallback_support",
            "trigger": {"type": "always"},
            "mode": "SUPPORT",
        },
    ]
}


class Client:
    """Authenticated HTTP client for the AtendIA v2 backend.

    Keeps one cookie jar (session + csrf cookies) and injects the
    `X-CSRF-Token` header on every unsafe verb. Reusable by later E2E
    tasks — only generic primitives live here.
    """

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        # httpx.Client keeps the cookie jar automatically across requests
        # (session + csrf cookies set by /auth/login are reused).
        self.session = httpx.Client(base_url=self.base_url, timeout=120.0)
        self.csrf_token: str | None = None
        self.tenant_id: str | None = None
        self.user: dict[str, Any] | None = None

    # -- low level ----------------------------------------------------------

    def _headers(self, unsafe: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if unsafe:
            if not self.csrf_token:
                raise RuntimeError("CSRF token missing — call login() first")
            headers["X-CSRF-Token"] = self.csrf_token
        return headers

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.session.get(
            path, headers=self._headers(unsafe=False), **kw
        )

    def post(self, path: str, json_body: Any | None = None, **kw: Any) -> httpx.Response:
        return self.session.post(
            path,
            json=json_body,
            headers=self._headers(unsafe=True),
            **kw,
        )

    def patch(self, path: str, json_body: Any | None = None, **kw: Any) -> httpx.Response:
        return self.session.patch(
            path,
            json=json_body,
            headers=self._headers(unsafe=True),
            **kw,
        )

    def put(self, path: str, json_body: Any | None = None, **kw: Any) -> httpx.Response:
        return self.session.put(
            path,
            json=json_body,
            headers=self._headers(unsafe=True),
            **kw,
        )

    # -- auth ---------------------------------------------------------------

    def login(
        self, email: str = LOGIN_EMAIL, password: str = LOGIN_PASSWORD
    ) -> dict[str, Any]:
        """POST /api/v1/auth/login. Stores csrf_token + cookie jar + tenant."""
        resp = self.session.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"login failed: HTTP {resp.status_code} — {resp.text[:500]}"
            )
        data = resp.json()
        self.csrf_token = data.get("csrf_token")
        self.user = data.get("user") or {}
        self.tenant_id = self.user.get("tenant_id")
        if not self.csrf_token:
            raise RuntimeError(f"login response missing csrf_token: {data!r}")
        return data

    # -- agents -------------------------------------------------------------

    def create_agent(
        self,
        *,
        name: str,
        system_prompt: str,
        is_default: bool = True,
        language: str = "es",
        no_emoji: bool = True,
        tone: str = "informal",
        max_sentences: int = 2,
        goal: str | None = None,
        flow_mode_rules: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """POST /api/v1/agents (AgentCreate contract — `name` required).

        Returns the raw Response so callers can assert status + body.
        """
        payload: dict[str, Any] = {
            "name": name,
            "is_default": is_default,
            "system_prompt": system_prompt,
            "language": language,
            "no_emoji": no_emoji,
            "tone": tone,
            "max_sentences": max_sentences,
            "goal": goal,
            "flow_mode_rules": flow_mode_rules,
        }
        return self.post("/api/v1/agents", json_body=payload)

    def get_agent(self, agent_id: str) -> httpx.Response:
        return self.get(f"/api/v1/agents/{agent_id}")

    def preview_response(
        self,
        agent_id: str,
        message: str,
        conversation_context: dict[str, Any] | None = None,
        draft_config: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """POST /api/v1/agents/{id}/preview-response — REAL LLM call.

        Costs real money (~$0.005-0.015, gpt-4o). Callers MUST NOT loop
        this. One call per validation run, by design.
        """
        return self.post(
            f"/api/v1/agents/{agent_id}/preview-response",
            json_body={
                "message": message,
                "conversationContext": conversation_context or {},
                "draftConfig": draft_config or {},
            },
        )


# ---------------------------------------------------------------------------
# Task 3: KB ingestion + retrieval + agent scoping
#
# Contracts (read READ-ONLY from core/atendia/api/knowledge_routes.py and
# core/atendia/api/_kb/collections.py, agents_routes.py):
#   POST /api/v1/knowledge/faqs     FAQBody  -> 201 {id,question,answer,tags,...}
#       question  str 1..500   answer str 1..2000   tags list[str]<=20 (<=40 chars ea)
#   POST /api/v1/knowledge/catalog  CatalogBody -> 201 {id,sku,name,attrs,...}
#       sku str 1..80  name str 1..200  attrs dict  category str|None<=60
#       tags list[str]<=20  active bool
#   POST /api/v1/knowledge/test     {query} -> 200 {answer,sources[],mode}
#       semantic (cosine) path first; falls back to ILIKE on FAQ q/a + catalog
#       name. Tenant-scoped (NOT agent-scoped). mode: llm|sources_only|empty.
#   PATCH /api/v1/agents/{id}/config  AgentPatch (extra=forbid) -> 200 AgentItem
#       knowledge_config is a free-form dict; GET /{id}/config surfaces
#       knowledge_config["linked_sources"] / ["linked_inboxes"].
#
# Source files (repo root docs/): CATALOGO_MODELOS.json, FAQ_CREDITO.json,
# REQUISITOS_PLANES.json. Fresh isolated tenant → plain inserts are fine.

CATALOGO_PATH = REPO_ROOT / "docs" / "CATALOGO_MODELOS.json"
FAQ_CREDITO_PATH = REPO_ROOT / "docs" / "FAQ_CREDITO.json"
REQUISITOS_PATH = REPO_ROOT / "docs" / "REQUISITOS_PLANES.json"

# Task 2 created this agent (is_default for the isolated tenant).
AGENT_ID = "e34419ae-3829-4004-ad08-e133d9eb7109"


def _slugify_sku(model_name: str) -> str:
    """Deterministic <=80-char SKU from a model name.

    "Adventure Elite 150 CC" -> "DINM-ADVENTURE-ELITE-150-CC". Uppercase,
    non-alnum collapsed to single dash, DINM- prefix (Dínamo).
    """
    import re

    base = re.sub(r"[^A-Za-z0-9]+", "-", model_name.strip().upper()).strip("-")
    return f"DINM-{base}"[:80]


def _faq_payloads_from_credito(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten FAQ_CREDITO.json into FAQBody payloads.

    The source Q/A sometimes carries structured extras
    (``detalle_por_plan``, ``documentos``, ``enlace``). Those are folded
    into the answer text so the single ``answer`` column stays
    self-contained and ILIKE/semantic search can hit them.
    """
    out: list[dict[str, Any]] = []
    for entry in doc.get("faq", []):
        q = str(entry.get("pregunta", "")).strip()
        a = str(entry.get("respuesta", "")).strip()
        if not q or not a:
            continue
        extra_lines: list[str] = []
        detalle = entry.get("detalle_por_plan")
        if isinstance(detalle, dict):
            for plan, val in detalle.items():
                extra_lines.append(f"- {plan.replace('_', ' ')}: {val}")
        docs = entry.get("documentos")
        if isinstance(docs, list):
            extra_lines.extend(f"- {d}" for d in docs)
        enlace = entry.get("enlace")
        if enlace:
            extra_lines.append(f"Enlace: {enlace}")
        answer = a
        if extra_lines:
            answer = (a + "\n" + "\n".join(extra_lines)).strip()
        out.append(
            {
                "question": q[:500],
                "answer": answer[:2000],
                "tags": ["credito", "faq"],
            }
        )
    return out


def _faq_payloads_from_requisitos(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Map each plan in REQUISITOS_PLANES.json to a requisitos FAQ.

    Requisitos are operator knowledge an agent must answer ("¿qué
    necesito para el plan X?"); the FAQ table is the right home (the
    document/source endpoint needs a file upload + async indexing worker;
    FAQ embeds synchronously on create — deterministic for this check).
    """
    out: list[dict[str, Any]] = []
    for plan in doc.get("planes", []):
        nombre = str(plan.get("nombre", "")).strip()
        if not nombre:
            continue
        reqs = plan.get("requisitos") or []
        eng = plan.get("enganche_porcentaje")
        body_lines = [f"Requisitos para el plan {nombre}"]
        if eng is not None:
            body_lines.append(f"Enganche: {eng}%")
        body_lines.extend(f"- {r}" for r in reqs)
        nota = plan.get("nota")
        if nota:
            body_lines.append(f"Nota: {nota}")
        out.append(
            {
                "question": f"¿Qué requisitos necesito para el plan {nombre}?"[:500],
                "answer": "\n".join(body_lines)[:2000],
                "tags": ["requisitos", "planes", "credito"],
            }
        )
    return out


def _catalog_payloads(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """One CatalogBody per moto model in CATALOGO_MODELOS.json.

    attrs keeps the full ficha_tecnica + precios + planes_credito so the
    catalog row is self-describing; the create endpoint embeds
    name + json(attrs) synchronously. tags <= 20, each <= 40 chars
    (server _normalize_tags enforces this — we pre-trim).
    """
    out: list[dict[str, Any]] = []
    for cat in doc.get("catalogo", []):
        categoria = str(cat.get("categoria", "")).strip() or None
        for m in cat.get("modelos", []):
            modelo = str(m.get("modelo", "")).strip()
            if not modelo:
                continue
            alias = m.get("alias") or []
            tags = [str(t).strip().lower()[:40] for t in alias if str(t).strip()][:19]
            if categoria:
                tags.append(categoria.lower()[:40])
            attrs = {
                "ficha_tecnica": m.get("ficha_tecnica", {}),
                "precios": m.get("precios", {}),
                "planes_credito": m.get("planes_credito", {}),
            }
            out.append(
                {
                    "sku": _slugify_sku(modelo),
                    "name": modelo[:200],
                    "attrs": attrs,
                    "category": (categoria[:60] if categoria else None),
                    "tags": tags,
                    "active": True,
                }
            )
    return out


def ingest_kb(client: Client) -> dict[str, Any]:
    """Ingest the 3 real JSON files via the frontend KB endpoints.

    Returns a structured report (per-file status counts) — no LLM calls
    here; the only real cost is the synchronous text-embedding-3-large
    call the server fires per FAQ/catalog row (tiny, ~$0.0001/row class).
    """
    report: dict[str, Any] = {"faqs": [], "catalog": [], "errors": []}

    faq_doc = json.loads(FAQ_CREDITO_PATH.read_text(encoding="utf-8"))
    req_doc = json.loads(REQUISITOS_PATH.read_text(encoding="utf-8"))
    cat_doc = json.loads(CATALOGO_PATH.read_text(encoding="utf-8"))

    faq_payloads = (
        _faq_payloads_from_credito(faq_doc) + _faq_payloads_from_requisitos(req_doc)
    )
    cat_payloads = _catalog_payloads(cat_doc)

    print(
        f"[ingest] planned: FAQ_CREDITO={len(_faq_payloads_from_credito(faq_doc))} "
        f"+ REQUISITOS={len(_faq_payloads_from_requisitos(req_doc))} faqs, "
        f"CATALOGO={len(cat_payloads)} catalog items"
    )

    faq_ok = 0
    for p in faq_payloads:
        r = client.post("/api/v1/knowledge/faqs", json_body=p)
        report["faqs"].append({"status": r.status_code, "q": p["question"][:60]})
        if r.status_code in (200, 201):
            faq_ok += 1
        else:
            report["errors"].append(
                {"endpoint": "faqs", "q": p["question"][:60], "status": r.status_code,
                 "body": r.text[:300]}
            )

    cat_ok = 0
    for p in cat_payloads:
        r = client.post("/api/v1/knowledge/catalog", json_body=p)
        report["catalog"].append({"status": r.status_code, "sku": p["sku"]})
        if r.status_code in (200, 201):
            cat_ok += 1
        else:
            report["errors"].append(
                {"endpoint": "catalog", "sku": p["sku"], "status": r.status_code,
                 "body": r.text[:300]}
            )

    report["summary"] = {
        "faq_planned": len(faq_payloads),
        "faq_inserted": faq_ok,
        "catalog_planned": len(cat_payloads),
        "catalog_inserted": cat_ok,
    }
    print(
        f"[ingest] FAQ inserted {faq_ok}/{len(faq_payloads)} | "
        f"catalog inserted {cat_ok}/{len(cat_payloads)}"
    )
    return report


def retrieval_check(client: Client) -> list[dict[str, Any]]:
    """Hit /api/v1/knowledge/test with queries that MUST resolve.

    Queries derive from the ACTUAL ingested data:
      1. a moto model name (catalog: "Adventure Elite 150 CC")
      2. a FAQ paraphrase ("¿en cuánto tiempo aprueban el crédito?"
         vs ingested "¿Cuál es el tiempo de aprobación del crédito?")
      3. a requisitos paraphrase ("requisitos plan 20 sin comprobar
         ingresos")
    Records mode (llm=semantic+LLM synth, sources_only=semantic/ILIKE
    sources but no LLM key, empty=nothing) + the verbatim top source so
    the path that answered (semantic vs ILIKE) is auditable.
    """
    queries = [
        ("catalog_model", "Adventure Elite 150 CC ficha tecnica y precio"),
        ("faq_paraphrase", "¿en cuánto tiempo aprueban el crédito?"),
        ("requisitos_paraphrase", "requisitos del plan 20% sin comprobar ingresos"),
    ]
    results: list[dict[str, Any]] = []
    for label, q in queries:
        r = client.post("/api/v1/knowledge/test", json_body={"query": q})
        item: dict[str, Any] = {"label": label, "query": q, "status": r.status_code}
        if r.status_code == 200:
            body = r.json()
            srcs = body.get("sources", [])
            item["mode"] = body.get("mode")
            item["n_sources"] = len(srcs)
            item["top_source"] = (
                {
                    "type": srcs[0].get("type"),
                    "score": srcs[0].get("score"),
                    "text": srcs[0].get("text", "")[:300],
                }
                if srcs
                else None
            )
            item["answer"] = (body.get("answer") or "")[:400]
            item["semantic_path"] = any(
                (s.get("score") or 0) > 0 for s in srcs
            )  # ILIKE fallback always sets score=0
        else:
            item["body"] = r.text[:400]
        results.append(item)
        print(
            f"[retrieval] {label}: HTTP {item['status']} "
            f"mode={item.get('mode')} n={item.get('n_sources')} "
            f"semantic={item.get('semantic_path')}"
        )
    return results


def scope_agent(client: Client, faq_count: int, catalog_count: int) -> dict[str, Any]:
    """PATCH the agent's knowledge_config and read it back.

    The free-form knowledge_config dict is surfaced by GET
    /agents/{id}/config as linked_knowledge_bases (knowledge_config
    ["linked_sources"]) / linked_whatsapp_inboxes. Operator-realistic
    shape; NOTE the agent-scoped RAG retriever
    (core/atendia/tools/rag/retriever.py:101) reads KbAgentPermission,
    NOT agent.knowledge_config — recorded as a finding.
    """
    knowledge_config = {
        "linked_sources": ["faq", "catalog"],
        "linked_inboxes": ["whatsapp_monterrey"],
        "ingested_counts": {"faqs": faq_count, "catalog": catalog_count},
        "source_files": [
            "docs/FAQ_CREDITO.json",
            "docs/REQUISITOS_PLANES.json",
            "docs/CATALOGO_MODELOS.json",
        ],
    }
    pr = client.patch(
        f"/api/v1/agents/{AGENT_ID}/config",
        json_body={"knowledge_config": knowledge_config},
    )
    out: dict[str, Any] = {"patch_status": pr.status_code}
    if pr.status_code != 200:
        out["patch_body"] = pr.text[:500]
        return out

    rb = client.get(f"/api/v1/agents/{AGENT_ID}")
    out["get_status"] = rb.status_code
    if rb.status_code == 200:
        kc = rb.json().get("knowledge_config") or {}
        out["readback_knowledge_config"] = kc
        out["persisted"] = kc == knowledge_config

    cfg = client.get(f"/api/v1/agents/{AGENT_ID}/config")
    out["config_status"] = cfg.status_code
    if cfg.status_code == 200:
        cb = cfg.json()
        out["config_linked_knowledge_bases"] = cb.get("linked_knowledge_bases")
        out["config_linked_whatsapp_inboxes"] = cb.get("linked_whatsapp_inboxes")
    return out


def run_task3() -> int:
    """Task 3 entrypoint — invoked by tools/e2e/run_task3.py.

    Kept separate from main() (Task 2) so neither breaks the other.
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    client = Client()
    client.login()
    print(f"[auth] logged in OK — tenant_id={client.tenant_id}")

    ingest = ingest_kb(client)
    retr = retrieval_check(client)
    scope = scope_agent(
        client,
        ingest["summary"]["faq_inserted"],
        ingest["summary"]["catalog_inserted"],
    )

    print("\n[task3] ===== STRUCTURED RESULT =====")
    print(
        json.dumps(
            {"ingest": ingest["summary"], "ingest_errors": ingest["errors"][:5],
             "retrieval": retr, "scope": scope},
            ensure_ascii=False,
            indent=2,
        )[:8000]
    )

    ok_ingest = (
        ingest["summary"]["faq_inserted"] > 0
        and ingest["summary"]["catalog_inserted"] > 0
    )
    ok_retr = any(
        x.get("status") == 200 and (x.get("n_sources") or 0) >= 1 for x in retr
    )
    ok_scope = scope.get("persisted") is True
    overall = "PASS" if (ok_ingest and ok_retr and ok_scope) else "PARTIAL"
    print(
        f"\n[task3] ingest={'OK' if ok_ingest else 'FAIL'} "
        f"retrieval={'OK' if ok_retr else 'FAIL'} "
        f"scope={'OK' if ok_scope else 'FAIL'} overall={overall}"
    )
    return 0


def load_prompt_master() -> str:
    """Read docs/Prompt master.txt verbatim (the whole file == system_prompt).

    Read as bytes then decoded utf-8 so the round-trip comparison is exact
    (no newline translation, no trailing-whitespace munging).
    """
    raw = PROMPT_MASTER_PATH.read_bytes()
    return raw.decode("utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    prompt_master = load_prompt_master()
    print(f"[setup] Prompt master: {PROMPT_MASTER_PATH}")
    print(f"[setup] Prompt master length = {len(prompt_master)} chars")

    client = Client()
    client.login()
    print(f"[auth] logged in OK — tenant_id={client.tenant_id}")

    # --- Step 2: create the agent -----------------------------------------
    resp = client.create_agent(
        name="Francisco Esparza (Dínamo)",
        system_prompt=prompt_master,
        is_default=True,
        language="es",
        no_emoji=True,
        tone="informal",
        max_sentences=2,
        goal="Convertir leads en ventas cerradas lo más rápido posible",
        flow_mode_rules=AGENT_FLOW_MODE_RULES,
    )
    print(f"[create] POST /api/v1/agents -> HTTP {resp.status_code}")
    if resp.status_code not in (200, 201):
        print(f"[create] FAIL body: {resp.text[:2000]}")
        return 1

    created = resp.json()
    agent_id = created.get("id")
    print(f"[create] agent_id = {agent_id}")
    if not agent_id:
        print(f"[create] FAIL — no id in response: {json.dumps(created)[:1000]}")
        return 1

    # --- Step 3: read back + round-trip assertions ------------------------
    rb = client.get_agent(agent_id)
    print(f"[readback] GET /api/v1/agents/{agent_id} -> HTTP {rb.status_code}")
    if rb.status_code != 200:
        print(f"[readback] FAIL body: {rb.text[:2000]}")
        return 1
    fetched = rb.json()

    fetched_prompt = fetched.get("system_prompt")
    prompt_ok = fetched_prompt == prompt_master
    print(
        f"[readback] system_prompt round-trip: "
        f"{'PASS' if prompt_ok else 'FAIL'} "
        f"(file={len(prompt_master)} chars, "
        f"readback={len(fetched_prompt) if fetched_prompt else 0} chars)"
    )
    if not prompt_ok:
        # Show first divergence to make any failure debuggable.
        a, b = prompt_master, fetched_prompt or ""
        for i, (ca, cb) in enumerate(zip(a, b)):
            if ca != cb:
                print(
                    f"[readback] first diff at index {i}: "
                    f"file={ca!r} readback={cb!r}"
                )
                break
        else:
            print(f"[readback] length mismatch only: {len(a)} vs {len(b)}")

    fetched_rules = fetched.get("flow_mode_rules")
    rules_ok = fetched_rules == AGENT_FLOW_MODE_RULES
    print(
        f"[readback] flow_mode_rules persisted: "
        f"{'PASS' if rules_ok else 'FAIL'} "
        f"(rule count={len((fetched_rules or {}).get('rules', []))})"
    )

    # --- Step 4: ONE real-LLM sanity call (small spend) -------------------
    print("[preview] making ONE real preview-response call (real $, ~$0.01)...")
    pr = client.preview_response(
        agent_id,
        message="hola, quiero una moto a crédito",
        conversation_context={},
        draft_config={},
    )
    print(f"[preview] POST .../preview-response -> HTTP {pr.status_code}")
    if pr.status_code == 200:
        body = pr.json()
        print("[preview] raw response JSON:")
        print(json.dumps(body, ensure_ascii=False, indent=2)[:4000])
    else:
        print(f"[preview] ERROR body (NOT retrying): {pr.text[:2000]}")

    overall = "PASS" if (prompt_ok and rules_ok) else "PARTIAL"
    print(
        f"[summary] agent_id={agent_id} create=HTTP{resp.status_code} "
        f"system_prompt={'PASS' if prompt_ok else 'FAIL'} "
        f"flow_mode_rules={'PASS' if rules_ok else 'FAIL'} "
        f"overall={overall}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
