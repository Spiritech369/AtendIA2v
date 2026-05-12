import { cn } from "@/lib/utils";

interface DemoBadgeProps {
  wrap?: boolean;
  className?: string;
  children?: React.ReactNode;
}

/**
 * DemoBadge — marks data or actions that are implemented but simulated.
 * Violet chip inline, or violet-bordered wrapper block.
 * Distinct from NYIButton (amber), which marks not-yet-built features.
 */
export function DemoBadge({ wrap = false, className, children }: DemoBadgeProps) {
  const chip = (
    <span
      title="Datos de demostración — no reflejan operación real"
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium",
        "bg-violet-500/20 text-violet-300 border border-violet-500/30",
        className,
      )}
    >
      Demo
    </span>
  );

  if (!wrap) return chip;

  return (
    <div className="relative rounded-lg border border-violet-500/20">
      <div className="absolute -top-2 left-2">{chip}</div>
      {children}
    </div>
  );
}
