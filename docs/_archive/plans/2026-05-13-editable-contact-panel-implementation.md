# Editable Contact Panel — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Hacer que las 10 cards de `ContactDetailGridSection` (DATOS DE CONTACTO) sean editables inline, addable (custom attrs ad-hoc) y eliminables, sin migración de schema ni nuevos endpoints.

**Architecture:** Híbrido. Cada card sabe a qué endpoint pertenece. 4 fields → endpoints PATCH existentes (`customers`, `conversations`). 5 fields free-form → `customer.attrs` JSONB con merge en cliente (read-modify-write porque el backend reemplaza el dict completo). Componentes reusables: `EditableDetailRow`, `AddCustomAttrDialog`, hooks `useCustomerAttrs` + `usePatchConversation`. Teléfono read-only.

**Tech Stack:** React 19 + TS strict + Tailwind + shadcn/ui + TanStack Query + Vitest + Testing Library. Backend: FastAPI + SQLAlchemy async + pytest. Cero migraciones nuevas.

**Design doc:** `docs/plans/2026-05-13-editable-contact-panel-design.md`

---

## Task 1 — Backend test que documenta `attrs` overwrite semantics

**Files:**
- Modify: `core/tests/api/test_customers_patch.py`

**Step 1: Verificar fixtures existentes**

Run: `grep -n "def test_" core/tests/api/test_customers_patch.py | head -10`

**Step 2: Agregar test que documenta el contrato**

Apéndice al final del archivo:

```python
def test_patch_customer_attrs_replaces_whole_dict(client_operator):
    """PATCH /customers/:id with `attrs` REPLACES the dict — keys not in the
    payload are dropped. Frontend hooks MUST read-modify-write to update a
    single key without losing the rest.

    This is the contract that useCustomerAttrs depends on.
    """
    import uuid
    from sqlalchemy import text
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine
    from atendia.config import get_settings

    async def _seed() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cid = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, attrs) "
                        "VALUES (:t, :p, CAST(:a AS jsonb)) RETURNING id"
                    ),
                    {
                        "t": client_operator.tenant_id,
                        "p": f"+5215555{uuid.uuid4().hex[:8]}",
                        "a": '{"foo": "1", "bar": "2"}',
                    },
                )
            ).scalar()
        await engine.dispose()
        return str(cid)

    customer_id = asyncio.run(_seed())

    # PATCH with only foo=99 → expect bar to be dropped (full overwrite).
    resp = client_operator.patch(
        f"/api/v1/customers/{customer_id}",
        json={"attrs": {"foo": "99"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attrs"] == {"foo": "99"}, (
        "Backend SHOULD replace the whole attrs dict on PATCH; "
        "this test documents the contract the frontend hook relies on."
    )
```

**Step 3: Verificar que pasa**

```bash
$env:ATENDIA_V2_DATABASE_URL = "postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2"
uv run python -m pytest core/tests/api/test_customers_patch.py::test_patch_customer_attrs_replaces_whole_dict -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git add core/tests/api/test_customers_patch.py
git commit -m "test(customers): document attrs overwrite semantics for PATCH"
```

---

## Task 2 — Hook `useCustomerAttrs` con merge cliente

**Files:**
- Create: `frontend/src/features/conversations/hooks/useCustomerAttrs.ts`
- Create: `frontend/tests/features/conversations/useCustomerAttrs.test.tsx`

**Step 1: Test que verifica merge correcto**

```tsx
// frontend/tests/features/conversations/useCustomerAttrs.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { useCustomerAttrs } from "@/features/conversations/hooks/useCustomerAttrs";
import { customersApi } from "@/features/customers/api";

const customerId = "11111111-1111-1111-1111-111111111111";

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Seed the cache as if useCustomerDetail had already fetched.
  qc.setQueryData(["customer", customerId], {
    id: customerId,
    attrs: { foo: "1", bar: "2" },
  });
  const Provider = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, Provider };
}

describe("useCustomerAttrs", () => {
  it("patchAttr merges with current attrs (read-modify-write)", async () => {
    const spy = vi.spyOn(customersApi, "patch").mockResolvedValue({} as never);
    const { Provider } = wrap();
    const { result } = renderHook(() => useCustomerAttrs(customerId), {
      wrapper: Provider,
    });
    await act(async () => {
      await result.current.patchAttr.mutateAsync({ key: "baz", value: "3" });
    });
    expect(spy).toHaveBeenCalledWith(customerId, {
      attrs: { foo: "1", bar: "2", baz: "3" },
    });
    spy.mockRestore();
  });

  it("deleteAttr removes the key from current attrs", async () => {
    const spy = vi.spyOn(customersApi, "patch").mockResolvedValue({} as never);
    const { Provider } = wrap();
    const { result } = renderHook(() => useCustomerAttrs(customerId), {
      wrapper: Provider,
    });
    await act(async () => {
      await result.current.deleteAttr.mutateAsync("foo");
    });
    expect(spy).toHaveBeenCalledWith(customerId, { attrs: { bar: "2" } });
    spy.mockRestore();
  });

  it("patchAttr handles missing customer in cache gracefully", async () => {
    const spy = vi.spyOn(customersApi, "patch").mockResolvedValue({} as never);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Provider = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useCustomerAttrs(customerId), {
      wrapper: Provider,
    });
    await act(async () => {
      await result.current.patchAttr.mutateAsync({ key: "x", value: "1" });
    });
    expect(spy).toHaveBeenCalledWith(customerId, { attrs: { x: "1" } });
    spy.mockRestore();
  });
});
```

**Step 2: Run test → expect FAIL** (module not found)

```bash
cd frontend
pnpm exec vitest run tests/features/conversations/useCustomerAttrs.test.tsx
```

**Step 3: Implementación**

```ts
// frontend/src/features/conversations/hooks/useCustomerAttrs.ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { type CustomerDetail, customersApi } from "@/features/customers/api";

/**
 * Reads the current attrs dict from the TanStack cache, applies a single
 * key change, and PATCHes the whole dict. Required because the backend
 * replaces attrs on PATCH — see test_patch_customer_attrs_replaces_whole_dict.
 */
export function useCustomerAttrs(customerId: string) {
  const qc = useQueryClient();

  function currentAttrs(): Record<string, unknown> {
    const cached = qc.getQueryData<CustomerDetail>(["customer", customerId]);
    return (cached?.attrs as Record<string, unknown> | undefined) ?? {};
  }

  const patchAttr = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const next = { ...currentAttrs(), [key]: value };
      return customersApi.patch(customerId, { attrs: next });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) =>
      toast.error("Error al guardar el campo", { description: (e as Error).message }),
  });

  const deleteAttr = useMutation({
    mutationFn: async (key: string) => {
      const current = currentAttrs();
      const next = { ...current };
      delete next[key];
      return customersApi.patch(customerId, { attrs: next });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
    },
    onError: (e) =>
      toast.error("Error al eliminar el campo", { description: (e as Error).message }),
  });

  return { patchAttr, deleteAttr };
}
```

**Step 4: Verificar tests verdes**

```bash
pnpm exec vitest run tests/features/conversations/useCustomerAttrs.test.tsx
```

Expected: 3 passed.

**Step 5: Commit**

```bash
git add frontend/src/features/conversations/hooks/useCustomerAttrs.ts frontend/tests/features/conversations/useCustomerAttrs.test.tsx
git commit -m "feat(customer-data): useCustomerAttrs hook with read-modify-write merge"
```

---

## Task 3 — Hook `usePatchConversation`

**Files:**
- Modify: `frontend/src/features/conversations/hooks/useContactPanel.ts`

**Step 1: Append hook**

Al final del archivo:

```ts
import { conversationsApi } from "@/features/conversations/api";

export function usePatchConversation(conversationId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      current_stage?: string;
      assigned_user_id?: string | null;
      assigned_agent_id?: string | null;
    }) => {
      if (!conversationId) throw new Error("conversationId required");
      return conversationsApi.patchConversation(conversationId, body);
    },
    onSuccess: () => {
      if (conversationId) {
        void qc.invalidateQueries({ queryKey: ["conversation", conversationId] });
      }
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast.error("Error al actualizar conversación", { description: e.message }),
  });
}
```

**Step 2: Typecheck**

```bash
cd frontend
pnpm exec tsc --noEmit
```

Expected: PASS.

**Step 3: Commit**

```bash
git add frontend/src/features/conversations/hooks/useContactPanel.ts
git commit -m "feat(customer-data): usePatchConversation hook"
```

---

## Task 4 — `EditableDetailRow` componente genérico

**Files:**
- Create: `frontend/src/features/conversations/components/EditableDetailRow.tsx`
- Create: `frontend/tests/features/conversations/EditableDetailRow.test.tsx`

**Step 1: Test**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EditableDetailRow } from "@/features/conversations/components/EditableDetailRow";

describe("EditableDetailRow", () => {
  it("renders value in read mode", () => {
    render(
      <EditableDetailRow
        label="Etapa"
        value="Nuevo Lead"
        editable={false}
        deletable={false}
        onSave={() => {}}
      />,
    );
    expect(screen.getByText("Etapa")).toBeInTheDocument();
    expect(screen.getByText("Nuevo Lead")).toBeInTheDocument();
  });

  it("falls back to 'Sin dato' when value is null", () => {
    render(
      <EditableDetailRow
        label="Email"
        value={null}
        editable
        deletable={false}
        onSave={() => {}}
      />,
    );
    expect(screen.getByText("Sin dato")).toBeInTheDocument();
  });

  it("enters edit mode on pencil click and saves on Enter", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <EditableDetailRow
        label="Email"
        value="old@x.com"
        editable
        deletable={false}
        inputType="text"
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByLabelText("Editar Email"));
    const input = screen.getByRole("textbox");
    await userEvent.clear(input);
    await userEvent.type(input, "new@x.com{Enter}");
    expect(onSave).toHaveBeenCalledWith("new@x.com");
  });

  it("cancels on Escape without calling onSave", async () => {
    const onSave = vi.fn();
    render(
      <EditableDetailRow
        label="X"
        value="v"
        editable
        deletable={false}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByLabelText("Editar X"));
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders select when inputType is select and uses options", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <EditableDetailRow
        label="Plan"
        value="10"
        editable
        deletable={false}
        inputType="select"
        options={[
          { value: "10", label: "10" },
          { value: "20", label: "20" },
        ]}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByLabelText("Editar Plan"));
    // shadcn Select uses a combobox role
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("calls onDelete when delete button confirmed", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <EditableDetailRow
        label="Custom"
        value="abc"
        editable
        deletable
        onSave={() => {}}
        onDelete={onDelete}
      />,
    );
    await userEvent.click(screen.getByLabelText("Eliminar Custom"));
    // Confirm dialog
    await userEvent.click(screen.getByRole("button", { name: /confirmar/i }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("blocks save when validate returns an error", async () => {
    const onSave = vi.fn();
    render(
      <EditableDetailRow
        label="Email"
        value="x@x.com"
        editable
        deletable={false}
        validate={(v) => (v.includes("@") ? null : "Email inválido")}
        onSave={onSave}
      />,
    );
    await userEvent.click(screen.getByLabelText("Editar Email"));
    const input = screen.getByRole("textbox");
    await userEvent.clear(input);
    await userEvent.type(input, "not-an-email{Enter}");
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Email inválido")).toBeInTheDocument();
  });
});
```

**Step 2: Run → FAIL**

```bash
pnpm exec vitest run tests/features/conversations/EditableDetailRow.test.tsx
```

**Step 3: Implementación**

```tsx
// frontend/src/features/conversations/components/EditableDetailRow.tsx
import { Check, Pencil, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export interface EditableDetailRowOption {
  value: string;
  label: string;
}

export interface EditableDetailRowProps {
  label: string;
  value: string | null | undefined;
  icon?: React.ComponentType<{ className?: string }>;
  editable: boolean;
  deletable: boolean;
  inputType?: "text" | "number" | "email" | "select";
  options?: EditableDetailRowOption[];
  placeholder?: string;
  validate?: (raw: string) => string | null;
  onSave: (newValue: string | null) => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
}

export function EditableDetailRow({
  label,
  value,
  icon: Icon,
  editable,
  deletable,
  inputType = "text",
  options,
  placeholder = "Sin dato",
  validate,
  onSave,
  onDelete,
}: EditableDetailRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(value ?? "");
      setError(null);
      inputRef.current?.focus();
    }
  }, [editing, value]);

  async function save() {
    const trimmed = draft.trim();
    if (validate) {
      const err = validate(trimmed);
      if (err) {
        setError(err);
        return;
      }
    }
    await onSave(trimmed === "" ? null : trimmed);
    setEditing(false);
  }

  return (
    <div className="group min-w-0 rounded-md border border-border bg-muted/30 px-2 py-1.5">
      <div className="flex items-center justify-between gap-1 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1">
          {Icon && <Icon className="h-3 w-3 shrink-0" />}
          <span>{label}</span>
        </div>
        {editable && !editing && (
          <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              type="button"
              aria-label={`Editar ${label}`}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground"
              onClick={() => setEditing(true)}
            >
              <Pencil className="h-3 w-3" />
            </button>
            {deletable && onDelete && (
              <button
                type="button"
                aria-label={`Eliminar ${label}`}
                className="rounded p-0.5 text-muted-foreground hover:text-destructive"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <div className="mt-1 space-y-1">
          {inputType === "select" ? (
            <Select value={draft} onValueChange={(v) => setDraft(v)}>
              <SelectTrigger className="h-7 text-xs">
                <SelectValue placeholder={placeholder} />
              </SelectTrigger>
              <SelectContent>
                {(options ?? []).map((opt) => (
                  <SelectItem key={opt.value} value={opt.value} className="text-xs">
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              ref={inputRef}
              type={inputType}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void save();
                }
                if (e.key === "Escape") {
                  setEditing(false);
                  setError(null);
                }
              }}
              className="h-7 text-xs"
              placeholder={placeholder}
            />
          )}
          {error && <p className="text-[10px] text-destructive">{error}</p>}
          <div className="flex gap-1">
            <Button size="sm" className="h-6 px-2 text-[11px]" onClick={() => void save()}>
              <Check className="mr-1 h-3 w-3" /> Guardar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-[11px]"
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <div className={cn("mt-0.5 truncate text-[11px] font-medium", !value && "text-muted-foreground")}>
          {value || placeholder}
        </div>
      )}

      {confirmDelete && onDelete && (
        <div className="mt-1 flex items-center gap-1 rounded bg-destructive/10 px-1.5 py-1 text-[11px]">
          <span className="flex-1">¿Eliminar este campo?</span>
          <Button
            size="sm"
            variant="destructive"
            className="h-5 px-1.5 text-[10px]"
            onClick={async () => {
              await onDelete();
              setConfirmDelete(false);
            }}
          >
            Confirmar
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-5 px-1.5 text-[10px]"
            onClick={() => setConfirmDelete(false)}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  );
}
```

**Step 4: Run tests**

```bash
pnpm exec vitest run tests/features/conversations/EditableDetailRow.test.tsx
```

Expected: 7 passed.

**Step 5: Commit**

```bash
git add frontend/src/features/conversations/components/EditableDetailRow.tsx frontend/tests/features/conversations/EditableDetailRow.test.tsx
git commit -m "feat(customer-data): EditableDetailRow reusable inline-edit primitive"
```

---

## Task 5 — `AddCustomAttrDialog`

**Files:**
- Create: `frontend/src/features/conversations/components/AddCustomAttrDialog.tsx`
- Create: `frontend/tests/features/conversations/AddCustomAttrDialog.test.tsx`

**Step 1: Test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AddCustomAttrDialog } from "@/features/conversations/components/AddCustomAttrDialog";

describe("AddCustomAttrDialog", () => {
  it("auto-slugifies the key from the label", async () => {
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={() => {}} />);
    const labelInput = screen.getByLabelText("Etiqueta");
    await userEvent.type(labelInput, "Color Favorito");
    const keyInput = screen.getByLabelText("Clave") as HTMLInputElement;
    expect(keyInput.value).toBe("color_favorito");
  });

  it("allows manual key override that sticks", async () => {
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={() => {}} />);
    const labelInput = screen.getByLabelText("Etiqueta");
    const keyInput = screen.getByLabelText("Clave");
    await userEvent.type(labelInput, "Algo");
    await userEvent.clear(keyInput);
    await userEvent.type(keyInput, "custom_key");
    await userEvent.type(labelInput, " mas");
    // After manual edit, label changes should NOT overwrite key
    expect((keyInput as HTMLInputElement).value).toBe("custom_key");
  });

  it("calls onSubmit with key/value/label/type on save", async () => {
    const onSubmit = vi.fn();
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("Etiqueta"), "Color");
    await userEvent.type(screen.getByLabelText("Valor"), "Rojo");
    await userEvent.click(screen.getByRole("button", { name: /guardar/i }));
    expect(onSubmit).toHaveBeenCalledWith({
      key: "color",
      label: "Color",
      value: "Rojo",
      field_type: "text",
    });
  });

  it("blocks save when key or value is empty", async () => {
    const onSubmit = vi.fn();
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /guardar/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
```

**Step 2: Run → FAIL**

**Step 3: Implementación**

```tsx
// frontend/src/features/conversations/components/AddCustomAttrDialog.tsx
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type CustomAttrFieldType = "text" | "number" | "date" | "boolean";

export interface CustomAttrPayload {
  key: string;
  label: string;
  field_type: CustomAttrFieldType;
  value: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: CustomAttrPayload) => void;
}

function slugify(input: string): string {
  return input
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function AddCustomAttrDialog({ open, onClose, onSubmit }: Props) {
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [fieldType, setFieldType] = useState<CustomAttrFieldType>("text");
  const [value, setValue] = useState("");

  function handleLabelChange(next: string) {
    setLabel(next);
    if (!keyTouched) setKey(slugify(next));
  }

  function handleSave() {
    if (!key.trim() || !value.trim()) return;
    onSubmit({ key: key.trim(), label: label.trim() || key, field_type: fieldType, value: value.trim() });
    setLabel("");
    setKey("");
    setKeyTouched(false);
    setFieldType("text");
    setValue("");
    onClose();
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Agregar campo personalizado</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="custom-attr-label">Etiqueta</Label>
            <Input
              id="custom-attr-label"
              value={label}
              onChange={(e) => handleLabelChange(e.target.value)}
              placeholder="Ej. Color favorito"
            />
          </div>
          <div>
            <Label htmlFor="custom-attr-key">Clave</Label>
            <Input
              id="custom-attr-key"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setKeyTouched(true);
              }}
              placeholder="color_favorito"
              className="font-mono text-xs"
            />
          </div>
          <div>
            <Label>Tipo</Label>
            <Select value={fieldType} onValueChange={(v) => setFieldType(v as CustomAttrFieldType)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="text">Texto</SelectItem>
                <SelectItem value="number">Número</SelectItem>
                <SelectItem value="date">Fecha</SelectItem>
                <SelectItem value="boolean">Sí/No</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="custom-attr-value">Valor</Label>
            <Input
              id="custom-attr-value"
              type={fieldType === "number" ? "number" : fieldType === "date" ? "date" : "text"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={handleSave} disabled={!key.trim() || !value.trim()}>
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

**Step 4: Tests verdes**

```bash
pnpm exec vitest run tests/features/conversations/AddCustomAttrDialog.test.tsx
```

Expected: 4 passed.

**Step 5: Commit**

```bash
git add frontend/src/features/conversations/components/AddCustomAttrDialog.tsx frontend/tests/features/conversations/AddCustomAttrDialog.test.tsx
git commit -m "feat(customer-data): AddCustomAttrDialog with auto-slug and type select"
```

---

## Task 6 — Refactor `ContactDetailGridSection` (parte 1: cards estructurales)

**Files:**
- Modify: `frontend/src/features/conversations/components/ContactPanel.tsx:616-708`

**Step 1: Pre-trabajo — agregar imports y handlers**

En la cabecera del archivo:

```tsx
import { EditableDetailRow } from "@/features/conversations/components/EditableDetailRow";
import { AddCustomAttrDialog } from "@/features/conversations/components/AddCustomAttrDialog";
import { useCustomerAttrs } from "@/features/conversations/hooks/useCustomerAttrs";
import { useFieldDefinitions, useCustomerDetail, usePatchConversation, usePatchCustomer } from "@/features/conversations/hooks/useContactPanel";
```

(`usePatchCustomer` y `useCustomerDetail` ya existen; agregar `usePatchConversation`.)

**Step 2: Reemplazar `ContactDetailGridSection`**

Sustituir el cuerpo (líneas ~616-708) por:

```tsx
const CREDIT_TYPE_OPTIONS = [
  { value: "sin_dato", label: "Sin dato" },
  { value: "nomina_tarjeta", label: "Nómina tarjeta" },
  { value: "nomina_recibos", label: "Nómina recibos" },
  { value: "pensionado_imss", label: "Pensionado IMSS" },
  { value: "negocio_sat", label: "Negocio SAT" },
  { value: "sin_comprobantes", label: "Sin comprobantes" },
];
const PLAN_OPTIONS = ["10", "15", "20", "25", "30"].map((v) => ({ value: v, label: v }));
const CANONICAL_ATTR_KEYS = new Set([
  "estimated_value", "valor_estimado",
  "tipo_credito", "tipo_de_credito",
  "plan_credito", "plan_de_credito",
  "modelo_interes", "producto", "modelo_moto",
  "city", "ciudad",
]);
const META_ATTR_KEYS = new Set(["mock_seed", "slug", "model_sku", "campaign"]);

function isEditableRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function ContactDetailGridSection({
  customerId,
  customer,
  conversation,
}: {
  customerId: string;
  customer: CustomerRecord | undefined;
  conversation: ConversationDetail | undefined;
}) {
  const patchCustomer = usePatchCustomer(customerId);
  const patchConversation = usePatchConversation(conversation?.id);
  const { patchAttr, deleteAttr } = useCustomerAttrs(customerId);
  const pipeline = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });
  const [addOpen, setAddOpen] = useState(false);

  if (!customer) {
    return (
      <div className="px-3 py-3 space-y-2">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-16 rounded-lg" />
      </div>
    );
  }

  const sources = getDetailSources(customer, conversation);
  const source = pickValue(sources, ["source", "fuente", "lead_source", "origen"]);
  const campaign = pickValue(sources, ["campaign", "campana", "campaign_name"]);
  const estimatedValue =
    formatMoney(pickNumber(sources, ["estimated_value", "valor_estimado", "precio"])) ?? null;
  const creditType = pickValue(sources, ["tipo_credito", "tipo_de_credito"]);
  const creditPlan = pickValue(sources, ["plan_credito", "plan_de_credito"]);
  const product = pickValue(sources, ["modelo_interes", "modelo_moto", "producto"]);
  const city = pickValue(sources, ["ciudad", "city"]);
  const advisor =
    conversation?.assigned_agent_name ??
    conversation?.assigned_user_email ??
    pickValue(sources, ["advisor", "asesor"]);

  const stages =
    (pipeline.data?.definition?.stages as Array<{ id: string; label?: string }> | undefined) ?? [];
  const stageOptions = stages.map((s) => ({ value: s.id, label: s.label ?? s.id }));

  const customAttrs = isEditableRecord(customer.attrs)
    ? Object.entries(customer.attrs).filter(
        ([k]) => !CANONICAL_ATTR_KEYS.has(k) && !META_ATTR_KEYS.has(k),
      )
    : [];

  return (
    <div className="px-3 py-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <SectionLabel icon={Info}>Datos de contacto</SectionLabel>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[11px]"
          onClick={() => setAddOpen(true)}
        >
          <Plus className="mr-1 h-3 w-3" /> Agregar campo
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <EditableDetailRow
          label="Etapa"
          value={stageLabel(conversation?.current_stage ?? customer.effective_stage)}
          icon={Target}
          editable={!!conversation && stageOptions.length > 0}
          deletable={false}
          inputType="select"
          options={stageOptions}
          onSave={(v) => v && patchConversation.mutateAsync({ current_stage: v })}
        />
        <EditableDetailRow
          label="Fuente"
          value={campaign ? `${source ?? "WhatsApp"} · ${campaign}` : (source ?? "WhatsApp")}
          icon={Sparkles}
          editable
          deletable
          onSave={(v) => patchCustomer.mutateAsync({ source: v })}
          onDelete={() => patchCustomer.mutateAsync({ source: null })}
        />
        <EditableDetailRow
          label="Asesor"
          value={advisor}
          icon={UserCheck}
          editable
          deletable
          onSave={(v) =>
            patchAttr.mutateAsync({ key: "advisor_label", value: v })
          }
          onDelete={() => deleteAttr.mutateAsync("advisor_label")}
        />
        <EditableDetailRow
          label="Valor estimado"
          value={estimatedValue}
          icon={Zap}
          editable
          deletable
          inputType="number"
          onSave={(v) =>
            patchAttr.mutateAsync({ key: "estimated_value", value: v ? Number(v) : null })
          }
          onDelete={() => deleteAttr.mutateAsync("estimated_value")}
        />
        <EditableDetailRow
          label="Tipo de crédito"
          value={creditType}
          editable
          deletable
          inputType="select"
          options={CREDIT_TYPE_OPTIONS}
          onSave={(v) => patchAttr.mutateAsync({ key: "tipo_credito", value: v })}
          onDelete={() => deleteAttr.mutateAsync("tipo_credito")}
        />
        <EditableDetailRow
          label="Plan de crédito"
          value={creditPlan}
          editable
          deletable
          inputType="select"
          options={PLAN_OPTIONS}
          onSave={(v) => patchAttr.mutateAsync({ key: "plan_credito", value: v })}
          onDelete={() => deleteAttr.mutateAsync("plan_credito")}
        />
        <EditableDetailRow
          label="Producto"
          value={product}
          editable
          deletable
          onSave={(v) => patchAttr.mutateAsync({ key: "modelo_interes", value: v })}
          onDelete={() => deleteAttr.mutateAsync("modelo_interes")}
        />
        <EditableDetailRow
          label="Ubicación"
          value={city}
          editable
          deletable
          onSave={(v) => patchAttr.mutateAsync({ key: "city", value: v })}
          onDelete={() => deleteAttr.mutateAsync("city")}
        />
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <EditableDetailRow
          label="Teléfono"
          value={customer.phone_e164}
          icon={Phone}
          editable={false}
          deletable={false}
          onSave={() => {}}
        />
        <EditableDetailRow
          label="Email"
          value={customer.email}
          icon={Mail}
          editable
          deletable
          inputType="email"
          validate={(v) => (v === "" || /^.+@.+\..+$/.test(v) ? null : "Email inválido")}
          onSave={(v) => patchCustomer.mutateAsync({ email: v })}
          onDelete={() => patchCustomer.mutateAsync({ email: null })}
        />
      </div>

      {customAttrs.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5 pt-1">
          {customAttrs.map(([k, v]) => (
            <EditableDetailRow
              key={k}
              label={k.replace(/_/g, " ")}
              value={String(v ?? "")}
              editable
              deletable
              onSave={(next) => patchAttr.mutateAsync({ key: k, value: next })}
              onDelete={() => deleteAttr.mutateAsync(k)}
            />
          ))}
        </div>
      )}

      <div className="text-[10px] text-muted-foreground">
        Última actividad: {formatElapsed(customer.last_activity_at) ?? "sin registro"}
      </div>

      <AddCustomAttrDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSubmit={(payload) =>
          patchAttr.mutate({
            key: payload.key,
            value:
              payload.field_type === "number"
                ? Number(payload.value)
                : payload.field_type === "boolean"
                  ? payload.value === "true" || payload.value === "1"
                  : payload.value,
          })
        }
      />
    </div>
  );
}
```

**Step 3: Actualizar la llamada**

Antes:
```tsx
<ContactDetailGridSection customer={customer.data} conversation={conversation} />
```
Después:
```tsx
<ContactDetailGridSection customerId={customerId} customer={customer.data} conversation={conversation} />
```

**Step 4: Typecheck**

```bash
pnpm exec tsc --noEmit
```

Expected: PASS.

**Step 5: Run full vitest**

```bash
pnpm exec vitest run
```

Expected: todos los tests previos pasan + nuevos pasan.

**Step 6: Commit**

```bash
git add frontend/src/features/conversations/components/ContactPanel.tsx
git commit -m "feat(customer-data): wire ContactDetailGridSection to editable rows + custom attrs"
```

---

## Task 7 — Lint + smoke final + push

**Step 1: Biome check sobre archivos tocados**

```bash
cd frontend
pnpm exec biome check --write \
  src/features/conversations/components/EditableDetailRow.tsx \
  src/features/conversations/components/AddCustomAttrDialog.tsx \
  src/features/conversations/components/ContactPanel.tsx \
  src/features/conversations/hooks/useCustomerAttrs.ts \
  src/features/conversations/hooks/useContactPanel.ts \
  tests/features/conversations/EditableDetailRow.test.tsx \
  tests/features/conversations/AddCustomAttrDialog.test.tsx \
  tests/features/conversations/useCustomerAttrs.test.tsx
```

**Step 2: TypeScript**

```bash
pnpm exec tsc --noEmit
```

Expected: PASS.

**Step 3: Full vitest**

```bash
pnpm exec vitest run
```

Expected: tests existentes (44 + algunos nuevos) verdes.

**Step 4: Backend smoke**

```bash
$env:ATENDIA_V2_DATABASE_URL = "postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2"
uv run python -m pytest core/tests/api/test_customers_patch.py -v
```

Expected: incluyendo el test nuevo, todos verdes.

**Step 5: Commit cualquier lint fix**

```bash
git commit -am "chore(lint): biome formatting on contact-panel files" || echo "nothing to commit"
```

---

## Criterios de éxito

- [ ] `test_patch_customer_attrs_replaces_whole_dict` pasa.
- [ ] `useCustomerAttrs` tests (3) pasan.
- [ ] `EditableDetailRow` tests (7) pasan.
- [ ] `AddCustomAttrDialog` tests (4) pasan.
- [ ] La sección "Datos de contacto" muestra los 10 cards con ícono lápiz en hover (excepto Teléfono).
- [ ] Editar Etapa cambia `conversation.current_stage` (verificable en `/conversations/:id` GET).
- [ ] Editar Email persiste vía PATCH customer.
- [ ] Editar Valor estimado, Tipo de crédito, Plan de crédito, Producto, Ubicación persiste como merge en `customer.attrs` (sin perder otras keys).
- [ ] Botón "Agregar campo" abre dialog → guardar inserta `key:value` en `customer.attrs`.
- [ ] Card extra renderiza debajo del grid con botón eliminar.
- [ ] Eliminar lo remueve de `attrs`.
- [ ] Audit timeline del cliente (`/customers/:cid/timeline`) registra cada cambio.
- [ ] Frontend + backend tests verdes.
- [ ] Biome + TSC limpios sobre los archivos tocados.
