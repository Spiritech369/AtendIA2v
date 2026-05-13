# Datos de contacto editables — diseño

**Fecha:** 2026-05-13
**Branch sugerido:** `feat/editable-contact-panel`
**Autor:** Claude + zpiritech369@gmail.com

Hacer que las 10 cards de la sección "Datos de contacto" en `ContactPanel`
(la del screenshot que mostró el usuario) sean editables, addable y
eliminables, alineado al stack actual (FastAPI + SQLAlchemy + React +
shadcn), sin crear infra paralela (NestJS/Prisma) ni duplicar funcionalidad
que ya existe (notas, audit log, custom fields tenant-wide, timeline,
documentos, next best action — todos ya implementados en módulos
separados).

## Estado verificado del código (2026-05-13)

- `frontend/src/features/conversations/components/ContactPanel.tsx:616-708`
  contiene `ContactDetailGridSection`. Las 10 cards son `<DetailRow>`
  read-only. Los valores los obtiene con `pickValue()` sobre
  `[conversation.extracted_data, customer.last_extracted_data,
  customer.attrs]`.
- `core/atendia/api/customers_routes.py:1431-1470` `PATCH /:id` acepta
  `attrs: dict | None` y al recibirlo **reemplaza** el dict completo
  (`setattr(customer, k, v)`), por lo que actualizar una sola clave
  requiere read-modify-write. Tras el patch:
  - Inserta un `CustomerTimelineEvent` con `event_type='field_changed'`.
  - Emite admin event `customer.updated`.
- `core/atendia/api/conversations_routes.py` ya expone
  `PATCH /:cid` con `current_stage`, `assigned_user_id`,
  `assigned_agent_id` (usado por `ConversationSummarySection`).
- `frontend/src/features/conversations/components/ContactPanel.tsx:1101`
  tiene `CustomFieldsSection` con CRUD tenant-wide ya funcional contra
  `/api/v1/customer-fields/definitions` y `/api/v1/customers/:id/field-values`.
  Lo dejamos como está — sirve para campos schema-driven que el
  tenant_admin define.

**El gap:** ad-hoc per-customer attrs no tienen UI. Las 10 cards no se
pueden editar.

## Approaches considerados

### A — Híbrido (recomendado)

Cada card sabe a qué endpoint pertenece:

- 4 fields estructurales → endpoints PATCH existentes.
- 5 fields free-form → `customer.attrs` JSONB con merge cliente.
- Teléfono → read-only (identity).
- "Agregar campo" → nuevo par `key:value` en `customer.attrs`.
- "Eliminar" → quita la key de `attrs` o setea null en el structural.

**Pros**: cero migraciones, reusa toda la infra existente, no rompe el
pipeline kanban / dashboard / exportaciones que dependen de
`customer.stage`, `conversation.assigned_user_id`, etc.
**Contras**: el frontend acarrea un map field→endpoint (manejable, 10
entradas).

### B — Migrar todo a `customer_field_definitions` tenant-wide

Las 10 cards se vuelven custom fields definidos por defecto al crear
tenant. Edits via `/customers/:id/field-values`.

**Pros**: modelo de datos unificado.
**Contras**: duplica con first-class columns que YA usa el sistema
(pipeline kanban, dashboard, analytics, exports). Requiere sincronización
bidireccional o renunciar a esas dependencias. Demasiado costo.

### C — Nueva columna `customer.contact_data` JSONB

Migración + columna nueva, todos los fields ahí. Requiere igual
sincronización con first-class y duplica el propósito de `attrs`.
Descartado por overhead vs beneficio.

**Decisión: A.**

## Mapa field → endpoint

| Card en UI | Origen del valor | Editar | Eliminar/Limpiar |
|---|---|---|---|
| Etapa | `conversation.current_stage` | `PATCH /conversations/:cid {current_stage}` | n/a (no nullable) |
| Fuente | `customer.source` | `PATCH /customers/:id {source}` | `PATCH ... {source: null}` |
| Asesor | `conversation.assigned_user_id` o `assigned_agent_id` | `PATCH /conversations/:cid` | `PATCH ... {assigned_user_id: null}` |
| Valor estimado | `customer.attrs.estimated_value` | `PATCH /customers/:id {attrs: merged}` | merge sin la key |
| Tipo de crédito | `customer.attrs.tipo_credito` | idem | idem |
| Plan de crédito | `customer.attrs.plan_credito` | idem | idem |
| Producto | `customer.attrs.modelo_interes` (con fallback `producto.modelo`) | idem | idem |
| Ubicación | `customer.attrs.city` | idem | idem |
| Teléfono | `customer.phone_e164` | read-only | read-only |
| Email | `customer.email` | `PATCH /customers/:id {email}` | `PATCH ... {email: null}` |

## Componentes nuevos

### `frontend/src/features/conversations/hooks/useCustomerAttrs.ts`

```ts
export function useCustomerAttrs(customerId: string) {
  const qc = useQueryClient();
  const customer = useCustomerDetail(customerId);

  const patchAttr = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const current = (customer.data?.attrs ?? {}) as Record<string, unknown>;
      const next = { ...current, [key]: value };
      return customersApi.patch(customerId, { attrs: next });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customer", customerId] }),
  });

  const deleteAttr = useMutation({
    mutationFn: async (key: string) => {
      const current = (customer.data?.attrs ?? {}) as Record<string, unknown>;
      const { [key]: _drop, ...rest } = current;
      return customersApi.patch(customerId, { attrs: rest });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customer", customerId] }),
  });

  return { patchAttr, deleteAttr };
}
```

### `EditableDetailRow.tsx`

Reemplaza al `DetailRow` actual. Props:

```ts
interface Props {
  label: string;
  value: string | null | undefined;
  icon?: React.ComponentType<{ className?: string }>;
  editable: boolean;
  deletable: boolean;
  inputType?: "text" | "number" | "email" | "select";
  options?: Array<{ value: string; label: string }>; // si select
  onSave: (newValue: string | null) => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
  placeholder?: string;
  validate?: (raw: string) => string | null; // devuelve error string o null
}
```

Comportamiento:
- Reposo: misma estética que el `DetailRow` actual.
- Hover: lápiz aparece (CSS `group-hover`).
- Click lápiz: input/select toma el lugar del valor.
- Enter o blur fuera: `onSave`.
- Esc: cancela.
- Si `deletable`, ícono X pequeño en el ángulo superior derecho cuando
  está en edición; pide confirmación inline antes de borrar.

### `AddCustomAttrDialog.tsx`

Modal de shadcn con:
- `label` (text)
- `key` (auto-slugificada desde label, editable)
- `field_type`: text | number | date | boolean (select)
- `value` (input dependiente del tipo)
- Botón Guardar → llama `patchAttr.mutate({ key, value })`.

### Refactor de `ContactDetailGridSection`

- 9 de las 10 cards usan `EditableDetailRow` (Teléfono queda con
  `DetailRow` o `EditableDetailRow` con `editable=false`).
- Render adicional debajo del grid de los attrs ad-hoc:
  ```tsx
  {Object.entries(customAttrs).map(([k, v]) => (
    <EditableDetailRow key={k} label={prettify(k)} value={v} ... onDelete={...} />
  ))}
  ```
  Donde `customAttrs` son keys en `customer.attrs` que NO son las 5
  canónicas (estimated_value, tipo_credito, plan_credito, modelo_interes,
  city) ni metadata (mock_seed, slug, model_sku, campaign).
- Botón "Agregar campo" abre `AddCustomAttrDialog`.

## Restricciones por field

| Card | Tipo input | Validación / opciones |
|---|---|---|
| Etapa | select | stages del pipeline activo (`tenantsApi.getPipeline()`) |
| Fuente | text | libre |
| Asesor | select | lista de usuarios del tenant + agentes IA (endpoint existente `usersApi.list` + `agentsApi.list`) |
| Valor estimado | number | ≥ 0; formateo MXN solo en render |
| Tipo de crédito | select | `sin_dato`, `nomina_tarjeta`, `nomina_recibos`, `pensionado_imss`, `negocio_sat`, `sin_comprobantes` |
| Plan de crédito | select | `10`, `15`, `20`, `25`, `30` |
| Producto | text | libre |
| Ubicación | text | libre |
| Email | text | regex básica `^.+@.+\..+$` |

## RBAC

Sin cambios. Endpoints `PATCH /customers/:id` y `PATCH /conversations/:cid`
ya usan `current_user` (operator+ permitido). El operador puede editar
todo el grid. Si producto luego pide gating fino, envolvemos cards
sensibles en `<RoleGate>` ya disponible.

## Auditoría

Cero código nuevo. El backend ya emite:
- `CustomerTimelineEvent` (`field_changed`) por cada PATCH customer.
- `customer.updated` admin event.

Se ven en `/customers/:cid/timeline` (Customer detail page) que ya existe.
La conversación tiene su propio audit en `audit_log_routes.py`.

## Tests

### Backend
- `core/tests/api/test_customers_patch.py` ya existe. Agregar un test que
  verifique la semántica read-modify-write de `attrs`:
  ```python
  def test_patch_customer_attrs_overwrites_dict():
      """Patch attrs reemplaza el dict completo — el cliente debe hacer merge."""
      # PATCH {attrs: {a: 1}} → attrs = {a: 1}
      # PATCH {attrs: {b: 2}} → attrs = {b: 2} (a se borra)
  ```
  Esto documenta el contrato que el hook frontend debe respetar.

### Frontend
- `useCustomerAttrs.test.ts` — el hook hace merge correcto:
  - `patchAttr` con `attrs={a:1}` y mutación `{b:2}` produce `{a:1, b:2}`.
  - `deleteAttr("a")` con `attrs={a:1, b:2}` produce `{b:2}`.
- `EditableDetailRow.test.tsx`:
  - Render reposo muestra valor.
  - Click lápiz revela input.
  - Enter dispara `onSave`.
  - Esc cancela sin disparar.
  - `deletable=true` muestra el botón eliminar con confirmación.
  - `validate` que retorna error bloquea el save.
- `AddCustomAttrDialog.test.tsx`:
  - Label "Color favorito" → key auto `color_favorito`.
  - Key editable conserva slug.
  - Save llama callback con `{key, value}`.

## YAGNI explícito (NO en este sprint)

- **Sin nueva tabla `FieldEvidence`** — la evidencia desde IA ya queda en
  `turn_traces.nlu_output` y se ve en el `TurnStoryView` del sprint
  anterior.
- **Sin `FieldSuggestion` pending/accept/reject UI** — sería Phase 3e
  cuando se cableé NLU → autoupdate de structured fields.
- **Sin webhook `/webhooks/messages` nuevo** — `meta_routes.py` ya recibe
  WhatsApp Cloud API y dispara el runner.
- **Sin `evaluateLeadCompleteness()`** — el sistema ya calcula
  `required_docs` (vía conversations) y `next_best_action` (endpoint
  customer-level).
- **Sin tabla `LeadDocument`/`LeadCreditProfile`** — duplicaría
  `customer_documents` y los attrs.
- **Sin reglas de auto-cálculo en backend** (ej. "si plan=10 entonces
  tipo_credito recomendado=nomina_tarjeta") — eso es lógica del runner /
  composer, no del CRUD.
- **Sin migración del stack a NestJS/Prisma** — explícito.

## Orden de implementación

1. **`useCustomerAttrs.ts` + tests** (lógica pura, ningún componente
   depende).
2. **`EditableDetailRow.tsx` + tests** (componente genérico reusable).
3. **`AddCustomAttrDialog.tsx` + tests**.
4. **Refactor `ContactDetailGridSection`** para usar
   `EditableDetailRow` en las 9 cards editables; cablear cada una a su
   endpoint correcto via `usePatchCustomer`, `useCustomerAttrs`, y un
   nuevo `usePatchConversation` (en `hooks/useContactPanel.ts`).
5. **Render de attrs ad-hoc** debajo del grid canónico con
   `onDelete=deleteAttr`.
6. **Botón "Agregar campo"** abre `AddCustomAttrDialog`.
7. **Backend test** verificando read-modify-write de `attrs`.
8. **Smoke + lint + commit**.

## Criterios de éxito

- Las 10 cards visibles en el screenshot son editables inline (excepto
  Teléfono) sin cambio de pantalla.
- Tras editar y guardar, el valor se persiste en el endpoint correcto
  (verificable vía `pytest` para attrs y vía smoke en navegador para
  conversation/customer first-class fields).
- "Agregar campo" inserta un nuevo par en `customer.attrs` que se
  visualiza inmediatamente debajo del grid canónico.
- Eliminar un attr ad-hoc lo quita de `customer.attrs`.
- Audit timeline del cliente registra el cambio (sin código nuevo —
  backend ya lo hace).
- `pnpm test` y `pytest` siguen verdes.
