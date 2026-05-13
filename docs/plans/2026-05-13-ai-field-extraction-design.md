# Extracción IA → campos del panel — diseño

**Fecha:** 2026-05-13
**Branch:** `claude/beautiful-mirzakhani-55368f`
**Autor:** Claude + zpiritech369@gmail.com

Cablear el output del NLU (que ya extrae entidades con confidence en
cada turno) al `customer.attrs` del contacto: auto-aplicar cuando
confidence ≥ 0.85 sobre campos vacíos, crear sugerencias pendientes
para revisión humana cuando el confidence es medio o cuando habría
overwrite, y UI para que el operador acepte/rechace.

## Estado actual verificado

- `core/atendia/runner/conversation_runner.py:355-371` extrae
  `nlu.entities: dict[str, ExtractedField]` por turno y las guarda en
  `conversation_state.extracted_data` JSONB. `ExtractedField{value,
  confidence, source_turn}`.
- `customer.last_extracted_data` (vista en `customers_routes.py:1076-1082`)
  se deriva al vuelo desde la conversación más reciente — **no es
  columna persistente**.
- `customer.attrs` JSONB se escribe sólo por `PATCH /customers/:id`
  (manual). El sprint anterior agregó UI editable + `useCustomerAttrs`
  hook con read-modify-write.
- `ContactDetailGridSection.pickValue()` ya lee de
  `[conversation.extracted_data, customer.last_extracted_data,
  customer.attrs]` con esa prioridad. Las 5 cards canónicas (valor
  estimado, tipo/plan crédito, producto, ubicación) ya muestran lo
  que NLU detectó — pero sólo en sesión, sin persistir, sin auditoría
  y sin permitir al operador confirmar o corregir.

**El gap:** no hay persistencia a `customer.attrs` desde NLU, ni rango
medio de sugerencias, ni UI para gestionarlas.

## Decisiones de diseño

### Mapping entity → attr (hardcoded v1)

`core/atendia/runner/field_extraction_mapping.py`:

```python
ENTITY_TO_ATTR: dict[str, str] = {
    "brand": "marca",
    "model": "modelo_interes",
    "modelo_interes": "modelo_interes",
    "plan": "plan_credito",
    "credit_plan": "plan_credito",
    "plan_credito": "plan_credito",
    "credit_type": "tipo_credito",
    "income_type": "tipo_credito",
    "tipo_credito": "tipo_credito",
    "city": "city",
    "ciudad": "city",
    "estimated_value": "estimated_value",
    "valor_estimado": "estimated_value",
    "labor_seniority": "antiguedad_laboral_meses",
    "antiguedad_laboral_meses": "antiguedad_laboral_meses",
}

CONFIDENCE_AUTO_THRESHOLD = 0.85
CONFIDENCE_SUGGESTION_MIN = 0.60
```

Per-tenant mapping queda fuera de v1 (configurable es Phase 3e).

### Reglas de overwrite

| Estado actual `attrs[k]` | confidence | Resultado |
|---|---|---|
| Vacío/null | ≥ 0.85 | **Overwrite directo** |
| Vacío/null | 0.60–0.84 | **Suggestion** pending |
| Vacío/null | < 0.60 | **Log only** (no DB write) |
| Existe = nuevo valor | cualquiera | **No-op** |
| Existe ≠ nuevo valor | cualquier | **Suggestion** (nunca sobrescribir sin OK humano) |

Razón clave: el operador nunca debe ver un campo cambiar sin haberlo
aprobado. Aún con confidence alta, si ya había valor distinto, vamos
a sugerencia.

### Nueva tabla `field_suggestions`

```sql
CREATE TABLE field_suggestions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id   UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  turn_number   INTEGER,
  key           TEXT NOT NULL,
  suggested_value TEXT NOT NULL,
  confidence    NUMERIC(4,3) NOT NULL,
  evidence_text TEXT,
  status        TEXT NOT NULL DEFAULT 'pending',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at    TIMESTAMPTZ,
  decided_by_user_id UUID REFERENCES tenant_users(id) ON DELETE SET NULL
);

CREATE INDEX ix_field_suggestions_tenant_customer_status
  ON field_suggestions (tenant_id, customer_id, status);

ALTER TABLE field_suggestions
  ADD CONSTRAINT ck_field_suggestions_status
  CHECK (status IN ('pending', 'accepted', 'rejected'));
```

### Cableado en el runner

En `conversation_runner.py` justo después de:

```python
for k, field in nlu.entities.items():
    state_obj.extracted_data[k] = field
```

llamar a una nueva función `apply_extractions_to_customer(...)` que:
1. Carga `customer.attrs`.
2. Por cada entity, aplica las reglas de overwrite arriba.
3. Hace los `INSERT field_suggestions` y/o `UPDATE customers SET attrs`
   en el mismo turn-commit.

Una función pura `decide_action(entity_key, entity_value, confidence,
current_attr_value)` que devuelve uno de `{"auto", "suggest", "skip",
"noop"}` permite TDD limpio.

### Endpoints

| Método | Path | Quién | Qué |
|---|---|---|---|
| GET | `/api/v1/customers/:cid/field-suggestions?status=pending` | operator+ | Lista |
| POST | `/api/v1/field-suggestions/:sid/accept` | operator+ | Mueve a `customer.attrs[k]`, status=accepted |
| POST | `/api/v1/field-suggestions/:sid/reject` | operator+ | status=rejected, sin tocar attrs |

Sin nuevo router separado — agregar al `customers_routes.py` para
mantener la ruta tenant-scoped consistente.

### Frontend

```
src/features/conversations/
  api.ts                                  # agregar fieldSuggestionsApi
  hooks/useFieldSuggestions.ts           # nuevo
  components/
    FieldSuggestionsPanel.tsx            # banner arriba del grid
```

Render en `ContactPanel` después del Identity y antes del
`ContactDetailGridSection`:

```
[Identity]
[QuickActions]
[Intelligence score]
[FieldSuggestionsPanel]   ← nuevo
[ContactDetailGridSection]
...
```

`FieldSuggestionsPanel` muestra:
- Banner colapsable con el conteo de sugerencias pendientes.
- Por sugerencia: `📍 Plan de crédito · "10" · 92% conf. · "…quiero el plan del 10%…"` con botones Aceptar / Rechazar.

## YAGNI cuts explícitos

- Sin "edit before accept" — para v1, accept aplica el valor exacto.
  Después el operador puede pulsar el lápiz del card para corregir.
- Sin batch accept/reject — uno a uno.
- Sin auto-reject por antigüedad — quedan pendientes hasta que humano
  las atiende.
- Sin `provenance` per-attr (suggestion + timeline + turn_trace ya dan
  auditoría suficiente).
- Sin endpoint `/api/ai/extract-lead-fields` separado — extracción
  vive en el runner, no es servicio independiente.
- Sin mapping per-tenant (hardcoded en backend para v1).
- Sin notificación push al operador — verá el panel cuando entre.

## Criterios de éxito

- Sembrar una conversación + correr un turno con mensaje "Quiero la
  Dinamo R4 250 con plan del 10%" debe producir auto-apply de
  `modelo_interes="Dinamo R4 250"` y `plan_credito="10"` en
  `customer.attrs` (asumiendo confidence ≥ 0.85 desde NLU).
- Sembrar con menor confianza debe producir suggestion en estado
  `pending`.
- Operador con UI: `FieldSuggestionsPanel` renderiza N sugerencias;
  click Aceptar las aplica y desaparecen del panel.
- Backend tests: tabla de reglas + endpoints accept/reject + tenant
  scope.
- Frontend tests: hook + componente con accept/reject que dispara
  mutations.
- TSC + biome limpios.
- Branch mergeada a main + push.
