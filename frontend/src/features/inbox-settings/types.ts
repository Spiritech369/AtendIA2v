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
    { id: "unread",            label: "Sin leer",             color: "#4f72f5", query: "read_at IS NULL",                            live_count: true,  visible: true, order: 0 },
    { id: "mine",              label: "Mías",                 color: "#9b72f5", query: "assigned_to = current_user",                 live_count: true,  visible: true, order: 1 },
    { id: "unassigned",        label: "Sin asignar",          color: "#f5a623", query: "assigned_to IS NULL AND status != 'closed'", live_count: false, visible: true, order: 2 },
    { id: "awaiting_customer", label: "En espera de cliente", color: "#4fa8f5", query: "stage = 'waiting_customer'",                 live_count: true,  visible: true, order: 3 },
    { id: "stale",             label: "Inactivas >24h",       color: "#f25252", query: "last_message_at < now() - interval '24h'",  live_count: true,  visible: true, order: 4 },
  ],
  stage_rings: [
    { stage_id: "nuevo",      emoji: "🆕", color: "#6b7cf5", sla_hours: 24   },
    { stage_id: "en_curso",   emoji: "🔄", color: "#10c98f", sla_hours: 4    },
    { stage_id: "en_espera",  emoji: "⏳", color: "#f5a623", sla_hours: 48   },
    { stage_id: "cotizacion", emoji: "💰", color: "#9b72f5", sla_hours: 12   },
    { stage_id: "documentos", emoji: "📄", color: "#4fa8f5", sla_hours: 24   },
    { stage_id: "cierre",     emoji: "🏁", color: "#10c98f", sla_hours: null },
  ],
  handoff_rules: [
    { id: "ask_price", intent: "ASK_PRICE",       confidence: 82,  action: "suggest_template",        template: "precio_hr_v_2025",  enabled: true,  order: 0 },
    { id: "docs_miss", intent: "DOCS_MISSING",    confidence: 75,  action: "send_checklist",          template: "docs_checklist_v2", enabled: true,  order: 1 },
    { id: "human_req", intent: "HUMAN_REQUESTED", confidence: 90,  action: "assign_to_free_operator", template: "",                  enabled: true,  order: 2 },
    { id: "stale_24h", intent: "STALE_24H",       confidence: 100, action: "trigger_followup",        template: "followup_24h",      enabled: false, order: 3 },
  ],
};
