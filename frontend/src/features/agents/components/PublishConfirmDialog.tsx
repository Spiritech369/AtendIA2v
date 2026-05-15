import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  agentName: string;
  version: string;
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * A11 — publish replaces the agent that answers real customers
 * immediately. The action used to fire on a single click from three
 * different entry points; this gate makes the operator confirm first.
 */
export function PublishConfirmDialog({
  open,
  agentName,
  version,
  pending,
  onConfirm,
  onCancel,
}: Props) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            Publicar agente
          </DialogTitle>
          <DialogDescription>
            Vas a publicar <strong>{agentName}</strong> ({version}) en
            producción. El agente publicado responde a los clientes reales de
            inmediato y reemplaza a la versión activa.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            Cancelar
          </Button>
          <Button onClick={onConfirm} disabled={pending}>
            {pending ? "Publicando…" : "Publicar a producción"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
