# RBAC por pantalla + Observabilidad UX — diseño

**Fecha:** 2026-05-12
**Branch:** `claude/beautiful-mirzakhani-55368f`
**Autor:** Claude + zpiritech369@gmail.com

Dos chunks de trabajo independientes pero que se pueden enviar en un mismo
PR porque tocan archivos disjuntos:

1. Endurecer permisos y RBAC con guards a nivel de ruta + cobertura E2E.
2. Reescribir el panel de debug de turnos para que sea legible (no JSON).

## Parte 1 — RBAC

### Estado actual (verificado en código, 2026-05-12)

- `core/atendia/api/_deps.py:74-87` define `require_superadmin` y
  `require_tenant_admin`. Se usan en ~67 endpoints (agents, knowledge,
  workflows, tenants, users, customer_fields).
- `frontend/src/components/AppShell.tsx:51-80` esconde 3 ítems del sidebar:
  `Agentes IA` y `Usuarios` para `tenantAdminOnly`, `Auditoría` para
  `superadminOnly`. Pero la ruta `/(auth)/users.tsx` y compañía no tienen
  guard — un operador que teclea la URL aterriza en la página y el API
  responde 403, dejando la pantalla rota.
- `core/tests/api/test_users_rbac.py` (104 líneas) cubre 5 casos.
  `core/tests/api/test_deps.py` cubre el comportamiento de las deps. **Cero
  cobertura RBAC para los otros ~60 endpoints `require_tenant_admin`**.

### Diseño

#### F1. Helper `requireRole` para `beforeLoad`

`frontend/src/lib/auth-guards.ts`:

```ts
import { redirect } from "@tanstack/react-router";
import type { Role } from "@/stores/auth";
import { useAuthStore } from "@/stores/auth";

export function requireRole(allowed: readonly Role[]) {
  return async () => {
    const state = useAuthStore.getState();
    const user = state.user ?? (await state.fetchMe());
    if (!user) throw redirect({ to: "/login" });
    if (!allowed.includes(user.role)) {
      throw redirect({ to: "/" });
    }
  };
}
```

Se chainea con el `beforeLoad` existente en `(auth)/route.tsx` que ya valida
"hay sesión". El helper hace login-check + role-check. Cuando un operador
abre `/users` directamente, lo manda a `/` en vez de mostrar una pantalla
rota.

#### F2. Mapeo ruta → roles permitidos

| Ruta                 | Roles permitidos                    | Razón                                            |
| -------------------- | ----------------------------------- | ------------------------------------------------ |
| `/users`             | `tenant_admin`, `superadmin`        | Sidebar ya lo oculta, pero la URL es pública    |
| `/agents`            | `tenant_admin`, `superadmin`        | Idem                                             |
| `/audit-log`         | `superadmin`                        | Idem                                             |
| `/inbox-settings`    | `tenant_admin`, `superadmin`        | Permisos de operadores se editan ahí            |
| `/config`            | `tenant_admin`, `superadmin`        | Toda la pestaña es configuración de tenant      |
| `/workflows`         | (cualquiera) — escritura sólo admin | Ver, sí; editar, ver F3                          |
| `/knowledge`         | (cualquiera) — escritura sólo admin | Idem                                             |
| Resto                | sin guard                            | Visible para operator                            |

#### F3. `<RoleGate>` para gating dentro de páginas mixtas

`frontend/src/components/RoleGate.tsx`:

```tsx
export function RoleGate({
  roles,
  children,
  fallback = null,
}: {
  roles: readonly Role[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const role = useAuthStore((s) => s.user?.role);
  if (!role || !roles.includes(role)) return <>{fallback}</>;
  return <>{children}</>;
}
```

Se usa donde un botón/sección dentro de una página visible es sólo admin:

```tsx
<RoleGate roles={["tenant_admin", "superadmin"]}>
  <Button onClick={deleteWorkflow}>Borrar workflow</Button>
</RoleGate>
```

#### B1. `core/tests/api/test_rbac_matrix.py`

Una sola tabla parametrizada que cubre los endpoints admin-gated. Patrón:

```python
RBAC_MATRIX = [
    # (method, path, payload, allowed_roles)
    ("POST", "/api/v1/workflows", {"name": "x"}, {"tenant_admin", "superadmin"}),
    ("DELETE", "/api/v1/workflows/{wid}", None, {"tenant_admin", "superadmin"}),
    ("POST", "/api/v1/agents", {"name": "x"}, {"tenant_admin", "superadmin"}),
    # … 25-30 entradas total
]

@pytest.mark.parametrize("method,path,payload,allowed", RBAC_MATRIX)
def test_rbac(method, path, payload, allowed, client_operator,
              client_tenant_admin, client_superadmin):
    for role, client in [
        ("operator", client_operator),
        ("tenant_admin", client_tenant_admin),
        ("superadmin", client_superadmin),
    ]:
        resp = client.request(method, path.format(wid=...), json=payload)
        if role in allowed:
            assert resp.status_code != 403, f"{role} should be allowed"
        else:
            assert resp.status_code == 403, f"{role} should be denied"
```

Sólo verifica el bit RBAC. Los endpoints quizás devuelvan 422 (validación) o
404 (recurso no existe) — eso es ok mientras no sea 403 para roles
permitidos y SÍ 403 para roles denegados.

#### B2. Cobertura específica para `/customer_fields`, `/tenants`, `/knowledge`

Estos endpoints tienen lógica de negocio más rica donde un test simple "no
403" no captura bien la regresión. Una pequeña suite adicional con casos
positivos (admin crea, lee de vuelta) y negativos (operator → 403).

### Tests

**Backend**
- `test_rbac_matrix.py` — nuevo, ~30 entradas parametrizadas.
- Tests específicos por dominio donde aplique (knowledge, tenants).

**Frontend**
- `frontend/src/lib/__tests__/auth-guards.test.ts` — unit test que verifica
  que `requireRole` lanza `redirect` para el rol equivocado.
- `frontend/src/components/__tests__/RoleGate.test.tsx` — render con
  diferentes roles, verifica que esconde/muestra.

## Parte 2 — Observabilidad UX

### Estado actual (verificado)

- `frontend/src/features/conversations/components/DebugPanel.tsx` (370
  líneas): ya tiene secciones (Resumen, Pipeline, NLU, Composer, Tools,
  Estado, Errores), latencia con barra, KV pairs, JSON colapsable. Está
  bien.
- `frontend/src/features/turn-traces/components/TurnTraceInspector.tsx`
  (110 líneas): tabs simples con `<JsonBlock>` en bruto. **Aquí está la
  regresión.**
- `frontend/src/features/turn-traces/components/TurnTraceList.tsx`: tabla
  con #/modo/NLU model/composer model/latencia/costo. Falta el mensaje
  inbound — sin él un operador no puede escanear la lista.
- Backend `core/atendia/api/turn_traces_routes.py:58-81`: el payload
  `TurnTraceDetail` ya tiene todo lo necesario (`inbound_text`,
  `nlu_output`, `composer_output`, `tool_calls`, `state_before/after`,
  `stage_transition`, `outbound_messages`). **No requiere cambios.**

### Diseño

#### O1. `turnStory.ts` — derivar narrativa en español

`frontend/src/features/turn-traces/lib/turnStory.ts`:

```ts
export type StoryStep =
  | { kind: "inbound"; text: string | null; hasMedia: boolean }
  | { kind: "nlu"; intent: string | null; extracted: Record<string, unknown> | null }
  | { kind: "mode"; mode: string | null }
  | { kind: "tool"; toolName: string; summary: string; error: string | null }
  | { kind: "composer"; action: string | null; summary: string | null }
  | { kind: "outbound"; count: number; previews: string[] }
  | { kind: "transition"; from: string; to: string };

export function buildTurnStory(trace: TurnTraceDetail): StoryStep[] {
  // Lee inbound_text, nlu_output, flow_mode, tool_calls,
  // composer_output, outbound_messages, stage_transition.
  // Produce un array tipado de pasos.
}

export function describeStep(step: StoryStep): string {
  // Convierte cada paso a una línea en español.
}
```

Las extracciones específicas (intent de `nlu_output.intent`, extracted de
`nlu_output.extracted_fields`, etc.) viven aquí. Si la estructura del
backend cambia, sólo tocamos este archivo. Tests unitarios con fixtures
JSON.

#### O2. `FlowModeBadge.tsx` — badge coloreado

`frontend/src/features/turn-traces/components/FlowModeBadge.tsx`:

```tsx
const MODE_LABELS: Record<string, { label: string; color: string }> = {
  PLAN: { label: "Planes", color: "bg-blue-500/20 text-blue-700" },
  SALES: { label: "Ventas", color: "bg-emerald-500/20 text-emerald-700" },
  DOC: { label: "Documentos", color: "bg-purple-500/20 text-purple-700" },
  OBSTACLE: { label: "Obstáculo", color: "bg-amber-500/20 text-amber-700" },
  RETENTION: { label: "Retención", color: "bg-rose-500/20 text-rose-700" },
  SUPPORT: { label: "Soporte", color: "bg-slate-500/20 text-slate-700" },
};
```

#### O3. `TurnStoryView.tsx` — render de la narrativa

Una secuencia vertical de cards con ícono+texto, ej.:

```
🗨️  Cliente: "¿Cuánto cuesta el Civic 2024?"
🧠  Entendido: intención SALES, marca=Honda, modelo=Civic, año=2024
🎯  Modo: [Ventas] (verde)
🛠️  search_catalog → Honda Civic 2024 — $325,000
✍️  Decisión: cotizar
📤  Envió 2 mensajes:
     · "Claro, el Civic 2024 cuesta $325,000…"
     · "¿Quieres apartarlo?"
↪️  Etapa: lead_warm → quote_sent
```

#### O4. Rediseño `TurnTraceInspector.tsx`

Pasar de tabs raw-json a:

- Header: `Turn N · [mode badge] · latencia · costo`
- Sección "Resumen" (`TurnStoryView`) — siempre visible.
- Sección "Detalle técnico" — reusa los componentes secciones de
  `DebugPanel` (extraídos a `frontend/src/features/turn-traces/components/TurnTraceSections.tsx`).
- Sección "Raw" — colapsada por default para power users.

#### O5. `DebugPanel.tsx` — agregar sección Resumen arriba

Reusa `TurnStoryView`. Mismo data path. Cero duplicación.

#### O6. `TurnTraceList.tsx` — mejorar lista

- Nueva columna "Mensaje" (primeros 40 chars de `inbound_text`, truncado).
- Reemplazar `<Badge variant="outline">{flow_mode}</Badge>` por
  `<FlowModeBadge mode={flow_mode} />`.

### Tests

**Frontend**
- `turnStory.test.ts` — fixtures de `TurnTraceDetail` JSON, verificar que
  `buildTurnStory` produce los pasos esperados.
- `TurnStoryView.test.tsx` — render snapshot con una traza canónica.
- `FlowModeBadge.test.tsx` — verifica color por modo.

**Backend**
- Ninguno (no cambia el payload).

## Lo que NO se incluye

- Permission registry / RBAC data-driven: 3 roles, no amerita.
- Browser E2E (Playwright): fuera de scope, Phase 4 lo difirió.
- Cargar full conversations en el inspector: ya están en `/conversations/:id`.
- Filtros por modo/costo/latencia en `TurnTraceList`: si lo piden,
  agregar después.
- Storybook: Phase 4 lo difirió, mantenemos el deferral.

## Orden de implementación

1. **Backend RBAC matrix test** (descubre gaps existentes antes de mover UI).
2. **Frontend `requireRole` + RoleGate + aplicar a rutas + tests**.
3. **`turnStory.ts` + unit tests**.
4. **`FlowModeBadge` + actualizar `TurnTraceList`**.
5. **Extraer `TurnTraceSections` + rediseñar `TurnTraceInspector`**.
6. **Sección Resumen en `DebugPanel`**.
7. Smoke local: login como operator vs tenant_admin, abrir un turno con
   datos reales, verificar que la story se ve bien.

## Criterios de éxito

- `pytest core/tests/api/test_rbac_matrix.py` pasa con la matriz.
- Operator que abre `/users` directamente es redirigido a `/`.
- Abrir un turno en `/turn-traces` o desde una conversación muestra una
  narrativa en español en la parte de arriba; el detalle técnico sigue
  disponible pero no es lo primero que ve el operador.
- Cobertura de tests no baja del nivel actual.
