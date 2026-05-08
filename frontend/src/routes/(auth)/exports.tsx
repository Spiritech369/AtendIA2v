import { createFileRoute } from "@tanstack/react-router";
import { Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/(auth)/exports")({
  component: ExportsPage,
});

function ExportsPage() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  function downloadHref(kind: "conversations" | "messages") {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    const qs = params.toString();
    return `/api/v1/exports/${kind}.csv${qs ? `?${qs}` : ""}`;
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Exportar</h1>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Rango de fechas (opcional)</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="from">Desde</Label>
            <Input id="from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="to">Hasta</Label>
            <Input id="to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Conversaciones</CardTitle>
            <div className="text-xs text-muted-foreground">
              Cliente, etapa, plan, costo y datos extraídos clave por fila.
            </div>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <a href={downloadHref("conversations")} download>
                <Download className="mr-2 h-4 w-4" /> Descargar CSV
              </a>
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Mensajes</CardTitle>
            <div className="text-xs text-muted-foreground">
              Cada inbound/outbound con sent_at y conversation_id.
            </div>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <a href={downloadHref("messages")} download>
                <Download className="mr-2 h-4 w-4" /> Descargar CSV
              </a>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
