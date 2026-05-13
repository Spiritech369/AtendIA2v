import { createFileRoute } from "@tanstack/react-router";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BrandFactsEditor } from "@/features/config/components/BrandFactsEditor";
import { IntegrationsTab } from "@/features/config/components/IntegrationsTab";
import { ToneEditor } from "@/features/config/components/ToneEditor";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/config")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: ConfigPage,
});

// Pipeline editing used to live here as the first tab. It now lives on the
// `/pipeline` page itself (single source of truth for everything pipeline-
// related: board, editor, first-time setup). Configuración keeps tone/brand
// facts/integrations only.
function ConfigPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Configuración</h1>
      <Tabs defaultValue="brand-facts">
        <TabsList>
          <TabsTrigger value="brand-facts">Brand facts</TabsTrigger>
          <TabsTrigger value="tone">Tono</TabsTrigger>
          <TabsTrigger value="integrations">Integraciones</TabsTrigger>
        </TabsList>
        <TabsContent value="brand-facts" className="mt-4">
          <BrandFactsEditor />
        </TabsContent>
        <TabsContent value="tone" className="mt-4">
          <ToneEditor />
        </TabsContent>
        <TabsContent value="integrations" className="mt-4">
          <IntegrationsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
