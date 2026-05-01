# AtendIA v2 — Fase 2: Transporte WhatsApp Cloud API — Plan de Implementación

> **Para Claude:** SUB-SKILL REQUERIDA: Usar `superpowers:executing-plans` para implementar este plan tarea por tarea.

**Goal:** Hacer que los mensajes de WhatsApp lleguen, salgan y se actualicen en tiempo real, contra Meta Cloud API directo (sin Baileys, sin BSPs). Webhook receiver con dedup, cola de outbound con retries y circuit breaker, status callbacks que actualizan `delivery_status`, y un canal WebSocket para que el panel vea todo en realtime. Sin IA todavía — un bot "echo" minimal valida el flujo end-to-end.

**Architecture:** Extiende el paquete Python `core/` de Fase 1 con 4 sub-paquetes nuevos: `channels/` (adapter Meta), `webhooks/` (FastAPI receiver), `queue/` (arq + Redis), `realtime/` (WebSocket + Pub/Sub). Cero código TypeScript — un solo stack, un CI, un deploy. Multi-tenant compartiendo una sola Meta App; cada tenant tiene su propio `phone_number_id` en `tenants.config` JSONB.

**Tech Stack:** Python 3.12 · FastAPI 0.115+ · SQLAlchemy 2.0 async · asyncpg · Pydantic v2 · `arq` (cola Redis async) · `respx` (mock httpx en tests) · WebSocket nativo de FastAPI · Redis Pub/Sub · `httpx` (cliente HTTP para Meta) · `hmac` (stdlib).

**Pre-requisitos del entorno:**
- Fase 1 completa (branch `feat/v2-nucleo-conversacional`, commit base `b13306d`).
- Postgres v2 + Redis v2 corriendo (`docker compose -f docker-compose.yml up -d`).
- 90 tests de Fase 1 verdes (`uv run pytest -v` desde `core/`).
- Para smoke test contra Meta real: cuenta Meta Business + WhatsApp Cloud API + número de teléfono verificado + permanent access token. **No bloqueante** para el plan — tests usan respx (mocks).

**Decisiones fijas:**
1. **Branch nuevo desde Fase 1:** `feat/v2-fase2-transporte-whatsapp` (worktree nuevo o sobre el actual, decisión del implementador en T1).
2. **Multi-tenant compartiendo Meta App:** un solo `META_APP_SECRET` y `META_ACCESS_TOKEN` global en env vars; `phone_number_id` y `verify_token` por tenant en `tenants.config` JSONB.
3. **Cola:** `arq` (Redis-backed, async-native). El worker corre en un proceso separado: `uv run arq atendia.queue.worker.WorkerSettings`.
4. **Sin migración SQL nueva en Fase 2.** Las tablas `messages`, `events`, `tenants.config` JSONB ya cubren todo. Si la encriptación de credenciales se necesita más adelante, va en Fase 6+.
5. **WebSocket auth:** JWT corto-plazo emitido por la API REST. Validación per-conexión, scope por tenant.

---

## Mapa de tareas

| Bloque | Tareas | Duración estimada |
|---|---|---|
| **A.** Setup + Channel adapter base | T1–T6 | 2 días |
| **B.** Meta Cloud API adapter (send + DTOs + HMAC) | T7–T10 | 2 días |
| **C.** Webhook receiver + dedup + parser | T11–T15 | 2 días |
| **D.** Cola outbound + worker + retries + breaker | T16–T20 | 2 días |
| **E.** Realtime: Redis Pub/Sub + WebSocket | T21–T24 | 2 días |
| **F.** Integración E2E + echo bot smoke | T25–T28 | 2 días |
| **G.** Cobertura + docs | T29–T30 | 0.5 día |
| **TOTAL** | **30 tareas** | **~12 días hábiles (2.5 semanas)** |

---

# Bloque A — Setup + Channel adapter base

## Task 1: Branch + worktree + dependencias

**Files:**
- Modify: `core/pyproject.toml` (agregar `arq`, `respx`, `pyjwt`)

**Step 1: Crear branch desde el actual `feat/v2-nucleo-conversacional`** (Fase 1 ya está sobre él):

Decisión: trabajar sobre el mismo worktree y branch de Fase 1, o crear un branch nuevo `feat/v2-fase2-transporte-whatsapp` desde `feat/v2-nucleo-conversacional`.

Recomendación: branch nuevo. Esto permite mergear Fase 1 a `main` independientemente de Fase 2.

```bash
cd .worktrees/v2-nucleo-conversacional
git checkout -b feat/v2-fase2-transporte-whatsapp
```

Si el implementador prefiere un worktree limpio:

```bash
git worktree add .worktrees/v2-fase2 -b feat/v2-fase2-transporte-whatsapp feat/v2-nucleo-conversacional
cd .worktrees/v2-fase2
```

**Step 2: Agregar dependencias**

```bash
cd core
uv add arq pyjwt
uv add --dev respx
```

Esto modifica `core/pyproject.toml` y `core/uv.lock`.

**Step 3: Smoke test**

```bash
cd core
uv run python -c "import arq, jwt, respx; print('deps OK')"
```

Expected: `deps OK`

**Step 4: Commit**

```bash
git add core/pyproject.toml core/uv.lock
git commit -m "chore(deps): add arq, pyjwt, respx for Phase 2"
```

---

## Task 2: Settings — variables de entorno Meta

**Files:**
- Modify: `core/atendia/config.py`
- Modify: `.env.example`
- Test: `core/tests/test_config_meta.py` (nuevo)

**Step 1: Test failing `core/tests/test_config_meta.py`**

```python
import pytest
from atendia.config import get_settings


def test_settings_includes_meta_credentials(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "test_secret")
    monkeypatch.setenv("ATENDIA_V2_META_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("ATENDIA_V2_META_API_VERSION", "v21.0")
    monkeypatch.setenv("ATENDIA_V2_META_BASE_URL", "https://graph.facebook.com")

    # bypass lru_cache
    get_settings.cache_clear()
    s = get_settings()
    assert s.meta_app_secret == "test_secret"
    assert s.meta_access_token == "test_token"
    assert s.meta_api_version == "v21.0"
    assert s.meta_base_url == "https://graph.facebook.com"


def test_settings_defaults_for_meta(monkeypatch):
    monkeypatch.delenv("ATENDIA_V2_META_APP_SECRET", raising=False)
    monkeypatch.delenv("ATENDIA_V2_META_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.meta_app_secret == ""  # empty default
    assert s.meta_access_token == ""
    assert s.meta_api_version == "v21.0"  # version default
    assert s.meta_base_url == "https://graph.facebook.com"
```

**Step 2: Run, expect FAIL** (Settings no tiene esos campos).

**Step 3: Modificar `core/atendia/config.py`**

Agregar a la clase `Settings` (después de `log_level`):

```python
    meta_app_secret: str = Field(default="")
    meta_access_token: str = Field(default="")
    meta_api_version: str = Field(default="v21.0")
    meta_base_url: str = Field(default="https://graph.facebook.com")
```

**Step 4: Modificar `.env.example`**

Agregar al final:

```
ATENDIA_V2_META_APP_SECRET=
ATENDIA_V2_META_ACCESS_TOKEN=
ATENDIA_V2_META_API_VERSION=v21.0
ATENDIA_V2_META_BASE_URL=https://graph.facebook.com
```

**Step 5: Run tests**

```bash
cd core && uv run pytest tests/test_config_meta.py -v
```

Expected: 2 passed.

**Step 6: Commit**

```bash
git add core/atendia/config.py .env.example core/tests/test_config_meta.py
git commit -m "feat(config): add Meta Cloud API env vars to Settings"
```

---

## Task 3: Layout de paquetes nuevos

**Files:**
- Create: `core/atendia/channels/__init__.py`
- Create: `core/atendia/webhooks/__init__.py`
- Create: `core/atendia/queue/__init__.py`
- Create: `core/atendia/realtime/__init__.py`
- Create: `core/tests/channels/__init__.py`
- Create: `core/tests/webhooks/__init__.py`
- Create: `core/tests/queue/__init__.py`
- Create: `core/tests/realtime/__init__.py`

**Step 1: Crear directorios y archivos vacíos**

```bash
mkdir -p core/atendia/{channels,webhooks,queue,realtime}
mkdir -p core/tests/{channels,webhooks,queue,realtime}
touch core/atendia/{channels,webhooks,queue,realtime}/__init__.py
touch core/tests/{channels,webhooks,queue,realtime}/__init__.py
```

**Step 2: Smoke test**

```bash
cd core && uv run python -c "from atendia import channels, webhooks, queue, realtime; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add core/atendia/channels core/atendia/webhooks core/atendia/queue core/atendia/realtime core/tests/channels core/tests/webhooks core/tests/queue core/tests/realtime
git commit -m "chore(v2): scaffold channels/, webhooks/, queue/, realtime/ packages"
```

---

## Task 4: `ChannelAdapter` ABC

**Files:**
- Create: `core/atendia/channels/base.py`
- Create: `core/tests/channels/test_base.py`

**Step 1: Failing test `core/tests/channels/test_base.py`**

```python
import pytest

from atendia.channels.base import (
    ChannelAdapter,
    DeliveryReceipt,
    OutboundMessage,
    InboundMessage,
)


def test_outbound_message_text_is_valid():
    msg = OutboundMessage(
        tenant_id="dinamomotos",
        to_phone_e164="+5215555550000",
        text="Hola",
        idempotency_key="abc-123",
    )
    assert msg.text == "Hola"
    assert msg.template is None


def test_outbound_message_template_is_valid():
    msg = OutboundMessage(
        tenant_id="dinamomotos",
        to_phone_e164="+5215555550000",
        template={"name": "lead_warm_v2", "language": "es_MX", "components": []},
        idempotency_key="def-456",
    )
    assert msg.template is not None
    assert msg.text is None


def test_outbound_message_requires_text_or_template():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        OutboundMessage(
            tenant_id="x",
            to_phone_e164="+1",
            idempotency_key="z",
        )


def test_channel_adapter_is_abstract():
    with pytest.raises(TypeError):
        ChannelAdapter()  # type: ignore[abstract]


def test_delivery_receipt_minimal():
    r = DeliveryReceipt(
        message_id="local-uuid-x",
        channel_message_id="wamid.HBgL...",
        status="sent",
    )
    assert r.status == "sent"
```

**Step 2: Run, expect FAIL** (`atendia.channels.base` no existe).

**Step 3: Implementar `core/atendia/channels/base.py`**

```python
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutboundMessage(BaseModel):
    """Channel-agnostic outbound message request."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    to_phone_e164: str
    text: str | None = None
    template: dict | None = None  # {name, language, components}
    idempotency_key: str
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_text_or_template(self) -> "OutboundMessage":
        if self.text is None and self.template is None:
            raise ValueError("OutboundMessage requires either `text` or `template`")
        if self.text is not None and self.template is not None:
            raise ValueError("OutboundMessage cannot have both `text` and `template`")
        return self


class InboundMessage(BaseModel):
    """Channel-agnostic inbound message (parsed from a webhook)."""

    tenant_id: str
    from_phone_e164: str
    channel_message_id: str
    text: str | None = None
    media_url: str | None = None
    received_at: str  # ISO8601
    metadata: dict = Field(default_factory=dict)


class DeliveryReceipt(BaseModel):
    """Receipt from the channel after sending or status callback."""

    message_id: str  # our internal UUID
    channel_message_id: str | None = None
    status: Literal["queued", "sent", "delivered", "read", "failed"]
    error: str | None = None


class ChannelAdapter(ABC):
    """Abstract channel adapter. Implementations: MetaCloudAPIAdapter (Phase 2)."""

    name: str

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> DeliveryReceipt: ...

    @abstractmethod
    def validate_signature(self, body: bytes, signature_header: str) -> bool: ...

    @abstractmethod
    def parse_webhook(self, payload: dict, tenant_id: str) -> list[InboundMessage]: ...

    @abstractmethod
    def parse_status_callback(self, payload: dict) -> list[DeliveryReceipt]: ...
```

**Step 4: Run, expect 5 passed**

```bash
cd core && uv run pytest tests/channels/test_base.py -v
```

**Step 5: Commit**

```bash
git add core/atendia/channels/base.py core/tests/channels/test_base.py
git commit -m "feat(channels): ChannelAdapter ABC + OutboundMessage/InboundMessage/DeliveryReceipt DTOs"
```

---

## Task 5: HMAC signing utility

**Files:**
- Create: `core/atendia/channels/meta_signing.py`
- Create: `core/tests/channels/test_meta_signing.py`

**Step 1: Test (TDD)**

```python
import hashlib
import hmac

import pytest

from atendia.channels.meta_signing import verify_meta_signature


SECRET = "test_app_secret"
BODY = b'{"object":"whatsapp_business_account","entry":[{"id":"123"}]}'
EXPECTED_SIG = "sha256=" + hmac.new(
    SECRET.encode("utf-8"), BODY, hashlib.sha256
).hexdigest()


def test_valid_signature_returns_true():
    assert verify_meta_signature(BODY, EXPECTED_SIG, SECRET) is True


def test_invalid_signature_returns_false():
    assert verify_meta_signature(BODY, "sha256=deadbeef", SECRET) is False


def test_missing_sha256_prefix_returns_false():
    raw = EXPECTED_SIG.removeprefix("sha256=")
    assert verify_meta_signature(BODY, raw, SECRET) is False


def test_empty_secret_returns_false():
    assert verify_meta_signature(BODY, EXPECTED_SIG, "") is False


def test_constant_time_comparison():
    """Smoke: not a real timing test, just ensures we use hmac.compare_digest."""
    import inspect
    from atendia.channels import meta_signing
    src = inspect.getsource(meta_signing)
    assert "compare_digest" in src
```

**Step 2: Run, FAIL.**

**Step 3: Implement `core/atendia/channels/meta_signing.py`**

```python
import hashlib
import hmac


def verify_meta_signature(body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify the X-Hub-Signature-256 header on a Meta webhook.

    The header has the format `sha256=<hex>`. We compute HMAC-SHA256 over
    the raw body using `app_secret` and compare in constant time.
    Returns False on any malformed input — never raises.
    """
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    received = signature_header.removeprefix("sha256=")
    expected = hmac.new(
        app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(received, expected)
```

**Step 4: Run, 5 passed.**

**Step 5: Commit**

```bash
git add core/atendia/channels/meta_signing.py core/tests/channels/test_meta_signing.py
git commit -m "feat(channels): HMAC-SHA256 webhook signature verification"
```

---

## Task 6: Tenant Meta config helper

**Files:**
- Create: `core/atendia/channels/tenant_config.py`
- Create: `core/tests/channels/test_tenant_config.py`

Helper that reads Meta-specific tenant settings from `tenants.config` JSONB. Stores `phone_number_id` and `verify_token`.

**Step 1: Test**

```python
import json

import pytest
from sqlalchemy import text

from atendia.channels.tenant_config import (
    MetaTenantConfig,
    MetaTenantConfigNotFoundError,
    load_meta_config,
)


@pytest.mark.asyncio
async def test_load_meta_config_returns_struct(db_session):
    config = {
        "meta": {
            "phone_number_id": "1234567890",
            "verify_token": "tenant_verify_secret_xyz",
        }
    }
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
        {"n": "test_t6_meta", "c": json.dumps(config)},
    )).scalar()
    await db_session.commit()

    result = await load_meta_config(db_session, tid)
    assert isinstance(result, MetaTenantConfig)
    assert result.phone_number_id == "1234567890"
    assert result.verify_token == "tenant_verify_secret_xyz"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_load_meta_config_raises_when_no_meta_section(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name, config) VALUES ('test_t6_no_meta', '{}'::jsonb) RETURNING id")
    )).scalar()
    await db_session.commit()

    with pytest.raises(MetaTenantConfigNotFoundError):
        await load_meta_config(db_session, tid)

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
```

Re-use `db_session` fixture — create `core/tests/channels/conftest.py` mirroring the one from `tests/state_machine/conftest.py`.

**Step 2: Run, expect FAIL.**

**Step 3: Implement `core/atendia/channels/tenant_config.py`**

```python
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import Tenant


class MetaTenantConfigNotFoundError(Exception):
    """Raised when a tenant has no `meta` section in its config JSONB."""


class MetaTenantConfig(BaseModel):
    phone_number_id: str
    verify_token: str


async def load_meta_config(session: AsyncSession, tenant_id: UUID) -> MetaTenantConfig:
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await session.execute(stmt)).scalar_one_or_none()
    if tenant is None:
        raise MetaTenantConfigNotFoundError(f"tenant not found: {tenant_id}")
    meta = (tenant.config or {}).get("meta")
    if not meta or "phone_number_id" not in meta or "verify_token" not in meta:
        raise MetaTenantConfigNotFoundError(
            f"tenant {tenant_id} has no `meta.phone_number_id` and `meta.verify_token`"
        )
    return MetaTenantConfig.model_validate(meta)
```

**Step 4: Tests pass. Commit.**

```bash
git add core/atendia/channels/tenant_config.py core/atendia/channels/conftest.py core/tests/channels/test_tenant_config.py core/tests/channels/conftest.py
git commit -m "feat(channels): MetaTenantConfig loader from tenants.config JSONB"
```

---

# Bloque B — Meta Cloud API adapter

## Task 7: Meta Cloud API DTOs (webhook + outbound shape)

**Files:**
- Create: `core/atendia/channels/meta_dto.py`
- Create: `core/tests/channels/test_meta_dto.py`

These Pydantic models mirror Meta's webhook JSON shape and outbound payload shape. They live INSIDE the channel adapter (private to it). The canonical types (`InboundMessage`, `OutboundMessage`) are in `base.py`.

**Step 1: Test**

```python
import pytest
from pydantic import ValidationError

from atendia.channels.meta_dto import (
    MetaInboundWebhook,
    MetaInboundMessage,
    MetaStatusCallback,
)


def test_parses_real_meta_text_message_payload():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5215555000000",
                        "phone_number_id": "PHONE_NUMBER_ID",
                    },
                    "contacts": [{
                        "profile": {"name": "Juan"},
                        "wa_id": "5215555550001",
                    }],
                    "messages": [{
                        "from": "5215555550001",
                        "id": "wamid.HBgLNTIxNTU1NTU1NTAwMDEVAgASGBQzQUUz",
                        "timestamp": "1714579200",
                        "text": {"body": "hola"},
                        "type": "text",
                    }],
                },
            }],
        }],
    }
    parsed = MetaInboundWebhook.model_validate(payload)
    assert len(parsed.entry) == 1
    change = parsed.entry[0].changes[0]
    assert change.value.messages is not None
    assert change.value.messages[0].text.body == "hola"


def test_parses_status_callback():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5215555000000",
                        "phone_number_id": "PHONE_NUMBER_ID",
                    },
                    "statuses": [{
                        "id": "wamid.HBgL...",
                        "status": "delivered",
                        "timestamp": "1714579260",
                        "recipient_id": "5215555550001",
                    }],
                },
            }],
        }],
    }
    parsed = MetaInboundWebhook.model_validate(payload)
    statuses = parsed.entry[0].changes[0].value.statuses
    assert statuses is not None
    assert statuses[0].status == "delivered"
```

**Step 2: Run, FAIL.**

**Step 3: Implement `core/atendia/channels/meta_dto.py`**

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MetaText(BaseModel):
    body: str


class MetaInboundMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_: str
    id: str
    timestamp: str
    type: str
    text: MetaText | None = None

    def model_post_init(self, __context) -> None:
        # `from` is reserved in Python; allow alias via extra `from_` field.
        pass

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        if isinstance(obj, dict) and "from" in obj and "from_" not in obj:
            obj = {**obj, "from_": obj["from"]}
        return super().model_validate(obj, *args, **kwargs)


class MetaStatusCallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: Literal["sent", "delivered", "read", "failed"]
    timestamp: str
    recipient_id: str | None = None


class MetaWebhookValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messaging_product: str
    messages: list[MetaInboundMessage] | None = None
    statuses: list[MetaStatusCallback] | None = None


class MetaWebhookChange(BaseModel):
    field: str
    value: MetaWebhookValue


class MetaWebhookEntry(BaseModel):
    id: str
    changes: list[MetaWebhookChange]


class MetaInboundWebhook(BaseModel):
    object: str
    entry: list[MetaWebhookEntry]
```

**Step 4: Tests pass. Commit.**

```bash
git add core/atendia/channels/meta_dto.py core/tests/channels/test_meta_dto.py
git commit -m "feat(channels): Pydantic DTOs for Meta webhook payload"
```

---

## Task 8: `MetaCloudAPIAdapter.send` (text messages)

**Files:**
- Create: `core/atendia/channels/meta_cloud_api.py`
- Create: `core/tests/channels/test_meta_cloud_api_send.py`

`respx` mocks the HTTP call. No real Meta connection needed.

**Step 1: Test**

```python
import httpx
import pytest
import respx

from atendia.channels.base import OutboundMessage
from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter


@pytest.fixture
def adapter():
    return MetaCloudAPIAdapter(
        access_token="TEST_TOKEN",
        app_secret="TEST_SECRET",
        api_version="v21.0",
        base_url="https://graph.facebook.com",
    )


@pytest.mark.asyncio
@respx.mock
async def test_send_text_message_returns_delivery_receipt(adapter):
    route = respx.post(
        "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "+5215555550001", "wa_id": "5215555550001"}],
                "messages": [{"id": "wamid.HBgL_NEW_ID"}],
            },
        )
    )

    msg = OutboundMessage(
        tenant_id="t1",
        to_phone_e164="+5215555550001",
        text="Hola desde el bot",
        idempotency_key="key-001",
    )
    receipt = await adapter.send(msg, phone_number_id="PHONE_ID", message_id="local-uuid-1")
    assert route.called
    assert receipt.status == "sent"
    assert receipt.channel_message_id == "wamid.HBgL_NEW_ID"
    assert receipt.message_id == "local-uuid-1"

    # Verify request body shape
    sent = route.calls.last.request
    body = sent.read().decode()
    assert "Hola desde el bot" in body
    assert "5215555550001" in body
    assert sent.headers["Authorization"] == "Bearer TEST_TOKEN"


@pytest.mark.asyncio
@respx.mock
async def test_send_text_message_returns_failed_on_meta_error(adapter):
    respx.post(
        "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    ).mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": 131000, "message": "Recipient phone not on WhatsApp"}},
        )
    )

    msg = OutboundMessage(
        tenant_id="t1",
        to_phone_e164="+5215555550999",
        text="bad recipient",
        idempotency_key="key-002",
    )
    receipt = await adapter.send(msg, phone_number_id="PHONE_ID", message_id="local-uuid-2")
    assert receipt.status == "failed"
    assert "131000" in (receipt.error or "")
```

**Step 2: Run, FAIL.**

**Step 3: Implement `core/atendia/channels/meta_cloud_api.py`**

```python
import json

import httpx

from atendia.channels.base import (
    ChannelAdapter,
    DeliveryReceipt,
    InboundMessage,
    OutboundMessage,
)
from atendia.channels.meta_dto import MetaInboundWebhook
from atendia.channels.meta_signing import verify_meta_signature


class MetaCloudAPIAdapter(ChannelAdapter):
    name = "meta_cloud_api"

    def __init__(
        self,
        *,
        access_token: str,
        app_secret: str,
        api_version: str = "v21.0",
        base_url: str = "https://graph.facebook.com",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._access_token = access_token
        self._app_secret = app_secret
        self._api_version = api_version
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def send(
        self,
        msg: OutboundMessage,
        *,
        phone_number_id: str,
        message_id: str,
    ) -> DeliveryReceipt:
        url = f"{self._base_url}/{self._api_version}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        if msg.text is not None:
            body = {
                "messaging_product": "whatsapp",
                "to": msg.to_phone_e164.lstrip("+"),
                "type": "text",
                "text": {"body": msg.text},
            }
        elif msg.template is not None:
            body = {
                "messaging_product": "whatsapp",
                "to": msg.to_phone_e164.lstrip("+"),
                "type": "template",
                "template": msg.template,
            }
        else:  # pragma: no cover  -- model_validator prevents this
            raise ValueError("OutboundMessage has neither text nor template")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.HTTPError as e:
                return DeliveryReceipt(
                    message_id=message_id,
                    channel_message_id=None,
                    status="failed",
                    error=f"transport_error: {type(e).__name__}: {e}",
                )

        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
            except Exception:  # pragma: no cover
                err = {}
            return DeliveryReceipt(
                message_id=message_id,
                channel_message_id=None,
                status="failed",
                error=f"meta_error_{err.get('code', resp.status_code)}: {err.get('message', resp.text)}",
            )

        data = resp.json()
        wamid = (data.get("messages") or [{}])[0].get("id")
        return DeliveryReceipt(
            message_id=message_id,
            channel_message_id=wamid,
            status="sent" if wamid else "failed",
            error=None if wamid else "no_message_id_in_response",
        )

    def validate_signature(self, body: bytes, signature_header: str) -> bool:
        return verify_meta_signature(body, signature_header, self._app_secret)

    def parse_webhook(self, payload: dict, tenant_id: str) -> list[InboundMessage]:
        # Implemented in T9.
        raise NotImplementedError

    def parse_status_callback(self, payload: dict) -> list[DeliveryReceipt]:
        # Implemented in T10.
        raise NotImplementedError
```

**Step 4: Tests pass.**

```bash
cd core && uv run pytest tests/channels/test_meta_cloud_api_send.py -v
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add core/atendia/channels/meta_cloud_api.py core/tests/channels/test_meta_cloud_api_send.py
git commit -m "feat(channels): MetaCloudAPIAdapter.send for text + template (mocked tests)"
```

---

## Task 9: `MetaCloudAPIAdapter.parse_webhook` — webhook → InboundMessage

**Files:**
- Modify: `core/atendia/channels/meta_cloud_api.py` (implement `parse_webhook`)
- Create: `core/tests/channels/test_meta_cloud_api_parse_webhook.py`

**Step 1: Test**

```python
import pytest

from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter


@pytest.fixture
def adapter():
    return MetaCloudAPIAdapter(
        access_token="x", app_secret="y",
        api_version="v21.0", base_url="https://graph.facebook.com",
    )


def test_parse_webhook_extracts_text_messages(adapter):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5215555000000",
                        "phone_number_id": "PHONE_NUMBER_ID",
                    },
                    "messages": [{
                        "from": "5215555550001",
                        "id": "wamid.HBgL_X",
                        "timestamp": "1714579200",
                        "text": {"body": "hola"},
                        "type": "text",
                    }],
                },
            }],
        }],
    }
    messages = adapter.parse_webhook(payload, tenant_id="dinamomotos")
    assert len(messages) == 1
    m = messages[0]
    assert m.tenant_id == "dinamomotos"
    assert m.from_phone_e164 == "+5215555550001"
    assert m.channel_message_id == "wamid.HBgL_X"
    assert m.text == "hola"


def test_parse_webhook_returns_empty_for_status_only_payload(adapter):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "x", "phone_number_id": "y"},
                    "statuses": [{"id": "wamid.x", "status": "delivered", "timestamp": "1", "recipient_id": "5215"}],
                },
            }],
        }],
    }
    messages = adapter.parse_webhook(payload, tenant_id="dinamomotos")
    assert messages == []
```

**Step 2: Run, FAIL** (NotImplementedError).

**Step 3: Implement** — replace the `raise NotImplementedError` body of `parse_webhook` in `meta_cloud_api.py`:

```python
    def parse_webhook(self, payload: dict, tenant_id: str) -> list[InboundMessage]:
        try:
            wh = MetaInboundWebhook.model_validate(payload)
        except Exception:
            return []
        result: list[InboundMessage] = []
        for entry in wh.entry:
            for change in entry.changes:
                msgs = change.value.messages or []
                for m in msgs:
                    text = m.text.body if m.text else None
                    result.append(InboundMessage(
                        tenant_id=tenant_id,
                        from_phone_e164=f"+{m.from_}",
                        channel_message_id=m.id,
                        text=text,
                        received_at=m.timestamp,
                    ))
        return result
```

**Step 4: Tests pass.**

**Step 5: Commit**

```bash
git add core/atendia/channels/meta_cloud_api.py core/tests/channels/test_meta_cloud_api_parse_webhook.py
git commit -m "feat(channels): parse_webhook extracts InboundMessage list from Meta payload"
```

---

## Task 10: `MetaCloudAPIAdapter.parse_status_callback`

Similar pattern. **Step 1: Test**:

```python
def test_parse_status_callback_extracts_receipts(adapter):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "x", "phone_number_id": "y"},
                    "statuses": [
                        {"id": "wamid.X", "status": "delivered", "timestamp": "1", "recipient_id": "5215"},
                        {"id": "wamid.Y", "status": "read", "timestamp": "2", "recipient_id": "5215"},
                    ],
                },
            }],
        }],
    }
    receipts = adapter.parse_status_callback(payload)
    assert len(receipts) == 2
    assert receipts[0].channel_message_id == "wamid.X"
    assert receipts[0].status == "delivered"
    assert receipts[1].status == "read"
```

**Step 2: FAIL.**

**Step 3: Implement** in `meta_cloud_api.py`:

```python
    def parse_status_callback(self, payload: dict) -> list[DeliveryReceipt]:
        try:
            wh = MetaInboundWebhook.model_validate(payload)
        except Exception:
            return []
        result: list[DeliveryReceipt] = []
        for entry in wh.entry:
            for change in entry.changes:
                statuses = change.value.statuses or []
                for s in statuses:
                    result.append(DeliveryReceipt(
                        message_id="",  # filled by webhook receiver from messages table lookup
                        channel_message_id=s.id,
                        status=s.status,  # type: ignore[arg-type]
                        error=None,
                    ))
        return result
```

**Step 4: Tests pass.**

**Step 5: Commit**

```bash
git add core/atendia/channels/meta_cloud_api.py core/tests/channels/test_meta_cloud_api_parse_webhook.py
git commit -m "feat(channels): parse_status_callback extracts DeliveryReceipts"
```

---

# Bloque C — Webhook receiver

## Task 11: Webhook deduplication via Redis SET NX

**Files:**
- Create: `core/atendia/webhooks/deduplication.py`
- Create: `core/tests/webhooks/test_deduplication.py`

**Step 1: Test**

```python
import pytest
from redis.asyncio import Redis

from atendia.config import get_settings
from atendia.webhooks.deduplication import is_duplicate, DEDUP_TTL_SECONDS


@pytest.fixture
async def redis_client():
    client = Redis.from_url(get_settings().redis_url)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_first_call_is_not_duplicate(redis_client):
    await redis_client.delete("dedup:test_t11_a")
    assert await is_duplicate(redis_client, "test_t11_a") is False


@pytest.mark.asyncio
async def test_second_call_is_duplicate(redis_client):
    await redis_client.delete("dedup:test_t11_b")
    assert await is_duplicate(redis_client, "test_t11_b") is False
    assert await is_duplicate(redis_client, "test_t11_b") is True


@pytest.mark.asyncio
async def test_ttl_is_set(redis_client):
    await redis_client.delete("dedup:test_t11_c")
    await is_duplicate(redis_client, "test_t11_c")
    ttl = await redis_client.ttl("dedup:test_t11_c")
    assert 0 < ttl <= DEDUP_TTL_SECONDS
```

Create `core/tests/webhooks/conftest.py` with the standard `db_session` fixture.

**Step 2: Run, FAIL.**

**Step 3: Implement `core/atendia/webhooks/deduplication.py`**

```python
from redis.asyncio import Redis

DEDUP_TTL_SECONDS = 24 * 3600  # 24h matches Meta's deduplication recommendation


async def is_duplicate(redis_client: Redis, message_id: str) -> bool:
    """Returns True if `message_id` was seen before (in the last 24h).

    Uses Redis SET NX with TTL: the first call inserts and returns False; subsequent
    calls within TTL find the key and return True.
    """
    key = f"dedup:{message_id}"
    inserted = await redis_client.set(key, "1", ex=DEDUP_TTL_SECONDS, nx=True)
    return inserted is None or inserted is False
```

**Step 4: Tests pass.**

**Step 5: Commit**

```bash
git add core/atendia/webhooks/deduplication.py core/atendia/webhooks/conftest.py core/tests/webhooks/test_deduplication.py core/tests/webhooks/conftest.py
git commit -m "feat(webhooks): Redis-based deduplication with 24h TTL"
```

---

## Task 12: Webhook GET handler — verification challenge

Meta sends a GET to `/webhooks/meta/{tenant_id}?hub.mode=subscribe&hub.challenge=X&hub.verify_token=Y` when subscribing. We must echo back `hub.challenge` if `verify_token` matches the tenant's.

**Files:**
- Create: `core/atendia/webhooks/meta_routes.py`
- Modify: `core/atendia/main.py` (include router)
- Create: `core/tests/webhooks/test_meta_get_verification.py`

**Step 1: Test**

```python
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atendia.config import get_settings
from atendia.main import app


@pytest.fixture
def setup_tenant_with_meta_config():
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t12_verify",
                    "c": json.dumps({"meta": {"phone_number_id": "PID", "verify_token": "tenant_verify_xyz"}}),
                },
            )).scalar()
        await engine.dispose()
        return tid

    async def _cleanup(tid):
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await engine.dispose()

    tid = asyncio.run(_setup())
    yield tid
    asyncio.run(_cleanup(tid))


def test_meta_webhook_verify_returns_challenge_when_token_matches(setup_tenant_with_meta_config):
    tid = setup_tenant_with_meta_config
    with TestClient(app) as client:
        r = client.get(
            f"/webhooks/meta/{tid}",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "challenge_string_42",
                "hub.verify_token": "tenant_verify_xyz",
            },
        )
        assert r.status_code == 200
        assert r.text == "challenge_string_42"


def test_meta_webhook_verify_403_when_token_mismatch(setup_tenant_with_meta_config):
    tid = setup_tenant_with_meta_config
    with TestClient(app) as client:
        r = client.get(
            f"/webhooks/meta/{tid}",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "x",
                "hub.verify_token": "WRONG_TOKEN",
            },
        )
        assert r.status_code == 403
```

**Step 2: FAIL.**

**Step 3: Create `core/atendia/webhooks/meta_routes.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.channels.tenant_config import (
    MetaTenantConfigNotFoundError,
    load_meta_config,
)
from atendia.db.session import get_db_session

router = APIRouter()


@router.get("/webhooks/meta/{tenant_id}", response_class=PlainTextResponse)
async def verify_subscription(
    tenant_id: UUID,
    hub_mode: str = Query("", alias="hub.mode"),
    hub_challenge: str = Query("", alias="hub.challenge"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    session: AsyncSession = Depends(get_db_session),
) -> str:
    if hub_mode != "subscribe":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid hub.mode")
    try:
        cfg = await load_meta_config(session, tenant_id)
    except MetaTenantConfigNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant has no Meta config",
        )
    if hub_verify_token != cfg.verify_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="verify_token mismatch")
    return hub_challenge
```

**Step 4: Modify `core/atendia/main.py`** — add the router:

```python
# add import
from atendia.webhooks.meta_routes import router as meta_webhook_router

# in app setup, AFTER existing app.include_router(runner_router, ...)
app.include_router(meta_webhook_router)
```

**Step 5: Tests pass.**

**Step 6: Commit**

```bash
git add core/atendia/webhooks/meta_routes.py core/atendia/main.py core/tests/webhooks/test_meta_get_verification.py
git commit -m "feat(webhooks): GET /webhooks/meta/:tenant_id verifies subscription challenge"
```

---

## Task 13: Webhook POST handler — receive + dedup + persist

Receives the JSON payload, verifies HMAC signature, dedups, parses to `InboundMessage`, writes a row to `messages`. **Does NOT yet call ConversationRunner** — that's T22.

**Files:**
- Modify: `core/atendia/webhooks/meta_routes.py`
- Create: `core/tests/webhooks/test_meta_post_inbound.py`

**Step 1: Test** — uses TestClient, patches `MetaCloudAPIAdapter.validate_signature` to True for simplicity, asserts that a `messages` row is created with the right `direction='inbound'`, `text`, `channel_message_id`. Re-running the same payload twice asserts only ONE row exists (dedup).

(Test is long — implementer can write it from the pattern above; key assertions: 200 OK on first call, 200 OK on second call but message count stays at 1.)

**Step 2: Run, FAIL.**

**Step 3: Implement POST handler** in `meta_routes.py`. Add:

```python
import json as _json
from datetime import datetime, timezone
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import text

from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter
from atendia.config import get_settings
from atendia.webhooks.deduplication import is_duplicate


async def _get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


@router.post("/webhooks/meta/{tenant_id}")
async def receive_inbound(
    tenant_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")

    settings = get_settings()
    adapter = MetaCloudAPIAdapter(
        access_token=settings.meta_access_token,
        app_secret=settings.meta_app_secret,
        api_version=settings.meta_api_version,
        base_url=settings.meta_base_url,
    )
    if not adapter.validate_signature(body, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid signature")

    try:
        payload = _json.loads(body)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json")

    inbound_messages = adapter.parse_webhook(payload, tenant_id=str(tenant_id))
    statuses = adapter.parse_status_callback(payload)

    redis = await _get_redis()
    try:
        for m in inbound_messages:
            if await is_duplicate(redis, m.channel_message_id):
                continue
            await _persist_inbound(session, tenant_id, m)
        for r in statuses:
            await _update_status(session, r)
        await session.commit()
    finally:
        await redis.aclose()

    return {"status": "ok", "received": len(inbound_messages), "statuses": len(statuses)}


async def _persist_inbound(session, tenant_id, m) -> None:
    # Find or create customer + conversation, then insert message.
    cust_id = (await session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) "
             "ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164 "
             "RETURNING id"),
        {"t": tenant_id, "p": m.from_phone_e164},
    )).scalar()
    conv_id = (await session.execute(
        text("SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
             "ORDER BY last_activity_at DESC LIMIT 1"),
        {"t": tenant_id, "c": cust_id},
    )).scalar()
    if conv_id is None:
        conv_id = (await session.execute(
            text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
            {"t": tenant_id, "c": cust_id},
        )).scalar()
        await session.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv_id},
        )
    await session.execute(
        text("""INSERT INTO messages (conversation_id, tenant_id, direction, text,
                channel_message_id, sent_at, metadata_json)
                VALUES (:c, :t, 'inbound', :txt, :cmid, :ts\\:\\:timestamptz, '{}'::jsonb)"""),
        {
            "c": conv_id,
            "t": tenant_id,
            "txt": m.text or "",
            "cmid": m.channel_message_id,
            "ts": datetime.now(timezone.utc),
        },
    )


async def _update_status(session, r) -> None:
    await session.execute(
        text("UPDATE messages SET delivery_status = :s WHERE channel_message_id = :cm"),
        {"s": r.status, "cm": r.channel_message_id},
    )
```

**Step 4: Tests pass.**

**Step 5: Commit**

```bash
git add core/atendia/webhooks/meta_routes.py core/tests/webhooks/test_meta_post_inbound.py
git commit -m "feat(webhooks): POST /webhooks/meta/:tenant_id with HMAC + dedup + persist"
```

---

## Task 14: Status-only payload updates `delivery_status`

Test that a status-only payload updates `messages.delivery_status` for the message previously sent (we seed an outbound message in the test).

**Step 1: Test** in `core/tests/webhooks/test_meta_post_status.py`. Seed: tenant + Meta config + outbound message with `channel_message_id='wamid.test'` and `delivery_status='sent'`. POST status payload `{status: 'delivered', id: 'wamid.test'}` with valid HMAC. Assert: `delivery_status` updated to `'delivered'`.

**Step 2/3:** Already implemented in T13 via `_update_status`. Test just verifies it works in isolation.

**Step 4:** Commit.

```bash
git add core/tests/webhooks/test_meta_post_status.py
git commit -m "test(webhooks): assert status-only payload updates delivery_status"
```

---

## Task 15: Webhook handler emits `message_received` event

When inbound is persisted, emit an event row so realtime subscribers learn.

**Files:**
- Modify: `core/atendia/webhooks/meta_routes.py` (call `EventEmitter` after persisting inbound)
- Create: `core/tests/webhooks/test_meta_post_emits_event.py`

**Step 1: Test** — same setup as T13, assert one row in `events` with `type='message_received'` and `payload.channel_message_id` matches.

**Step 2/3:** Add to `_persist_inbound` (or after the loop in `receive_inbound`):

```python
from atendia.contracts.event import EventType
from atendia.state_machine.event_emitter import EventEmitter

# inside receive_inbound, AFTER _persist_inbound:
emitter = EventEmitter(session)
await emitter.emit(
    conversation_id=conv_id,
    tenant_id=tenant_id,
    event_type=EventType.MESSAGE_RECEIVED,
    payload={"channel_message_id": m.channel_message_id, "text": m.text},
)
```

(`_persist_inbound` returns `conv_id` — refactor needed.)

**Step 4:** Tests pass. **Step 5:** Commit `feat(webhooks): emit message_received event after persisting inbound`.

---

# Bloque D — Cola outbound + worker

## Task 16: Outbound job model + enqueue helper

**Files:**
- Create: `core/atendia/queue/jobs.py`
- Create: `core/atendia/queue/enqueue.py`
- Create: `core/tests/queue/test_enqueue.py`
- Create: `core/tests/queue/conftest.py` (db_session + redis_client fixtures)

**Step 1: Test** — call `enqueue_outbound(redis_client, OutboundMessage(...))`, then verify the job is in the Redis queue (`ARQ:queue:atendia:default` or similar — depends on arq config).

**Step 2: FAIL.**

**Step 3: `core/atendia/queue/jobs.py`**

```python
from atendia.channels.base import OutboundMessage  # re-export

__all__ = ["OutboundMessage"]
```

**Step 4: `core/atendia/queue/enqueue.py`**

```python
from arq.connections import ArqRedis

from atendia.channels.base import OutboundMessage


async def enqueue_outbound(redis: ArqRedis, msg: OutboundMessage) -> str:
    """Enqueue an outbound send job. Returns the arq job id."""
    job = await redis.enqueue_job(
        "send_outbound",  # name of the worker function (T17)
        msg.model_dump(mode="json"),
        _job_id=msg.idempotency_key,  # arq dedupes if same id
    )
    if job is None:
        return msg.idempotency_key  # already enqueued (idempotency hit)
    return job.job_id
```

**Step 5:** Tests pass. Commit.

```bash
git add core/atendia/queue/jobs.py core/atendia/queue/enqueue.py core/atendia/queue/conftest.py core/tests/queue/test_enqueue.py core/tests/queue/conftest.py
git commit -m "feat(queue): outbound job enqueue with idempotency key"
```

---

## Task 17: Worker function — calls adapter and persists

**Files:**
- Create: `core/atendia/queue/worker.py`
- Create: `core/tests/queue/test_worker.py`

The worker function `send_outbound(ctx, msg_dict)` is a coroutine arq calls. It loads tenant config, calls `MetaCloudAPIAdapter.send`, and updates the `messages` table.

**Step 1: Test** — mock the adapter via dependency injection or direct call to the function. Assert: messages row inserted with `direction='outbound'`, status set from receipt.

**Step 2: FAIL.**

**Step 3: Implement** — `core/atendia/queue/worker.py`:

```python
from datetime import datetime, timezone
from uuid import UUID, uuid4

from arq.connections import RedisSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.channels.base import OutboundMessage
from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter
from atendia.channels.tenant_config import load_meta_config
from atendia.config import get_settings


async def send_outbound(ctx: dict, msg_dict: dict) -> dict:
    msg = OutboundMessage.model_validate(msg_dict)
    settings = get_settings()
    engine = ctx.get("engine") or create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        cfg = await load_meta_config(session, UUID(msg.tenant_id))
        adapter = MetaCloudAPIAdapter(
            access_token=settings.meta_access_token,
            app_secret=settings.meta_app_secret,
            api_version=settings.meta_api_version,
            base_url=settings.meta_base_url,
        )
        message_id = str(uuid4())
        receipt = await adapter.send(
            msg, phone_number_id=cfg.phone_number_id, message_id=message_id,
        )
        # persist outbound row
        # find conversation by phone (similar to webhook receiver)
        cust_id = (await session.execute(
            text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) "
                 "ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164 "
                 "RETURNING id"),
            {"t": msg.tenant_id, "p": msg.to_phone_e164},
        )).scalar()
        conv_id = (await session.execute(
            text("SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
                 "ORDER BY last_activity_at DESC LIMIT 1"),
            {"t": msg.tenant_id, "c": cust_id},
        )).scalar()
        if conv_id is None:
            conv_id = (await session.execute(
                text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
                {"t": msg.tenant_id, "c": cust_id},
            )).scalar()
            await session.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await session.execute(
            text("""INSERT INTO messages (id, conversation_id, tenant_id, direction, text,
                    channel_message_id, delivery_status, sent_at)
                    VALUES (:id, :c, :t, 'outbound', :txt, :cmid, :st, :ts\\:\\:timestamptz)"""),
            {
                "id": message_id, "c": conv_id, "t": msg.tenant_id,
                "txt": msg.text or "",
                "cmid": receipt.channel_message_id,
                "st": receipt.status,
                "ts": datetime.now(timezone.utc),
            },
        )
        await session.commit()

    return {"message_id": message_id, "status": receipt.status}


class WorkerSettings:
    functions = [send_outbound]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    keep_result = 0  # we persist to DB; arq result store not needed
```

**Step 4:** Tests pass. **Step 5:** Commit.

```bash
git add core/atendia/queue/worker.py core/tests/queue/test_worker.py
git commit -m "feat(queue): worker function send_outbound + WorkerSettings"
```

---

## Task 18: Retry with exponential backoff

arq has `Retry(defer=Xs)` built in. Modify `send_outbound` to raise `Retry(defer=2 ** ctx["job_try"])` when receipt is `failed` AND the error indicates a transient cause (HTTP 5xx, transport_error). Cap retries at 4.

**Files:**
- Modify: `core/atendia/queue/worker.py`
- Create: `core/tests/queue/test_worker_retry.py`

**Step 1: Test** — call `send_outbound` with a mock where the first 3 calls fail with 503, the 4th succeeds. Assert the function retries (uses `arq.testing.RuntimeContext` or similar).

**Step 2/3:** Add retry logic:

```python
from arq.worker import Retry

# after `receipt = await adapter.send(...)`:
if receipt.status == "failed" and _is_transient(receipt.error):
    if ctx.get("job_try", 1) >= 4:
        # final failure, persist and give up
        ...
    else:
        raise Retry(defer=2 ** ctx.get("job_try", 1))


def _is_transient(err: str | None) -> bool:
    if not err:
        return False
    return "transport_error" in err or "meta_error_5" in err
```

**Step 4:** Tests pass. **Step 5:** Commit.

---

## Task 19: Circuit breaker

Redis-based: if Meta returns >= 10 failures in 60s, open circuit for 30s. Implementation: counter `breaker:meta:{tenant_id}` with TTL.

**Files:**
- Create: `core/atendia/queue/circuit_breaker.py`
- Create: `core/tests/queue/test_circuit_breaker.py`
- Modify: `core/atendia/queue/worker.py` (check breaker before send)

**Step 1-3:**

```python
# circuit_breaker.py
from redis.asyncio import Redis

THRESHOLD = 10
WINDOW_SECONDS = 60
OPEN_DURATION_SECONDS = 30


class CircuitOpenError(Exception):
    pass


async def record_failure(redis: Redis, tenant_id: str) -> None:
    key = f"breaker:fail:{tenant_id}"
    n = await redis.incr(key)
    if n == 1:
        await redis.expire(key, WINDOW_SECONDS)
    if n >= THRESHOLD:
        await redis.set(f"breaker:open:{tenant_id}", "1", ex=OPEN_DURATION_SECONDS)


async def record_success(redis: Redis, tenant_id: str) -> None:
    await redis.delete(f"breaker:fail:{tenant_id}")
    await redis.delete(f"breaker:open:{tenant_id}")


async def is_open(redis: Redis, tenant_id: str) -> bool:
    return bool(await redis.exists(f"breaker:open:{tenant_id}"))
```

**Step 4:** Tests pass. **Step 5:** Commit.

---

## Task 20: Worker integration with breaker

Modify `send_outbound` to check `is_open(...)` before send; raise `Retry(defer=OPEN_DURATION_SECONDS)` if open. On failure call `record_failure`; on success `record_success`.

Single tests + commit.

---

# Bloque E — Realtime: Redis Pub/Sub + WebSocket

## Task 21: Redis Pub/Sub publisher

**Files:**
- Create: `core/atendia/realtime/publisher.py`
- Create: `core/tests/realtime/test_publisher.py`

**Step 1-3:**

```python
# publisher.py
import json
from redis.asyncio import Redis


async def publish_event(redis: Redis, *, tenant_id: str, conversation_id: str, event: dict) -> None:
    channel = f"tenant:{tenant_id}:conversation:{conversation_id}"
    await redis.publish(channel, json.dumps(event))
```

**Step 4-5:** test → commit.

---

## Task 22: Hook publisher into webhook receiver and worker

Modify `receive_inbound` (T13) and `send_outbound` (T17) to publish events:
- Inbound: `{"type": "message_received", "data": {...}}` after persistence.
- Outbound: `{"type": "message_sent", "data": {...}}` after persistence.

Tests + commit.

---

## Task 23: WebSocket endpoint with JWT auth

**Files:**
- Create: `core/atendia/realtime/auth.py` (JWT helpers)
- Create: `core/atendia/realtime/ws_routes.py`
- Modify: `core/atendia/main.py` (include WS router)
- Tests for both

**Step 1-3:**

```python
# auth.py
from datetime import datetime, timedelta, timezone

import jwt

from atendia.config import get_settings


def issue_token(*, tenant_id: str, ttl_seconds: int = 3600) -> str:
    payload = {
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    }
    # WS auth secret is reused from app secret; in production, separate secret.
    secret = get_settings().meta_app_secret or "dev-only-fallback"
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str) -> str:
    secret = get_settings().meta_app_secret or "dev-only-fallback"
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    return payload["tenant_id"]
```

(Add a real WS_AUTH_SECRET env var in production; for Phase 2 dev, reuse meta_app_secret.)

```python
# ws_routes.py
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis

from atendia.config import get_settings
from atendia.realtime.auth import decode_token

router = APIRouter()


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_ws(websocket: WebSocket, conversation_id: str) -> None:
    token = websocket.query_params.get("token", "")
    try:
        tenant_id = decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    redis = Redis.from_url(get_settings().redis_url)
    pubsub = redis.pubsub()
    channel = f"tenant:{tenant_id}:conversation:{conversation_id}"
    await pubsub.subscribe(channel)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None:
                await websocket.send_text(msg["data"].decode("utf-8"))
            await asyncio.sleep(0)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis.aclose()
```

**Step 4:** Tests pass. **Step 5:** Commit.

---

## Task 24: WS test — connect, publish, receive

End-to-end test: subscribe via WS, publish to the channel directly with `redis.publish`, assert message received within 2 seconds.

Test + commit.

---

# Bloque F — Integración E2E

## Task 25: Wire webhook → ConversationRunner

When `receive_inbound` persists a message, also call `ConversationRunner.run_turn(...)` to trigger the state machine. The runner emits an outbound text via the queue (T26).

For Phase 2 (no LLM), a "canned NLU" is too rigid for production. Provide a SIMPLE rule-based fallback that classifies intent based on keywords (good enough for echo/smoke; LLM lands in Phase 3).

**Files:**
- Create: `core/atendia/runner/nlu_keywords.py` (simple keyword-based NLU)
- Modify: `core/atendia/webhooks/meta_routes.py`
- Create: `core/tests/integration/test_inbound_to_runner.py`

**Step 1-3:** keyword NLU implementation (matches "hola" → greeting, "precio/cuánto" → ask_price, etc.) + integration in webhook handler.

(Detailed code template provided in the running plan; implementer fills in.)

**Step 4-5:** Tests + commit.

---

## Task 26: Runner emits outbound to queue

After `ConversationRunner.run_turn` completes, if the orchestrator's decision implies an outbound (action like `greet`, `ask_field`, `quote`), build an `OutboundMessage` and enqueue it.

For Phase 2, the message text comes from a fixed template per action (no LLM Composer). Phase 3 replaces this with the real Composer.

**Files:**
- Create: `core/atendia/runner/outbound_dispatcher.py`
- Modify: webhook receiver to call dispatcher

**Step 1-5:** test → impl → commit.

---

## Task 27: Echo bot E2E test

Stand up the full stack in tests:
- Seed tenant + Meta config
- POST simulated inbound webhook
- Assert: message persisted, runner ran, outbound enqueued, worker processed (call directly), Meta API call made (mocked via respx), outbound persisted with status=sent.

This is THE Phase 2 keystone test. **Files:**
- Create: `core/tests/integration/test_e2e_echo_bot.py`

Test + commit.

---

## Task 28: Smoke test script for Phase 2

**Files:**
- Create: `core/scripts/smoke_test_phase2.py`

Manual script that:
1. Connects to Postgres + Redis + (mocked) Meta API
2. Simulates 3 inbound webhooks
3. Asserts 3 outbound messages were processed by the worker

Print summary, exit 0 on success.

Commit.

---

# Bloque G — Cobertura + docs

## Task 29: Coverage stays ≥ 85%

Run `uv run pytest --cov=atendia --cov-report=term-missing`. Fix any module that drops below 85%. Commit if any tests added.

## Task 30: README — Fase 2 sections

Update `core/README.md`:
- Add "Phase 2 status" section: webhook receiver works, outbound queue works, status callbacks update delivery, WebSocket realtime alive.
- Add "Running the worker": `uv run arq atendia.queue.worker.WorkerSettings`.
- Add "Connecting to WebSocket from a client": example with `wscat` or a small JS snippet.

Commit.

---

# Verificación final de Fase 2

```bash
cd core
uv run alembic downgrade base && uv run alembic upgrade head
uv run ruff check . && uv run ruff format --check .
uv run pytest --cov=atendia --cov-report=term-missing
uv run python scripts/smoke_test_phase2.py
```

**Criterios de salida de Fase 2:**

- [ ] Webhook GET (verification challenge) responde 200 con challenge correcto.
- [ ] Webhook POST con HMAC válida persiste mensaje inbound.
- [ ] Dedup por `channel_message_id` funciona.
- [ ] Status callbacks actualizan `delivery_status`.
- [ ] Cola de outbound procesa mensajes con retries exponenciales.
- [ ] Circuit breaker abre tras 10 fallos en 60s, cierra tras 30s.
- [ ] WebSocket `/ws/conversations/:id?token=...` autentica vía JWT, recibe eventos en realtime.
- [ ] E2E: inbound webhook → runner → outbound queue → Meta API mock → status update visible en WS.
- [ ] Cobertura ≥ 85% (gate activo).
- [ ] CI verde.

---

# Próximo paso de planeación

Cuando Fase 2 esté completa: **Fase 3 — Motor IA híbrido** (NLU extractor real con gpt-4o-mini, Composer real con gpt-4o, tools reales en lugar de stubs). El plan se generará con `superpowers:writing-plans`. Documento esperado: `docs/plans/YYYY-MM-DD-atendia-v2-fase3-motor-ia.md`.
