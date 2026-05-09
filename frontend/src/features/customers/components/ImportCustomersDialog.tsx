import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FileSpreadsheet, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type CustomerImportPreview,
  customersApi,
} from "@/features/customers/api";

/**
 * Two-step import: pick file → preview the parsed rows + errors → confirm.
 *
 * v1 had a similar modal; v2 was committing immediately on file pick which
 * is unsafe for an operator who might paste the wrong column. The preview
 * endpoint validates with the same rules as the commit endpoint, and the
 * confirm step calls the actual import.
 */
export function ImportCustomersDialog() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CustomerImportPreview | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const previewMutation = useMutation({
    mutationFn: customersApi.importPreview,
    onSuccess: setPreview,
    onError: () => {
      toast.error("No se pudo analizar el archivo");
    },
  });
  const commit = useMutation({
    mutationFn: customersApi.importCsv,
    onSuccess: (res) => {
      toast.success(
        `Importación: ${res.created} nuevos, ${res.updated} actualizados`,
      );
      if (res.errors.length) {
        toast.warning(`${res.errors.length} filas con error — revisa el reporte`);
      }
      void qc.invalidateQueries({ queryKey: ["customers"] });
      reset();
      setOpen(false);
    },
    onError: () => {
      toast.error("La importación falló");
    },
  });

  const reset = () => {
    setFile(null);
    setPreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const onFileChange = (f: File | null) => {
    setFile(f);
    setPreview(null);
    if (f) previewMutation.mutate(f);
  };

  const created = preview?.valid_rows.filter((r) => r.will === "create").length ?? 0;
  const updated = preview?.valid_rows.filter((r) => r.will === "update").length ?? 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">
          <Upload className="mr-2 h-4 w-4" /> Importar
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-3xl">
        <DialogHeader>
          <DialogTitle>Importar clientes desde CSV</DialogTitle>
          <DialogDescription>
            Columnas reconocidas: <code>phone</code> / <code>telefono</code>{" "}
            (requerida), <code>name</code> / <code>nombre</code>,{" "}
            <code>email</code> / <code>correo</code>, <code>score</code> /{" "}
            <code>puntaje</code> (0–100). Máximo 2,000 filas.
          </DialogDescription>
        </DialogHeader>

        {!file && (
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed p-8 text-sm text-muted-foreground hover:bg-muted/40">
            <FileSpreadsheet className="h-8 w-8" />
            <span>Click para elegir el archivo CSV</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
            />
          </label>
        )}

        {file && previewMutation.isPending && (
          <div className="py-4 text-sm text-muted-foreground">Analizando…</div>
        )}

        {file && preview && (
          <>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline">Total filas: {preview.total}</Badge>
              <Badge variant="default" className="bg-emerald-600">
                Crear: {created}
              </Badge>
              <Badge variant="default" className="bg-blue-600">
                Actualizar: {updated}
              </Badge>
              {preview.errors.length > 0 && (
                <Badge variant="destructive">
                  Errores: {preview.errors.length}
                </Badge>
              )}
            </div>

            {preview.errors.length > 0 && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                <div className="mb-1 flex items-center gap-1 font-medium">
                  <AlertCircle className="h-3 w-3" /> Filas con error (se omitirán al confirmar)
                </div>
                <ul className="list-disc space-y-0.5 pl-5">
                  {preview.errors.slice(0, 20).map((err) => (
                    <li key={err}>{err}</li>
                  ))}
                  {preview.errors.length > 20 && (
                    <li>… y {preview.errors.length - 20} más.</li>
                  )}
                </ul>
              </div>
            )}

            <ScrollArea className="max-h-72 rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">#</TableHead>
                    <TableHead>Teléfono (canonical)</TableHead>
                    <TableHead>Nombre</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead className="w-20">Score</TableHead>
                    <TableHead className="w-24">Acción</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.valid_rows.slice(0, 200).map((row) => (
                    <TableRow key={row.row}>
                      <TableCell className="text-xs text-muted-foreground">
                        {row.row}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {row.phone}
                      </TableCell>
                      <TableCell>{row.name ?? "-"}</TableCell>
                      <TableCell className="text-xs">{row.email ?? "-"}</TableCell>
                      <TableCell>{row.score ?? "-"}</TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={
                            row.will === "create"
                              ? "border-emerald-300 text-emerald-700"
                              : "border-blue-300 text-blue-700"
                          }
                        >
                          {row.will === "create" ? "Crear" : "Actualizar"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          </>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancelar
          </Button>
          <Button
            disabled={!file || !preview || preview.valid_rows.length === 0 || commit.isPending}
            onClick={() => file && commit.mutate(file)}
          >
            Confirmar importación ({preview?.valid_rows.length ?? 0})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
