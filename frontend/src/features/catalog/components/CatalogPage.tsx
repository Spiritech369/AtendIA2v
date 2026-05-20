import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, CheckCircle2, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { knowledgeApi, type CatalogItem } from "@/features/knowledge/api";

function pesosToCents(value: string): number | null {
  const normalized = value.replace(/[,$\s]/g, "");
  if (!normalized) return null;
  const num = Number(normalized);
  if (!Number.isFinite(num) || num < 0) return null;
  return Math.round(num * 100);
}

function centsToPesos(value: number | null): string {
  if (value === null || value === undefined) return "";
  return String(value / 100);
}

function parsePaymentPlans(raw: string): unknown[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  const parsed = JSON.parse(trimmed) as unknown;
  if (!Array.isArray(parsed)) throw new Error("Los planes deben ser un JSON array.");
  return parsed;
}

function formatPaymentPlans(plans: unknown[]): string {
  return plans.length ? JSON.stringify(plans, null, 2) : "";
}

function hasOfficialPrice(item: CatalogItem): boolean {
  return item.price_cents !== null || item.payment_plans.length > 0;
}

export function CatalogPage() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["knowledge", "catalog"], queryFn: knowledgeApi.listCatalog });
  const [draft, setDraft] = useState({
    sku: "",
    name: "",
    category: "motos",
    price: "",
    stock_status: "unknown",
    payment_plans: "",
  });

  const items = query.data ?? [];
  const priced = useMemo(() => items.filter(hasOfficialPrice).length, [items]);

  const create = useMutation({
    mutationFn: async () =>
      knowledgeApi.createCatalog({
        sku: draft.sku.trim(),
        name: draft.name.trim(),
        category: draft.category.trim() || null,
        tags: [],
        attrs: {},
        status: "published",
        active: true,
        price_cents: pesosToCents(draft.price),
        stock_status: draft.stock_status.trim() || "unknown",
        payment_plans: parsePaymentPlans(draft.payment_plans),
      }),
    onSuccess: () => {
      setDraft({ sku: "", name: "", category: "motos", price: "", stock_status: "unknown", payment_plans: "" });
      void qc.invalidateQueries({ queryKey: ["knowledge", "catalog"] });
      toast.success("Producto agregado al catálogo oficial");
    },
    onError: (error: Error) => toast.error("No se pudo guardar", { description: error.message }),
  });

  const patch = useMutation({
    mutationFn: async ({
      item,
      price,
      paymentPlans,
      stockStatus,
    }: {
      item: CatalogItem;
      price: string;
      paymentPlans: string;
      stockStatus: string;
    }) =>
      knowledgeApi.patchCatalog(item.id, {
        price_cents: pesosToCents(price),
        payment_plans: parsePaymentPlans(paymentPlans),
        stock_status: stockStatus.trim() || "unknown",
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["knowledge", "catalog"] });
      toast.success("Catálogo actualizado");
    },
    onError: (error: Error) => toast.error("No se pudo actualizar", { description: error.message }),
  });

  const remove = useMutation({
    mutationFn: knowledgeApi.deleteCatalog,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["knowledge", "catalog"] });
      toast.success("Producto eliminado");
    },
    onError: (error: Error) => toast.error("No se pudo eliminar", { description: error.message }),
  });

  if (query.isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Catálogo oficial</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Productos, precios y planes que el Composer puede usar para cotizar.
          </p>
        </div>
        <div className="flex gap-2">
          <Badge variant="outline">{items.length} productos</Badge>
          <Badge variant={priced > 0 ? "default" : "destructive"}>{priced} con precio/plan</Badge>
        </div>
      </div>

      <section className="grid gap-3 rounded-md border bg-card p-3 md:grid-cols-[1fr_1fr_120px_130px_auto]">
        <div>
          <Label>SKU</Label>
          <Input value={draft.sku} onChange={(event) => setDraft((d) => ({ ...d, sku: event.target.value }))} placeholder="GLG-150" />
        </div>
        <div>
          <Label>Modelo</Label>
          <Input value={draft.name} onChange={(event) => setDraft((d) => ({ ...d, name: event.target.value }))} placeholder="Galgo 150" />
        </div>
        <div>
          <Label>Precio contado</Label>
          <Input value={draft.price} onChange={(event) => setDraft((d) => ({ ...d, price: event.target.value }))} placeholder="28999" />
        </div>
        <div>
          <Label>Stock</Label>
          <Input value={draft.stock_status} onChange={(event) => setDraft((d) => ({ ...d, stock_status: event.target.value }))} placeholder="available" />
        </div>
        <div className="flex items-end">
          <Button disabled={!draft.sku.trim() || !draft.name.trim() || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Agregar
          </Button>
        </div>
        <div className="md:col-span-5">
          <Label>Planes de pago (JSON opcional)</Label>
          <Input
            value={draft.payment_plans}
            onChange={(event) => setDraft((d) => ({ ...d, payment_plans: event.target.value }))}
            placeholder='[{"plan":"10%","enganche_mxn":3000,"pago_quincenal_mxn":900,"numero_quincenas":48}]'
          />
        </div>
      </section>

      <section className="space-y-2">
        {items.length === 0 && (
          <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
            <Boxes className="mx-auto mb-2 h-8 w-8" />
            Sin catálogo oficial. Agrega al menos un producto con precio o plan para desbloquear cotizaciones.
          </div>
        )}
        {items.map((item) => (
          <CatalogRow
            key={item.id}
            item={item}
            saving={patch.isPending}
            deleting={remove.isPending}
            onSave={(price, paymentPlans, stockStatus) => patch.mutate({ item, price, paymentPlans, stockStatus })}
            onDelete={() => remove.mutate(item.id)}
          />
        ))}
      </section>
    </div>
  );
}

function CatalogRow({
  item,
  saving,
  deleting,
  onSave,
  onDelete,
}: {
  item: CatalogItem;
  saving: boolean;
  deleting: boolean;
  onSave: (price: string, paymentPlans: string, stockStatus: string) => void;
  onDelete: () => void;
}) {
  const [price, setPrice] = useState(centsToPesos(item.price_cents));
  const [stockStatus, setStockStatus] = useState(item.stock_status);
  const [paymentPlans, setPaymentPlans] = useState(formatPaymentPlans(item.payment_plans));
  const official = hasOfficialPrice(item);

  return (
    <div className="grid gap-3 rounded-md border bg-card p-3 lg:grid-cols-[1fr_120px_130px_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <div className="truncate font-medium">{item.name}</div>
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{item.sku}</code>
          {official ? (
            <Badge className="gap-1">
              <CheckCircle2 className="h-3 w-3" />
              Cotizable
            </Badge>
          ) : (
            <Badge variant="destructive">Sin precio</Badge>
          )}
        </div>
        <div className="mt-2">
          <Label>Planes JSON</Label>
          <Input value={paymentPlans} onChange={(event) => setPaymentPlans(event.target.value)} />
        </div>
      </div>
      <div>
        <Label>Precio</Label>
        <Input value={price} onChange={(event) => setPrice(event.target.value)} placeholder="0" />
      </div>
      <div>
        <Label>Stock</Label>
        <Input value={stockStatus} onChange={(event) => setStockStatus(event.target.value)} />
      </div>
      <div className="flex items-end gap-1">
        <Button variant="outline" disabled={saving} onClick={() => onSave(price, paymentPlans, stockStatus)}>
          <Save className="h-4 w-4" />
        </Button>
        <Button variant="ghost" disabled={deleting} onClick={onDelete}>
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </div>
    </div>
  );
}
