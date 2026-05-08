import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { tenantsApi } from "@/features/config/api";

const REGISTERS = ["informal_mexicano", "formal", "casual"];

export function ToneEditor() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["tenants", "tone"],
    queryFn: tenantsApi.getTone,
  });

  const [reg, setReg] = useState("informal_mexicano");
  const [energy, setEnergy] = useState("");
  const [fillers, setFillers] = useState("");

  useEffect(() => {
    if (query.data) {
      const v = query.data.voice as Record<string, unknown>;
      if (typeof v["register"] === "string") setReg(v["register"]);
      if (typeof v["energy"] === "string") setEnergy(v["energy"]);
      if (Array.isArray(v["fillers"])) setFillers((v["fillers"] as string[]).join(", "));
    }
  }, [query.data]);

  const save = useMutation({
    mutationFn: async () => {
      const voice: Record<string, unknown> = { register: reg };
      if (energy) voice["energy"] = energy;
      if (fillers.trim()) {
        voice["fillers"] = fillers
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
      return tenantsApi.putTone(voice);
    },
    onSuccess: () => {
      toast.success("Tono guardado");
      void qc.invalidateQueries({ queryKey: ["tenants", "tone"] });
    },
    onError: (e) => toast.error("Error", { description: e.message }),
  });

  if (query.isLoading) return <Skeleton className="h-72 w-full" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tono</CardTitle>
        <div className="text-xs text-muted-foreground">
          Personalidad de las respuestas del bot. El composer lo incorpora al system prompt.
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="register">Registro</Label>
          <Select value={reg} onValueChange={setReg}>
            <SelectTrigger id="register" className="max-w-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {REGISTERS.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="energy">Energía</Label>
          <Input
            id="energy"
            placeholder="ej. high, medium, low"
            value={energy}
            onChange={(e) => setEnergy(e.target.value)}
            className="max-w-xs"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="fillers">Muletillas (separadas por coma)</Label>
          <Textarea
            id="fillers"
            placeholder="ándele, sí pues, claro que sí"
            value={fillers}
            onChange={(e) => setFillers(e.target.value)}
            rows={2}
          />
        </div>
        <div className="flex justify-end">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Guardando…" : "Guardar"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
