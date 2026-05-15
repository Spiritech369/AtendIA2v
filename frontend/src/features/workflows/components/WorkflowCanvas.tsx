import { Lock, Maximize2, Minus, MoreVertical, Plus, Unlock, type Zap } from "lucide-react";
import {
  type MouseEvent,
  type ReactNode,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { WorkflowNode } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

type Edge = { from: string; to: string; label?: string };

type LayoutNode = {
  node: WorkflowNode;
  row: number;
  col: number;
};

type LayoutEdge = {
  from: LayoutNode;
  to: LayoutNode;
  label: string | null;
};

type Layout = {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  rows: number;
  cols: number;
};

// Compute a centered branching layout. The renderer paints column 0 in the
// middle, column -1 on the left, column +1 on the right (SI/NO). Multi-node
// branches keep their column until they merge back to center.
//
// The algorithm:
//   1. If explicit edges exist, do a DFS from the root, propagating column.
//      A node with 2+ outgoing edges splits its children: first labeled
//      "si"/"yes"/"true"/"left" → -1, second → +1, rest alternate.
//   2. If no edges, fall back to a sequential rule: after a condition/branch
//      node, the next two nodes are placed at col -1 / col +1, then the
//      layout returns to col 0. This matches the screenshot for a typical
//      "condition → SI/NO siblings → merge" flow.
export function computeLayout(nodes: WorkflowNode[], edges: Edge[]): Layout {
  if (nodes.length === 0) return { nodes: [], edges: [], rows: 0, cols: 1 };

  const byId = new Map(nodes.map((n) => [n.id, n] as const));
  const positions = new Map<string, { row: number; col: number }>();

  if (edges.length > 0) {
    const outgoing = new Map<string, Edge[]>();
    const incoming = new Map<string, number>();
    for (const n of nodes) {
      outgoing.set(n.id, []);
      incoming.set(n.id, 0);
    }
    for (const e of edges) {
      outgoing.get(e.from)?.push(e);
      incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1);
    }
    const roots = nodes.filter((n) => (incoming.get(n.id) ?? 0) === 0);
    const start = roots[0] ?? nodes[0];
    if (start) {
      const visit = (id: string, row: number, col: number) => {
        const existing = positions.get(id);
        if (existing) {
          // Merge: keep the deepest row, prefer col=0 if conflict.
          positions.set(id, {
            row: Math.max(existing.row, row),
            col: existing.col === col ? col : 0,
          });
          return;
        }
        positions.set(id, { row, col });
        const next = outgoing.get(id) ?? [];
        if (next.length === 0) return;
        if (next.length === 1) {
          // Linear continuation — same column.
          visit(next[0]!.to, row + 1, col);
          return;
        }
        // Branching node: assign children to -1 / +1 by label.
        next.forEach((edge, index) => {
          const label = (edge.label ?? "").toLowerCase();
          let childCol: number;
          if (label === "si" || label === "sí" || label === "yes" || label === "true") {
            childCol = -1;
          } else if (label === "no" || label === "false") {
            childCol = 1;
          } else if (label === "else") {
            childCol = 1;
          } else {
            childCol = index === 0 ? -1 : index === 1 ? 1 : 0;
          }
          visit(edge.to, row + 1, childCol);
        });
      };
      visit(start.id, 0, 0);
    }
  }

  // Fallback for unpositioned nodes — and for the edgeless case.
  if (positions.size < nodes.length) {
    let row = 0;
    let pendingBranchSlots = 0; // 0 = center, 2 = next two go to -1/+1
    for (const node of nodes) {
      if (positions.has(node.id)) continue;
      if (pendingBranchSlots === 2) {
        positions.set(node.id, { row, col: -1 });
        pendingBranchSlots = 1;
      } else if (pendingBranchSlots === 1) {
        positions.set(node.id, { row, col: 1 });
        pendingBranchSlots = 0;
        row += 1;
      } else {
        positions.set(node.id, { row, col: 0 });
        if (node.type === "condition" || node.type === "branch") {
          pendingBranchSlots = 2;
          row += 1;
        } else {
          row += 1;
        }
      }
    }
  }

  // Resolve row collisions on the same column by pushing later nodes down.
  const occupied = new Set<string>();
  const layoutNodes: LayoutNode[] = nodes
    .map((node) => {
      const pos = positions.get(node.id) ?? { row: 0, col: 0 };
      let row = pos.row;
      while (occupied.has(`${row}:${pos.col}`)) row += 1;
      occupied.add(`${row}:${pos.col}`);
      return { node, row, col: pos.col };
    })
    .sort((a, b) => a.row - b.row || a.col - b.col);

  // Build layout edges. Prefer explicit edges; else connect each node to the
  // next node in topological order (whose row is strictly greater).
  const layoutEdges: LayoutEdge[] = [];
  if (edges.length > 0) {
    for (const e of edges) {
      const from = layoutNodes.find((ln) => ln.node.id === e.from);
      const to = layoutNodes.find((ln) => ln.node.id === e.to);
      if (from && to) {
        layoutEdges.push({ from, to, label: e.label ?? null });
      }
    }
  } else {
    // Edgeless: connect each branching node to its SI/NO siblings, and connect
    // linear runs to their next neighbor. Also reconnect post-branch nodes
    // back to center.
    for (let i = 0; i < layoutNodes.length; i += 1) {
      const current = layoutNodes[i]!;
      const type = current.node.type;
      if (type === "condition" || type === "branch") {
        const left = layoutNodes
          .slice(i + 1)
          .find((ln) => ln.col === -1 && ln.row === current.row + 1);
        const right = layoutNodes
          .slice(i + 1)
          .find((ln) => ln.col === 1 && ln.row === current.row + 1);
        if (left) layoutEdges.push({ from: current, to: left, label: "SI" });
        if (right) layoutEdges.push({ from: current, to: right, label: "NO" });
      } else {
        // Find the next node in the same column, or merge to center.
        const next = layoutNodes
          .slice(i + 1)
          .find((ln) => ln.row > current.row && (ln.col === current.col || ln.col === 0));
        if (next) {
          layoutEdges.push({ from: current, to: next, label: null });
        }
      }
    }
  }

  const rows = Math.max(0, ...layoutNodes.map((ln) => ln.row)) + 1;
  return { nodes: layoutNodes, edges: layoutEdges, rows, cols: 3 };
}

type CanvasMeta = { label: string; icon: typeof Zap; color: string; bg: string };

interface WorkflowCanvasProps {
  nodes: WorkflowNode[];
  edges: Edge[];
  selectedNodeId: string;
  onSelect: (id: string) => void;
  onContextMenu?: (event: MouseEvent, nodeId: string) => void;
  nodeMeta: (type: string) => CanvasMeta;
  titleFor: (node: WorkflowNode) => string;
  summaryFor: (node: WorkflowNode) => string;
  nodeMetrics: (nodeId: string) => Record<string, unknown>;
  issueForNode: (nodeId: string) => { message: string } | undefined;
  readOnly: boolean;
  addNodeMenu: ReactNode;
}

const NODE_WIDTH = 268;
const NODE_HEIGHT = 80;
const COL_GAP = 96;
const ROW_GAP = 56;
const CANVAS_PADDING = 64;

function pct(value: unknown, fallback = 0) {
  return typeof value === "number" ? `${value}%` : `${fallback}%`;
}

export function WorkflowCanvas({
  nodes,
  edges,
  selectedNodeId,
  onSelect,
  onContextMenu,
  nodeMeta,
  titleFor,
  summaryFor,
  nodeMetrics,
  issueForNode,
  readOnly,
  addNodeMenu,
}: WorkflowCanvasProps) {
  const [zoom, setZoom] = useState(1);
  const [locked, setLocked] = useState(readOnly);
  const scrollRef = useRef<HTMLDivElement>(null);

  const layout = useMemo(() => computeLayout(nodes, edges), [nodes, edges]);

  // Translate columns -1, 0, +1 → 0, 1, 2 for px math.
  const colIndex = (col: number) => col + 1;
  const xFor = (col: number) =>
    CANVAS_PADDING + colIndex(col) * (NODE_WIDTH + COL_GAP) - COL_GAP / 2;
  const yFor = (row: number) => CANVAS_PADDING + row * (NODE_HEIGHT + ROW_GAP);

  const canvasWidth = CANVAS_PADDING * 2 + 3 * NODE_WIDTH + 2 * COL_GAP;
  const canvasHeight = CANVAS_PADDING * 2 + Math.max(1, layout.rows) * (NODE_HEIGHT + ROW_GAP);

  const zoomIn = () => setZoom((z) => Math.min(1.5, Math.round((z + 0.1) * 100) / 100));
  const zoomOut = () => setZoom((z) => Math.max(0.5, Math.round((z - 0.1) * 100) / 100));
  const fit = () => setZoom(1);

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden border-r border-white/10 bg-[#0b1420]">
      {/* Canvas toolbar (top-left) */}
      <div className="pointer-events-none absolute left-3 top-3 z-10 flex flex-col gap-2">
        <div className="pointer-events-auto flex flex-col rounded-md border border-white/10 bg-[#101b27]/95 shadow-lg backdrop-blur">
          {addNodeMenu}
        </div>
        <div className="pointer-events-auto flex flex-col rounded-md border border-white/10 bg-[#101b27]/95 shadow-lg backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-none text-slate-300 hover:bg-white/5"
            title="Acercar"
            onClick={zoomIn}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-none text-slate-300 hover:bg-white/5"
            title="Alejar"
            onClick={zoomOut}
          >
            <Minus className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-none text-slate-300 hover:bg-white/5"
            title="Ajustar (100%)"
            onClick={fit}
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="pointer-events-auto rounded-md border border-white/10 bg-[#101b27]/95 shadow-lg backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              "h-8 w-8 rounded-md text-slate-300 hover:bg-white/5",
              locked && "text-amber-300",
            )}
            title={locked ? "Canvas bloqueado (solo lectura)" : "Canvas editable"}
            onClick={() => setLocked((v) => !v)}
            disabled={readOnly}
          >
            {locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>

      {/* Zoom badge (top-right) */}
      <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-md border border-white/10 bg-[#101b27]/95 px-2 py-1 text-[10px] text-slate-300 shadow-lg backdrop-blur">
        {Math.round(zoom * 100)}%
      </div>

      {/* Read-only banner */}
      {readOnly && (
        <div className="pointer-events-none absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-full border border-amber-400/40 bg-amber-500/15 px-3 py-1 text-[10px] text-amber-200 shadow-lg backdrop-blur">
          Workflow publicado — deténlo para editar el canvas
        </div>
      )}

      {/* Scrollable canvas */}
      <div ref={scrollRef} className="h-full w-full overflow-auto">
        <div
          className="relative origin-top-left"
          style={{
            width: canvasWidth,
            height: canvasHeight,
            transform: `scale(${zoom})`,
            transformOrigin: "top left",
          }}
        >
          {/* Grid background */}
          <svg width={canvasWidth} height={canvasHeight} className="absolute inset-0" aria-hidden>
            <defs>
              <pattern id="canvas-grid" width="24" height="24" patternUnits="userSpaceOnUse">
                <path
                  d="M 24 0 L 0 0 0 24"
                  fill="none"
                  stroke="rgba(148,163,184,0.07)"
                  strokeWidth="1"
                />
              </pattern>
              <marker
                id="canvas-arrow"
                viewBox="0 0 8 8"
                refX="7"
                refY="4"
                markerWidth="6"
                markerHeight="6"
                orient="auto"
              >
                <path d="M0 0 L8 4 L0 8 Z" fill="rgba(148,163,184,0.55)" />
              </marker>
            </defs>
            <rect width="100%" height="100%" fill="url(#canvas-grid)" />

            {/* Edges */}
            {layout.edges.map((edge, idx) => {
              const fromX = xFor(edge.from.col) + NODE_WIDTH / 2;
              const fromY = yFor(edge.from.row) + NODE_HEIGHT;
              const toX = xFor(edge.to.col) + NODE_WIDTH / 2;
              const toY = yFor(edge.to.row);
              const midY = (fromY + toY) / 2;
              const isBranch = edge.label !== null && edge.label !== undefined && edge.label !== "";
              const path =
                fromX === toX
                  ? `M ${fromX} ${fromY} L ${toX} ${toY}`
                  : `M ${fromX} ${fromY} C ${fromX} ${midY}, ${toX} ${midY}, ${toX} ${toY}`;
              return (
                <g key={`edge-${idx}-${edge.from.node.id}-${edge.to.node.id}`}>
                  <path
                    d={path}
                    fill="none"
                    stroke="rgba(148,163,184,0.55)"
                    strokeWidth="1.4"
                    strokeDasharray={isBranch ? "5 4" : undefined}
                    markerEnd="url(#canvas-arrow)"
                  />
                  {isBranch && (
                    <g transform={`translate(${(fromX + toX) / 2 - 12}, ${midY - 9})`}>
                      <rect
                        width="24"
                        height="18"
                        rx="4"
                        fill="#0d1822"
                        stroke={
                          edge.label?.toLowerCase().startsWith("s")
                            ? "rgba(52,211,153,0.55)"
                            : "rgba(248,113,113,0.55)"
                        }
                        strokeWidth="1"
                      />
                      <text
                        x="12"
                        y="13"
                        textAnchor="middle"
                        fontSize="9"
                        fontWeight="600"
                        fill={edge.label?.toLowerCase().startsWith("s") ? "#34d399" : "#f87171"}
                      >
                        {edge.label?.toUpperCase()}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>

          {/* Node cards */}
          {layout.nodes.map((ln, index) => {
            const meta = nodeMeta(ln.node.type);
            const Icon = meta.icon;
            const metrics = nodeMetrics(ln.node.id);
            const issue = issueForNode(ln.node.id);
            const selected = ln.node.id === selectedNodeId;
            const conversion = pct(metrics.conversion_rate, 100);
            const dropoff = pct(metrics.dropoff);
            return (
              <button
                key={ln.node.id}
                type="button"
                onClick={() => onSelect(ln.node.id)}
                onContextMenu={(event) => onContextMenu?.(event, ln.node.id)}
                data-node-row={ln.node.id}
                className={cn(
                  "absolute flex flex-col gap-1 rounded-md border bg-[#101f2c] px-2.5 py-2 text-left shadow-md transition",
                  "hover:bg-[#142637]",
                  selected
                    ? "border-blue-400/70 ring-2 ring-blue-400/40"
                    : issue
                      ? "border-amber-400/50"
                      : "border-white/10",
                  ln.node.enabled === false && "opacity-50",
                )}
                style={{
                  left: xFor(ln.col),
                  top: yFor(ln.row),
                  width: NODE_WIDTH,
                  height: NODE_HEIGHT,
                }}
              >
                <div className="flex items-center gap-2">
                  <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded", meta.bg)}>
                    <Icon className={cn("h-3.5 w-3.5", meta.color)} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[11px] font-medium text-slate-100">
                      {meta.label}: {titleFor(ln.node)}
                    </span>
                    <span className="block truncate text-[10px] text-slate-400">
                      {summaryFor(ln.node)}
                    </span>
                  </span>
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-white/5 text-[9px] text-slate-400">
                    {index + 1}
                  </span>
                </div>
                <div className="mt-auto flex items-center justify-between text-[9px] text-slate-500">
                  <span>{conversion}</span>
                  <span className={Number(metrics.dropoff ?? 0) > 20 ? "text-red-300" : ""}>
                    {dropoff}
                  </span>
                  {issue ? (
                    <span className="ml-1 truncate text-amber-300" title={issue.message}>
                      ⚠ {issue.message.slice(0, 22)}
                    </span>
                  ) : (
                    <span className="text-slate-600">·</span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Minimap (bottom-right) */}
      <Minimap
        layout={layout}
        canvasWidth={canvasWidth}
        canvasHeight={canvasHeight}
        scrollRef={scrollRef}
        zoom={zoom}
      />
    </div>
  );
}

function Minimap({
  layout,
  canvasWidth,
  canvasHeight,
  scrollRef,
  zoom,
}: {
  layout: Layout;
  canvasWidth: number;
  canvasHeight: number;
  scrollRef: RefObject<HTMLDivElement | null>;
  zoom: number;
}) {
  const w = 140;
  const h = 96;
  const scale = Math.min(w / canvasWidth, h / canvasHeight);
  const [viewport, setViewport] = useState<{ x: number; y: number; w: number; h: number }>({
    x: 0,
    y: 0,
    w: 0,
    h: 0,
  });

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const update = () => {
      setViewport({
        x: (el.scrollLeft / zoom) * scale,
        y: (el.scrollTop / zoom) * scale,
        w: Math.min(w, (el.clientWidth / zoom) * scale),
        h: Math.min(h, (el.clientHeight / zoom) * scale),
      });
    };
    el.addEventListener("scroll", update, { passive: true });
    update();
    return () => el.removeEventListener("scroll", update);
  }, [scrollRef, zoom, scale]);

  return (
    <div className="pointer-events-none absolute bottom-3 right-3 z-10 rounded-md border border-white/10 bg-[#101b27]/95 p-1.5 shadow-lg backdrop-blur">
      <svg width={w} height={h} className="block">
        <rect width={w} height={h} fill="#0b1420" rx="3" />
        {layout.nodes.map((ln) => (
          <rect
            key={`mm-${ln.node.id}`}
            x={(64 + (ln.col + 1) * (268 + 96) - 48) * scale}
            y={(64 + ln.row * (80 + 56)) * scale}
            width={268 * scale}
            height={80 * scale}
            fill="rgba(96,165,250,0.45)"
            rx={1}
          />
        ))}
        <rect
          x={viewport.x}
          y={viewport.y}
          width={Math.max(8, viewport.w)}
          height={Math.max(8, viewport.h)}
          fill="rgba(96,165,250,0.15)"
          stroke="rgba(96,165,250,0.8)"
          strokeWidth="1"
        />
      </svg>
    </div>
  );
}

// Helper: produce a context-menu trigger that mirrors the inline dropdown
// the editor used on each row. Exported for reuse in WorkflowEditor.
export function NodeRowMenu({
  actions,
}: {
  actions: { label: string; action: () => void; danger?: boolean }[];
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-300">
          <MoreVertical className="h-3.5 w-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {actions.map((action) => (
          <DropdownMenuItem
            key={action.label}
            className={action.danger ? "text-destructive focus:text-destructive" : undefined}
            onClick={action.action}
          >
            {action.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
