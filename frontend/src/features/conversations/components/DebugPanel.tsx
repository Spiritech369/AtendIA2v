import { useQuery } from "@tanstack/react-query";
import { Cpu, MessageSquareText, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { turnTracesApi } from "@/features/turn-traces/api";
import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import {
  ComposerSection,
  ErrorsSection,
  NluSection,
  OverviewSection,
  PipelineSection,
  SectionHeader,
  StateSection,
  ToolCallsSection,
} from "@/features/turn-traces/components/TurnTraceSections";
import { buildTurnStory } from "@/features/turn-traces/lib/turnStory";

interface Props {
  traceId: string;
  onClose: () => void;
}

export function DebugPanel({ traceId, onClose }: Props) {
  const { data: t, isLoading } = useQuery({
    queryKey: ["turn-trace", traceId],
    queryFn: () => turnTracesApi.getOne(traceId),
  });

  if (isLoading || !t) {
    return (
      <PanelShell onClose={onClose} title="Cargando…">
        <div className="space-y-3 p-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </PanelShell>
    );
  }

  return (
    <PanelShell
      onClose={onClose}
      title={`Turn ${t.turn_number}`}
      subtitle={t.flow_mode ?? undefined}
    >
      <ScrollArea className="flex-1">
        <div className="space-y-0">
          <div className="space-y-2 p-3">
            <SectionHeader icon={MessageSquareText} label="Resumen" />
            <TurnStoryView steps={buildTurnStory(t)} />
          </div>
          <Separator />
          <OverviewSection trace={t} />
          <Separator />
          <PipelineSection trace={t} />
          <Separator />
          <NluSection trace={t} />
          <Separator />
          <ComposerSection trace={t} />
          {t.tool_calls.length > 0 && (
            <>
              <Separator />
              <ToolCallsSection trace={t} />
            </>
          )}
          <Separator />
          <StateSection trace={t} />
          <Separator />
          <ErrorsSection trace={t} />
        </div>
      </ScrollArea>
    </PanelShell>
  );
}

function PanelShell({
  onClose,
  title,
  subtitle,
  children,
}: {
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full w-96 shrink-0 flex-col overflow-hidden rounded-lg border bg-background shadow-lg">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{title}</span>
          {subtitle && (
            <Badge variant="outline" className="text-[10px]">
              {subtitle}
            </Badge>
          )}
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>
      {children}
    </div>
  );
}
