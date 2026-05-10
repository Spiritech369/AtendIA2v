import { cn } from "@/lib/utils";
import type { InboxConfig } from "../types";

export type SectionId = "layout" | "chips" | "rings" | "handoff" | "permissions";

interface Props {
  config: InboxConfig;
  activeSection: SectionId;
}

const MOCK_CONVERSATIONS = [
  { name: "María González", stage_id: "nuevo",      preview: "Hola, me interesa el HR-V blanco",   unread: 3, time: "09:14" },
  { name: "Carlos Ramos",   stage_id: "cotizacion", preview: "¿Me pueden dar el precio final?",    unread: 0, time: "08:52" },
  { name: "Ana Martínez",   stage_id: "en_espera",  preview: "Esperando los documentos del banco", unread: 1, time: "Ayer"  },
  { name: "Roberto Díaz",   stage_id: "en_curso",   preview: "¿Cuándo puedo pasar por la unidad?", unread: 0, time: "Lun"   },
  { name: "Laura Vega",     stage_id: "documentos", preview: "Les mando los comprobantes ahora",   unread: 2, time: "Dom"   },
];

function initials(name: string) {
  return name.split(" ").slice(0, 2).map((w) => w[0]).join("");
}

export function InboxPreviewPanel({ config, activeSection }: Props) {
  const { layout, filter_chips, stage_rings, handoff_rules } = config;
  const visibleChips = [...filter_chips].sort((a, b) => a.order - b.order).filter((c) => c.visible);

  const getRing = (stage_id: string) =>
    stage_rings.find((r) => r.stage_id === stage_id) ?? { color: "#6b7280", emoji: "⚪" };

  return (
    <div className="flex h-full flex-col overflow-hidden border-l bg-muted/20">
      {/* Preview header */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b bg-background px-3">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Vista previa en vivo
        </span>
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[9px] font-medium",
            layout.three_pane
              ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
              : "bg-muted text-muted-foreground",
          )}
        >
          {layout.three_pane ? "3 paneles" : "2 paneles"}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Layout section highlight */}
        {activeSection === "layout" && (
          <div className="border-b bg-blue-500/5 px-3 py-2">
            <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-blue-600 dark:text-blue-400">
              Diseño de paneles
            </p>
            <div className="flex h-12 gap-1 rounded-md border bg-background p-1.5">
              {layout.three_pane && (
                <div
                  className="shrink-0 rounded-sm bg-muted-foreground/20"
                  style={{ width: layout.rail_width === "expanded" ? 28 : 12 }}
                />
              )}
              <div className="flex-none w-[45%] rounded-sm bg-muted-foreground/15" />
              <div className="flex-1 rounded-sm bg-primary/10" />
            </div>
            <p className="mt-1 text-[9px] text-muted-foreground">
              Lista máx. {layout.list_max_width}px · Composer {layout.composer_density}
              {layout.sticky_composer ? " · sticky" : ""}
            </p>
          </div>
        )}

        {/* Filter chips highlight */}
        {activeSection === "chips" && visibleChips.length > 0 && (
          <div className="border-b bg-background px-2 py-1.5">
            <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
              Chips activos ({visibleChips.length})
            </p>
            <div className="flex flex-wrap gap-1">
              {visibleChips.map((chip) => (
                <span
                  key={chip.id}
                  className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[9px] font-medium"
                  style={{ background: `${chip.color}1a`, color: chip.color }}
                >
                  {chip.label}
                  {chip.live_count && (
                    <span
                      className="ml-0.5 rounded px-0.5 text-[8px] font-bold text-white"
                      style={{ background: chip.color }}
                    >
                      {Math.floor(Math.random() * 20) + 1}
                    </span>
                  )}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Handoff rules highlight */}
        {activeSection === "handoff" && (
          <div className="border-b bg-background px-3 py-2">
            <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
              Reglas activas ({handoff_rules.filter((r) => r.enabled).length}/{handoff_rules.length})
            </p>
            {handoff_rules
              .filter((r) => r.enabled)
              .sort((a, b) => a.order - b.order)
              .map((rule) => (
                <div key={rule.id} className="mb-0.5 flex items-center gap-1">
                  <span className="w-1 h-1 rounded-full bg-emerald-500 shrink-0" />
                  <span className="font-mono text-[8px] text-muted-foreground truncate">
                    {rule.intent} → {rule.action}
                  </span>
                  <span className="ml-auto shrink-0 text-[8px] text-muted-foreground">
                    {rule.confidence}%
                  </span>
                </div>
              ))}
          </div>
        )}

        {/* Permissions highlight */}
        {activeSection === "permissions" && (
          <div className="border-b bg-background px-3 py-2">
            <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
              Roles
            </p>
            <div className="space-y-0.5">
              {(["Admin", "Supervisor", "Operador"] as const).map((role) => (
                <div key={role} className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "text-[9px] font-medium w-16",
                      role === "Admin" && "text-red-600 dark:text-red-400",
                      role === "Supervisor" && "text-blue-600 dark:text-blue-400",
                      role === "Operador" && "text-muted-foreground",
                    )}
                  >
                    {role}
                  </span>
                  <div className="flex gap-0.5">
                    {[...Array(role === "Admin" ? 5 : role === "Supervisor" ? 3 : 1)].map((_, i) => (
                      <div key={i} className="h-1.5 w-3 rounded-full bg-primary/40" />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Mock inbox conversation list */}
        <div className="divide-y">
          {MOCK_CONVERSATIONS.map((conv) => {
            const ring = getRing(conv.stage_id);
            const highlight = activeSection === "rings";
            return (
              <div
                key={conv.name}
                className={cn(
                  "flex items-center gap-2 px-2 py-2 transition-colors",
                  highlight && "bg-background",
                )}
              >
                {/* Avatar with ring */}
                <div className="relative h-7 w-7 shrink-0">
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-[9px] font-semibold">
                    {initials(conv.name)}
                  </div>
                  <div
                    className={cn(
                      "pointer-events-none absolute inset-0 rounded-full border-2 transition-all",
                      highlight && "ring-1 ring-offset-1",
                    )}
                    style={{
                      borderColor: ring.color,
                      ...(highlight ? { ringColor: ring.color } : {}),
                    }}
                  />
                  {highlight && (
                    <span
                      className="absolute -bottom-0.5 -right-0.5 text-[8px]"
                      title={conv.stage_id}
                    >
                      {ring.emoji}
                    </span>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="truncate text-[10px] font-medium">{conv.name}</span>
                    <span className="shrink-0 text-[8px] text-muted-foreground">{conv.time}</span>
                  </div>
                  <p className="truncate text-[9px] text-muted-foreground">{conv.preview}</p>
                </div>

                {conv.unread > 0 && (
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary text-[8px] font-bold text-primary-foreground">
                    {conv.unread}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Stage ring legend when rings section is active */}
        {activeSection === "rings" && (
          <div className="border-t px-3 py-2">
            <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
              Anillos configurados
            </p>
            <div className="space-y-1">
              {stage_rings.map((ring) => (
                <div key={ring.stage_id} className="flex items-center gap-1.5">
                  <div
                    className="h-3 w-3 rounded-full border-2 shrink-0"
                    style={{ borderColor: ring.color }}
                  />
                  <span className="text-[9px]">{ring.emoji}</span>
                  <span className="font-mono text-[9px] text-muted-foreground">{ring.stage_id}</span>
                  {ring.sla_hours != null && (
                    <span className="ml-auto text-[8px] text-muted-foreground">
                      SLA {ring.sla_hours}h
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
