import { Lock } from "lucide-react";
import { toast } from "sonner";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface NYIButtonProps {
  label: string;
  icon?: LucideIcon;
  size?: "sm" | "default" | "lg" | "icon";
  variant?: "outline" | "ghost" | "default";
  className?: string;
}

/**
 * NYIButton — Not Yet Implemented button.
 *
 * Replaces toast.info(...) stubs for features not yet built.
 * Visual: amber color + lock icon.
 * Distinct from DemoBadge (violet), which marks simulated-but-implemented features.
 *
 * Sprint B.2 gating: by default the button renders `null` so production
 * users never see aspirational chrome. Set `VITE_SHOW_NYI=true` in dev
 * to surface them while the team is reviewing/triaging which to build
 * next. Tests opt in explicitly via the same env var or by mocking it.
 */
const SHOW_NYI = import.meta.env?.VITE_SHOW_NYI === "true";

export function NYIButton({
  label,
  icon: Icon,
  size = "sm",
  variant = "outline",
  className,
}: NYIButtonProps) {
  if (!SHOW_NYI) {
    return null;
  }
  return (
    <Button
      size={size}
      variant={variant}
      title="Feature en construcción — disponible próximamente"
      onClick={() =>
        toast.info("Feature en construcción", {
          description: `"${label}" estará disponible próximamente.`,
        })
      }
      className={cn(
        "border-amber-500/20 bg-amber-500/5 text-slate-300",
        "hover:border-amber-500/40 hover:bg-amber-500/10",
        className,
      )}
    >
      {Icon && <Icon className="mr-1.5 h-3.5 w-3.5" />}
      {label}
      <Lock className="ml-1.5 h-3 w-3 text-amber-400/70" />
    </Button>
  );
}
