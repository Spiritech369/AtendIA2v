import { ExternalLink, FileText } from "lucide-react";

import type { MessageMedia } from "@/features/conversations/api";

interface Props {
  media: MessageMedia;
}

export function MediaContent({ media }: Props) {
  if (media.type === "image") {
    return (
      <div className="mb-1">
        <img
          src={media.url}
          alt={media.caption ?? "imagen"}
          className="max-h-48 max-w-full cursor-pointer rounded-lg object-cover"
          onClick={() => window.open(media.url, "_blank")}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
        {media.caption && <p className="mt-0.5 text-xs opacity-70">{media.caption}</p>}
      </div>
    );
  }

  if (media.type === "audio") {
    return (
      <div className="mb-1">
        <audio controls src={media.url} style={{ maxWidth: "200px", height: "32px" }}>
          Audio no soportado
        </audio>
      </div>
    );
  }

  if (media.type === "document") {
    return (
      <div className="mb-1 flex items-center gap-2">
        <FileText className="h-4 w-4 shrink-0 opacity-60" />
        <div className="min-w-0">
          <p className="truncate text-xs font-medium">
            {media.original_filename ?? "documento"}
          </p>
          {media.file_size != null && (
            <p className="text-xs opacity-60">{(media.file_size / 1024).toFixed(0)} KB</p>
          )}
        </div>
        <a
          href={media.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 text-xs underline"
        >
          Ver <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    );
  }

  return null;
}
