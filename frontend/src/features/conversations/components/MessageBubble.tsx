import type { MessageItem } from "@/features/conversations/api";
import { cn } from "@/lib/utils";

export function MessageBubble({ message }: { message: MessageItem }) {
  const isInbound = message.direction === "inbound";
  const isSystem = message.direction === "system";

  return (
    <div
      className={cn(
        "flex w-full",
        isSystem ? "justify-center" : isInbound ? "justify-start" : "justify-end",
      )}
    >
      <div
        className={cn(
          "max-w-[75%] rounded-lg px-3 py-2 text-sm",
          isSystem && "bg-muted text-muted-foreground italic text-xs",
          isInbound && !isSystem && "bg-muted text-foreground",
          !isInbound && !isSystem && "bg-primary text-primary-foreground",
        )}
      >
        <div className="whitespace-pre-wrap">{message.text}</div>
        {message.sent_at && !isSystem && (
          <div
            className={cn(
              "mt-1 text-[10px]",
              isInbound ? "text-muted-foreground" : "text-primary-foreground/70",
            )}
          >
            {new Date(message.sent_at).toLocaleTimeString("es-MX", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </div>
        )}
      </div>
    </div>
  );
}
