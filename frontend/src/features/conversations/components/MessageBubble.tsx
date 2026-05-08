import { Check, Copy, Cpu } from "lucide-react";
import { useCallback, useState } from "react";

import type { MessageItem, MessageMedia } from "@/features/conversations/api";
import { cn } from "@/lib/utils";

import {
  cleanInternalNotes,
  shouldSkipText,
} from "@/features/conversations/lib/cleanInternalNotes";
import { MediaContent } from "./MediaContent";

interface Props {
  message: MessageItem;
  hasTrace?: boolean;
  isSelected?: boolean;
  onDebug?: (messageId: string) => void;
}

function extractMedia(metadata: Record<string, unknown>): MessageMedia | null {
  const media = metadata?.media;
  if (!media || typeof media !== "object") return null;
  const m = media as Record<string, unknown>;
  if (typeof m.type !== "string" || typeof m.url !== "string") return null;
  return m as unknown as MessageMedia;
}

export function MessageBubble({ message, hasTrace, isSelected, onDebug }: Props) {
  const isInbound = message.direction === "inbound";
  const isSystem = message.direction === "system";
  const clickable = hasTrace && onDebug;
  const [copied, setCopied] = useState(false);

  const media = extractMedia(message.metadata);
  const cleanedText = cleanInternalNotes(message.text);
  const showText = cleanedText && !shouldSkipText(cleanedText, !!media);

  const handleCopy = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      void navigator.clipboard.writeText(message.text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    },
    [message.text],
  );

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
        {media && <MediaContent media={media} />}
        {showText && <div className="whitespace-pre-wrap">{cleanedText}</div>}
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

        {!isSystem && (
          <button
            type="button"
            onClick={handleCopy}
            className={cn(
              "absolute -top-2 right-1 rounded p-0.5 opacity-0 transition-opacity group-hover:opacity-100",
              isInbound
                ? "bg-background text-muted-foreground hover:text-foreground"
                : "bg-primary-foreground/20 text-primary-foreground hover:bg-primary-foreground/30",
            )}
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          </button>
        )}
      </div>
    </div>
  );
}
