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

# Operator-realistic flow_mode_rules. NOTE (confirmed bug, recorded in
# FINDINGS): the runner reads flow routing ONLY from
# pipeline.flow_mode_rules (conversation_runner.py:766; comment :749).
# agent.flow_mode_rules is stored + returned by the API but never read by
# the runner/router — so setting it here is operator-realistic but DEAD for
# routing. The real routing rules go into the pipeline (a later task).
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
