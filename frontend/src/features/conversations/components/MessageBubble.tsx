import { Cpu } from "lucide-react";

import type { MessageItem } from "@/features/conversations/api";
import { cn } from "@/lib/utils";

interface Props {
  message: MessageItem;
  hasTrace?: boolean;
  isSelected?: boolean;
  onDebug?: (messageId: string) => void;
}

export function MessageBubble({ message, hasTrace, isSelected, onDebug }: Props) {
  const isInbound = message.direction === "inbound";
  const isSystem = message.direction === "system";
  const clickable = hasTrace && onDebug;

  return (
    <div
      className={cn(
        "flex w-full",
        isSystem ? "justify-center" : isInbound ? "justify-start" : "justify-end",
      )}
    >
      <div
        className={cn(
          "group relative max-w-[75%] rounded-lg px-3 py-2 text-sm",
          isSystem && "bg-muted text-muted-foreground italic text-xs",
          isInbound && !isSystem && "bg-muted text-foreground",
          !isInbound && !isSystem && "bg-primary text-primary-foreground",
          clickable && "cursor-pointer transition-shadow hover:ring-2 hover:ring-indigo-400/50",
          isSelected && "ring-2 ring-indigo-500",
        )}
        onClick={clickable ? () => onDebug(message.id) : undefined}
      >
        <div className="whitespace-pre-wrap">{message.text}</div>
        <div className="mt-1 flex items-center gap-1">
          {message.sent_at && !isSystem && (
            <span
              className={cn(
                "text-[10px]",
                isInbound ? "text-muted-foreground" : "text-primary-foreground/70",
              )}
            >
              {new Date(message.sent_at).toLocaleTimeString("es-MX", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          )}
          {hasTrace && (
            <Cpu
              className={cn(
                "h-3 w-3",
                isInbound
                  ? "text-muted-foreground/50 group-hover:text-indigo-500"
                  : "text-primary-foreground/40 group-hover:text-primary-foreground/80",
              )}
            />
          )}
        </div>
      </div>
    </div>
  );
}
