import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Permission = "full" | "partial" | "none";

interface Feature {
  name: string;
  admin: Permission;
  supervisor: Permission;
  operator: Permission;
}

const FEATURES: Feature[] = [
  { name: "Chips de filtro",    admin: "full", supervisor: "partial", operator: "none"    },
  { name: "Anillos de etapa",   admin: "full", supervisor: "none",    operator: "none"    },
  { name: "Reglas de handoff",  admin: "full", supervisor: "partial", operator: "none"    },
  { name: "Acciones composer",  admin: "full", supervisor: "partial", operator: "partial" },
  { name: "Diseño de bandeja",  admin: "full", supervisor: "none",    operator: "none"    },
];

const CELL: Record<Permission, { label: string; className: string }> = {
  full:    { label: "✓ Todos",  className: "text-emerald-600 dark:text-emerald-400" },
  partial: { label: "◑ Editar", className: "text-amber-600 dark:text-amber-400"    },
  none:    { label: "✗",        className: "text-muted-foreground/40"               },
};

const ROLE_STYLES: { role: string; className: string }[] = [
  { role: "Admin",      className: "text-red-600 dark:text-red-400"   },
  { role: "Supervisor", className: "text-blue-600 dark:text-blue-400" },
  { role: "Operador",   className: "text-muted-foreground"            },
];

export function PermissionsSection() {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Permisos y roles</CardTitle>
          <p className="text-xs text-muted-foreground">
            Qué puede hacer cada rol en la configuración de bandeja. Solo los admins pueden
            escribir configuración.
          </p>
        </CardHeader>
        <CardContent>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b">
                <th className="pb-2 text-left font-medium text-muted-foreground">Función</th>
                {ROLE_STYLES.map(({ role, className }) => (
                  <th key={role} className={cn("pb-2 text-center font-semibold", className)}>
                    {role}
                  </th>
                ))}
                <th className="pb-2 text-center font-medium text-muted-foreground">Ver</th>
                <th className="pb-2 text-center font-medium text-muted-foreground">Probar</th>
              </tr>
            </thead>
            <tbody>
              {FEATURES.map((f) => (
                <tr key={f.name} className="border-b last:border-0">
                  <td className="py-2 font-medium">{f.name}</td>
                  <td className={cn("py-2 text-center", CELL[f.admin].className)}>
                    {CELL[f.admin].label}
                  </td>
                  <td className={cn("py-2 text-center", CELL[f.supervisor].className)}>
                    {CELL[f.supervisor].label}
                  </td>
                  <td className={cn("py-2 text-center", CELL[f.operator].className)}>
                    {CELL[f.operator].label}
                  </td>
                  <td className="py-2 text-center text-emerald-600 dark:text-emerald-400">✓</td>
                  <td className="py-2 text-center text-amber-600 dark:text-amber-400">◑</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-[10px] text-muted-foreground">
            ✓ Acceso completo · ◑ Acceso parcial · ✗ Sin acceso
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
