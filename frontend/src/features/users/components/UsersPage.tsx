import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usersApi } from "@/features/users/api";
import { useAuthStore } from "@/stores/auth";

const ROLES = ["operator", "tenant_admin", "superadmin"];

export function UsersPage() {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const query = useQuery({ queryKey: ["users"], queryFn: usersApi.list });

  const [createOpen, setCreateOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("operator");

  const create = useMutation({
    mutationFn: () =>
      usersApi.create({
        email,
        password,
        role,
        // operator backend forces tenant from JWT; superadmin must pass tid
        tenant_id: me?.role === "superadmin" ? (me.tenant_id ?? undefined) : undefined,
      }),
    onSuccess: () => {
      toast.success("Usuario creado");
      setCreateOpen(false);
      setEmail("");
      setPassword("");
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error("Error", { description: e.message }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => usersApi.remove(id),
    onSuccess: () => {
      toast.success("Usuario eliminado");
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error("Error", { description: e.message }),
  });

  const items = query.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Usuarios</h1>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="mr-1 h-4 w-4" /> Nuevo
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Nuevo usuario</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="email">Correo</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Contraseña</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="role">Rol</Label>
                <Select value={role} onValueChange={setRole}>
                  <SelectTrigger id="role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.filter((r) => r !== "superadmin" || me?.role === "superadmin").map(
                      (r) => (
                        <SelectItem key={r} value={r}>
                          {r}
                        </SelectItem>
                      ),
                    )}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setCreateOpen(false)}
                disabled={create.isPending}
              >
                Cancelar
              </Button>
              <Button onClick={() => create.mutate()} disabled={create.isPending}>
                {create.isPending ? "Creando…" : "Crear"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {query.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{items.length} usuarios</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Correo</TableHead>
                  <TableHead>Rol</TableHead>
                  <TableHead>Tenant</TableHead>
                  <TableHead className="text-right">Acción</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                      Sin usuarios.
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell>{u.email}</TableCell>
                      <TableCell>{u.role}</TableCell>
                      <TableCell className="font-mono text-xs">{u.tenant_id}</TableCell>
                      <TableCell className="text-right">
                        {u.id !== me?.id && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              if (confirm(`¿Eliminar a ${u.email}?`)) {
                                remove.mutate(u.id);
                              }
                            }}
                            disabled={remove.isPending}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
