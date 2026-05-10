import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleDot,
  GitBranch,
  LayoutGrid,
  Save,
  Shield,
  SlidersHorizontal,
  Undo2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { inboxConfigApi } from "@/features/config/api";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";
import { DEFAULT_INBOX_CONFIG, type InboxConfig } from "../types";
import { FilterChipsSection } from "./FilterChipsSection";
import { HandoffRulesSection } from "./HandoffRulesSection";
import { InboxLayoutSection } from "./InboxLayoutSection";
import { InboxPreviewPanel, type SectionId } from "./InboxPreviewPanel";
import { PermissionsSection } from "./PermissionsSection";
import { StageRingsSection } from "./StageRingsSection";

interface NavSection {
  id: SectionId;
  label: string;
  icon: typeof LayoutGrid;
}

const SECTIONS: NavSection[] = [
  { id: "layout",      label: "Diseño de bandeja", icon: LayoutGrid        },
  { id: "chips",       label: "Chips de filtro",   icon: SlidersHorizontal },
  { id: "rings",       label: "Anillos de etapa",  icon: CircleDot         },
  { id: "handoff",     label: "Reglas de handoff", icon: GitBranch         },
  { id: "permissions", label: "Permisos y roles",  icon: Shield            },
];

export function InboxSettingsPage() {
  const user = useAuthStore((s) => s.user);
  const canEdit = user?.role === "tenant_admin" || user?.role === "superadmin";
  const qc = useQueryClient();

  const [activeSection, setActiveSection] = useState<SectionId>("layout");
  const [draft, setDraft] = useState<InboxConfig | null>(null);
  const [savedConfig, setSavedConfig] = useState<InboxConfig | null>(null);

  const query = useQuery({
    queryKey: ["tenants", "inbox-config"],
    queryFn: inboxConfigApi.get,
    staleTime: 60_000,
  });

  // Initialise draft once query resolves
  const remoteConfig = query.data ?? DEFAULT_INBOX_CONFIG;
  const activeDraft = draft ?? remoteConfig;
  const isDirty =
    draft !== null && JSON.stringify(draft) !== JSON.stringify(savedConfig ?? remoteConfig);

  const patchDraft = (patch: Partial<InboxConfig>) => {
    setDraft((prev) => ({ ...(prev ?? remoteConfig), ...patch }));
  };

  const saveMutation = useMutation({
    mutationFn: inboxConfigApi.put,
    onSuccess: (saved) => {
      setSavedConfig(saved);
      setDraft(null);
      qc.setQueryData(["tenants", "inbox-config"], saved);
      toast.success("Configuración guardada");
    },
    onError: () => toast.error("No se pudo guardar la configuración"),
  });

  const handleSave = () => saveMutation.mutate(activeDraft);

  const handleDiscard = () => {
    setDraft(null);
    toast("Cambios descartados");
  };

  if (query.isLoading) {
    return (
      <div className="-m-6 flex h-[calc(100vh-3.5rem)] items-center justify-center">
        <Skeleton className="h-64 w-full max-w-md" />
      </div>
    );
  }

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Left category nav */}
      <nav className="flex w-48 shrink-0 flex-col border-r bg-sidebar">
        <div className="flex h-10 items-center border-b px-4">
          <span className="text-xs font-semibold text-sidebar-foreground/70">
            Config. de Bandeja
          </span>
        </div>
        <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveSection(id)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-xs transition-colors",
                activeSection === id
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              {label}
            </button>
          ))}
        </div>

        {/* Role badge at bottom */}
        <div className="border-t p-3">
          <div
            className={cn(
              "rounded-md px-2 py-1 text-center text-[10px] font-medium",
              canEdit
                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "bg-muted text-muted-foreground",
            )}
          >
            {canEdit ? "Puede editar" : "Solo lectura"}
          </div>
        </div>
      </nav>

      {/* Center workspace */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Section topbar */}
        <div className="flex h-10 shrink-0 items-center justify-between border-b bg-background px-4">
          <div className="flex items-center gap-2">
            {(() => {
              const section = SECTIONS.find((s) => s.id === activeSection)!;
              const Icon = section.icon;
              return (
                <>
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-sm font-medium">{section.label}</span>
                </>
              );
            })()}
          </div>
          {isDirty && (
            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
              Cambios sin guardar
            </span>
          )}
        </div>

        {/* Scrollable section content */}
        <div className="flex-1 overflow-y-auto p-4">
          {activeSection === "layout" && (
            <InboxLayoutSection draft={activeDraft} patchDraft={patchDraft} canEdit={canEdit} />
          )}
          {activeSection === "chips" && (
            <FilterChipsSection draft={activeDraft} patchDraft={patchDraft} canEdit={canEdit} />
          )}
          {activeSection === "rings" && (
            <StageRingsSection draft={activeDraft} patchDraft={patchDraft} canEdit={canEdit} />
          )}
          {activeSection === "handoff" && (
            <HandoffRulesSection draft={activeDraft} patchDraft={patchDraft} canEdit={canEdit} />
          )}
          {activeSection === "permissions" && <PermissionsSection />}
        </div>

        {/* Sticky save bar */}
        {isDirty && canEdit && (
          <div className="flex shrink-0 items-center justify-end gap-2 border-t bg-background px-4 py-2.5">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleDiscard}
              disabled={saveMutation.isPending}
              className="h-8 text-xs"
            >
              <Undo2 className="mr-1.5 h-3.5 w-3.5" />
              Descartar
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saveMutation.isPending}
              className="h-8 text-xs"
            >
              <Save className="mr-1.5 h-3.5 w-3.5" />
              {saveMutation.isPending ? "Guardando…" : "Guardar cambios"}
            </Button>
          </div>
        )}
      </div>

      {/* Right preview panel */}
      <div className="w-64 shrink-0">
        <InboxPreviewPanel config={activeDraft} activeSection={activeSection} />
      </div>
    </div>
  );
}
