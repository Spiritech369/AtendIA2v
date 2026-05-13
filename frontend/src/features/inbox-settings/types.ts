export interface InboxLayout {
  three_pane: boolean;
  rail_width: "collapsed" | "expanded";
  list_max_width: number;
  composer_density: "compact" | "comfortable";
  sticky_composer: boolean;
}

export interface FilterChip {
  id: string;
  label: string;
  color: string;
  query: string;
  live_count: boolean;
  visible: boolean;
  order: number;
}

export interface StageRing {
  stage_id: string;
  emoji: string;
  color: string;
  sla_hours: number | null;
}

export interface HandoffRule {
  id: string;
  intent: string;
  confidence: number;
  action: string;
  template: string;
  enabled: boolean;
  order: number;
}

export interface InboxConfig {
  layout: InboxLayout;
  filter_chips: FilterChip[];
  stage_rings: StageRing[];
  handoff_rules: HandoffRule[];
}

export const DEFAULT_INBOX_CONFIG: InboxConfig = {
  layout: {
    three_pane: true,
    rail_width: "expanded",
    list_max_width: 360,
    composer_density: "comfortable",
    sticky_composer: true,
  },
  filter_chips: [
    {
      id: "unread",
      label: "Sin leer",
      color: "#4f72f5",
      query: "read_at IS NULL",
      live_count: true,
      visible: true,
      order: 0,
    },
    {
      id: "mine",
      label: "Mías",
      color: "#9b72f5",
      query: "assigned_to = current_user",
      live_count: true,
      visible: true,
      order: 1,
    },
    {
      id: "unassigned",
      label: "Sin asignar",
      color: "#f5a623",
      query: "assigned_to IS NULL AND status != 'closed'",
      live_count: false,
      visible: true,
      order: 2,
    },
    {
      id: "awaiting_customer",
      label: "En espera de cliente",
      color: "#4fa8f5",
      query: "stage = 'waiting_customer'",
      live_count: true,
      visible: true,
      order: 3,
    },
    {
      id: "stale",
      label: "Inactivas >24h",
      color: "#f25252",
      query: "last_message_at < now() - interval '24h'",
      live_count: true,
      visible: true,
      order: 4,
    },
  ],
  stage_rings: [
    { stage_id: "nuevo", emoji: "🆕", color: "#6b7cf5", sla_hours: 24 },
    { stage_id: "en_curso", emoji: "🔄", color: "#10c98f", sla_hours: 4 },
    { stage_id: "en_espera", emoji: "⏳", color: "#f5a623", sla_hours: 48 },
    { stage_id: "cotizacion", emoji: "💰", color: "#9b72f5", sla_hours: 12 },
    { stage_id: "documentos", emoji: "📄", color: "#4fa8f5", sla_hours: 24 },
    { stage_id: "cierre", emoji: "🏁", color: "#10c98f", sla_hours: null },
  ],
  handoff_rules: [
    {
      id: "ask_price",
      intent: "ASK_PRICE",
      confidence: 82,
      action: "suggest_template",
      template: "precio_hr_v_2025",
      enabled: true,
      order: 0,
    },
    {
      id: "docs_miss",
      intent: "DOCS_MISSING",
      confidence: 75,
      action: "send_checklist",
      template: "docs_checklist_v2",
      enabled: true,
      order: 1,
    },
    {
      id: "human_req",
      intent: "HUMAN_REQUESTED",
      confidence: 90,
      action: "assign_to_free_operator",
      template: "",
      enabled: true,
      order: 2,
    },
    {
      id: "stale_24h",
      intent: "STALE_24H",
      confidence: 100,
      action: "trigger_followup",
      template: "followup_24h",
      enabled: false,
      order: 3,
    },
  ],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneArray<T extends object>(items: T[]): T[] {
  return items.map((item) => ({ ...item }));
}

function normalizeArray<T extends object>(value: unknown, fallback: T[]): T[] {
  if (!Array.isArray(value)) return cloneArray(fallback);
  const records = value.filter(isRecord).map((item) => ({ ...item })) as T[];
  return records.length > 0 || value.length === 0 ? records : cloneArray(fallback);
}

function normalizeLayout(value: unknown): InboxLayout {
  const fallback = DEFAULT_INBOX_CONFIG.layout;
  if (!isRecord(value)) return { ...fallback };

  return {
    three_pane: typeof value.three_pane === "boolean" ? value.three_pane : fallback.three_pane,
    rail_width:
      value.rail_width === "collapsed" || value.rail_width === "expanded"
        ? value.rail_width
        : fallback.rail_width,
    list_max_width:
      typeof value.list_max_width === "number" ? value.list_max_width : fallback.list_max_width,
    composer_density:
      value.composer_density === "compact" || value.composer_density === "comfortable"
        ? value.composer_density
        : fallback.composer_density,
    sticky_composer:
      typeof value.sticky_composer === "boolean" ? value.sticky_composer : fallback.sticky_composer,
  };
}

export function normalizeInboxConfig(value: unknown): InboxConfig {
  const source = isRecord(value) ? value : {};

  return {
    layout: normalizeLayout(source.layout),
    filter_chips: normalizeArray(source.filter_chips, DEFAULT_INBOX_CONFIG.filter_chips),
    stage_rings: normalizeArray(source.stage_rings, DEFAULT_INBOX_CONFIG.stage_rings),
    handoff_rules: normalizeArray(source.handoff_rules, DEFAULT_INBOX_CONFIG.handoff_rules),
  };
}
